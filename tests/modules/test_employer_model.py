from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import (
    Employer,
    PriceIndexType,
    Project,
    ProjectContract,
    ProjectStatus,
)


async def test_create_and_read_employer(db_session):
    employer = Employer(name="Ankara Yapı A.Ş.", tax_number="1234567890", contact_person="A. Veli")
    db_session.add(employer)
    await db_session.flush()

    loaded = (
        await db_session.execute(select(Employer).where(Employer.name == "Ankara Yapı A.Ş."))
    ).scalar_one()
    assert loaded.tax_number == "1234567890"
    assert loaded.contact_person == "A. Veli"
    assert loaded.is_active is True


async def test_multiple_null_tax_numbers_allowed(db_session):
    """VKN opsiyoneldir (spec §2.2): kismi benzersiz indeks coklu NULL'a izin verir."""
    db_session.add(Employer(name="Firma A"))
    db_session.add(Employer(name="Firma B"))
    await db_session.flush()

    count = len((await db_session.execute(select(Employer))).scalars().all())
    assert count == 2


async def test_duplicate_filled_tax_number_rejected(db_session):
    db_session.add(Employer(name="Firma A", tax_number="1112223334"))
    db_session.add(Employer(name="Firma B", tax_number="1112223334"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


def test_price_index_type_values():
    assert {t.value for t in PriceIndexType} == {
        "ufe",
        "tufe",
        "construction_cost",
        "fixed_coefficient",
    }


async def test_project_employer_fk_and_snapshot(db_session, project_factory):
    employer = Employer(name="Güneş İnşaat")
    db_session.add(employer)
    await db_session.flush()

    project = await project_factory("EMP-1", employer_name="Güneş İnşaat")
    project.employer_id = employer.id
    await db_session.flush()

    loaded = await db_session.get(Project, project.id, populate_existing=True)
    assert loaded.employer_id == employer.id
    assert loaded.employer.name == "Güneş İnşaat"
    # employer_name anlik goruntu olarak KALIR (spec §2.3).
    assert loaded.employer_name == "Güneş İnşaat"


async def test_new_project_budget_line_defaults(db_session, project_factory):
    """Yeni sutunlar NOT NULL default 0 / false — factory vermese de dolu gelir."""
    project = await project_factory("BUD-1")
    loaded = await db_session.get(Project, project.id, populate_existing=True)
    assert loaded.budget_material == Decimal("0")
    assert loaded.budget_labor == Decimal("0")
    assert loaded.budget_subcontractor == Decimal("0")
    assert loaded.budget_overhead == Decimal("0")
    assert loaded.is_draft is False
    assert loaded.parcel is None
    assert loaded.address is None


async def test_contract_roundtrip(db_session, project_factory):
    project = await project_factory("C-1", status=ProjectStatus.active.value)
    db_session.add(
        ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-001",
            amount=Decimal("22400000.00"),
            has_price_escalation=True,
            index_type=PriceIndexType.ufe,
            base_index_value=Decimal("1.000"),
        )
    )
    await db_session.flush()

    loaded = await db_session.get(Project, project.id, populate_existing=True)
    assert loaded.contract.contract_no == "SZL-2026-001"
    assert loaded.contract.amount == Decimal("22400000.00")
    # Varsayilanlar (spec §2.4).
    assert loaded.contract.advance_pct == Decimal("20")
    assert loaded.contract.retainage_pct == Decimal("5")
    assert loaded.contract.vat_pct == Decimal("20")


async def test_contract_pct_range_check_rejects_vat_150(db_session, project_factory):
    project = await project_factory("C-2")
    db_session.add(ProjectContract(project_id=project.id, vat_pct=Decimal("150")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_contract_escalation_check_rejects_index_when_disabled(db_session, project_factory):
    """has_price_escalation=false iken dolu index_type reddedilir (ck_contract_escalation)."""
    project = await project_factory("C-3")
    db_session.add(
        ProjectContract(
            project_id=project.id,
            has_price_escalation=False,
            index_type=PriceIndexType.tufe,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
