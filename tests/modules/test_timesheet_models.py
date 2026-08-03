"""T1 — `personnel` / `timesheet_entries` modelleri ve DB kisitlari (puantaj spec §2).

Router/servis YOKTUR (T2-T4) — burada yalnizca semanin vaat ettigi kisitlar
dogrulanir: kisi-gun tekligi, FM saat araligi, taseron bagi CHECK'i ve
puantaji olan personelin silinemezligi.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.modules.contracts.models import Subcontractor
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource
from app.modules.sites.models import Site
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry


async def _site(session, project, code: str = "PT-BLOK") -> Site:
    site = Site(project_id=project.id, code=code, name="Puantaj Şantiyesi")
    session.add(site)
    await session.flush()
    return site


async def _personnel(session, **kwargs) -> Personnel:
    defaults = {
        "full_name": "Ahmet Yılmaz",
        "trade": "Kalıpçı",
        "source": WorkerSource.company,
    }
    defaults.update(kwargs)
    person = Personnel(**defaults)
    session.add(person)
    await session.flush()
    return person


def _entry(person: Personnel, site: Site, user, day: date, **kwargs) -> TimesheetEntry:
    defaults = {"code": TimesheetCode.worked}
    defaults.update(kwargs)
    return TimesheetEntry(
        personnel_id=person.id,
        site_id=site.id,
        project_id=site.project_id,
        work_date=day,
        created_by=user.id,
        **defaults,
    )


async def test_personnel_defaults(db_session):
    person = await _personnel(db_session)

    loaded = (
        await db_session.execute(select(Personnel).where(Personnel.id == person.id))
    ).scalar_one()
    assert loaded.is_active is True
    assert loaded.subcontractor_id is None
    # Login SART DEGIL: isci bir `users` kaydi olmadan da var olur.
    assert loaded.user_id is None


async def test_personnel_non_subcontractor_source_cannot_have_subcontractor(db_session):
    firma = Subcontractor(name="Akın İnşaat")
    db_session.add(firma)
    await db_session.flush()

    db_session.add(
        Personnel(
            full_name="Mehmet Demir",
            source=WorkerSource.company,
            subcontractor_id=firma.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_personnel_subcontractor_source_may_have_no_subcontractor(db_session):
    """Ters yon ZORLANMAZ (spec §2) — taslak esnekligi."""
    person = await _personnel(db_session, source=WorkerSource.subcontractor)
    assert person.subcontractor_id is None


async def test_person_can_have_only_one_entry_per_day(db_session, project_factory, user_factory):
    project = await project_factory("P-PT-1")
    site_a = await _site(db_session, project, code="PT-A")
    site_b = await _site(db_session, project, code="PT-B")
    user = await user_factory("pt1@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    db_session.add(_entry(person, site_a, user, date(2026, 8, 3)))
    await db_session.flush()

    # Ayni gun BASKA santiyede ikinci kayit: santiye cakismasi UQ ile duser.
    db_session.add(_entry(person, site_b, user, date(2026, 8, 3)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize("hours", [Decimal("0"), Decimal("-1.0"), Decimal("24.5")])
async def test_overtime_hours_out_of_range_rejected(
    db_session, project_factory, user_factory, hours
):
    project = await project_factory("P-PT-2")
    site = await _site(db_session, project)
    user = await user_factory("pt2@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    db_session.add(
        _entry(
            person, site, user, date(2026, 8, 3), code=TimesheetCode.overtime, overtime_hours=hours
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_overtime_hours_optional(db_session, project_factory, user_factory):
    """FM hucresinde saat OPSIYONELDIR (spec §7 S2)."""
    project = await project_factory("P-PT-3")
    site = await _site(db_session, project)
    user = await user_factory("pt3@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    entry = _entry(person, site, user, date(2026, 8, 3), code=TimesheetCode.overtime)
    db_session.add(entry)
    await db_session.flush()
    assert entry.overtime_hours is None


async def test_personnel_with_entries_cannot_be_deleted(db_session, project_factory, user_factory):
    project = await project_factory("P-PT-4")
    site = await _site(db_session, project)
    user = await user_factory("pt4@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)
    db_session.add(_entry(person, site, user, date(2026, 8, 3)))
    await db_session.flush()

    # RESTRICT: silme YOK (spec §3) — pasiflestirme `is_active=false` iledir.
    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Personnel).where(Personnel.id == person.id))
