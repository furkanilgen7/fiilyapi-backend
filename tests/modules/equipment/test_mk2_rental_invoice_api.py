"""MK-2 — kira faturası: SATIR KURULUMU ve SNAPSHOT (K2 · K3 · MK-3 K1-K5).

Satırlar çalışma kaydından yüklenir, türü MÜLKİYETTEN okunur ve bir kez
yazıldıktan sonra kaynak veri değişse bile fatura toplamı DEĞİŞMEZ — türev para
N çarpandan oluşuyorsa snapshot N'in HEPSİNİ kapsar (bedel · kapasite · saat).

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): durum
makinesi, görünürlük, tedarikçi eşleşmesi ve liste uçları
`test_mk2_rental_invoice_state.py`ye taşındı; paylaşılan yardımcılar
`_mk2_rental_invoice.py`dedir. Hiçbir testin iddiası değişmedi.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    EquipmentOwnership,
    WorkLogType,
)
from app.modules.sites.models import Site

from ._mk2_rental_invoice import (
    _AYLIK_BEDEL,
    _BEDEL,
    _KAPASITE,
    _db_satir,
    _detay,
    _durum_ilerlet,
    _fatura_kur,
    _kayit,
    _satir,
    _tedarikci,
)

pytestmark = pytest.mark.asyncio


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


# --- MK-3: aylık kira paydası da SATIRDAN okunur (spec 2026-08-14 · K1-K5) ---


async def test_MK3_snapshot_KAPASITE_degisince_ONAYLI_faturanin_toplami_DEGISMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 MK-3 nüks testi — snapshot iddiası paranın ÜÇÜNCÜ çarpanını da kapsar.

    `monthly` dönemde saatlik bedel `rate_amount / monthly_capacity_hours`tır.
    MK-2'de saat donduruldu, bedel unutuldu; bedel donduruldu, PAYDA unutuldu.
    Payda ekipman kartından CANLI okunsaydı, kapasite düzeltmesi ONAYLANMIŞ
    (hatta ödenmiş) bir faturanın ödenecek tutarını geriye dönük oynatırdı —
    kimse faturaya dokunmamışken. Kalıcı ders: bir türev para değeri N çarpandan
    oluşuyorsa snapshot iddiası N'in HEPSİNİ kapsamalıdır.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_AYLIK_BEDEL,
        monthly_capacity_hours=_KAPASITE,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier, rate_period="monthly")
    detay = await _detay(client, admin_headers, fatura["id"])
    beklenen = Decimal("100") * (_AYLIK_BEDEL / Decimal(_KAPASITE))
    assert Decimal(detay["totals"]["our_total"]) == beklenen
    # Payda satırın KENDİ kolonunda taşınmalı; dayanağını taşımayan satır okuma
    # anındaki karta bağımlı kalırdı.
    assert (await _db_satir(seeded_db, fatura["id"])).capacity_hours == _KAPASITE

    # Fatura ONAYLANIR (`draft → pending_verification → approved`).
    await _durum_ilerlet(client, admin_headers, fatura["id"], 2)

    # Ekipman kartının kapasitesi SONRADAN düzeltilir (200 → 400).
    kiralik.monthly_capacity_hours = _KAPASITE * 2
    await seeded_db.flush()

    sonra = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(sonra["totals"]["our_total"]) == beklenen
    assert Decimal(_satir(sonra, "rented", kiralik.id)["our_amount"]) == beklenen


async def test_MK3_kapasitesiz_satirin_our_amount_i_NULL_kalir_SIFIR_DEGIL(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 MK-3 K2 — kapasite yok/0 ise `monthly` maliyet BİLİNMEZ, 0 DEĞİL.

    Sıfıra bölmede 0 basmak maliyeti yok göstermek olurdu (MK-1 K16). Uydurma
    bir varsayılan (200) da ENJEKTE EDİLMEZ: varsayılan ekipman tablosunun
    işidir, faturanın değil. Bilinmeyen sessiz kalmaz, `our_total_unknown_count`
    ile adetçe bildirilir.

    İkinci yarı asıl deliği ölçer: karta sonradan geçerli bir kapasite girilince
    — faturaya HİÇ dokunulmamışken — `null` tutar kendiliğinden bir sayıya
    dönmemelidir. Bilinmeyen, ancak AÇIK bir eylemle (`reload`) bilinir olur.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_AYLIK_BEDEL,
        monthly_capacity_hours=0,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier, rate_period="monthly")
    detay = await _detay(client, admin_headers, fatura["id"])
    assert _satir(detay, "rented", kiralik.id)["our_amount"] is None
    assert Decimal(detay["totals"]["our_total"]) == Decimal("0")
    assert detay["totals"]["our_total_unknown_count"] == 1

    satir = await _db_satir(seeded_db, fatura["id"])
    assert satir.capacity_hours == 0
    # `NULL` yolu da aynı yerde biter (migration'ın dolduramadığı eski satır).
    satir.capacity_hours = None
    kiralik.monthly_capacity_hours = _KAPASITE
    await seeded_db.flush()

    sonra = await _detay(client, admin_headers, fatura["id"])
    assert _satir(sonra, "rented", kiralik.id)["our_amount"] is None
    assert Decimal(sonra["totals"]["our_total"]) == Decimal("0")
    assert sonra["totals"]["our_total_unknown_count"] == 1


async def test_MK3_reload_BOS_kapasiteyi_doldurur_DOLU_degeri_EZMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 MK-3 K5 — `reload` davranışı `rate_amount`la BİREBİR aynıdır.

    Tazeleme dolu bir paydayı ezseydi, snapshot'ın verdiği güvence her
    tazelemede geri alınır ve fatura yeniden karta bağlanırdı. Hiç yazılmamış
    bir değeri doldurmak veri kaybı değildir; yazılmış bir değeri ezmek olurdu.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_AYLIK_BEDEL,
        monthly_capacity_hours=_KAPASITE,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier, rate_period="monthly")
    beklenen = Decimal("100") * (_AYLIK_BEDEL / Decimal(_KAPASITE))

    # Kart kapasitesi değişir; DOLU satır değeri tazelemede KORUNUR.
    kiralik.monthly_capacity_hours = _KAPASITE * 2
    await seeded_db.flush()
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["totals"]["our_total"]) == beklenen
    satir = await _db_satir(seeded_db, fatura["id"])
    assert satir.capacity_hours == _KAPASITE

    # BOŞ değer ise tazelemede karttan doldurulur.
    satir.capacity_hours = None
    await seeded_db.flush()
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert (await _db_satir(seeded_db, fatura["id"])).capacity_hours == _KAPASITE * 2
    assert Decimal(resp.json()["totals"]["our_total"]) == Decimal("100") * (
        _AYLIK_BEDEL / Decimal(_KAPASITE * 2)
    )


async def test_MK3_hourly_faturada_da_kapasite_satira_YAZILIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """🔴 MK-3 K3 — kapasite YALNIZ `monthly`de okunur ama HER satırda doldurulur.

    Faturanın dönemi `draft`ta serbestçe `PATCH`lenebilir. Kapasite yalnız
    `monthly` satırlara yazılsaydı, dönem sonradan `monthly`ye çevrildiğinde
    payda için canlı karta dönmek gerekirdi — tam da kapattığımız şey.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    kiralik = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
        monthly_capacity_hours=_KAPASITE,
    )
    await _kayit(seeded_db, kiralik, hours="100", ilk_gun=1, site=gorunen_santiye)

    # Dönem `hourly` — payda hiç OKUNMAZ, yine de YAZILIR.
    fatura = await _fatura_kur(client, admin_headers, supplier)
    detay = await _detay(client, admin_headers, fatura["id"])
    assert Decimal(detay["totals"]["our_total"]) == Decimal("100") * _BEDEL
    assert (await _db_satir(seeded_db, fatura["id"])).capacity_hours == _KAPASITE

    # Kart kapasitesi değişir, ARDINDAN dönem `monthly`ye çevrilir.
    kiralik.monthly_capacity_hours = 999
    await seeded_db.flush()
    resp = await client.patch(
        f"/equipment/rental-invoices/{fatura['id']}",
        json={"rate_period": "monthly"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    # Payda satırın KURULDUĞU andaki 200'dür; 999 değil.
    assert Decimal(resp.json()["totals"]["our_total"]) == Decimal("100") * (
        _BEDEL / Decimal(_KAPASITE)
    )


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
