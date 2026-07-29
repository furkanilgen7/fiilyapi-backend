from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import (
    LandShareShareholder,
    Project,
    ProjectInvestment,
    ProjectLandShare,
    ProjectStatus,
    ProjectType,
)


async def test_create_and_read_project(db_session):
    project = Project(
        code="GK-A",
        name="Güneşkent A-Blok",
        status=ProjectStatus.active,
        budget=Decimal("1500000.00"),
        progress_pct=Decimal("42.50"),
    )
    db_session.add(project)
    await db_session.flush()

    loaded = (await db_session.execute(select(Project).where(Project.code == "GK-A"))).scalar_one()
    assert loaded.name == "Güneşkent A-Blok"
    assert loaded.status is ProjectStatus.active
    assert loaded.budget == Decimal("1500000.00")


def test_project_status_values():
    # B1: `planning` eklendi; mevcut uc deger korunur (spec §2.1, §7.2).
    assert {s.value for s in ProjectStatus} == {"planning", "active", "on_hold", "completed"}


def test_project_status_enum_order():
    """Enum sirasi mockup Durum acilirini yansitir: Planlama · Aktif · Beklemede · (Tamamlandi)."""
    assert [s.value for s in ProjectStatus] == ["planning", "active", "on_hold", "completed"]


async def test_planning_status_roundtrip(db_session, project_factory):
    """Yeni `planning` degeri yazilip okunabiliyor; varsayilan yine `active`."""
    project = await project_factory("PLAN-1", status="planning")
    loaded = await db_session.get(Project, project.id, populate_existing=True)
    assert loaded.status is ProjectStatus.planning

    default_project = await project_factory("PLAN-2")
    assert default_project.status is ProjectStatus.active


async def test_project_factory_creates_row(project_factory):
    project = await project_factory("TMP-1", name="Geçici")
    assert project.id is not None
    assert project.code == "TMP-1"


def test_project_type_values():
    assert {t.value for t in ProjectType} == {"taahhut", "kendi_yatirim", "kat_karsiligi"}


async def test_project_defaults_to_taahhut(project_factory):
    project = await project_factory("TIP-1")
    assert project.project_type is ProjectType.taahhut
    assert project.category is None
    assert project.employer_name is None


async def test_investment_extension_roundtrip(db_session, project_factory):
    project = await project_factory("KY-1", project_type="kendi_yatirim")
    db_session.add(
        ProjectInvestment(
            project_id=project.id,
            sales_target=Decimal("48200000.00"),
            land_cost=Decimal("9500000.00"),
        )
    )
    await db_session.flush()

    loaded = await db_session.get(Project, project.id, populate_existing=True)

    assert loaded.investment.sales_target == Decimal("48200000.00")
    assert loaded.land_share is None
    assert loaded.shareholders == []


async def test_land_share_extension_with_shareholders(db_session, project_factory):
    project = await project_factory("KK-1", project_type="kat_karsiligi")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    db_session.add(
        LandShareShareholder(project_id=project.id, name="A. Yılmaz", share_pct=Decimal("60.00"))
    )
    db_session.add(
        LandShareShareholder(project_id=project.id, name="B. Yılmaz", share_pct=Decimal("40.00"))
    )
    await db_session.flush()

    loaded = await db_session.get(Project, project.id, populate_existing=True)

    assert loaded.land_share.landowner_name == "Yılmaz Ailesi"
    assert [s.name for s in loaded.shareholders] == ["A. Yılmaz", "B. Yılmaz"]


async def test_land_share_pct_total_check(db_session, project_factory):
    project = await project_factory("KK-2", project_type="kat_karsiligi")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Test",
            our_share_pct=Decimal("70.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
