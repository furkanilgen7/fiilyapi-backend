"""Task 5 — santiye/bolum repository katmani."""

import uuid

from app.modules.sites import repository
from app.modules.sites.models import Section, Site


async def _site(session, project, code: str, **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", f"{code} Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


async def test_list_sites_for_project_is_scoped_and_ordered(db_session, project_factory):
    project = await project_factory("R-1")
    other = await project_factory("R-2")
    await _site(db_session, project, "C-BLOK")
    await _site(db_session, project, "A-BLOK")
    await _site(db_session, other, "Z-BLOK")

    sites = await repository.list_sites_for_project(db_session, project.id)

    assert [s.code for s in sites] == ["A-BLOK", "C-BLOK"]


async def test_list_sites_for_project_without_sites_is_empty(db_session, project_factory):
    project = await project_factory("R-3")
    assert await repository.list_sites_for_project(db_session, project.id) == []


async def test_get_site_loads_sections_ordered(db_session, project_factory):
    project = await project_factory("R-4")
    site = await _site(db_session, project, "A-BLOK")
    db_session.add(Section(site_id=site.id, name="İkinci", sort_order=2))
    db_session.add(Section(site_id=site.id, name="Birinci", sort_order=1))
    await db_session.flush()
    db_session.expunge_all()

    loaded = await repository.get_site(db_session, site.id)

    assert [s.name for s in loaded.sections] == ["Birinci", "İkinci"]
    assert loaded.project.id == project.id


async def test_get_site_missing_returns_none(db_session):
    assert await repository.get_site(db_session, uuid.uuid4()) is None


async def test_site_without_sections_returns_empty_list(db_session, project_factory):
    """Karar 4 (spec §2.4): santiye SIFIR bolumle gecerlidir."""
    project = await project_factory("R-5")
    site = await _site(db_session, project, "A-BLOK")
    db_session.expunge_all()

    loaded = await repository.get_site(db_session, site.id)

    assert loaded.sections == []
    assert await repository.list_sections(db_session, site.id) == []


async def test_list_sections_is_scoped_and_ordered(db_session, project_factory):
    project = await project_factory("R-6")
    site = await _site(db_session, project, "A-BLOK")
    other_site = await _site(db_session, project, "B-BLOK")
    db_session.add(Section(site_id=site.id, name="Üçüncü", sort_order=3))
    db_session.add(Section(site_id=site.id, name="Birinci", sort_order=1))
    db_session.add(Section(site_id=other_site.id, name="Yabancı", sort_order=1))
    await db_session.flush()

    sections = await repository.list_sections(db_session, site.id)

    assert [s.name for s in sections] == ["Birinci", "Üçüncü"]


async def test_get_section_resolves_owning_site(db_session, project_factory):
    """Yetki yolu: bolum -> santiye -> proje (spec §5.2)."""
    project = await project_factory("R-7")
    site = await _site(db_session, project, "A-BLOK")
    section = Section(site_id=site.id, name="Bölüm")
    db_session.add(section)
    await db_session.flush()
    db_session.expunge_all()

    loaded = await repository.get_section(db_session, section.id)

    assert loaded.site_id == site.id
    owning_site = await repository.get_site(db_session, loaded.site_id)
    assert owning_site.project_id == project.id


async def test_get_section_missing_returns_none(db_session):
    assert await repository.get_section(db_session, uuid.uuid4()) is None


# --- Atanabilir kullanici (karar 2026-07-30) ---
#
# IZINLI (`on_leave`) personel ATANABILIR. Izin GECICI bir durumdur: yillik
# izindeki sef hâlâ o santiyenin sefidir. Reddedilirse sef tatildeyken santiye
# ACILAMAZ. Yalniz gercekten kullanilamaz durum (`passive`) reddedilir.


async def test_assignable_user_accepts_active(db_session, user_factory):
    user = await user_factory(
        email=f"aktif-{uuid.uuid4().hex[:6]}@t.co", password="parola1234", role_key="site_chief"
    )

    assert (await repository.get_assignable_user(db_session, user.id)).id == user.id


async def test_assignable_user_accepts_on_leave(db_session, user_factory):
    """Izin gecicidir: izindeki sef hâlâ atanabilir (karar 2026-07-30)."""
    user = await user_factory(
        email=f"izinli-{uuid.uuid4().hex[:6]}@t.co",
        password="parola1234",
        role_key="site_chief",
        status="on_leave",
    )

    assert (await repository.get_assignable_user(db_session, user.id)).id == user.id


async def test_assignable_user_rejects_passive(db_session, user_factory):
    """Pasif kullanici ATANAMAZ: gecici degil, kalici bir kullanilamazlik."""
    user = await user_factory(
        email=f"pasif-{uuid.uuid4().hex[:6]}@t.co",
        password="parola1234",
        role_key="site_chief",
        status="passive",
    )

    assert await repository.get_assignable_user(db_session, user.id) is None


async def test_assignable_user_missing_returns_none(db_session, seeded_db):
    assert await repository.get_assignable_user(db_session, uuid.uuid4()) is None
