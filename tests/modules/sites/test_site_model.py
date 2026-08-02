"""Task 1 — sites/sections modelleri, kisitlar ve cascade davranisi (spec §2.1-2.3)."""

import pytest
from sqlalchemy import Boolean, Integer, Numeric, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import Project
from app.modules.sites.models import Section, SectionStatus, Site, SiteStatus
from app.modules.users.models import User


async def _site(session, project, code: str = "A-BLOK", **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", "A-Blok Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


def test_site_status_values():
    # `preparation` T1'de eklendi (spec §3.1); `completed` KALDIRILMADI.
    assert {s.value for s in SiteStatus} == {"preparation", "active", "on_hold", "completed"}


def test_section_status_values():
    # `on_hold` P6'da eklendi (spec §4, Form 71 "Beklemede").
    assert {s.value for s in SectionStatus} == {"planned", "active", "on_hold", "completed"}


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


# =========================================================================== #
# T2 — santiye formu genislemesi: 22 yeni `sites` kolonu + `sections.manager_user_id`
# (spec §3.0). Kritik korkuluk: HICBIR yeni kolon "NOT NULL + varsayilansiz"
# degildir. GEREKCE TASLAK DESTEGIDIR: "Taslak Kaydet" yarim doldurulmus formu
# kaydeder, yani mockup'ta zorunlu (*) isaretli alanlar bile DB'de bos durabilmeli.
# Zorunluluk yalniz uygulama katmaninda ve yalniz TASLAK-DISI POST'ta uygulanir.
# =========================================================================== #

# (kolon adi, SQLAlchemy tip sinifi, nullable)
NEW_SITE_COLUMNS = [
    ("site_manager_user_id", PgUUID, True),
    ("safety_officer_user_id", PgUUID, True),
    ("safety_officer_name", String, True),
    ("safety_officer_is_outsourced", Boolean, False),
    ("neighborhood", String, True),
    ("parcel", String, True),
    ("gps_coordinates", String, True),
    ("land_area_m2", Numeric, True),
    ("floor_info", String, True),
    ("budget", Numeric, True),
    ("has_closed_warehouse", Boolean, False),
    ("has_open_storage", Boolean, False),
    ("has_cold_storage", Boolean, False),
    ("has_site_office", Boolean, False),
    ("has_canteen", Boolean, False),
    ("has_changing_room_wc", Boolean, False),
    ("has_dormitory", Boolean, False),
    ("has_infirmary", Boolean, False),
    ("electricity_subscription_no", String, True),
    ("water_subscription_no", String, True),
    ("planned_worker_count", Integer, True),
    ("is_draft", Boolean, False),
]

FACILITY_COLUMNS = [
    "has_closed_warehouse",
    "has_open_storage",
    "has_cold_storage",
    "has_site_office",
    "has_canteen",
    "has_changing_room_wc",
    "has_dormitory",
    "has_infirmary",
]

STRING_LENGTHS = {
    "safety_officer_name": 200,
    "neighborhood": 150,
    "parcel": 50,
    "gps_coordinates": 50,
    "floor_info": 100,
    "electricity_subscription_no": 50,
    "water_subscription_no": 50,
}


def test_site_has_all_twenty_two_new_columns():
    assert len(NEW_SITE_COLUMNS) == 22
    columns = Site.__table__.columns
    for name, type_cls, nullable in NEW_SITE_COLUMNS:
        assert name in columns, f"{name} kolonu yok"
        column = columns[name]
        assert isinstance(column.type, type_cls), f"{name} tipi {column.type}"
        assert column.nullable is nullable, f"{name} nullable={column.nullable}"
    for name, expected_length in STRING_LENGTHS.items():
        assert columns[name].type.length == expected_length, name


def test_facility_columns_are_not_null_with_false_default():
    columns = Site.__table__.columns
    for name in FACILITY_COLUMNS:
        column = columns[name]
        assert column.nullable is False, name
        assert column.server_default is not None, name
        assert "false" in str(column.server_default.arg).lower(), name


async def test_facility_defaults_are_all_false_on_insert(db_session, project_factory):
    """Onayli sapma §14.2: mockup'taki on-isaretler UYGULANMAZ — sekizi de false dogar."""
    project = await project_factory("P-FAC")
    site = await _site(db_session, project, code="SNT-FAC")
    db_session.expunge_all()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    for name in FACILITY_COLUMNS:
        assert getattr(loaded, name) is False, name


async def test_is_draft_defaults_to_false(db_session, project_factory):
    project = await project_factory("P-DRAFT")
    site = await _site(db_session, project, code="SNT-DRAFT")
    db_session.expunge_all()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.is_draft is False


async def test_safety_officer_is_outsourced_defaults_to_false(db_session, project_factory):
    project = await project_factory("P-ISG")
    site = await _site(db_session, project, code="SNT-ISG")
    db_session.expunge_all()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.safety_officer_is_outsourced is False
    assert loaded.safety_officer_user_id is None
    assert loaded.safety_officer_name is None


async def test_safety_officer_check_rejects_both(db_session, project_factory, user_factory):
    """ck_sites_safety_officer: ya sistem kullanicisi ya OSGB — ikisi birden OLMAZ."""
    project = await project_factory("P-CK1")
    user = await user_factory("isg1@test.local", "Passw0rd!", "site_chief")

    db_session.add(
        Site(
            project_id=project.id,
            code="SNT-CK1",
            name="Ikisi Birden",
            safety_officer_user_id=user.id,
            safety_officer_is_outsourced=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_safety_officer_check_allows_fk_only(db_session, project_factory, user_factory):
    project = await project_factory("P-CK2")
    user = await user_factory("isg2@test.local", "Passw0rd!", "site_chief")

    site = await _site(
        db_session,
        project,
        code="SNT-CK2",
        safety_officer_user_id=user.id,
        safety_officer_name=user.full_name,
    )
    assert site.id is not None


async def test_safety_officer_check_allows_outsourced_only(db_session, project_factory):
    project = await project_factory("P-CK3")
    site = await _site(
        db_session,
        project,
        code="SNT-CK3",
        safety_officer_is_outsourced=True,
        safety_officer_name="Dış Kaynak — OSGB",
    )
    assert site.id is not None


async def test_safety_officer_check_allows_neither(db_session, project_factory):
    project = await project_factory("P-CK4")
    site = await _site(db_session, project, code="SNT-CK4")
    assert site.id is not None


async def test_site_manager_user_delete_sets_null(db_session, project_factory, user_factory):
    """ON DELETE SET NULL — kullanici silinse de ad anlik goruntusu KALIR."""
    project = await project_factory("P-MGR")
    user = await user_factory("sef@test.local", "Passw0rd!", "site_chief")
    site = await _site(
        db_session,
        project,
        code="SNT-MGR",
        site_manager_user_id=user.id,
        site_manager_name=user.full_name,
    )
    db_session.expunge_all()

    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.flush()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.site_manager_user_id is None
    assert loaded.site_manager_name == "Test Kullanıcı"


async def test_safety_officer_user_delete_sets_null(db_session, project_factory, user_factory):
    project = await project_factory("P-ISGDEL")
    user = await user_factory("isgdel@test.local", "Passw0rd!", "site_chief")
    site = await _site(
        db_session,
        project,
        code="SNT-ISGDEL",
        safety_officer_user_id=user.id,
        safety_officer_name=user.full_name,
    )
    db_session.expunge_all()

    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.flush()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.safety_officer_user_id is None
    assert loaded.safety_officer_name == "Test Kullanıcı"


def test_no_new_column_is_non_nullable_without_default():
    """KRITIK korkuluk: NOT NULL + varsayilansiz kolon TASLAK kaydini imkansiz kilar
    (yarim doldurulmus form kaydedilemez) ve mevcut satirlarda deploy'u kilitler."""
    columns = Site.__table__.columns
    offenders = [
        name
        for name, _, _ in NEW_SITE_COLUMNS
        if columns[name].nullable is False and columns[name].server_default is None
    ]
    assert offenders == [], f"NOT NULL + varsayilansiz kolon(lar): {offenders}"

    section_column = Section.__table__.columns["manager_user_id"]
    assert section_column.nullable is True or section_column.server_default is not None


def test_section_has_manager_user_id():
    column = Section.__table__.columns["manager_user_id"]
    assert isinstance(column.type, PgUUID)
    assert column.nullable is True
    assert column.index is True


async def test_section_manager_user_delete_sets_null(db_session, project_factory, user_factory):
    project = await project_factory("P-SECMGR")
    user = await user_factory("secmgr@test.local", "Passw0rd!", "site_chief")
    site = await _site(db_session, project, code="SNT-SECMGR")
    section = Section(
        site_id=site.id,
        name="Kaba İnşaat",
        manager_user_id=user.id,
        manager_name=user.full_name,
    )
    db_session.add(section)
    await db_session.flush()
    db_session.expunge_all()

    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.flush()

    loaded = (
        await db_session.execute(select(Section).where(Section.id == section.id))
    ).scalar_one()
    assert loaded.manager_user_id is None
    assert loaded.manager_name == "Test Kullanıcı"


def test_section_has_no_estimated_amount_column():
    """Spec §3.4 karar kilidi: bolum bedeli BOQ turevidir, elle girilmez."""
    assert "estimated_amount" not in Section.__table__.columns


def test_no_latitude_longitude_columns():
    """Spec §3.5 karar kilidi: GPS TEK metin kolonudur."""
    columns = Site.__table__.columns
    assert "latitude" not in columns
    assert "longitude" not in columns
    assert isinstance(columns["gps_coordinates"].type, String)
    assert columns["gps_coordinates"].type.length == 50


def test_uq_sites_project_code_unchanged():
    """Spec §11.3/2: kisit PROJE ICI tekil kalir, global UNIQUE'e cevrilmez."""
    constraints = {c.name: c for c in Site.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_sites_project_code" in constraints
    assert [c.name for c in constraints["uq_sites_project_code"].columns] == ["project_id", "code"]
    assert Site.__table__.columns["code"].unique is not True


def test_numeric_precisions_match_spec():
    columns = Site.__table__.columns
    assert (columns["land_area_m2"].type.precision, columns["land_area_m2"].type.scale) == (12, 2)
    assert (
        columns["construction_area_m2"].type.precision,
        columns["construction_area_m2"].type.scale,
    ) == (12, 2)
    assert (columns["budget"].type.precision, columns["budget"].type.scale) == (18, 2)
