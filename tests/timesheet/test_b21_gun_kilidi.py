"""PLN-B2.1 (B2-6) — puantaj `PUT …/timesheet/week` gün KİLİDİ portu.

Kural: port YALNIZ GERÇEKTEN DEĞİŞEN günleri sorar (gelen ≠ mevcut: yeni hücre ·
silinen hücre · saat/kod/bölüm farkı). Gövde haftanın TAM kümesidir: kilitli günü
AYNEN geri gönderen istek geçer — bütün hafta sorulsaydı kilitli tek gün bütün
haftayı dondururdu.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.timesheet.models import TimesheetEntry
from tests.site_diary._port import KILIT_METNI
from tests.timesheet.conftest import ISO_HAFTA, ISO_YIL, hafta_gunu

pytestmark = pytest.mark.asyncio


def _hucre(personnel, offset: int, hours: str = "9") -> dict:
    return {
        "personnel_id": str(personnel.id),
        "work_date": hafta_gunu(offset).isoformat(),
        "hours": hours,
    }


async def _kaydet(client: AsyncClient, headers, site_id, cells):
    return await client.put(
        f"/sites/{site_id}/timesheet/week",
        params={"iso_year": ISO_YIL, "iso_week": ISO_HAFTA},
        json={"cells": cells},
        headers=headers,
    )


async def _saatler(session: AsyncSession, site_id) -> dict:
    rows = (
        (await session.execute(select(TimesheetEntry).where(TimesheetEntry.site_id == site_id)))
        .scalars()
        .all()
    )
    return {(r.personnel_id, r.work_date): r.hours for r in rows}


async def test_degismeyen_kilitli_gun_sorun_degil_yalniz_degisen_gun_sorulur(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, port
) -> None:
    # Arrange: Pazartesi (kilitli) ve Salı mevcut.
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(1), admin_kullanicisi, hours=9)
    port.kilitle(santiye.id, hafta_gunu(0))

    # Act: Pazartesi AYNEN, Salı 9 → 11.
    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 0, "9"), _hucre(mehmet, 1, "11")]
    )

    # Assert: yazma yolu değişmeyen kilitli günü ENGEL saymaz (200). PLN-B2.x-B'den beri
    # yanıt (`week.build`) ekran için haftanın 7 gününü porta sorar (`locked_days`), bu
    # yüzden "yalnız değişen gün sorulur" kapısı burada ölçülemez; o kapının bekçisi
    # `tests/earned_value_budget/test_b2x_locked_days.py::test_P5_unchanged_…` (+ MP1).
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["locked_days"] == [hafta_gunu(0).isoformat()]
    assert hafta_gunu(1) in port.sorulan_gunler()


async def test_kilitli_gunu_degistirmek_409_ve_hicbir_sey_yazilmaz(
    client: AsyncClient,
    sef_headers,
    santiye,
    mehmet,
    admin_kullanicisi,
    hucre_fabrikasi,
    port,
    seeded_db: AsyncSession,
) -> None:
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(0), admin_kullanicisi, hours=9)
    port.kilitle(santiye.id, hafta_gunu(0))

    yanit = await _kaydet(
        client, sef_headers, santiye.id, [_hucre(mehmet, 0, "10"), _hucre(mehmet, 2, "8")]
    )

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == KILIT_METNI
    assert await _saatler(seeded_db, santiye.id) == {(mehmet.id, hafta_gunu(0)): Decimal("9.0")}


async def test_kilitli_gunun_hucresini_silmek_de_degisikliktir_409(
    client: AsyncClient, sef_headers, santiye, mehmet, admin_kullanicisi, hucre_fabrikasi, port
) -> None:
    await hucre_fabrikasi(santiye, mehmet, hafta_gunu(3), admin_kullanicisi, hours=9)
    port.kilitle(santiye.id, hafta_gunu(3))

    yanit = await _kaydet(client, sef_headers, santiye.id, [])

    assert yanit.status_code == 409, yanit.text


async def test_kilitli_gune_yeni_hucre_409(
    client: AsyncClient, sef_headers, santiye, mehmet, port
) -> None:
    port.kilitle(santiye.id, hafta_gunu(4))

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 4)])

    assert yanit.status_code == 409, yanit.text


async def test_baska_santiyenin_kilidi_bu_santiyeyi_etkilemez(
    client: AsyncClient, sef_headers, santiye, ikinci_santiye, mehmet, port
) -> None:
    port.kilitle(ikinci_santiye.id, hafta_gunu(0))

    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 0)])

    assert yanit.status_code == 200, yanit.text


async def test_kayit_yokken_bugunku_davranis(
    client: AsyncClient, sef_headers, santiye, mehmet, port, seeded_db: AsyncSession
) -> None:
    """Port BOŞ (modülsüz kurulum): kilit kavramı yoktur, yazma aynen geçer."""
    yanit = await _kaydet(client, sef_headers, santiye.id, [_hucre(mehmet, 0)])

    assert yanit.status_code == 200, yanit.text
    assert await _saatler(seeded_db, santiye.id) == {(mehmet.id, hafta_gunu(0)): Decimal("9.0")}
