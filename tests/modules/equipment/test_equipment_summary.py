"""MK-1 T3 — `GET /equipment/summary` (M1 KPI'ları).

Kilitlenen kararlar: **K21** (mockup ÜÇ durum çiziyor, sunucu DÖRDÜNÜ verir) ·
**K15** (`monthly_cost` SATIRLARDAN türer, mockup'ın ₺124K'sı kopyalanmaz) ·
**K18** (maliyet formülü `cost.py`dedir, ikinci kez yazılmaz) · **K16**
(bedeli bilinmeyen makine maliyete UYDURMA 0 ile girmez).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.equipment.models import (
    EquipmentRatePeriod,
    EquipmentStatus,
    EquipmentWorkLog,
    WorkLogType,
)

#: 🔴 M1 KPI kartının bastığı sayı (M3 tfoot'unun ₺124.800'ü). Sunucu bu sayıyı
#: ASLA üretmemelidir — mockup'ın tfoot'u KENDİ satırlarıyla tutarsızdır (K15).
MOCKUP_AYLIK_MALIYET = Decimal("124800")


def _ayin_ici(gun: int = 15) -> date:
    """Cari ayın içinde, ay sonu taşmayan bir gün."""
    bugun = date.today()
    return bugun.replace(day=min(gun, bugun.day if bugun.day > 1 else 28))


@pytest.fixture
def kayit_fabrikasi(seeded_db):
    async def _create(
        equipment,
        *,
        hours: str,
        work_date: date | None = None,
        record_type: WorkLogType = WorkLogType.worked,
        site=None,
    ) -> EquipmentWorkLog:
        log = EquipmentWorkLog(
            equipment_id=equipment.id,
            work_date=work_date or _ayin_ici(),
            site_id=equipment.site_id if site is None else site.id,
            record_type=record_type,
            hours=Decimal(hours),
        )
        seeded_db.add(log)
        await seeded_db.flush()
        return log

    return _create


@pytest.mark.asyncio
async def test_dort_durum_sayaci_doner(client, admin_headers, ekipman_fabrikasi, gorunen_santiye):
    """🔴 K21: mockup üç rozet çiziyor (Çalışıyor/Arızalı/Bakımda) ama
    `idle` DÖRDÜNCÜ bir durumdur ve sayılmazsa filo toplamı tutmaz."""
    await ekipman_fabrikasi("A", site=gorunen_santiye, status=EquipmentStatus.working)
    await ekipman_fabrikasi("B", site=gorunen_santiye, status=EquipmentStatus.working)
    await ekipman_fabrikasi("C", site=gorunen_santiye, status=EquipmentStatus.broken)
    await ekipman_fabrikasi("D", site=gorunen_santiye, status=EquipmentStatus.maintenance)
    await ekipman_fabrikasi("E", site=gorunen_santiye, status=EquipmentStatus.idle)

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["working"] == 2
    assert govde["broken"] == 1
    assert govde["maintenance"] == 1
    assert govde["idle"] == 1


@pytest.mark.asyncio
async def test_pasif_ekipman_sayaclara_girmez(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye
):
    """Pasifleştirme SİLMENİN yerine geçer (spec §2.1); kullanımdan kaldırılmış
    bir makineyi "Aktif Çalışıyor" saymak KPI'ı yalan söyletirdi."""
    await ekipman_fabrikasi("Aktif", site=gorunen_santiye, status=EquipmentStatus.working)
    await ekipman_fabrikasi(
        "Hurda", site=gorunen_santiye, status=EquipmentStatus.working, is_active=False
    )

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert yanit.json()["working"] == 1


@pytest.mark.asyncio
async def test_aylik_maliyet_satirlardan_turer_mockup_kopyalanmaz(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye, kayit_fabrikasi
):
    """🔴 K15 + K18: 3.200 ₺/gün → 320 ₺/saat (`DAILY_HOURS = 10`);
    186 saat → ₺59.520 (M1 Tower Crane satırıyla birebir).

    Sunucu mockup'ın ₺124K KPI'ını KOPYALAMAZ; satırlardan toplar.
    """
    vinc = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        rate_amount=Decimal("3200.00"),
        rate_period=EquipmentRatePeriod.daily,
    )
    # Tek kaydın tavanı 24 saattir (DB CHECK), 186 saat sekiz kayda bölünür.
    for saat in ("24", "24", "24", "24", "24", "24", "24", "18"):  # toplam 186 saat
        await kayit_fabrikasi(vinc, hours=saat)

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    maliyet = Decimal(yanit.json()["monthly_cost"])
    assert maliyet == Decimal("59520")
    assert maliyet != MOCKUP_AYLIK_MALIYET


@pytest.mark.asyncio
async def test_aylik_maliyet_yalniz_cari_ayi_toplar(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye, kayit_fabrikasi
):
    """ "Aylık maliyet" cari aydır: geçmiş ay dahil edilseydi KPI her ay birikerek
    büyür ve hiçbir zaman düşmezdi."""
    vinc = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        rate_amount=Decimal("320.00"),
        rate_period=EquipmentRatePeriod.hourly,
    )
    await kayit_fabrikasi(vinc, hours="10")
    gecen_ay = date.today().replace(day=1) - timedelta(days=1)
    await kayit_fabrikasi(vinc, hours="20", work_date=gecen_ay)

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert Decimal(yanit.json()["monthly_cost"]) == Decimal("3200")


@pytest.mark.asyncio
async def test_ariza_kaydi_maliyete_girmez(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye, kayit_fabrikasi
):
    """K10: arıza AYRI kayıt tipidir; M3 onu ayrı sütunda sayar ve satır
    maliyetine katmaz (₺ sütunu çalışma saatinden üretilir)."""
    vinc = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        rate_amount=Decimal("320.00"),
        rate_period=EquipmentRatePeriod.hourly,
    )
    await kayit_fabrikasi(vinc, hours="10")
    await kayit_fabrikasi(vinc, hours="8", record_type=WorkLogType.breakdown)

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert Decimal(yanit.json()["monthly_cost"]) == Decimal("3200")


@pytest.mark.asyncio
async def test_bedeli_bilinmeyen_makine_maliyete_sifir_olarak_girmez(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye, kayit_fabrikasi
):
    """K16 fail-closed: bedeli/dönemi olmayan makine UYDURMA bir 0 ile toplama
    girmez; bilinen makinelerin maliyeti bundan ETKİLENMEZ."""
    bedelsiz = await ekipman_fabrikasi("Bedelsiz", site=gorunen_santiye)
    await kayit_fabrikasi(bedelsiz, hours="20")
    bilinen = await ekipman_fabrikasi(
        "Bilinen",
        site=gorunen_santiye,
        rate_amount=Decimal("100.00"),
        rate_period=EquipmentRatePeriod.hourly,
    )
    await kayit_fabrikasi(bilinen, hours="10")

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert Decimal(yanit.json()["monthly_cost"]) == Decimal("1000")


@pytest.mark.asyncio
async def test_aylik_bedelde_payda_ekipmanin_kapasitesidir(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye, kayit_fabrikasi
):
    """K7: `monthly_capacity_hours` VERİDİR (varsayılan 200), koda gömülü sabit
    değil — 40.000 ₺/ay ÷ 200 sa = 200 ₺/sa; 10 saat → ₺2.000."""
    makine = await ekipman_fabrikasi(
        "Aylık Kiralık",
        site=gorunen_santiye,
        rate_amount=Decimal("40000.00"),
        rate_period=EquipmentRatePeriod.monthly,
    )
    await kayit_fabrikasi(makine, hours="10")

    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert Decimal(yanit.json()["monthly_cost"]) == Decimal("2000")


@pytest.mark.asyncio
async def test_kayit_yokken_maliyet_sifirdir(client, admin_headers):
    yanit = await client.get("/equipment/summary", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["monthly_cost"]) == Decimal("0")
    assert govde == {
        "working": 0,
        "broken": 0,
        "maintenance": 0,
        "idle": 0,
        "monthly_cost": govde["monthly_cost"],
    }
