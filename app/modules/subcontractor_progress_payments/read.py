"""Taşeron hakedişi OKUMA yolu (T2) — detay ve liste yanıtlarının kurulumu.

`service.py`den ayrı durur (işveren modülünün `summary.py`/`lines.py` ayrımının
aynı gerekçesi): yazma yolu (kapsam + kilit + kurallar) ile okuma yolu (yanıt
inşası) farklı hızda değişir ve T3 hesap bloklarını BURAYA ekleyecektir.

Yön TEK taraflıdır: bu modül `service`in kapsam yardımcılarını çağırır, `service`
buradan hiçbir şey İMPORT ETMEZ — döngüsel import doğmaz.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.service import visible_projects
from app.modules.subcontractor_progress_payments import repository
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPaymentLine,
)
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentDetail,
    SubcontractorProgressPaymentLineRead,
    SubcontractorProgressPaymentListItem,
    SubcontractorProgressPaymentListResponse,
)
from app.modules.subcontractor_progress_payments.service import PaymentContext, visible_payment
from app.modules.users.models import User


def _line_read(line: SubcontractorProgressPaymentLine) -> SubcontractorProgressPaymentLineRead:
    return SubcontractorProgressPaymentLineRead(
        id=line.id,
        contract_item_id=line.contract_item_id,
        code=line.code,
        description=line.description,
        unit=line.unit,
        contract_unit_price=line.contract_unit_price,
        coefficient=line.coefficient,
        quantity=line.quantity,
        group_name=line.group_name,
        sort_order=line.sort_order,
        quantity_source=line.quantity_source,
    )


def build_detail(context: PaymentContext) -> SubcontractorProgressPaymentDetail:
    """GÖRÜNÜRLÜK KONTROLÜ YAPMAZ — çağıranın kapsam kararını çoktan vermiş
    olması ŞARTTIR (işveren `build_detail` ayrımının aynı gerekçesi: `POST`/
    `PATCH` uçları `visible_projects` sorgusunu ikinci kez koşturmasın)."""
    payment, contract, project = context
    return SubcontractorProgressPaymentDetail(
        id=payment.id,
        contract_id=payment.contract_id,
        project_id=payment.project_id,
        project_name=project.name,
        subcontractor_name=contract.subcontractor_name,
        contract_no=contract.contract_no,
        sequence_no=payment.sequence_no,
        period_year=payment.period_year,
        period_month=payment.period_month,
        description=payment.description,
        status=payment.status,
        vat_pct=payment.vat_pct,
        advance_pct=payment.advance_pct,
        retainage_pct=payment.retainage_pct,
        default_coefficient=payment.default_coefficient,
        section_id=payment.section_id,
        submitted_at=payment.submitted_at,
        approved_at=payment.approved_at,
        approved_by=payment.approved_by,
        paid_at=payment.paid_at,
        rejected_at=payment.rejected_at,
        rejection_reason=payment.rejection_reason,
        created_by=payment.created_by,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        lines=[_line_read(line) for line in payment.lines],
    )


async def get_detail(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> SubcontractorProgressPaymentDetail:
    return build_detail(await visible_payment(session, actor, payment_id))


async def list_payments(
    session: AsyncSession,
    actor: User,
    *,
    project_id: uuid.UUID | None,
    period_year: int | None,
    period_month: int | None,
    status_filter: SubcontractorPaymentStatus | None,
    q: str | None,
    limit: int,
    offset: int,
) -> SubcontractorProgressPaymentListResponse:
    """Kapsam SQL'de kalır: süzgeç `visible_projects`ten türeyen kimlik listesidir,
    ikinci bir görünürlük kararı VERİLMEZ (spec §9.0)."""
    visible_ids = [p.id for p in await visible_projects(session, actor)]
    filters = {
        "project_id": project_id,
        "period_year": period_year,
        "period_month": period_month,
        "status_filter": status_filter,
        "q": q,
    }
    rows = await repository.list_payments(
        session, visible_ids, limit=limit, offset=offset, **filters
    )
    total = await repository.count_payments(session, visible_ids, **filters)
    return SubcontractorProgressPaymentListResponse(
        items=[
            SubcontractorProgressPaymentListItem(
                id=payment.id,
                contract_id=payment.contract_id,
                project_id=payment.project_id,
                project_name=project.name,
                subcontractor_name=contract.subcontractor_name,
                contract_no=contract.contract_no,
                sequence_no=payment.sequence_no,
                period_year=payment.period_year,
                period_month=payment.period_month,
                description=payment.description,
                status=payment.status,
                section_id=payment.section_id,
                created_at=payment.created_at,
            )
            for payment, contract, project in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
