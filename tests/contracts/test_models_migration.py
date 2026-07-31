import pytest
from sqlalchemy import inspect, text

from app.modules.contracts.models import (  # noqa: F401 -- ice aktarilabilir oldugu dogrulanir
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
    PaymentPeriod,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)


def test_contract_status_uyeleri():
    assert [s.value for s in ContractStatus] == ["active", "completed", "on_hold"]


def test_payment_period_uyeleri():
    assert [p.value for p in PaymentPeriod] == ["monthly", "biweekly", "on_completion"]


@pytest.mark.asyncio
async def test_yeni_tablolar_olusur(db_session):
    tablolar = await db_session.run_sync(lambda s: inspect(s.bind).get_table_names())
    for ad in (
        "subcontractors",
        "employer_contract_groups",
        "employer_contract_items",
        "subcontractor_contracts",
        "subcontractor_contract_items",
    ):
        assert ad in tablolar


@pytest.mark.asyncio
async def test_boq_item_contract_item_id_nullable(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='boq_items' AND column_name='contract_item_id'"
        )
    )
    assert sonuc.scalar_one() == "YES"


@pytest.mark.asyncio
async def test_project_contract_status_varsayilani(db_session):
    sonuc = await db_session.execute(
        text(
            "SELECT column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name='project_contracts' AND column_name='status'"
        )
    )
    varsayilan, nullable = sonuc.one()
    assert nullable == "NO"
    assert "active" in varsayilan
