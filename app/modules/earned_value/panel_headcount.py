"""Panel isci histogrami — gunluk KISI SAYIMI (spec §3.13 histogram; CEO inceltmesi).

Kisi = puantajda o gun SAATI olan personel + gunlukteki taseron FIRMA satirinin kisi
sayisi (B2-5: `subcontractor_id` + `hours` dolu satir — dagitim izgarasiyla ayni kaynak,
`diary_adapter.source_rows`). Yuklenici tipi: personel `source = subcontractor` → taseron,
digeri kendi; gunluk firma satiri daima taseron. Disipline atanamaz (disiplin filtresinde
panel ESDEGER kisiye gecer — `report_panel`).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.earned_value.engine import ContractorType
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryWorkerCount, WorkerSource
from app.modules.timesheet.models import TimesheetEntry


async def daily_headcount(
    session: AsyncSession,
    site_id: uuid.UUID,
    start: date,
    end: date,
    contractor: ContractorType | None,
) -> dict[date, int]:
    """[start, end] gun → kisi sayisi (iki gruplu sorgu; gun basina sorgu YOK)."""
    out: dict[date, int] = defaultdict(int)
    is_sub = Personnel.source == WorkerSource.subcontractor
    people = (
        select(TimesheetEntry.work_date, func.count())
        .join(Personnel, Personnel.id == TimesheetEntry.personnel_id)
        .where(
            TimesheetEntry.site_id == site_id,
            TimesheetEntry.work_date.between(start, end),
            TimesheetEntry.hours.is_not(None),
        )
        .group_by(TimesheetEntry.work_date)
    )
    if contractor is ContractorType.OWN:
        people = people.where(~is_sub)
    elif contractor is ContractorType.SUBCON:
        people = people.where(is_sub)
    for day, n in (await session.execute(people)).all():
        out[day] += n
    if contractor is ContractorType.OWN:
        return dict(out)
    firms = (
        select(SiteDiaryEntry.entry_date, func.sum(SiteDiaryWorkerCount.count))
        .join(SiteDiaryEntry, SiteDiaryEntry.id == SiteDiaryWorkerCount.entry_id)
        .where(
            SiteDiaryEntry.site_id == site_id,
            SiteDiaryEntry.entry_date.between(start, end),
            SiteDiaryWorkerCount.subcontractor_id.is_not(None),
            SiteDiaryWorkerCount.hours.is_not(None),
        )
        .group_by(SiteDiaryEntry.entry_date)
    )
    for day, n in (await session.execute(firms)).all():
        out[day] += int(n or 0)
    return dict(out)
