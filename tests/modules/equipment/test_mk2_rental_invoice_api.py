"""MK-2 T3 — kira hakedişi uçları (spec §4 · K2 · K3 · K5 · K6 · K8 · K9).

Bu dosya M5'in TÜM iş kurallarını uçtan uca (HTTP üzerinden) tutar. Eşzamanlılık
regresyonu (EŞİK = KİLİT) AYRI dosyadadır
(`test_mk2_rental_invoice_concurrency.py`): oradaki testler gerçek COMMIT eder ve
buradaki SAVEPOINT'li `db_session` düzeniyle karışamaz.

🔴 **Mockup SAYILARI kural kanıtı DEĞİLDİR** (spec §0): M5'in ₺122.496/₺146.995'i
hiçbir beklentiye kopyalanmadı. Beklentiler testin KENDİ kurduğu saat ve bedelden
türetilir.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentOwnership,
    EquipmentWorkLog,
    WorkLogType,
)
from app.modules.procurement.models import PaymentTerms, Supplier
from app.modules.sites.models import Site

pytestmark = pytest.mark.asyncio

_YIL = 2026
_AY = 7

#: Tek çalışma kaydının GÜNLÜK tavanı 24 saattir (MK-1 K12, DB CHECK'i de aynısını
#: söyler) ama kira hakedişi satırı bir AYIN toplamını taşır. Bu yüzden testlerin
#: "186 saat"i art arda günlere BÖLÜNEREK yazılır — tek kayda sığdırmak MK-1'in
#: fizik kuralını çiğnerdi.
_GUNLUK_DILIM = Decimal("20")

#: Saatlik bedel — `rate_period=hourly` seçildiği için dönüşüm yoktur ve
#: beklentiler `saat × bedel`den DOĞRUDAN okunur (`cost.DAILY_HOURS` yolu MK-1'in
#: kendi testlerinde zaten kapalıdır; burada onu tekrar ölçmek kuralı iki yere
#: yazardı).
_BEDEL = Decimal("320.00")


async def _tedarikci(session: AsyncSession, name: str) -> Supplier:
    supplier = Supplier(name=name, payment_terms=PaymentTerms.days_30)
    session.add(supplier)
    await session.flush()
    return supplier


async def _kayit(
    session: AsyncSession,
    equipment: Equipment,
    *,
    hours: str,
    ilk_gun: int,
    site: Site | None = None,
    record_type: WorkLogType = WorkLogType.worked,
) -> list[EquipmentWorkLog]:
    """Dönem toplamını GÜNLERE BÖLEREK yazar (K12 tavanı: gün 24 saattir).

    `ilk_gun` çağrı başına AYRIDIR: aynı ekipmanın çalışma ve arıza kayıtları
    aynı güne düşseydi günlük tavan denetimi test kurulumunu reddederdi.
    """
    kalan = Decimal(hours)
    kayitlar: list[EquipmentWorkLog] = []
    gun = ilk_gun
    while kalan > 0:
        dilim = min(kalan, _GUNLUK_DILIM)
        log = EquipmentWorkLog(
            equipment_id=equipment.id,
            work_date=date(_YIL, _AY, gun),
            site_id=None if site is None else site.id,
            record_type=record_type,
            hours=dilim,
        )
        session.add(log)
        kayitlar.append(log)
        kalan -= dilim
        gun += 1
    await session.flush()
    return kayitlar


def _govde(supplier: Supplier, **kwargs) -> dict:
    govde = {
        "supplier_id": str(supplier.id),
        "period_year": _YIL,
        "period_month": _AY,
        "rate_period": "hourly",
    }
    govde.update(kwargs)
    return govde


async def _fatura_kur(
    client: AsyncClient, headers: dict[str, str], supplier: Supplier, **kwargs
) -> dict:
    resp = await client.post(
        "/equipment/rental-invoices", json=_govde(supplier, **kwargs), headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _detay(client: AsyncClient, headers: dict[str, str], invoice_id: str) -> dict:
    resp = await client.get(f"/equipment/rental-invoices/{invoice_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _satir(detay: dict, line_kind: str, equipment_id: uuid.UUID) -> dict:
    eslesenler = [
        s
        for s in detay["lines"]
        if s["line_kind"] == line_kind and s["equipment_id"] == str(equipment_id)
    ]
    assert len(eslesenler) == 1, f"{line_kind}/{equipment_id} satırı bulunamadı: {detay['lines']}"
    return eslesenler[0]


async def _durum_ilerlet(
    client: AsyncClient, headers: dict[str, str], invoice_id: str, adim: int
) -> None:
    """Faturayı `adim` kadar İLERİ taşır (her `approve` TEK adımdır, K5)."""
    for _ in range(adim):
        resp = await client.post(
            f"/equipment/rental-invoices/{invoice_id}/approve", headers=headers
        )
        assert resp.status_code == 200, resp.text


# --- Satır kurulumu: "Çalışma kaydından otomatik yüklendi" (M5:83) ---


async def test_satirlar_calisma_kaydindan_yuklenir_ve_turu_mulkiyetten_okunur(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """M5:83 "Çalışma kaydından otomatik yüklendi" — POST satırları KURAR.

    Üç satır tipi de M5'in tablosundan gelir: kiralık makine (`rented`), aynı
    makinenin arıza satırı (`breakdown`, AYRI satır — M5:128-139) ve kendi
    aracımız (`owned`, M5:140-151).
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    kendi = await ekipman_fabrikasi(
        "Damperli Kamyon",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.owned,
        purchase_amount=Decimal("1000000.00"),
        rate_amount=Decimal("140.00"),
    )
    await _kayit(seeded_db, kiralik, hours="186", ilk_gun=1, site=gorunen_santiye)
    await _kayit(
        seeded_db,
        kiralik,
        hours="38",
        ilk_gun=15,
        site=gorunen_santiye,
        record_type=WorkLogType.breakdown,
    )
    await _kayit(seeded_db, kendi, hours="168", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    detay = await _detay(client, admin_headers, fatura["id"])

    assert len(detay["lines"]) == 3
    kira_satiri = _satir(detay, "rented", kiralik.id)
    assert Decimal(kira_satiri["worked_hours"]) == Decimal("186.00")
    # 🔴 Arıza saati KİRA satırında DEĞİL kendi satırındadır (M5 ikisini ayrı
    # satır çizer); ikisi tek satırda toplansaydı "neyi ödemediğimiz" kaybolurdu.
    assert Decimal(kira_satiri["breakdown_hours"]) == Decimal("0.00")
    assert Decimal(kira_satiri["our_amount"]) == Decimal("186") * _BEDEL

    ariza_satiri = _satir(detay, "breakdown", kiralik.id)
    assert Decimal(ariza_satiri["worked_hours"]) == Decimal("0.00")
    assert Decimal(ariza_satiri["breakdown_hours"]) == Decimal("38.00")

    kendi_satiri = _satir(detay, "owned", kendi.id)
    assert Decimal(kendi_satiri["worked_hours"]) == Decimal("168.00")


async def test_baska_tedarikcinin_kiralik_makinesi_faturaya_GIRMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 K8 — bir fatura TEK tedarikçiye aittir; yabancı kiralık satır KURULMAZ.

    Kurulsaydı Liebherr'e kesilen fatura CAT'in makinesini de ödetir ve K8'in
    422 kapısı hiç görülmeden çift ödeme kapısı açılırdı.
    """
    bizim = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    yabanci = await _tedarikci(seeded_db, "CAT Finans")
    yabanci_makine = await ekipman_fabrikasi(
        "Ekskavatör CAT 320",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=yabanci.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, yabanci_makine, hours="152", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, bizim)
    detay = await _detay(client, admin_headers, fatura["id"])
    assert detay["lines"] == []


async def test_K3_owned_ve_breakdown_odenecek_toplamin_KAYNAGI_DEGILDIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 K3 — çift ödeme YAPISAL olarak imkânsız.

    `our_total` YALNIZ `rented` satırlardan beslenir; kendi makinemizin
    amortismanı ve arıza indirimi KENDİ alanlarına yazılır. Ödenecek toplam ise
    firmanın kestiği matrahtan + KDV'den gelir ve satırlarla KARIŞMAZ (K1).
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    kendi = await ekipman_fabrikasi(
        "Damperli Kamyon",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.owned,
        purchase_amount=Decimal("1000000.00"),
        rate_amount=Decimal("100.00"),
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)
    await _kayit(
        seeded_db,
        kiralik,
        hours="10",
        ilk_gun=15,
        site=gorunen_santiye,
        record_type=WorkLogType.breakdown,
    )
    await _kayit(seeded_db, kendi, hours="50", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_amount="100000.00")
    toplamlar = (await _detay(client, admin_headers, fatura["id"]))["totals"]

    assert Decimal(toplamlar["our_total"]) == Decimal("100") * _BEDEL
    assert Decimal(toplamlar["owned_total"]) == Decimal("5000")
    assert Decimal(toplamlar["excluded_breakdown_amount"]) == Decimal("10") * _BEDEL
    # K1: KDV oranı KOLONDAN gelir; ödenecek toplam matrah + KDV'dir.
    assert Decimal(toplamlar["vat_amount"]) == Decimal("20000.00")
    assert Decimal(toplamlar["payable_total"]) == Decimal("120000.00")


async def test_proje_dagilimi_satirlarin_kendi_santiyesinden_turer(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """M5:177-193 proje dağılımı — kova adı SUNUCUDAN çözülür."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="186", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    dagilim = (await _detay(client, admin_headers, fatura["id"]))["site_distribution"]

    assert len(dagilim) == 1
    assert dagilim[0]["site_id"] == str(gorunen_santiye.id)
    assert dagilim[0]["site_name"] == gorunen_santiye.name
    assert Decimal(dagilim[0]["hours"]) == Decimal("186.00")
    assert Decimal(dagilim[0]["amount"]) == Decimal("186") * _BEDEL
    assert [e["name"] for e in dagilim[0]["equipments"]] == ["Tower Crane TC-48"]


# --- K2 SNAPSHOT ---


async def test_K2_snapshot_calisma_kaydi_degisince_fatura_toplami_DEGISMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 K2 — satır kurulduktan SONRA çalışma kaydı değişse de toplam SABİTTİR.

    Canlı JOIN olsaydı, onaylanmış bir ödemenin dayanağı geçmiş bir kaydın
    düzeltilmesiyle SESSİZCE değişirdi. Tazeleme AYRI ve AÇIK bir eylemdir.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    kayitlar = await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    ilk = Decimal((await _detay(client, admin_headers, fatura["id"]))["totals"]["our_total"])
    assert ilk == Decimal("100") * _BEDEL

    # Geçmiş bir kayıt DÜZELTİLİR (20 → 4) ve yeni bir kayıt EKLENİR: canlı
    # toplam artık 104 saattir.
    kayitlar[0].hours = Decimal("4")
    await seeded_db.flush()
    await _kayit(seeded_db, kiralik, hours="8", ilk_gun=20, site=gorunen_santiye)

    sonra = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(sonra["totals"]["our_total"]) == ilk
    assert Decimal(_satir(sonra, "rented", kiralik.id)["worked_hours"]) == Decimal("100.00")

    # AÇIK tazeleme: `reload` (yalnız `draft`) snapshot'ı yeniler.
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["our_total"]) == Decimal("92") * _BEDEL


async def test_K2_snapshot_EKIPMAN_BEDELI_degisince_fatura_toplami_DEGISMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 K2 — snapshot SAATİ değil, PARANIN İKİ ÇARPANINI DA kapsar (T5 bulgusu).

    K4'ün "satırın bedeli boşsa ekipmanınki" kuralı bir ÇÖZÜM kuralıdır ve satır
    KURULURKEN uygulanır: bedel satıra KOPYALANIR (M5:93 alanı zaten dolu ve
    düzenlenebilir basıyor). Okuma yolunda ekipman kartına CANLI düşülseydi,
    K2'nin kapattığı delik ikinci çarpandan yeniden açılırdı — ONAYLANMIŞ bir
    faturanın ödenecek tutarı, kart üzerindeki bir bedel düzeltmesiyle SESSİZCE
    oynardı. Saatin snapshot'lanıp bedelin canlı bırakılması, aynı paranın
    yarısını dondurup yarısını serbest bırakmaktır.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    detay = await _detay(client, admin_headers, fatura["id"])
    ilk = Decimal(detay["totals"]["our_total"])
    assert ilk == Decimal("100") * _BEDEL
    # Bedel satıra KOPYALANMIŞ olmalı — dayanağı kendi kolonunda taşımayan satır
    # okuma anındaki karta bağımlı kalırdı.
    assert Decimal(_satir(detay, "rented", kiralik.id)["rate_amount"]) == _BEDEL

    # Ekipman kartının kira bedeli SONRADAN düzeltilir (320 → 999).
    kiralik.rate_amount = Decimal("999")
    await seeded_db.flush()

    sonra = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(sonra["totals"]["our_total"]) == ilk
    assert Decimal(_satir(sonra, "rented", kiralik.id)["effective_rate_amount"]) == _BEDEL

    # Tazeleme de yeni bedeli ÇEKMEZ: satırdaki bedel kullanıcının da
    # düzenleyebildiği bir alandır (M5:93) ve dolu bir değeri ezmek veri kaybı
    # olurdu. Bedel yalnız BOŞKEN karttan doldurulur.
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["our_total"]) == ilk


async def test_K2_bedelsiz_satir_KARTA_BEDEL_EKLENINCE_kendiliginden_dolmaz(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 Fail-closed satır SESSİZCE kendiliğinden dolmaz (T5 bulgusu).

    Bedeli olmayan makinenin satırı `our_amount = None` ile durur ve toplama
    GİRMEZ; adetçe `our_total_unknown_count`ta bildirilir (MK-1 K16 +
    `monthly_cost_unknown_count` kanonu). Okuma yolu ekipman kartına canlı
    düşseydi, karta sonradan bir bedel girildiği anda — hiç kimse faturaya
    dokunmamışken — `pending_verification` bir faturanın toplamı yoktan var
    olurdu. Bilinmeyen, ancak AÇIK bir eylemle (`reload`) bilinir hâle gelir.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=None,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    detay = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(detay["totals"]["our_total"]) == Decimal("0")
    assert detay["totals"]["our_total_unknown_count"] == 1
    assert _satir(detay, "rented", kiralik.id)["our_amount"] is None

    # Karta SONRADAN bedel girilir; faturaya DOKUNULMAZ.
    kiralik.rate_amount = _BEDEL
    await seeded_db.flush()

    sonra = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(sonra["totals"]["our_total"]) == Decimal("0")
    assert sonra["totals"]["our_total_unknown_count"] == 1
    assert _satir(sonra, "rented", kiralik.id)["our_amount"] is None

    # AÇIK tazeleme boş bedeli karttan doldurur.
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["our_total"]) == Decimal("100") * _BEDEL


async def test_reload_taslak_DISINDA_409(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """K2/K5 — `pending_verification`ta tazeleme KAPALIDIR.

    Doğrulama, kullanıcının GÖRDÜĞÜ saatler üzerinde yapılır; altından veri
    çekilebilseydi onaylanan şey ile doğrulanan şey ayrışırdı.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier)
    await _durum_ilerlet(client, admin_headers, fatura["id"], 1)

    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_reload_kullanicinin_girdigi_alanlari_KORUR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """Tazeleme SNAPSHOT'ı yeniler, kullanıcının girdiği fatura saatini ve
    birim bedelini EZMEZ — onlar bizim çalışma kaydımızdan gelmez."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier)
    satir = _satir(await _detay(client, admin_headers, fatura["id"]), "rented", kiralik.id)

    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{satir['id']}",
        json={"rate_amount": "400.00", "invoiced_hours": "106.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    await _kayit(seeded_db, kiralik, hours="8", ilk_gun=20, site=gorunen_santiye)
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    yeni = _satir(resp.json(), "rented", kiralik.id)
    assert Decimal(yeni["worked_hours"]) == Decimal("108.00")
    assert Decimal(yeni["rate_amount"]) == Decimal("400.00")
    assert Decimal(yeni["invoiced_hours"]) == Decimal("106.00")


# --- K6 fark rozeti ---


async def test_K6_fark_sunucu_damgasidir_ve_odemeyi_BLOKE_ETMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """K6 — `variance_status` SUNUCUDAN gelir; fark varken de onay/ödeme AKAR."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Ekskavatör CAT 320",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="152", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier)
    satir = _satir(await _detay(client, admin_headers, fatura["id"]), "rented", kiralik.id)
    assert satir["variance_status"] == "unknown"

    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{satir['id']}",
        json={"invoiced_hours": "158.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["variance_status"] == "over"
    assert Decimal(resp.json()["hours_variance"]) == Decimal("6.00")

    await _durum_ilerlet(client, admin_headers, fatura["id"], 2)
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/pay", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"


# --- K5 durum makinesi (her yasak geçiş AYRI test) ---


@pytest.fixture
async def akis_faturasi(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> dict:
    """Tek `rented` satırlı, `draft` bir fatura + satırı."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier, invoice_amount="30000.00")
    detay = await _detay(client, admin_headers, fatura["id"])
    return {"id": fatura["id"], "line_id": _satir(detay, "rented", kiralik.id)["id"]}


async def test_K5_ileri_zincir_ADIM_ATLAMAZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """`draft → pending_verification → approved`; her `approve` TEK adımdır."""
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/approve", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_verification"

    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/approve", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["approved_at"] is not None


async def test_K5_taslak_fatura_ODENEMEZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """`draft → paid` onay zincirini ATLARDI — 409."""
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_dogrulama_bekleyen_fatura_ODENEMEZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/approve", headers=admin_headers
    )
    assert resp.status_code == 200
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_odenmis_fatura_IKINCI_KEZ_odenemez(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """🔴 `paid` bir UÇ DAMGADIR: ikinci çağrı 409 (çift ödeme kapısı)."""
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["paid_at"] is not None

    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_onaylanmis_fatura_TEKRAR_onaylanamaz(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """`approved`ın ileri komşusu `paid`tir ve onun KENDİ ucu vardır: `approve`
    ikinci kez basıldığında ödeme damgası VURULMAZ, 409 döner."""
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/approve", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_odenmis_fatura_ONAYLANAMAZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/approve", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_red_onayi_DOGRULAMA_BEKLIYORA_geri_alir(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """🔴 Ayrı bir `rejected` durumu YOKTUR: red `approved → pending_verification`
    geri geçişidir ve fatura yeniden DÜZENLENEBİLİR hâle gelir."""
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/reject", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_verification"
    assert resp.json()["approved_at"] is None

    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}",
        json={"invoiced_hours": "101.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


async def test_K5_taslak_fatura_REDDEDILEMEZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """Red YALNIZ `approved`ın geri alınmasıdır; `draft`tan red anlamsızdır."""
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/reject", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_odenmis_fatura_REDDEDILEMEZ(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """Banka çıkışı olmuş bir kaydı geri sarmak, kayıt ile para hareketi
    arasındaki bağı koparırdı."""
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/pay", headers=admin_headers
    )
    resp = await client.post(
        f"/equipment/rental-invoices/{akis_faturasi['id']}/reject", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_onaylanmis_faturada_BASLIK_PATCHi_409(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.patch(
        f"/equipment/rental-invoices/{akis_faturasi['id']}",
        json={"invoice_amount": "1.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_K5_onaylanmis_faturada_SATIR_PATCHi_409(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """🔴 İK-3 S5 emsali: `approved`ta HİÇBİR ŞEY düzenlenemez — satır dahil.

    Satır kapısı ayrı ayrı testlenir çünkü başlık kapısı kapalıyken satır
    kapısının açık kalması, onaylanmış bir ödemenin tutarını sessizce
    değiştirmenin en kolay yoludur.
    """
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}",
        json={"rate_amount": "1.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_K5_onaylanmis_faturada_SATIR_SILME_409(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 2)
    resp = await client.delete(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text


async def test_K5_dogrulama_bekleyende_SATIR_SILME_409_ama_PATCH_serbest(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """Satır SİLME yalnız `draft`tadır (spec §4); satır DÜZENLEME
    `pending_verification`ta da açıktır (K5) — doğrulama tam olarak budur."""
    await _durum_ilerlet(client, admin_headers, akis_faturasi["id"], 1)
    resp = await client.delete(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}", headers=admin_headers
    )
    assert resp.status_code == 409, resp.text

    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}",
        json={"rate_amount": "400.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


async def test_taslakta_satir_silinir(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    resp = await client.delete(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}", headers=admin_headers
    )
    assert resp.status_code == 204, resp.text
    assert (await _detay(client, admin_headers, akis_faturasi["id"]))["lines"] == []


async def test_satir_PATCHi_YALNIZ_iki_alani_kabul_eder(
    client: AsyncClient, admin_headers: dict[str, str], akis_faturasi: dict
) -> None:
    """Spec §4: satır PATCH'i `rate_amount` + `invoiced_hours` DIŞINDA bir alan
    taşıyamaz — `worked_hours` gövdeden yazılabilseydi K2 snapshot'ı bir PATCH
    ile delinirdi."""
    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{akis_faturasi['line_id']}",
        json={"worked_hours": "1.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 422, resp.text


# --- K9 görünürlük ---


async def test_K9_gorunmeyen_santiyenin_faturasi_HER_UCTA_404(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    sef_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunmeyen_santiye: Site,
) -> None:
    """🔴 K9 — hiçbir uç atlanmaz: detay, PATCH, satır uçları ve durum uçları."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunmeyen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunmeyen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier, site_id=str(gorunmeyen_santiye.id))
    detay = await _detay(client, admin_headers, fatura["id"])
    line_id = _satir(detay, "rented", kiralik.id)["id"]

    fatura_id = fatura["id"]
    assert (
        await client.get(f"/equipment/rental-invoices/{fatura_id}", headers=sef_headers)
    ).status_code == 404
    assert (
        await client.patch(
            f"/equipment/rental-invoices/{fatura_id}",
            json={"invoice_no": "X"},
            headers=sef_headers,
        )
    ).status_code == 404
    for eylem in ("reload", "approve", "pay", "reject"):
        resp = await client.post(
            f"/equipment/rental-invoices/{fatura_id}/{eylem}", headers=sef_headers
        )
        assert resp.status_code == 404, f"{eylem}: {resp.text}"
    assert (
        await client.patch(
            f"/equipment/rental-invoice-lines/{line_id}",
            json={"rate_amount": "1.00"},
            headers=sef_headers,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/equipment/rental-invoice-lines/{line_id}", headers=sef_headers)
    ).status_code == 404

    liste = await client.get("/equipment/rental-invoices", headers=sef_headers)
    assert liste.status_code == 200, liste.text
    assert liste.json()["total"] == 0


async def test_K9_santiyesiz_fatura_HERKESE_gorunur(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    sef_headers: dict[str, str],
) -> None:
    """K9 — `site_id IS NULL` ("Tüm Projeler") fatura kapsam süzgecine TABİ
    DEĞİLDİR: hiçbir projeye ait değildir ve gizlenseydi hiç kimse göremezdi."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    fatura = await _fatura_kur(client, admin_headers, supplier)

    resp = await client.get(f"/equipment/rental-invoices/{fatura['id']}", headers=sef_headers)
    assert resp.status_code == 200, resp.text


async def test_gorunmeyen_santiyeye_fatura_ACILAMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    sef_headers: dict[str, str],
    gorunmeyen_santiye: Site,
) -> None:
    """Gövdedeki varlık referansı görünmüyorsa 404 (ST kanonu): aksi hâlde
    kullanıcı faturayı görmediği bir projeye taşıyıp kendinden gizlerdi."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    resp = await client.post(
        "/equipment/rental-invoices",
        json=_govde(supplier, site_id=str(gorunmeyen_santiye.id)),
        headers=sef_headers,
    )
    assert resp.status_code == 404, resp.text


async def test_olmayan_tedarikci_404(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/equipment/rental-invoices",
        json={
            "supplier_id": str(uuid.uuid4()),
            "period_year": _YIL,
            "period_month": _AY,
            "rate_period": "hourly",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 404, resp.text


# --- K8 tedarikçi eşleşmesi (422) ---


async def test_K8_tedarikci_degistirmek_kiralik_satirlarla_celisirse_422(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 K8 — `rented` satırların ekipmanı faturanın tedarikçisiyle EŞLEŞMELİDİR.

    İhlal 422'dir (404 değil: tedarikçi vardır ve görünür; 409 da değil: engel
    kaydın DURUMU değil GÖVDEDEKİ düzeltilebilir alan değeridir).
    """
    bizim = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    baskasi = await _tedarikci(seeded_db, "CAT Finans")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=bizim.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, bizim)

    resp = await client.patch(
        f"/equipment/rental-invoices/{fatura['id']}",
        json={"supplier_id": str(baskasi.id)},
        headers=admin_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_K8_kiralik_satiri_olmayan_faturada_tedarikci_degisir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """`owned` satırlarda tedarikçi ARANMAZ (K8) — kendi makinemizin kirası yok."""
    bizim = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    baskasi = await _tedarikci(seeded_db, "CAT Finans")
    kendi = await ekipman_fabrikasi(
        "Damperli Kamyon",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.owned,
        purchase_amount=Decimal("500000.00"),
        rate_amount=Decimal("100.00"),
    )
    await _kayit(seeded_db, kendi, hours="50", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, bizim)

    resp = await client.patch(
        f"/equipment/rental-invoices/{fatura['id']}",
        json={"supplier_id": str(baskasi.id)},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


# --- Liste + sayfalama + tekillik + yetki ---


async def test_liste_sayfalamasi_total_ve_tavan(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers: dict[str, str]
) -> None:
    """TB3 kanonu: `total` SÜZÜLMÜŞ kümeyi sayar, `limit ≤ 200`."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    for ay in (5, 6, 7):
        await _fatura_kur(client, admin_headers, supplier, period_month=ay)

    resp = await client.get("/equipment/rental-invoices?limit=2", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3
    assert len(resp.json()["items"]) == 2

    resp = await client.get(
        f"/equipment/rental-invoices?period_month=7&supplier_id={supplier.id}",
        headers=admin_headers,
    )
    assert resp.json()["total"] == 1

    assert (
        await client.get("/equipment/rental-invoices?limit=201", headers=admin_headers)
    ).status_code == 422


async def test_ayni_tedarikcide_ayni_fatura_no_409(
    client: AsyncClient, seeded_db: AsyncSession, admin_headers: dict[str, str]
) -> None:
    """UQ `(supplier_id, invoice_no)` — aynı faturayı iki kez ödemenin YAPISAL
    engeli. `invoice_no` NULL iken taslaklar serbesttir (NULLS DISTINCT)."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    await _fatura_kur(client, admin_headers, supplier, invoice_no="LT-2026-07-0184")
    await _fatura_kur(client, admin_headers, supplier)
    await _fatura_kur(client, admin_headers, supplier)

    resp = await client.post(
        "/equipment/rental-invoices",
        json=_govde(supplier, invoice_no="LT-2026-07-0184"),
        headers=admin_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_yetki_okuma_yazma_ayrimi(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    muhendis_headers: dict[str, str],
    yetkisiz_headers: dict[str, str],
) -> None:
    """Okuma `view`, yazma `full`; `equipment=_N` taşıyan rol okumada bile 403."""
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    fatura = await _fatura_kur(client, admin_headers, supplier)

    assert (
        await client.get("/equipment/rental-invoices", headers=muhendis_headers)
    ).status_code == 200
    assert (
        await client.post(
            "/equipment/rental-invoices", json=_govde(supplier), headers=muhendis_headers
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/equipment/rental-invoices/{fatura['id']}/approve", headers=muhendis_headers
        )
    ).status_code == 403
    assert (
        await client.get("/equipment/rental-invoices", headers=yetkisiz_headers)
    ).status_code == 403


async def test_rota_sirasi_rental_invoices_UUID_SANILMAZ(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """🔴 BEKÇİ: `/equipment/rental-invoices` `/equipment/{equipment_id}`den ÖNCE
    tanımlanmalıdır; sonra kalsaydı FastAPI onu bir UUID sanıp 422'ye düşürürdü.
    """
    resp = await client.get("/equipment/rental-invoices", headers=admin_headers)
    assert resp.status_code == 200, resp.text
