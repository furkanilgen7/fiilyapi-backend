"""Task 1 — sites/sections modelleri, kisitlar ve cascade davranisi (spec §2.1-2.3)."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import Project
from app.modules.sites.models import Section, SectionStatus, Site, SiteStatus


async def _site(session, project, code: str = "A-BLOK", **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", "A-Blok Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


def test_site_status_values():
    assert {s.value for s in SiteStatus} == {"active", "on_hold", "completed"}


def test_section_status_values():
    assert {s.value for s in SectionStatus} == {"planned", "active", "completed"}


async def test_site_defaults_to_active(db_session, project_factory):
    project = await project_factory("P-1")
    site = await _site(db_session, project)

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()

    assert loaded.status is SiteStatus.active
    assert loaded.address is None
    assert loaded.city is None
    assert loaded.site_manager_name is None
    assert loaded.delivery_date is None


async def test_section_defaults_to_planned(db_session, project_factory):
    """Spec §2.3: yeni bolum kural olarak PLANLANMIS dogar, aktif degil."""
    project = await project_factory("P-2")
    site = await _site(db_session, project)
    section = Section(site_id=site.id, name="Kat 6-10 Kaba İnşaat")
    db_session.add(section)
    await db_session.flush()

    loaded = (
        await db_session.execute(select(Section).where(Section.id == section.id))
    ).scalar_one()

    assert loaded.status is SectionStatus.planned
    assert loaded.sort_order == 0
    assert loaded.code is None
    assert loaded.manager_name is None


async def test_same_code_in_different_projects_is_allowed(db_session, project_factory):
    project_a = await project_factory("P-3")
    project_b = await project_factory("P-4")

    await _site(db_session, project_a, code="A-BLOK")
    await _site(db_session, project_b, code="A-BLOK")

    codes = (await db_session.execute(select(Site.code))).scalars().all()
    assert codes.count("A-BLOK") == 2


async def test_duplicate_code_in_same_project_raises(db_session, project_factory):
    """uq_sites_project_code — proje ICINDE benzersizlik."""
    project = await project_factory("P-5")
    await _site(db_session, project, code="A-BLOK")

    db_session.add(Site(project_id=project.id, code="A-BLOK", name="Kopya"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_multiple_sections_with_null_code_allowed(db_session, project_factory):
    """Kismi benzersiz indeks (WHERE code IS NOT NULL) — NULL kod cakismaz."""
    project = await project_factory("P-6")
    site = await _site(db_session, project)

    db_session.add(Section(site_id=site.id, name="Bölüm 1"))
    db_session.add(Section(site_id=site.id, name="Bölüm 2"))
    await db_session.flush()

    rows = (await db_session.execute(select(Section).where(Section.site_id == site.id))).scalars()
    assert len(list(rows)) == 2


async def test_duplicate_section_code_in_same_site_raises(db_session, project_factory):
    project = await project_factory("P-7")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, code="B1", name="Bölüm 1"))
    await db_session.flush()

    db_session.add(Section(site_id=site.id, code="B1", name="Bölüm 2"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_project_cascades_to_sites_and_sections(db_session, project_factory):
    project = await project_factory("P-8")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, name="Bölüm"))
    await db_session.flush()
    db_session.expunge_all()

    await db_session.execute(delete(Project).where(Project.id == project.id))
    await db_session.flush()

    assert (
        await db_session.execute(select(Site).where(Site.id == site.id))
    ).scalar_one_or_none() is None
    assert (await db_session.execute(select(Section))).scalars().all() == []


async def test_deleting_site_cascades_to_sections(db_session, project_factory):
    project = await project_factory("P-9")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, name="Bölüm"))
    await db_session.flush()
    db_session.expunge_all()

    await db_session.execute(delete(Site).where(Site.id == site.id))
    await db_session.flush()

    assert (await db_session.execute(select(Section))).scalars().all() == []


async def test_sections_relationship_is_ordered_by_sort_order(db_session, project_factory):
    project = await project_factory("P-10")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, name="Üçüncü", sort_order=3))
    db_session.add(Section(site_id=site.id, name="Birinci", sort_order=1))
    db_session.add(Section(site_id=site.id, name="İkinci", sort_order=2))
    await db_session.flush()

    loaded = await db_session.get(Site, site.id, populate_existing=True)

    assert [s.name for s in loaded.sections] == ["Birinci", "İkinci", "Üçüncü"]


async def test_project_sites_backref(db_session, project_factory):
    project = await project_factory("P-11")
    await _site(db_session, project, code="A")
    await _site(db_session, project, code="B", name="B-Blok")

    loaded = await db_session.get(Project, project.id, populate_existing=True)

    assert [s.code for s in loaded.sites] == ["A", "B"]
