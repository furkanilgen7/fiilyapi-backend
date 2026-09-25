"""EV-BORC-4 — puantaj kilidinin HANGİ raporla konduğu: `day_locks: [{day, report_date}]`.

Mockup: "25.09.2026 raporuyla kilitli". Kilit gün bazında açılabildiği için kilitli günler
ARDIŞIK olmayabilir ve FARKLI raporlara bağlı olabilir. Çekirdek (timesheet) EV import ETMEZ:
rapor tarihi port kaydına (`register_day_lock(check, report_date=…)`) iliştirilir.

Kurgu (ISO hafta 19 = 04–10.05.2026):
* onay B: rapor 07.05, 2 sa önce → ≤ 07.05 kilitler
* onay A: rapor 04.05, 1 sa önce → 04.05 için EN SON onay A (kilit = en son onay, B2)
* 05.05 kilidi SONRADAN açıldı (istisna B'yi ezer)
⇒ 04.05 → rapor 04.05 · 05.05 AÇIK · 06.05 → rapor 07.05 · 07.05 → rapor 07.05
(ardışık değil, iki farklı rapor; 06.05'te rapor tarihi GÜNDEN FARKLI — "rapor = gün" hatası
yakalanır)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.core import day_hooks
from app.modules.earned_value.models import EvDayUnlock, EvReportApproval

from .conftest import DAY

ISO_YEAR, ISO_WEEK, _ = DAY.isocalendar()
D4, D5, D6, D7 = date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7)
EXPECTED = [
    {"day": "2026-05-04", "report_date": "2026-05-04"},
    {"day": "2026-05-06", "report_date": "2026-05-07"},
    {"day": "2026-05-07", "report_date": "2026-05-07"},
]
LOCKED = ["2026-05-04", "2026-05-06", "2026-05-07"]


def _week(site) -> str:  # noqa: ANN001
    return f"/sites/{site.id}/timesheet/week"


async def _iki_raporla_kilitle(seeded_db, site) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    seeded_db.add_all(
        [
            EvReportApproval(site_id=site.id, report_date=D7, approved_at=now - timedelta(hours=2)),
            EvReportApproval(site_id=site.id, report_date=D4, approved_at=now - timedelta(hours=1)),
        ]
    )
    await seeded_db.flush()
    seeded_db.add(EvDayUnlock(site_id=site.id, day=D5, reason="düzeltme", unlocked_at=now))
    await seeded_db.flush()


async def test_week_day_locks_carry_their_own_report_dates(
    client, admin, seeded_db, santiye, baseline, saha_gunu
) -> None:
    await _iki_raporla_kilitle(seeded_db, santiye)
    week = await client.get(
        _week(santiye), headers=admin, params={"iso_year": ISO_YEAR, "iso_week": ISO_WEEK}
    )
    assert week.status_code == 200, week.text
    body = week.json()
    assert body["day_locks"] == EXPECTED
    assert body["locked_days"] == LOCKED  # gün kolonu AYNEN


async def test_p5_409_body_carries_day_locks(
    client, sef, seeded_db, santiye, baseline, saha_gunu
) -> None:
    await _iki_raporla_kilitle(seeded_db, santiye)
    ali, veli = saha_gunu["ali"], saha_gunu["veli"]

    def cell(person, day: date, hours: str) -> dict:  # noqa: ANN001
        return {"personnel_id": str(person.id), "work_date": day.isoformat(), "hours": hours}

    resp = await client.put(
        _week(santiye),
        params={"iso_year": ISO_YEAR, "iso_week": ISO_WEEK},
        json={"cells": [cell(ali, D5, "9"), cell(veli, D5, "8"), cell(ali, D6, "9")]},
        headers=sef,
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert "07.05.2026" in body["detail"]  # detail AYNEN (kilidi koyan raporun metni)
    assert body["locked_days"] == LOCKED
    assert body["day_locks"] == EXPECTED


async def test_port_lock_without_reporter_gives_none_report_date() -> None:
    """Rapor sağlayıcısı olmayan (eski imzalı) kilit kontrolü: gün kilitli, rapor None."""
    snapshot = day_hooks.registered()
    day_hooks.unregister_all()

    async def kilitli(_session, _site_id, day):  # noqa: ANN001, ANN202
        return "kilitli" if day == D4 else None

    try:
        day_hooks.register_day_lock(kilitli)
        locks = await day_hooks.day_locks(None, uuid.uuid4(), [D4, D5])  # type: ignore[arg-type]
    finally:
        day_hooks.restore(snapshot)
    assert locks == [day_hooks.DayLock(D4, None)]
