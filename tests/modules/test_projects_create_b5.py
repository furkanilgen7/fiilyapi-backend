"""B5 — oluşturma servisi: sözleşme + bütçe + satır içi şantiyeler, tek transaction."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import Project
from app.modules.projects.schemas import (
    ProjectBudgetInput,
    ProjectContractInput,
    ProjectCreate,
    ProjectSiteInput,
)
from app.modules.projects.service import create_project


async def test_budget_is_sum_of_lines(db_session):
    """budget = Σ kalemler; servis hesaplar (istemci `budget` göndermez, spec §2.3)."""
    project = await create_project(
        db_session,
        ProjectCreate(
            name="Bütçe",
            project_type="taahhut",
            is_draft=True,
            budget_lines=ProjectBudgetInput(
                material="100.00", labor="200.00", subcontractor="300.00", overhead="400.00"
            ),
        ),
    )
    assert project.budget == Decimal("1000.00")
    assert project.budget_material == Decimal("100.00")
    assert project.budget_overhead == Decimal("400.00")


async def test_contract_row_and_snapshot(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            name="Sözleşme",
            project_type="taahhut",
            is_draft=True,
            contract=ProjectContractInput(
                contract_no="SZL-2026-009",
                amount=Decimal("22400000.00"),
                has_price_escalation=False,
            ),
        ),
    )
    assert project.contract is not None
    assert project.contract.contract_no == "SZL-2026-009"
    assert project.contract.amount == Decimal("22400000.00")
    # contract_no/amount projeye anlık görüntü kopyalandı (spec §2.4, §5).
    assert project.contract_no == "SZL-2026-009"
    assert project.contract_amount == Decimal("22400000.00")


async def test_inline_sites_written_same_transaction(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            name="Şantiyeli",
            project_type="taahhut",
            is_draft=True,
            sites=[
                ProjectSiteInput(name="A-Blok Şantiyesi", construction_area_m2=Decimal("1200.00")),
                ProjectSiteInput(name="B-Blok Şantiyesi"),
            ],
        ),
    )
    assert len(project.sites) == 2
    # Kod P2 türeticisiyle (derive_code) üretildi — kopya mantık yok.
    assert sorted(s.code for s in project.sites) == ["A-BLOK", "B-BLOK"]
    a_blok = next(s for s in project.sites if s.code == "A-BLOK")
    assert a_blok.construction_area_m2 == Decimal("1200.00")


async def test_inline_site_manager_name_stored_as_text(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            name="Şefli",
            project_type="taahhut",
            is_draft=True,
            sites=[ProjectSiteInput(name="Merkez", site_manager_name="Ali Veli")],
        ),
    )
    assert project.sites[0].site_manager_name == "Ali Veli"


async def test_site_code_conflict_rolls_back_whole_project(db_session):
    """İkinci şantiyede kod çakışması → 409 ve proje de YAZILMAZ (tek transaction)."""
    before = (await db_session.execute(select(func.count()).select_from(Project))).scalar()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await create_project(
                db_session,
                ProjectCreate(
                    name="Atomik",
                    project_type="taahhut",
                    is_draft=True,
                    sites=[
                        ProjectSiteInput(name="A", code="DUP"),
                        ProjectSiteInput(name="B", code="DUP"),
                    ],
                ),
            )

    after = (await db_session.execute(select(func.count()).select_from(Project))).scalar()
    assert after == before  # yarım kayıt yok: proje satırı da geri alındı
