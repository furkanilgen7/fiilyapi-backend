"""Proje kartı maliyet bağlarının PAYLAŞILAN kurulumu.

`test_projects_cost_bindings.py` 800 satır tavanını aşınca bölündü
(`_journal.py` emsali): yardımcılar KOPYALANMADI, buraya alındı — iki kopya
olsaydı biri güncellenip öteki kalır ve iki dosya AYNI ismi taşıyan FARKLI
gövdelerle koşardı.

`_sorgu_sayaci` fikstürü de buradadır: N+1 iddiası hem tip bazlı alan setlerinde
hem taraf sayaçlarında ÖLÇÜLÜR, iki dosya da aynı sayacı kullanır.

Hiçbir testin iddiası bu bölmeyle değişmedi.
"""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.projects.models import Project
from app.modules.sites.models import Site
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.units.models import Block, Unit, UnitKind
from app.modules.users.models import User
from tests.conftest import test_engine

_TENTH = Decimal("0.1")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client, user_factory, role_key: str = "system_admin") -> str:
    address = f"{role_key}@p10t3.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


def _set_budget_lines(project: Project, *, material="0", labor="0", sub="0", overhead="0") -> None:
    project.budget_material = Decimal(material)
    project.budget_labor = Decimal(labor)
    project.budget_subcontractor = Decimal(sub)
    project.budget_overhead = Decimal(overhead)


async def _units(session: AsyncSession, project: Project, specs: list[dict]) -> list[Unit]:
    site = Site(project_id=project.id, code=f"SNT-{project.code}", name="Şantiye")
    session.add(site)
    await session.flush()
    block = Block(project_id=project.id, site_id=site.id, name="A Blok")
    session.add(block)
    await session.flush()
    created: list[Unit] = []
    for index, spec in enumerate(specs, start=1):
        unit = Unit(
            project_id=project.id,
            block_id=block.id,
            unit_no=str(index),
            unit_kind=UnitKind.apartment,
            list_price=spec.get("list_price"),
            appraisal_value=spec.get("appraisal_value"),
            gross_area_m2=spec.get("gross_area_m2"),
            owner_side=spec.get("owner_side"),
        )
        session.add(unit)
        created.append(unit)
    await session.flush()
    return created


async def _contract(
    session: AsyncSession, project: Project, creator: User, *, name: str
) -> SubcontractorContract:
    """Taşeron sözleşmesi + tek kalem (bedel türevdir, `amount` kolonu YOK)."""
    contract = SubcontractorContract(
        project_id=project.id, subcontractor_name=name, created_by=creator.id
    )
    session.add(contract)
    await session.flush()
    session.add(
        SubcontractorContractItem(
            contract_id=contract.id,
            code="A.001",
            description="Kalem",
            unit="m2",
            quantity=Decimal("1"),
            unit_price=Decimal("0"),
        )
    )
    await session.flush()
    return contract


async def _payment(
    session: AsyncSession,
    contract: SubcontractorContract,
    creator: User,
    status: SubcontractorPaymentStatus,
    *,
    quantity: str,
    sequence_no: int = 1,
) -> None:
    """Brüt = miktar × 1000 (kesintiler S2 gereği harcanana DOKUNMAZ)."""
    session.add(
        SubcontractorProgressPayment(
            contract_id=contract.id,
            project_id=contract.project_id,
            sequence_no=sequence_no,
            status=status,
            vat_pct=Decimal("20"),
            advance_pct=Decimal("10"),
            retainage_pct=Decimal("5"),
            created_by=creator.id,
            lines=[
                SubcontractorProgressPaymentLine(
                    code="A.001",
                    description="Kalem",
                    unit="m2",
                    contract_unit_price=Decimal("1000"),
                    coefficient=Decimal("1.000"),
                    quantity=Decimal(quantity),
                )
            ],
        )
    )
    await session.flush()


def _card(body: dict, project_id, key: str) -> dict:
    item = next(row for row in body["items"] if row["id"] == str(project_id))
    return item[key]


def _envelopes(node: Any, path: str = "") -> Iterator[tuple[str, dict]]:
    """Yanıt gövdesindeki TÜM zarfları (available/value|count taşıyan sözlük) gezer."""
    if isinstance(node, dict):
        if "available" in node and ("value" in node or "count" in node):
            yield path, node
        for key, value in node.items():
            yield from _envelopes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _envelopes(value, f"{path}[{index}]")


# Fikstür ADI açıkça verilir: iki test dosyası da bunu IMPORT eder ve import
# edilen ad, testlerin parametre adıyla çakışınca ruff F811 üretir. `name=`
# ile kayıt adı korunur (`_sorgu_sayaci`), modül düzeyindeki ad ayrışır.
@pytest.fixture(name="_sorgu_sayaci")
def _sorgu_sayaci_fixture() -> Iterator[list[str]]:
    """T1/T2 deseninin aynısı: N+1 iddiası tahmine değil ÖLÇÜME dayanır."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _tablo_sayimi(ifadeler: list[str], tablo: str) -> int:
    return sum(1 for ifade in ifadeler if f"from {tablo}" in ifade.lower())
