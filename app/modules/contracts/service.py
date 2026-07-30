"""Birleşik sözleşme listesi servis katmanı (spec §6.1, task C5).

İki katmanlı koruma (spec §6): `contracts` izni router'da (`_VIEW`) YETKİYİ
verir, bu modül `projects.service.visible_projects` ile KAPSAMI belirler —
görünmeyen projenin sözleşmesi listeye asla girmez. Bu iki katmandan biri
eksikse task başarısızdır (task brief kararı).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.contracts import repository
from app.modules.contracts.models import ContractStatus, SubcontractorContract
from app.modules.contracts.schemas import (
    ContractListItem,
    ContractListResponse,
    ContractSummary,
    ContractType,
    MetricPlaceholder,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.projects.service import visible_projects
from app.modules.users.models import User

# Spec §2.2: hakediş P7'nin işi, bu dilimde yazılmaz — yer tutucu anahtarı.
_PROGRESS_PAYMENTS = "progress_payments"
_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _employer_item(project: Project, contract: ProjectContract) -> ContractListItem:
    """Alan eşlemesi spec §6.1 tablosu — işveren sütunu BİREBİR."""
    return ContractListItem(
        id=project.id,
        title=project.name,
        contract_no=contract.contract_no,
        counterparty_name=project.employer_name,
        amount=contract.amount if contract.amount is not None else Decimal("0"),
        start_date=project.start_date,
        end_date=project.end_date,
        progress_pct=MetricPlaceholder(
            available=True, value=project.progress_pct, pending_module=_PROGRESS_PAYMENTS
        ),
        status=contract.status,
        is_draft=project.is_draft,
    )


def _subcontractor_amount(contract: SubcontractorContract) -> Decimal:
    """`Σ(quantity × unit_price)` — `unit_price IS NULL` olan satır 0 katkı verir

    (task brief kararı). Kalemler zaten `lazy="selectin"` ile yüklü, ek sorgu YOK.
    """
    total = sum(
        (
            item.quantity * item.unit_price
            for item in contract.items
            if item.unit_price is not None
        ),
        Decimal("0"),
    )
    return _quantize_money(total)


def _subcontractor_title(contract: SubcontractorContract) -> str:
    """`subcontractor_name + " — " + work_category` (`TSD` 40 deseni, spec §6.1)."""
    name = contract.subcontractor_name or ""
    category = contract.work_category or ""
    if name and category:
        return f"{name} — {category}"
    return name or category


def _subcontractor_item(contract: SubcontractorContract) -> ContractListItem:
    return ContractListItem(
        id=contract.id,
        title=_subcontractor_title(contract),
        contract_no=contract.contract_no,
        counterparty_name=contract.subcontractor_name,
        amount=_subcontractor_amount(contract),
        start_date=contract.start_date,
        end_date=contract.end_date,
        progress_pct=MetricPlaceholder(pending_module=_PROGRESS_PAYMENTS),
        status=contract.status,
        is_draft=contract.is_draft,
    )


def _summary(items: list[ContractListItem]) -> ContractSummary:
    """`SZL` 34-38 üst KPI şeridi (spec §6.1). `expiring_this_month_count`:

    durumu `active` VE bitiş tarihi sunucunun görüntüleme saat dilimindeki
    (`app/core/timezone.today`) içinde bulunulan ay içinde olan sözleşmeler.
    """
    total_amount = _quantize_money(sum((item.amount for item in items), Decimal("0")))
    active_count = sum(1 for item in items if item.status is ContractStatus.active)
    current = today()
    expiring_this_month_count = sum(
        1
        for item in items
        if item.status is ContractStatus.active
        and item.end_date is not None
        and item.end_date.year == current.year
        and item.end_date.month == current.month
    )
    return ContractSummary(
        total_amount=total_amount,
        active_count=active_count,
        expiring_this_month_count=expiring_this_month_count,
    )


async def list_contracts(
    session: AsyncSession,
    actor: User,
    contract_type: ContractType,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> ContractListResponse:
    visible_ids = [p.id for p in await visible_projects(session, actor)]

    if contract_type == "employer":
        rows = await repository.list_employer_contracts(
            session,
            visible_ids,
            project_id=project_id,
            status_filter=status_filter,
            q=q,
        )
        items = [_employer_item(project, contract) for project, contract in rows]
    else:
        contracts = await repository.list_subcontractor_contracts(
            session,
            visible_ids,
            project_id=project_id,
            status_filter=status_filter,
            q=q,
        )
        items = [_subcontractor_item(contract) for contract in contracts]

    return ContractListResponse(summary=_summary(items), items=items)
