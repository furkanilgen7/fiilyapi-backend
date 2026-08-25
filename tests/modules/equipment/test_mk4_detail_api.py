"""MK-4 T3 — Ekipman Detay ucu ve ON saklanan alan (uçtan uca).

Mockup: `projedesign/Makine - Ekipman Detay.dc.html` (kısaltma: **MD**).

Ölçüm: mockup 22 alan çiziyordu, `EquipmentResponse` 30 alan taşıyordu ve üç
kart eksikti — Teknik 5/8 (MD:58-65) · Kiralama 2/8 (MD:66-82) · Bakım 1/6
(MD:145-160). Bu dosya üç kartın da BESLENEBİLDİĞİNİ uçtan uca tutar.

🔴 **Sözleşme ADDITIVE genişler:** `GET /equipment/{id}` gövdesi DEĞİŞMEDİ,
yeni uç `GET /equipment/{id}/detail`tir. Türevler künyeye konsaydı LİSTE ucu da
(aynı şemayı paylaşır) her çizilişte hareket tablosunu tarardı.

Şema katmanı (DDL) AYRI dosyadadır (`test_mk4_migration.py`): bu dosyanın
şeması `create_all` ile modelden kurulur ve migration'ı HİÇ KOŞMAZ — sahte
yeşilin 8. hâli tam olarak budur, orada kapatılır.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment import service
from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentMaintenancePeriod,
    EquipmentOwnership,
    EquipmentRatePeriod,
    EquipmentRentalInvoice,
    EquipmentRentalInvoiceLine,
    EquipmentWorkLog,
    RentalInvoiceStatus,
    RentalLineKind,
    WorkLogType,
)
from app.modules.procurement.models import PaymentTerms, Supplier
from app.modules.sites.models import Site

pytestmark = pytest.mark.asyncio

#: MD:65/151 — hourmeter ve son bakım okuması. Aradaki 286 saat MD:160'ın
#: `286 / 500 saat çalışıldı` payıdır; 500'lük periyotla `%57,2` verir (MD:159
#: `%57` basar, biçimlendirme İSTEMCİNİNDİR).
_HOURMETER = "14286.00"
_LAST_SERVICE = "14000.00"

#: MD:58-80 — ekranın SAKLANAN on alanı, mockup değerleriyle.
_MK4_ALANLARI = {
    "engine_power_kw": "45.00",
    "capacity_description": "8 Ton · 60 m yükseklik",
    "hourmeter_hours": _HOURMETER,
    "rental_contract_no": "LT-KRA-2026-004",
    "rental_start_date": "2026-03-01",
    "rental_end_date": "2026-12-31",
    "rental_min_monthly_hours": 160,
    "rental_payment_terms": "Aylık — fatura üzerinden",
    "last_service_date": "2026-05-18",
    "last_service_hourmeter": _LAST_SERVICE,
}


def _govde(**kwargs) -> dict:
    govde: dict = {
        "name": "Tower Crane TC-48",
        "category": EquipmentCategory.crane.value,
        "ownership": EquipmentOwnership.rented.value,
    }
    govde.update(kwargs)
    return govde


async def _detayli_makine(fabrika, site: Site, **kwargs) -> Equipment:
    """MD'nin kartını kuran ekipman: periyot 500 saat, hourmeter 14.286."""
    alanlar = {
        "ownership": EquipmentOwnership.rented,
        "maintenance_period": EquipmentMaintenancePeriod.hours_500,
        "hourmeter_hours": Decimal(_HOURMETER),
        "last_service_hourmeter": Decimal(_LAST_SERVICE),
        "last_service_date": date(2026, 5, 18),
    }
    alanlar.update(kwargs)
    return await fabrika(
        "Tower Crane TC-48", category=EquipmentCategory.crane, site=site, **alanlar
    )


# --------------------------------------------------------------------------- #
# SAKLANAN alanlar — POST / GET / PATCH gidiş-dönüşü
# --------------------------------------------------------------------------- #


async def test_on_yeni_alan_POSTta_yazilir_ve_kunyede_geri_doner(client, sef_headers):
    """🔴 Emrin ölçtüğü boşluk: üç kartın eksik alanları ARTIK besleniyor."""
    yanit = await client.post("/equipment", json=_govde(**_MK4_ALANLARI), headers=sef_headers)
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    for alan, deger in _MK4_ALANLARI.items():
        assert govde[alan] == deger, alan


async def test_on_yeni_alan_PATCHte_guncellenir(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    makine = await ekipman_fabrikasi("Kule Vinç", site=gorunen_santiye)
    yanit = await client.patch(
        f"/equipment/{makine.id}", json=dict(_MK4_ALANLARI), headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    for alan, deger in _MK4_ALANLARI.items():
        assert yanit.json()[alan] == deger, alan


async def test_yeni_alanlar_ZORUNLU_DEGIL_mevcut_akis_bozulmaz(client, sef_headers):
    """Alanların hepsi `nullable`dır: mockup'ın basmadığı bir makine (el aleti)
    hâlâ tek satırla kaydedilebilmelidir."""
    yanit = await client.post("/equipment", json=_govde(), headers=sef_headers)
    assert yanit.status_code == 201, yanit.text
    for alan in _MK4_ALANLARI:
        assert yanit.json()[alan] is None, alan


@pytest.mark.parametrize(
    ("alan", "deger"),
    [
        ("engine_power_kw", "0"),
        ("engine_power_kw", "-1"),
        ("hourmeter_hours", "-1"),
        ("last_service_hourmeter", "-1"),
        ("rental_min_monthly_hours", -1),
    ],
)
async def test_anlamsiz_degerler_422(client, sef_headers, alan, deger):
    """Şema sınırı DB `CHECK`iyle BİREBİRDİR: kullanıcı opak bir bütünlük
    hatası yerine düzeltilebilir bir 422 görür."""
    yanit = await client.post("/equipment", json=_govde(**{alan: deger}), headers=sef_headers)
    assert yanit.status_code == 422, yanit.text


async def test_sifir_saat_ve_sifir_asgari_KABUL_edilir(client, sef_headers):
    """Sıfırın yasak olduğu TEK alan motor gücüdür (0 kW bir giriş hatasıdır);
    sıfır saatte teslim alınmış makine ve asgarisiz sözleşme GERÇEKTİR."""
    yanit = await client.post(
        "/equipment",
        json=_govde(hourmeter_hours="0", last_service_hourmeter="0", rental_min_monthly_hours=0),
        headers=sef_headers,
    )
    assert yanit.status_code == 201, yanit.text


# --- Kira dönemi sırası: KURAL SERVİSTE, CHECK emniyet ağı ---


async def test_ters_kira_donemi_POSTta_422_ve_turkce(client, sef_headers):
    """🔴 Beklenen metin ELLE yazılır (OK-1C dersi): sabitten okunsaydı sabitin
    kendisi değiştiğinde test onu takip eder ve mutasyonu sağ bırakırdı."""
    yanit = await client.post(
        "/equipment",
        json=_govde(rental_start_date="2026-12-31", rental_end_date="2026-03-01"),
        headers=sef_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == "Kira bitiş tarihi kira başlangıç tarihinden önce olamaz."


async def test_ters_kira_donemi_PATCHte_de_422_mevcut_satirla_birlesir(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 İKİNCİ YÖN (K2 emsali): doğru sırayla kaydedip sonra YALNIZ bitişi öne
    çekmek kuralı atlamamalıdır — gövde tek başına bakılsaydı atlardı."""
    makine = await ekipman_fabrikasi(
        "Kule Vinç",
        site=gorunen_santiye,
        rental_start_date=date(2026, 3, 1),
        rental_end_date=date(2026, 12, 31),
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"rental_end_date": "2026-01-01"}, headers=sef_headers
    )
    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == "Kira bitiş tarihi kira başlangıç tarihinden önce olamaz."


async def test_ayni_gun_baslayip_biten_ve_YARIM_donem_kabul_edilir(client, sef_headers):
    """Sınır günü (`end == start`) GEÇERLİDİR; bitişi belli olmayan sözleşme de."""
    ayni = await client.post(
        "/equipment",
        json=_govde(rental_start_date="2026-03-01", rental_end_date="2026-03-01"),
        headers=sef_headers,
    )
    assert ayni.status_code == 201, ayni.text
    yarim = await client.post(
        "/equipment",
        json=_govde(name="İkinci Vinç", rental_start_date="2026-03-01"),
        headers=sef_headers,
    )
    assert yarim.status_code == 201, yarim.text


async def test_yarim_donemli_kayitta_ALAKASIZ_patch_gecer(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 Kural "iki tarih de dolu olsun" DEĞİLDİR: bitişi henüz belli olmayan
    bir kira kartı her PATCH'te bitiş tarihi istemek zorunda kalsaydı, sözleşme
    imzalanana kadar makine hiç güncellenemezdi.

    Not: "kuralın öncesinden kalmış TERS bir dönem" senaryosu bu depoda
    ULAŞILAMAZDIR — `ck_equipment_rental_period_order` böyle bir satırın DB'de
    var olmasına izin vermez (ölçüldü: `test_mk4_migration.py`). `touched`
    kapısı bu yüzden `_assert_purchase_amount` ile aynı BİÇİMİ korumak için
    durur, ölçülebilir bir davranış farkı üretmez.
    """
    makine = await ekipman_fabrikasi(
        "Yarim Donem", site=gorunen_santiye, rental_start_date=date(2026, 3, 1)
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"brand": "Liebherr"}, headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text


# --------------------------------------------------------------------------- #
# TÜREV blok — bakım penceresi
# --------------------------------------------------------------------------- #


async def test_detay_ucu_bakim_penceresini_TURETIR(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """MD:151/153/155/159/160 — dört sayı da SAKLANMAZ, burada türer."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    yanit = await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)
    assert yanit.status_code == 200, yanit.text
    bakim = yanit.json()["maintenance"]
    assert bakim["period_hours"] == 500
    assert bakim["last_service_hourmeter"] == _LAST_SERVICE
    assert Decimal(bakim["next_service_hourmeter"]) == Decimal("14500")
    assert Decimal(bakim["used_hours"]) == Decimal("286")
    assert Decimal(bakim["remaining_hours"]) == Decimal("214")
    assert Decimal(bakim["usage_pct"]) == Decimal("57.2")


async def test_detay_ucu_kunyenin_SAKLANAN_alanlarini_da_tasir(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """`equipment` bloğu `GET /equipment/{id}` ile AYNI şemadır: ikinci bir
    künye şeması iki ekranda iki farklı kart üretirdi."""
    makine = await _detayli_makine(
        ekipman_fabrikasi, gorunen_santiye, capacity_description="8 Ton · 60 m yükseklik"
    )
    detay = await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)
    kunye = await client.get(f"/equipment/{makine.id}", headers=sef_headers)
    assert detay.status_code == 200 and kunye.status_code == 200
    assert detay.json()["equipment"] == kunye.json()


async def test_kunye_ucu_TUREV_ALAN_TASIMAZ(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 Sözleşme ADDITIVE genişledi: türevler künyeye SIZMADI (liste ucu aynı
    şemayı paylaşır ve her çizilişte hareket tablosunu tarardı)."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    govde = (await client.get(f"/equipment/{makine.id}", headers=sef_headers)).json()
    for yasak in (
        "next_service_hourmeter",
        "remaining_hours",
        "usage_pct",
        "estimated_service_date",
        "cumulative_paid",
        "maintenance",
        "rental",
    ):
        assert yasak not in govde, yasak


async def test_monthly_periyotta_saat_penceresi_None_TARIH_bilgisi_KALIR(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 K16 fail-closed + AYRI AYRI `None`: aylık bakımda saat penceresi
    YOKTUR ama son bakım TARİHİ bilinir. Tek bayrağa indirgenselerdi bilinen
    bir olgu, eksik bir ölçüt yüzünden ekrandan silinirdi."""
    makine = await _detayli_makine(
        ekipman_fabrikasi,
        gorunen_santiye,
        maintenance_period=EquipmentMaintenancePeriod.monthly,
    )
    bakim = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "maintenance"
    ]
    assert bakim["period"] == EquipmentMaintenancePeriod.monthly.value
    assert bakim["period_hours"] is None
    assert bakim["next_service_hourmeter"] is None
    assert bakim["usage_pct"] is None
    assert bakim["estimated_service_date"] is None
    assert bakim["last_service_date"] == "2026-05-18"


async def test_hourmeter_bilinmiyorsa_cubuk_CIZILMEZ(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """Uydurma bir `0` hourmeter, bilinmeyen bir okumayı bilinir sayıp çubuğu
    `%0` doldurur ve bakımı ERTELERDİ."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye, hourmeter_hours=None)
    bakim = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "maintenance"
    ]
    assert bakim["used_hours"] is None
    assert bakim["remaining_hours"] is None
    assert bakim["usage_pct"] is None
    # Sonraki bakım HEDEFİ hourmeter'a bağlı DEĞİLDİR — bilinir kalır.
    assert Decimal(bakim["next_service_hourmeter"]) == Decimal("14500")


# --- Tahmini bakım tarihi: `as_of` + çalışma temposu ---


async def test_tahmini_bakim_tarihi_calisma_temposundan_turer(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 Beklenti testin KENDİ kurduğu tempodan okunur, mockup'ın `~05.09.2026`
    tarihinden DEĞİL: 90 günün 450 saati → günde 5 sa → 214 sa ÷ 5 = 42,8 →
    YUKARI yuvarlanarak 43 gün."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    gun = date(2026, 7, 31)
    for i in range(45):
        seeded_db.add(
            EquipmentWorkLog(
                equipment_id=makine.id,
                work_date=gun - timedelta(days=i),
                site_id=gorunen_santiye.id,
                record_type=WorkLogType.worked,
                hours=Decimal("10"),
            )
        )
    await seeded_db.flush()
    yanit = await client.get(
        f"/equipment/{makine.id}/detail?as_of={gun.isoformat()}", headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["as_of"] == gun.isoformat()
    assert (
        yanit.json()["maintenance"]["estimated_service_date"]
        == (gun + timedelta(days=43)).isoformat()
    )


async def test_ariza_saatleri_tempoyu_HIZLANDIRMAZ(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 `record_type = worked` süzgeci: duran bir makine "hızlı çalışıyor"
    sayılsaydı bakım tarihi ERKENE alınırdı (MK-1 K10'un bakım tarafındaki eşi).
    Aynı tempoya arıza saati EKLENİR ve tahmini tarih DEĞİŞMEMELİDİR."""
    gun = date(2026, 7, 31)

    async def _tarih(makine_adi: str, ariza: bool) -> str:
        makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
        makine.name = makine_adi
        for i in range(45):
            seeded_db.add(
                EquipmentWorkLog(
                    equipment_id=makine.id,
                    work_date=gun - timedelta(days=i),
                    site_id=gorunen_santiye.id,
                    record_type=WorkLogType.worked,
                    hours=Decimal("10"),
                )
            )
            if ariza:
                seeded_db.add(
                    EquipmentWorkLog(
                        equipment_id=makine.id,
                        work_date=gun - timedelta(days=i),
                        site_id=gorunen_santiye.id,
                        record_type=WorkLogType.breakdown,
                        hours=Decimal("8"),
                    )
                )
        await seeded_db.flush()
        yanit = await client.get(
            f"/equipment/{makine.id}/detail?as_of={gun.isoformat()}", headers=sef_headers
        )
        assert yanit.status_code == 200, yanit.text
        return yanit.json()["maintenance"]["estimated_service_date"]

    assert await _tarih("Yalniz Calisma", ariza=False) == await _tarih("Ariza Da Var", ariza=True)


async def test_pencere_disindaki_kayitlar_tempoya_GIRMEZ(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """Pencere `ESTIMATE_WINDOW_DAYS` takvim günüdür; bir yıl önceki yoğun bir
    dönem bugünkü tempoyu temsil etmez."""
    from app.modules.equipment.maintenance import ESTIMATE_WINDOW_DAYS

    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    gun = date(2026, 7, 31)
    seeded_db.add(
        EquipmentWorkLog(
            equipment_id=makine.id,
            work_date=gun - timedelta(days=ESTIMATE_WINDOW_DAYS),
            site_id=gorunen_santiye.id,
            record_type=WorkLogType.worked,
            hours=Decimal("24"),
        )
    )
    await seeded_db.flush()
    bakim = (
        await client.get(
            f"/equipment/{makine.id}/detail?as_of={gun.isoformat()}", headers=sef_headers
        )
    ).json()["maintenance"]
    assert bakim["estimated_service_date"] is None, (
        "pencerenin BİR GÜN dışındaki kayıt tempoya girdi — sınır kaymış"
    )
    # Sınırın İÇİ: aynı kayıt bir gün sonraya alınınca tempo doğar.
    seeded_db.add(
        EquipmentWorkLog(
            equipment_id=makine.id,
            work_date=gun - timedelta(days=ESTIMATE_WINDOW_DAYS - 1),
            site_id=gorunen_santiye.id,
            record_type=WorkLogType.worked,
            hours=Decimal("24"),
        )
    )
    await seeded_db.flush()
    bakim = (
        await client.get(
            f"/equipment/{makine.id}/detail?as_of={gun.isoformat()}", headers=sef_headers
        )
    ).json()["maintenance"]
    assert bakim["estimated_service_date"] is not None


async def test_hic_calismamis_makinede_tahmini_tarih_None(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """Tempo 0 → `None`. `as_of` basmak "bugün bakım" demek olurdu."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    bakim = (
        await client.get(f"/equipment/{makine.id}/detail?as_of=2026-07-31", headers=sef_headers)
    ).json()["maintenance"]
    assert bakim["estimated_service_date"] is None


# --------------------------------------------------------------------------- #
# TÜREV blok — Kümülatif Ödenen (MD:82)
# --------------------------------------------------------------------------- #


async def _hakedis(
    session: AsyncSession,
    supplier: Supplier,
    makine: Equipment,
    *,
    status: RentalInvoiceStatus,
    hours: str,
    rate: str | None = "320.00",
    line_kind: RentalLineKind = RentalLineKind.rented,
    period_month: int = 7,
) -> EquipmentRentalInvoice:
    invoice = EquipmentRentalInvoice(
        supplier_id=supplier.id,
        invoice_no=f"FT-{uuid.uuid4().hex[:8]}",
        period_year=2026,
        period_month=period_month,
        rate_period=EquipmentRatePeriod.hourly,
        status=status,
    )
    session.add(invoice)
    await session.flush()
    session.add(
        EquipmentRentalInvoiceLine(
            invoice_id=invoice.id,
            equipment_id=makine.id,
            line_kind=line_kind,
            worked_hours=Decimal(hours),
            breakdown_hours=Decimal("0"),
            rate_amount=None if rate is None else Decimal(rate),
        )
    )
    await session.flush()
    return invoice


async def test_kumulatif_odenen_YALNIZ_odenmis_hakedislerden_turer(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 "Ödenen" ile "onaylanan" AYNI ŞEY DEĞİLDİR: `approved` de sayılsaydı
    ekran henüz çıkmamış bir parayı ödenmiş gösterirdi.

    Beklenti testin KENDİ saat ve bedelinden türer (100 × 320 = 32.000),
    MD'nin ₺284.160'ından DEĞİL.
    """
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    tedarikci = Supplier(name="Liebherr Türkiye A.Ş.", payment_terms=PaymentTerms.days_30)
    seeded_db.add(tedarikci)
    await seeded_db.flush()
    await _hakedis(
        seeded_db, tedarikci, makine, status=RentalInvoiceStatus.paid, hours="100", period_month=6
    )
    await _hakedis(
        seeded_db,
        tedarikci,
        makine,
        status=RentalInvoiceStatus.approved,
        hours="999",
        period_month=7,
    )
    kira = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "rental"
    ]
    assert Decimal(kira["cumulative_paid"]) == Decimal("32000")
    assert kira["paid_invoice_count"] == 1
    assert kira["cumulative_paid_unknown_count"] == 0


async def test_kumulatif_odenen_owned_ve_breakdown_satirlari_ICERMEZ(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 MK-2 K3 — çift ödeme YAPISAL olarak imkânsızdır: `owned` ve
    `breakdown` hiçbir ödenecek toplamın kaynağı DEĞİLDİR."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    tedarikci = Supplier(name="Liebherr", payment_terms=PaymentTerms.days_30)
    seeded_db.add(tedarikci)
    await seeded_db.flush()
    await _hakedis(
        seeded_db,
        tedarikci,
        makine,
        status=RentalInvoiceStatus.paid,
        hours="100",
        line_kind=RentalLineKind.owned,
        period_month=5,
    )
    await _hakedis(
        seeded_db,
        tedarikci,
        makine,
        status=RentalInvoiceStatus.paid,
        hours="50",
        line_kind=RentalLineKind.rented,
        period_month=6,
    )
    kira = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "rental"
    ]
    assert Decimal(kira["cumulative_paid"]) == Decimal("16000")
    assert kira["paid_invoice_count"] == 2


async def test_bedelsiz_satir_UYDURMA_sifirla_toplama_girmez_ADETCE_bildirilir(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """MK-1 `summarize` / MK-2 `our_total_unknown_count` kanonu."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    tedarikci = Supplier(name="Liebherr", payment_terms=PaymentTerms.days_30)
    seeded_db.add(tedarikci)
    await seeded_db.flush()
    await _hakedis(
        seeded_db, tedarikci, makine, status=RentalInvoiceStatus.paid, hours="100", period_month=6
    )
    # 🔴 Bedelsiz satır İKİNCİ faturadadır: `(invoice_id, equipment_id,
    # line_kind)` TEKİLDİR, aynı hakedişte aynı ekipmanın iki `rented` satırı
    # olamaz.
    await _hakedis(
        seeded_db,
        tedarikci,
        makine,
        status=RentalInvoiceStatus.paid,
        hours="40",
        rate=None,
        period_month=5,
    )
    kira = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "rental"
    ]
    assert Decimal(kira["cumulative_paid"]) == Decimal("32000")
    assert kira["cumulative_paid_unknown_count"] == 1


async def test_hic_odenmis_hakedis_yoksa_toplam_SIFIR_ve_adet_SIFIR(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """`paid_invoice_count == 0` "hiç ödeme yok" demektir; `cumulative_paid`in
    `0`ı "hepsi hesaplanamadı" ile karıştırılmasın diye vardır."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    kira = (await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)).json()[
        "rental"
    ]
    assert Decimal(kira["cumulative_paid"]) == Decimal("0")
    assert kira["paid_invoice_count"] == 0
    assert kira["cumulative_paid_unknown_count"] == 0


# --------------------------------------------------------------------------- #
# Kapı ve kapsam
# --------------------------------------------------------------------------- #


async def test_gorunmeyen_ekipmanin_detayi_404(
    client, sef_headers, ekipman_fabrikasi, gorunmeyen_santiye
):
    """🔴 K20: kapsam kapısı türevler HESAPLANMADAN ÖNCE geçilir — yoksa
    kullanıcı göremediği bir makinenin kira toplamını okurdu."""
    makine = await _detayli_makine(ekipman_fabrikasi, gorunmeyen_santiye)
    yanit = await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == service.EQUIPMENT_MISSING


async def test_olmayan_ekipmanin_detayi_AYNI_404(client, sef_headers):
    yanit = await client.get(f"/equipment/{uuid.uuid4()}/detail", headers=sef_headers)
    assert yanit.status_code == 404, yanit.text


async def test_detay_ucu_view_izniyle_okunur_izinsize_403(
    client, muhendis_headers, yetkisiz_headers, ekipman_fabrikasi, gorunen_santiye
):
    makine = await _detayli_makine(ekipman_fabrikasi, gorunen_santiye)
    okuma = await client.get(f"/equipment/{makine.id}/detail", headers=muhendis_headers)
    assert okuma.status_code == 200, okuma.text
    kapali = await client.get(f"/equipment/{makine.id}/detail", headers=yetkisiz_headers)
    assert kapali.status_code == 403, kapali.text


async def test_rota_sirasi_detail_UUID_SANILMAZ(client, sef_headers, ekipman_fabrikasi):
    """`/equipment/{id}/detail` `/equipment/{id}`den ÖNCE eşleşmelidir; aksi
    hâlde `detail` bir UUID sanılıp 422 dönerdi (MK-2 `rental-invoices` dersi)."""
    makine = await ekipman_fabrikasi("Depodaki Vinç")
    yanit = await client.get(f"/equipment/{makine.id}/detail", headers=sef_headers)
    assert yanit.status_code == 200, yanit.text
    assert set(yanit.json()) == {"equipment", "maintenance", "rental", "as_of"}
