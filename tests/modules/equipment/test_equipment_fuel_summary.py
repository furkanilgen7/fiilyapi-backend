"""MK-1 T5 — `GET /equipment/fuel-summary` (M4 üst blok + tablo).

Kilitlenen kararlar: **K15** (toplamlar SATIRLARDAN türer) · **K16** (dört
fail-closed `null` yolu, burada özellikle `lt_km` ve payda-sıfır) · **K17**
(rozet eşikleri + sunucu damgası) · **K19** (para/oran yuvarlaması) · **K20**
(görünürlük) · M4:39 filo tüketimi (`2.840 / 428 lt/saat = 6,6`).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.equipment.models import (
    EquipmentFuelLog,
    EquipmentNormUnit,
    EquipmentWorkLog,
    WorkLogType,
)

_YIL = 2026
_AY = 8


@pytest.fixture
def yakit_fabrikasi(seeded_db):
    async def _create(equipment, *, liters: str, unit_price: str, fuel_date: date, site=None):
        log = EquipmentFuelLog(
            equipment_id=equipment.id,
            fuel_date=fuel_date,
            site_id=equipment.site_id if site is None else site.id,
            liters=Decimal(liters),
            unit_price=Decimal(unit_price),
        )
        seeded_db.add(log)
        await seeded_db.flush()
        return log

    return _create


@pytest.fixture
def calisma_fabrikasi(seeded_db):
    async def _create(equipment, *, hours: str, work_date: date, site=None):
        log = EquipmentWorkLog(
            equipment_id=equipment.id,
            work_date=work_date,
            site_id=equipment.site_id if site is None else site.id,
            record_type=WorkLogType.worked,
            hours=Decimal(hours),
        )
        seeded_db.add(log)
        await seeded_db.flush()
        return log

    return _create


def _satir(govde: dict, ad: str) -> dict:
    return next(s for s in govde["rows"] if s["equipment_name"] == ad)


async def _dagit(calisma_fabrikasi, equipment, toplam: Decimal, ilk_gun: int) -> None:
    """Toplam saati `equipment_work_logs`in günlük 24 saat tavanına (K12)
    ÇARPMAYACAK şekilde 20'şer saatlik dilimlere böler."""
    gun = ilk_gun
    kalan = toplam
    while kalan > 0:
        dilim = min(kalan, Decimal("20"))
        await calisma_fabrikasi(equipment, hours=str(dilim), work_date=date(_YIL, _AY, gun))
        kalan -= dilim
        gun += 1


# --- M4:39 — filo tüketimi AYNI formülü paylaşır ---


@pytest.mark.asyncio
async def test_m4_39_filo_tuketimi_2840_bolu_428(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, calisma_fabrikasi, gorunen_santiye
):
    """🔴 M4:39: `2.840 lt / 428 saat = 6,6 Lt/saat` — payda ÇALIŞMA KAYDI saat
    toplamıdır (modüller arası bağ)."""
    a = await ekipman_fabrikasi("Vinç A", site=gorunen_santiye)
    b = await ekipman_fabrikasi("Vinç B", site=gorunen_santiye)
    await yakit_fabrikasi(a, liters="1500", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await yakit_fabrikasi(b, liters="1340", unit_price="10", fuel_date=date(_YIL, _AY, 3))
    await _dagit(calisma_fabrikasi, a, Decimal("220"), 1)
    await _dagit(calisma_fabrikasi, b, Decimal("208"), 1)

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()

    assert Decimal(govde["total_liters"]) == Decimal("2840")
    assert Decimal(govde["lt_per_hour_avg"]) == Decimal("6.6")


@pytest.mark.asyncio
async def test_payda_sifirsa_lt_per_hour_avg_null(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, gorunen_santiye
):
    """🔴 K16: dönemde HİÇ çalışma kaydı yoksa (payda 0) `lt_per_hour_avg`
    UYDURMA bir sayı DEĞİL, `null`dur."""
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    await yakit_fabrikasi(makine, liters="100", unit_price="10", fuel_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    assert govde["lt_per_hour_avg"] is None
    assert Decimal(govde["total_liters"]) == Decimal("100"), "litre bilinir, ORAN bilinmez"


# --- K19: satır bazlı para yuvarlaması, TOPLAMDAN türer ---


@pytest.mark.asyncio
async def test_k19_dort_satirin_yuvarlamasi_ve_k15_toplam(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, gorunen_santiye
):
    """🔴 K19: `45×39,70=1.786,5→₺1.787` ve `62×39,70=2.461,4→₺2.461` — dört
    satır TEK TEK yuvarlanır, toplam SATIRLARIN toplamıdır (K15)."""
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    satirlar = [
        ("45", "39.70", "1787"),
        ("62", "39.70", "2461"),
        ("30", "39.70", "1191"),
        ("20", "39.70", "794"),
    ]
    gun = 1
    beklenen_toplam = Decimal("0")
    for litre, fiyat, beklenen in satirlar:
        await yakit_fabrikasi(
            makine, liters=litre, unit_price=fiyat, fuel_date=date(_YIL, _AY, gun)
        )
        beklenen_toplam += Decimal(beklenen)
        gun += 1

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Vinç")
    assert Decimal(satir["amount"]) == beklenen_toplam
    assert Decimal(govde["total_amount"]) == beklenen_toplam


# --- K16: dört fail-closed `null` yolu ---


@pytest.mark.asyncio
async def test_k16_lt_km_ekipaninda_sapma_null_ve_gerekceli(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, calisma_fabrikasi, gorunen_santiye
):
    """🔴 K16 · yol 1: `norm_unit=lt_km` → kilometre verisi HİÇBİR ekranda
    girilmez, sapma `null` + `deviation_reason="no_distance_data"`. `actual`
    (Lt/saat) YİNE de doldurulur — girilmiş yakıt ekrandan silinmez."""
    makine = await ekipman_fabrikasi(
        "Kamyon",
        site=gorunen_santiye,
        norm_consumption=Decimal("5"),
        norm_unit=EquipmentNormUnit.lt_km,
    )
    await yakit_fabrikasi(makine, liters="100", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(makine, hours="10", work_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Kamyon")
    assert satir["deviation_pct"] is None
    assert satir["deviation_reason"] == "no_distance_data"
    assert satir["consumption_status"] is None
    assert Decimal(satir["actual"]) == Decimal("10.0"), "Lt/saat bilinen bir OLGUDUR, gizlenmez"


@pytest.mark.asyncio
async def test_k16_norm_yoksa_sapma_null(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, calisma_fabrikasi, gorunen_santiye
):
    """🔴 K16 · yol 2: `norm_consumption` yoksa karşılaştıracak ölçüt yoktur."""
    makine = await ekipman_fabrikasi("Normsuz Vinç", site=gorunen_santiye)
    await yakit_fabrikasi(makine, liters="50", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(makine, hours="10", work_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Normsuz Vinç")
    assert satir["deviation_pct"] is None
    assert satir["deviation_reason"] == "no_norm_consumption"
    assert satir["norm"] is None


@pytest.mark.asyncio
async def test_k16_calisma_kaydi_yoksa_actual_null(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, gorunen_santiye
):
    """🔴 K16 · yol 3: yakıt alınmış ama çalışma kaydı YOK (saat 0) → fiili
    tüketim `null` (sıfıra bölme yerine 0 basmak "hiç yakmadı" derdi)."""
    makine = await ekipman_fabrikasi(
        "Kayıtsız Vinç",
        site=gorunen_santiye,
        norm_consumption=Decimal("4"),
        norm_unit=EquipmentNormUnit.lt_hour,
    )
    await yakit_fabrikasi(makine, liters="50", unit_price="10", fuel_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    satir = _satir(govde, "Kayıtsız Vinç")
    assert satir["actual"] is None
    assert satir["deviation_pct"] is None
    assert satir["deviation_reason"] == "no_work_hours"


# --- K17: rozet eşikleri, sunucu damgası ---


@pytest.mark.asyncio
async def test_k17_esikler_normal_warning_critical(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, calisma_fabrikasi, gorunen_santiye
):
    """`dev ≤ 0` normal · `0 < dev < 10` warning · `dev ≥ 10` critical."""
    normal = await ekipman_fabrikasi(
        "Normal",
        site=gorunen_santiye,
        norm_consumption=Decimal("5"),
        norm_unit=EquipmentNormUnit.lt_hour,
    )
    uyari = await ekipman_fabrikasi(
        "Uyarı",
        site=gorunen_santiye,
        norm_consumption=Decimal("5"),
        norm_unit=EquipmentNormUnit.lt_hour,
    )
    kritik = await ekipman_fabrikasi(
        "Kritik",
        site=gorunen_santiye,
        norm_consumption=Decimal("5"),
        norm_unit=EquipmentNormUnit.lt_hour,
    )
    # normal: 50/10 = 5 Lt/saat (norm ile aynı, sapma 0)
    await yakit_fabrikasi(normal, liters="50", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(normal, hours="10", work_date=date(_YIL, _AY, 2))
    # uyarı: 53/10 = 5.3 Lt/saat → %6 sapma (0 < 6 < 10)
    await yakit_fabrikasi(uyari, liters="53", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(uyari, hours="10", work_date=date(_YIL, _AY, 2))
    # kritik: 60/10 = 6 Lt/saat → %20 sapma (>= 10)
    await yakit_fabrikasi(kritik, liters="60", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(kritik, hours="10", work_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    assert _satir(govde, "Normal")["consumption_status"] == "normal"
    assert _satir(govde, "Uyarı")["consumption_status"] == "warning"
    assert _satir(govde, "Kritik")["consumption_status"] == "critical"
    assert govde["abnormal_count"] == 2, "yalnız warning+critical sayılır"


# --- K20: görünürlük ---


@pytest.mark.asyncio
async def test_k20_gorunmeyen_projenin_makinesi_ozete_girmez(
    client, sef_headers, ekipman_fabrikasi, yakit_fabrikasi, gorunen_santiye, gorunmeyen_santiye
):
    gorunen = await ekipman_fabrikasi("Görünen", site=gorunen_santiye)
    gizli = await ekipman_fabrikasi("Gizli", site=gorunmeyen_santiye)
    await yakit_fabrikasi(gorunen, liters="10", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await yakit_fabrikasi(gizli, liters="9", unit_price="10", fuel_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=sef_headers)
    ).json()
    assert [s["equipment_name"] for s in govde["rows"]] == ["Görünen"]
    assert Decimal(govde["total_liters"]) == Decimal("10")


# --- `equipment_id` süzgeci ---


@pytest.mark.asyncio
async def test_equipment_id_suzgeci_tek_makineye_indirir(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, calisma_fabrikasi, gorunen_santiye
):
    a = await ekipman_fabrikasi("A", site=gorunen_santiye)
    b = await ekipman_fabrikasi("B", site=gorunen_santiye)
    await yakit_fabrikasi(a, liters="10", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await yakit_fabrikasi(b, liters="20", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await calisma_fabrikasi(a, hours="5", work_date=date(_YIL, _AY, 2))

    govde = (
        await client.get(
            f"/equipment/fuel-summary?year={_YIL}&month={_AY}&equipment_id={a.id}",
            headers=admin_headers,
        )
    ).json()
    assert [s["equipment_name"] for s in govde["rows"]] == ["A"]
    assert Decimal(govde["total_liters"]) == Decimal("10")
    assert Decimal(govde["lt_per_hour_avg"]) == Decimal("2.0")


# --- Dönem ---


@pytest.mark.asyncio
async def test_baska_ayin_kaydi_toplama_girmez(
    client, admin_headers, ekipman_fabrikasi, yakit_fabrikasi, gorunen_santiye
):
    makine = await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    await yakit_fabrikasi(makine, liters="10", unit_price="10", fuel_date=date(_YIL, _AY, 2))
    await yakit_fabrikasi(makine, liters="7", unit_price="10", fuel_date=date(_YIL, _AY + 1, 2))

    govde = (
        await client.get(f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=admin_headers)
    ).json()
    assert Decimal(govde["total_liters"]) == Decimal("10")


@pytest.mark.asyncio
async def test_gecersiz_ay_422(client, admin_headers):
    yanit = await client.get(f"/equipment/fuel-summary?year={_YIL}&month=13", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_izinsiz_kullanici_ozeti_goremez_403(client, yetkisiz_headers):
    yanit = await client.get(
        f"/equipment/fuel-summary?year={_YIL}&month={_AY}", headers=yetkisiz_headers
    )
    assert yanit.status_code == 403, yanit.text
