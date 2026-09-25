"""PLN-B2.x-B — puantaj haftası yanıtında `locked_days[]` (çekirdek → `day_hooks` portu).

Çekirdek (timesheet) EV'yi IMPORT ETMEZ; kilit bilgisi portun kayıtlı `DayLockCheck`inden
gelir. Port boşsa (modülsüz kurulum) liste boştur. Kurgu: `saha_gunu` 05.05.2026 (ISO
hafta 19) onaylanır → B2 kilidi o güne kadar olan günleri kilitler.
"""

from __future__ import annotations

from datetime import date

from app.core import day_hooks
from app.modules.site_diary.models import DiaryStatus

from .conftest import DAY
from .test_reports import _allocate, _rep

ISO_YEAR, ISO_WEEK, _ = DAY.isocalendar()


def _week(site) -> str:  # noqa: ANN001
    return f"/sites/{site.id}/timesheet/week"


async def _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu) -> None:  # noqa: ANN001
    await _allocate(client, saha, santiye, boq, saha_gunu)
    saha_gunu["diary"].status = DiaryStatus.submitted
    await seeded_db.flush()
    ok = await client.post(_rep(santiye, f"/daily/{DAY.isoformat()}/approve"), headers=sef)
    assert ok.status_code == 200, ok.text


async def test_week_reports_locked_days_from_port(
    client, sef, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    params = {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
    before = await client.get(_week(santiye), headers=admin, params=params)
    assert before.status_code == 200, before.text
    assert before.json()["locked_days"] == []
    await _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu)
    after = (await client.get(_week(santiye), headers=admin, params=params)).json()
    locked = [date.fromisoformat(d) for d in after["locked_days"]]
    assert DAY in locked
    assert all(d <= DAY for d in locked)  # onay o güne KADAR kilitler, sonrası açık
    assert date(2026, 5, 6) not in locked


async def test_week_locked_days_empty_without_port(
    client, sef, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu)
    snapshot = day_hooks.registered()
    day_hooks.unregister_all()
    try:
        resp = await client.get(
            _week(santiye), headers=admin, params={"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
        )
    finally:
        day_hooks.restore(snapshot)
    assert resp.status_code == 200 and resp.json()["locked_days"] == []


# --- P5 (spec §3.14): kilitli günü DEĞİŞMEDEN taşıyan PUT no-op; değişirse 409 + liste ---

FREE_DAY = date(2026, 5, 6)


def _cell(person, day: date, hours: str) -> dict:  # noqa: ANN001
    return {"personnel_id": str(person.id), "work_date": day.isoformat(), "hours": hours}


async def _put(client, headers, site, cells: list[dict]):  # noqa: ANN001, ANN202
    return await client.put(
        _week(site),
        params={"iso_year": ISO_YEAR, "iso_week": ISO_WEEK},
        json={"cells": cells},
        headers=headers,
    )


async def _hours_by_cell(client, headers, site) -> dict[tuple[str, str], str]:  # noqa: ANN001
    week = (
        await client.get(
            _week(site), headers=headers, params={"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
        )
    ).json()
    return {
        (row["personnel_id"], cell["work_date"]): cell["hours"]
        for row in week["rows"]
        for cell in row["cells"]
        if cell["hours"] is not None
    }


async def test_P5_unchanged_locked_day_is_noop_and_free_day_is_written(
    client, sef, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu)
    ali, veli = saha_gunu["ali"], saha_gunu["veli"]
    body = [_cell(ali, DAY, "9"), _cell(veli, DAY, "8"), _cell(ali, FREE_DAY, "9")]
    resp = await _put(client, sef, santiye, body)
    assert resp.status_code == 200, resp.text
    hours = await _hours_by_cell(client, admin, santiye)
    assert hours[(str(ali.id), FREE_DAY.isoformat())] is not None


async def test_P5_changed_locked_day_is_409_with_locked_days_and_atomic(
    client, sef, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu)
    ali, veli = saha_gunu["ali"], saha_gunu["veli"]
    before = await _hours_by_cell(client, admin, santiye)
    body = [_cell(ali, DAY, "11"), _cell(veli, DAY, "8"), _cell(ali, FREE_DAY, "9")]
    resp = await _put(client, sef, santiye, body)
    assert resp.status_code == 409, resp.text
    locked = resp.json()["locked_days"]
    assert DAY.isoformat() in locked and FREE_DAY.isoformat() not in locked
    assert all(date.fromisoformat(d) <= DAY for d in locked)
    assert await _hours_by_cell(client, admin, santiye) == before  # serbest gün de YAZILMADI


async def test_P5_dropping_locked_cell_counts_as_change(
    client, sef, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(client, sef, saha, seeded_db, santiye, boq, saha_gunu)
    resp = await _put(client, sef, santiye, [_cell(saha_gunu["ali"], DAY, "9")])  # Veli yok
    assert resp.status_code == 409 and DAY.isoformat() in resp.json()["locked_days"]
