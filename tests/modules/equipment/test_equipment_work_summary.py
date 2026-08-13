"""MK-1 T4 — `GET /equipment/work-summary` (M3 ana tablosu).

Kilitlenen kararlar: **K15** (🔴 TOPLAMLARIN TEK KAYNAĞI SATIRLARDIR — mockup'ın
tfoot'u KENDİ satırlarıyla tutarsızdır ve KOPYALANMAZ) · **K7** (kullanım %
paydası VERİDİR, 200 varsayılanı mockup'ta doğrulandı) · **K18** (maliyet
`cost.py`den gelir) · **K16** (uydurma 0 yok) · **K10** (arıza saati AYRI sütun,
paraya girmez) · haftalık kova dizisi (M3:219-243).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.equipment.models import (
    EquipmentRatePeriod,
    EquipmentStatus,
    EquipmentWorkLog,
    WorkLogType,
)

_YIL = 2026
_AY = 7

#: 🔴 M3 tfoot'unun BASTIĞI sayılar. Sunucu bunları ASLA üretmemelidir:
#: kendi satırlarıyla tutarsızdırlar (K15).
MOCKUP_TFOOT_SAAT = Decimal("428")
MOCKUP_TFOOT_MALIYET = Decimal("124800")
MOCKUP_TFOOT_KULLANIM = Decimal("69")

#: M3'ün SATIRLARI — (ad, çalışma saati, arıza saati, günlük bedel, satır maliyeti).
#: Günlük bedeller `DAILY_HOURS = 10` ile satır maliyetini birebir verir (K18).
MOCKUP_SATIRLAR = [
    ("Tower Crane TC-48", "186", "0", "3200", "59520"),
    ("Ekskavatör CAT 320", "152", "0", "2800", "42560"),
    ("Beton Pompası BP-36", "42", "38", "2200", "9240"),
    ("Damperli Kamyon", "168", "0", "1400", "23520"),
    ("Forklift Linde H30", "0", "0", "500", "0"),
    ("Kompresör SC-200", "144", "0", "650", "9360"),
]


@pytest.fixture
def kayit_fabrikasi(seeded_db):
    async def _create(
        equipment,
        *,
        hours: str,
        work_date: date,
        record_type: WorkLogType = WorkLogType.worked,
        site=None,
    ) -> EquipmentWorkLog:
        log = EquipmentWorkLog(
            equipment_id=equipment.id,
            work_date=work_date,
            site_id=equipment.site_id if site is None else site.id,
            record_type=record_type,
            hours=Decimal(hours),
        )
        seeded_db.add(log)
        await seeded_db.flush()
        return log

    return _create


async def _mockup_filosu(ekipman_fabrikasi, kayit_fabrikasi, santiye) -> None:
    """M3 tablosunun ALTI satırını birebir kurar.

    Saatler tek bir güne SIĞMAZ (K12 tavanı 24'tür) — aylık toplam olduğu için
    ay içine dağıtılır; 186 saat = 24 saatlik günlere bölünür.
    """
    for ad, saat, ariza, gunluk_bedel, _ in MOCKUP_SATIRLAR:
        makine = await ekipman_fabrikasi(
            ad,
            site=santiye,
            rate_amount=Decimal(gunluk_bedel),
            rate_period=EquipmentRatePeriod.daily,
        )
        await _dagit(kayit_fabrikasi, makine, Decimal(saat), WorkLogType.worked)
        await _dagit(kayit_fabrikasi, makine, Decimal(ariza), WorkLogType.breakdown)


async def _dagit(kayit_fabrikasi, makine, toplam: Decimal, tip: WorkLogType) -> None:
    """Toplam saati ayın günlerine 12'şer saatlik dilimlerle dağıtır.

    12 seçilir ki aynı güne düşen bir çalışma + bir arıza kaydı da 24 tavanını
    aşmasın (kurulum, denetlediği kuralın kendisini ihlal etmemelidir).
    """
    gun = 1
    kalan = toplam
    while kalan > 0:
        dilim = min(kalan, Decimal("12"))
        await kayit_fabrikasi(
            makine, hours=str(dilim), work_date=date(_YIL, _AY, gun), record_type=tip
        )
        kalan -= dilim
        gun += 1


def _satir(govde: dict, ad: str) -> dict:
    return next(s for s in govde["rows"] if s["equipment_name"] == ad)


# --- 🔴 K15: toplamlar SATIRLARDAN türer ---


@pytest.mark.asyncio
async def test_k15_toplamlar_satirlardan_turer_mockup_tfootu_KOPYALANMAZ(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """🔴 K15 · KABUL KRİTERİ 3.

    M3'ün tfoot'u 428 saat / ₺124.800 / %69 basıyor ama KENDİ satırları
    692 saat / ₺144.200 veriyor — mockup'ın aritmetik hatasıdır. Sunucu HER
    ZAMAN satırlardan toplar (TSD `contract_total` TEK KAYNAK emsali, F-P5 K5).
    """
    await _mockup_filosu(ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye)

    yanit = await client.get(
        f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    toplamlar = yanit.json()["totals"]

    assert Decimal(toplamlar["hours"]) == Decimal("692")
    assert Decimal(toplamlar["cost"]) == Decimal("144200")
    assert Decimal(toplamlar["breakdown_hours"]) == Decimal("38")

    assert Decimal(toplamlar["hours"]) != MOCKUP_TFOOT_SAAT, "mockup tfoot'u kopyalanmış"
    assert Decimal(toplamlar["cost"]) != MOCKUP_TFOOT_MALIYET, "mockup tfoot'u kopyalanmış"
    assert Decimal(toplamlar["usage_pct_avg"]) != MOCKUP_TFOOT_KULLANIM, (
        "kullanım ortalaması da SATIRLARDAN türer, mockup'ın %69'u kopyalanmaz"
    )


@pytest.mark.asyncio
async def test_k7_k18_satirlar_mockup_rozetleriyle_birebir(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """KABUL KRİTERİ 4: 200 saat paydası (K7) ve `DAILY_HOURS = 10` (K18)
    mockup'ın SATIRLARINDA birebir tutar."""
    await _mockup_filosu(ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye)

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()

    beklenen_kullanim = {
        "Tower Crane TC-48": "93.0",
        "Ekskavatör CAT 320": "76.0",
        "Beton Pompası BP-36": "21.0",
        "Damperli Kamyon": "84.0",
        "Forklift Linde H30": "0.0",
        "Kompresör SC-200": "72.0",
    }
    for ad, saat, ariza, _, maliyet in MOCKUP_SATIRLAR:
        satir = _satir(govde, ad)
        assert Decimal(satir["hours"]) == Decimal(saat), ad
        assert Decimal(satir["breakdown_hours"]) == Decimal(ariza), ad
        assert Decimal(satir["cost"]) == Decimal(maliyet), ad
        assert satir["usage_pct"] == beklenen_kullanim[ad], ad


# --- K16: uydurma 0 yok ---


@pytest.mark.asyncio
async def test_k16_bedeli_bilinmeyen_makinenin_maliyeti_null(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """Bedeli olmayan makine `cost: null` döner (0 DEĞİL: 0 "bedava çalıştı" derdi)
    ve toplama UYDURMA bir 0 ile GİRMEZ."""
    bedelsiz = await ekipman_fabrikasi("Bedelsiz Vinç", site=gorunen_santiye)
    await kayit_fabrikasi(bedelsiz, hours="10", work_date=date(_YIL, _AY, 3))

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    assert _satir(govde, "Bedelsiz Vinç")["cost"] is None
    assert Decimal(govde["totals"]["cost"]) == Decimal("0")
    assert Decimal(govde["totals"]["hours"]) == Decimal("10"), "saat bilinir, maliyet bilinmez"


@pytest.mark.asyncio
async def test_k16_kapasitesiz_makinede_kullanim_null_ve_gerekceli(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """K16 · yol 4: payda 0 ise kullanım % `null` + `no_capacity_hours`."""
    makine = await ekipman_fabrikasi("Kapasitesiz", site=gorunen_santiye, monthly_capacity_hours=0)
    await kayit_fabrikasi(makine, hours="10", work_date=date(_YIL, _AY, 3))

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Kapasitesiz")
    assert satir["usage_pct"] is None
    assert satir["usage_reason"] == "no_capacity_hours"


# --- Dönem ve kapsam ---


@pytest.mark.asyncio
async def test_baska_ayin_kaydi_toplama_girmez(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    await kayit_fabrikasi(makine, hours="10", work_date=date(_YIL, _AY, 3))
    await kayit_fabrikasi(makine, hours="7", work_date=date(_YIL, _AY + 1, 3))

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    assert Decimal(govde["totals"]["hours"]) == Decimal("10")


@pytest.mark.asyncio
async def test_k20_gorunmeyen_projenin_makinesi_ozete_girmez(
    client, sef_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye, gorunmeyen_santiye
):
    """K20 summary ucunda da koşar: sızıntı tek uçtan olur."""
    gorunen = await ekipman_fabrikasi("Görünen", site=gorunen_santiye)
    gizli = await ekipman_fabrikasi("Gizli", site=gorunmeyen_santiye)
    await kayit_fabrikasi(gorunen, hours="10", work_date=date(_YIL, _AY, 3))
    await kayit_fabrikasi(gizli, hours="9", work_date=date(_YIL, _AY, 3))

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=sef_headers)
    ).json()
    assert [s["equipment_name"] for s in govde["rows"]] == ["Görünen"]
    assert Decimal(govde["totals"]["hours"]) == Decimal("10")


@pytest.mark.asyncio
async def test_k9_kayit_KENDI_santiyesiyle_suzulur(
    client,
    admin_headers,
    ekipman_fabrikasi,
    kayit_fabrikasi,
    gorunen_santiye,
    seeded_db,
    gorunen_proje,
):
    """🔴 K9: `site_id` süzgeci KAYDIN kendi şantiyesine bakar, makinenin
    bugünkü atamasına DEĞİL — yoksa makine taşındığında geçmiş aylar geriye
    dönük başka projeye yazılırdı."""
    from app.modules.sites.models import Site

    eski_santiye = Site(project_id=gorunen_proje.id, code="MK-D", name="D-Blok")
    seeded_db.add(eski_santiye)
    await seeded_db.flush()

    makine = await ekipman_fabrikasi("Gezgin Vinç", site=gorunen_santiye)
    await kayit_fabrikasi(makine, hours="10", work_date=date(_YIL, _AY, 3), site=eski_santiye)
    await kayit_fabrikasi(makine, hours="6", work_date=date(_YIL, _AY, 4))

    eski = (
        await client.get(
            f"/equipment/work-summary?year={_YIL}&month={_AY}&site_id={eski_santiye.id}",
            headers=admin_headers,
        )
    ).json()
    assert Decimal(eski["totals"]["hours"]) == Decimal("10")

    bugunku = (
        await client.get(
            f"/equipment/work-summary?year={_YIL}&month={_AY}&site_id={gorunen_santiye.id}",
            headers=admin_headers,
        )
    ).json()
    assert Decimal(bugunku["totals"]["hours"]) == Decimal("6")


@pytest.mark.asyncio
async def test_kaydi_olmayan_makine_sifir_saatle_listelenir(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye
):
    """M3'ün Forklift satırı: hiç çalışmamış makine tablodan DÜŞMEZ, 0 saatle
    durur — düşseydi "bu ay hiç çalışmayan makine hangisi?" sorusu ekranda
    cevapsız kalırdı."""
    await ekipman_fabrikasi(
        "Forklift Linde H30",
        site=gorunen_santiye,
        status=EquipmentStatus.maintenance,
        rate_amount=Decimal("500"),
        rate_period=EquipmentRatePeriod.daily,
    )
    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Forklift Linde H30")
    assert Decimal(satir["hours"]) == Decimal("0")
    assert Decimal(satir["cost"]) == Decimal("0"), "bedeli BİLİNEN makinenin 0 saati gerçek bir 0"


@pytest.mark.asyncio
async def test_pasif_makine_kaydi_varsa_ozette_kalir(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """Kullanımdan kaldırılmış makinenin GEÇMİŞ maliyeti kaybolmaz; kaydı
    olmayan pasif makine ise tabloyu şişirmez."""
    calisan = await ekipman_fabrikasi("Hurdaya Ayrılan", site=gorunen_santiye, is_active=False)
    await ekipman_fabrikasi("Sessiz Hurda", site=gorunen_santiye, is_active=False)
    await kayit_fabrikasi(calisan, hours="10", work_date=date(_YIL, _AY, 3))

    govde = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    adlar = [s["equipment_name"] for s in govde["rows"]]
    assert "Hurdaya Ayrılan" in adlar
    assert "Sessiz Hurda" not in adlar


# --- Haftalık kovalar (M3:219-243) ---


@pytest.mark.asyncio
async def test_haftalik_kovalar_pazartesi_haftalariyla_kurulur(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """Hafta sınırı = **PAZARTESİ başlangıçlı ISO haftası**, ayın 1'ini içeren
    haftadan sayılır. Temmuz 2026 böylece BEŞ kovaya düşer (M3'ün H1–H5'i).

    Kova sınırları AYA KIRPILIR: kullanıcı "1–5 Temmuz" görür, haziranın son
    günlerini değil.
    """
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    await kayit_fabrikasi(makine, hours="8", work_date=date(2026, 7, 2))  # H1
    await kayit_fabrikasi(makine, hours="5", work_date=date(2026, 7, 8))  # H2
    await kayit_fabrikasi(makine, hours="3", work_date=date(2026, 7, 31))  # H5

    kovalar = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()["weeks"]

    assert [k["index"] for k in kovalar] == [1, 2, 3, 4, 5]
    assert kovalar[0]["start_date"] == "2026-07-01", "kova ayın dışına TAŞMAZ"
    assert kovalar[0]["end_date"] == "2026-07-05"
    assert kovalar[4]["end_date"] == "2026-07-31"
    assert Decimal(kovalar[0]["hours"]) == Decimal("8")
    assert Decimal(kovalar[1]["hours"]) == Decimal("5")
    assert Decimal(kovalar[2]["hours"]) == Decimal("0"), "kayıtsız hafta da kova olarak durur"
    assert Decimal(kovalar[4]["hours"]) == Decimal("3")


@pytest.mark.asyncio
async def test_haftalik_kovada_baskin_kayit_tipi_damgalanir(
    client, admin_headers, ekipman_fabrikasi, kayit_fabrikasi, gorunen_santiye
):
    """M3 barları çalışma/arıza rengiyle boyanıyor → baskın tip SUNUCUDAN gelir
    (F-P10 "rozet sunucu damgasıdır" kanonu). Kayıtsız haftanın tipi `null`."""
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    await kayit_fabrikasi(makine, hours="8", work_date=date(2026, 7, 2))
    await kayit_fabrikasi(
        makine, hours="10", work_date=date(2026, 7, 8), record_type=WorkLogType.breakdown
    )
    await kayit_fabrikasi(makine, hours="4", work_date=date(2026, 7, 9))

    kovalar = (
        await client.get(f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()["weeks"]

    assert kovalar[0]["dominant_record_type"] == "worked"
    assert kovalar[1]["dominant_record_type"] == "breakdown", "10 arıza > 4 çalışma"
    assert kovalar[2]["dominant_record_type"] is None
    assert Decimal(kovalar[1]["hours"]) == Decimal("14"), (
        "kova saati İKİ tipi de sayar (M3 barı günün tamamını gösterir)"
    )


@pytest.mark.asyncio
async def test_gecersiz_ay_422(client, admin_headers):
    yanit = await client.get(f"/equipment/work-summary?year={_YIL}&month=13", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_izinsiz_kullanici_ozeti_goremez_403(client, yetkisiz_headers):
    yanit = await client.get(
        f"/equipment/work-summary?year={_YIL}&month={_AY}", headers=yetkisiz_headers
    )
    assert yanit.status_code == 403, yanit.text
