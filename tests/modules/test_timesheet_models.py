"""T1 — `personnel` / `timesheet_entries` modelleri ve DB kisitlari (puantaj spec §2).

Router/servis YOKTUR (T2-T4) — burada yalnizca semanin vaat ettigi kisitlar
dogrulanir: kisi-gun tekligi, SAAT araligi, **saat XOR kod** sozlesmesi,
kalkan kodlarin geri sizamamasi, taseron bagi CHECK'i ve puantaji olan
personelin silinemezligi.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError

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
    defaults = {"hours": Decimal("9.0")}
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
async def test_hours_out_of_range_rejected(db_session, project_factory, user_factory, hours):
    """`0 < saat <= 24`. "0 saat calisti" bir hucre DEGIL, hucrenin YOKLUGUDUR."""
    project = await project_factory("P-PT-2")
    site = await _site(db_session, project)
    user = await user_factory("pt2@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    db_session.add(_entry(person, site, user, date(2026, 8, 3), hours=hours))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_kod_hucresi_saatsiz_kabul_edilir(db_session, project_factory, user_factory):
    """Kodlu hucre (izin/tatil/gorev) SAAT TASIMAZ ve gecerlidir."""
    project = await project_factory("P-PT-3")
    site = await _site(db_session, project)
    user = await user_factory("pt3@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    entry = _entry(person, site, user, date(2026, 8, 3), hours=None, code=TimesheetCode.leave)
    db_session.add(entry)
    await db_session.flush()
    assert entry.hours is None
    assert entry.code is TimesheetCode.leave


async def test_hem_saat_hem_kod_DB_DUZEYINDE_reddedilir(
    db_session, project_factory, user_factory
):
    """🔴 `ck_timesheet_entries_hours_xor_code` — sozlesme kisiti TIPTE YASAMAZ.

    Pydantic kapisi (`TimesheetCellInput`) ayni kurali soyler ama yalniz UC
    yolunda; migration, elle SQL ya da gelecekteki ikinci bir yazma yolu onu
    atlar. Asil bekci BURADADIR.
    """
    project = await project_factory("P-PT-5")
    site = await _site(db_session, project)
    user = await user_factory("pt5@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    db_session.add(
        _entry(
            person, site, user, date(2026, 8, 3), hours=Decimal("9.0"), code=TimesheetCode.leave
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_ne_saat_ne_kod_DB_DUZEYINDE_reddedilir(
    db_session, project_factory, user_factory
):
    """Bos hucre "gun girildi ama hicbir sey demiyor" olurdu."""
    project = await project_factory("P-PT-6")
    site = await _site(db_session, project)
    user = await user_factory("pt6@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    db_session.add(_entry(person, site, user, date(2026, 8, 3), hours=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_kalkan_kodlar_DB_DUZEYINDE_reddedilir(db_session, project_factory, user_factory):
    """🔴 `ck_timesheet_entries_code_allowed` — PG enum etiketi SILINEMEZ.

    `timesheet_code` tipi CANLIDA hala `worked`/`overtime` etiketlerini tasir
    (PostgreSQL enum'dan etiket dusuremez). Python enum'undan cikarmak yalniz
    UYGULAMA yolunu kapatir; ham SQL ile o etiket geri yazilabilirdi ve
    "saatsiz calisilmis gun" diye okunamayan bir hucre dogardi.

    ⚠️ **BU TEST SEMASINDA KISIT ISLETILEMEZ ve bu DURUSTCE soylenir:** test
    semasi `Base.metadata.create_all` ile kurulur, dolayisiyla enum tipi
    yalnizca UC etiketle dogar ve `'worked'` daha PG tipine ulasamadan reddedilir
    (`InvalidTextRepresentationError`). Yani burada olculen sey "kisit calisti"
    DEGIL, "**bu etiket hicbir yoldan yazilamaz**"tir. Kisitin CANLIDA (bes
    etiketli tipin ustunde) var oldugunu ayrica `test_code_allowed_kisiti_DBde_VAR`
    olcer.
    """
    from sqlalchemy import text

    project = await project_factory("P-PT-7")
    site = await _site(db_session, project)
    user = await user_factory("pt7@fiil.test", "Parola123!", "system_admin")
    person = await _personnel(db_session)

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "INSERT INTO timesheet_entries "
                "(id, personnel_id, site_id, project_id, work_date, code, created_by) "
                "VALUES (gen_random_uuid(), :p, :s, :pr, :d, 'worked', :u)"
            ),
            {
                "p": person.id,
                "s": site.id,
                "pr": site.project_id,
                "d": date(2026, 8, 3),
                "u": user.id,
            },
        )


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


async def test_code_allowed_kisiti_DBde_VAR(db_session):
    """🔴 Yukaridaki testin kapatamadigi bosluk: kisitin VARLIGI olculur.

    Test semasinda enum uc etiketli dogdugu icin CHECK'e sira gelmez; canlida
    ise tip bes etiketlidir ve tek bekci BU KISITTIR. Kisit dusurulurse burasi
    kirmizi olur — "test semasinda zaten yazilamiyor" gerekcesiyle kisiti
    silmek canlida sessizce delik acardi.
    """
    from sqlalchemy import text

    adlar = set(
        (
            await db_session.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'timesheet_entries'::regclass AND contype = 'c'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert "ck_timesheet_entries_code_allowed" in adlar
    assert "ck_timesheet_entries_hours_xor_code" in adlar
    assert "ck_timesheet_entries_hours_range" in adlar
