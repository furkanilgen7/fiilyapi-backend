"""Taşeron hakedişi uçları (T2) — oluşturma / liste / detay / PATCH / DELETE.

Kapılar `progress_payments` iznidir: iki hakediş ailesi AYNI ekran ailesidir,
**yeni izin modülü AÇILMAZ** (spec §1). Denetim günlüğü (`record_audit`) TÜM
yazma uçlarına bağlıdır; mesajlar `app/modules/audit/messages.py`de merkezîdir.

T3'te eklendi: `PUT …/lines` (değiştirme semantiği + kota) ve `refresh-prices`.
Kapsam DIŞI (T4/T5): durum aksiyonları, `summary`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.subcontractor_progress_payments import read, service
from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentCreate,
    SubcontractorProgressPaymentDetail,
    SubcontractorProgressPaymentLinesSave,
    SubcontractorProgressPaymentListResponse,
    SubcontractorProgressPaymentUpdate,
    SubcontractorRefreshPricesResponse,
)
from app.modules.users.models import User

router = APIRouter(tags=["subcontractor-progress-payments"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("progress_payments", AccessLevel.view)
_DRAFT = require_permission("progress_payments", AccessLevel.draft)


@router.get(
    "/subcontractor-progress-payments",
    response_model=SubcontractorProgressPaymentListResponse,
    dependencies=[_VIEW],
)
async def list_subcontractor_progress_payments_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID | None = None,
    period_year: int | None = None,
    period_month: Annotated[int | None, Query(ge=1, le=12)] = None,
    status_filter: Annotated[SubcontractorPaymentStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(description="Taşeron adı veya sözleşme no araması")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SubcontractorProgressPaymentListResponse:
    """L83-101 filtreleri + `audit`/`users` sayfalama deseni (`total`/`limit`/`offset`)."""
    return await read.list_payments(
        session,
        user,
        project_id=project_id,
        period_year=period_year,
        period_month=period_month,
        status_filter=status_filter,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/subcontractor-progress-payments/{payment_id}",
    response_model=SubcontractorProgressPaymentDetail,
    dependencies=[_VIEW],
)
async def get_subcontractor_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    return await read.get_detail(session, user, payment_id)


@router.post(
    "/subcontractor-contracts/{contract_id}/progress-payments",
    response_model=SubcontractorProgressPaymentDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_DRAFT],
)
async def create_subcontractor_progress_payment_endpoint(
    request: Request,
    contract_id: uuid.UUID,
    data: SubcontractorProgressPaymentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """O66: satırlar sözleşme kalemlerinden OTOMATİK yüklenir; gövdede satır YOK.

    Fiyatsız kalem 422, aynı sözleşmede açık hakediş 409 (spec §2/§5).
    Yanıt `read.build_detail`den gelir — `get_detail` çağrılsaydı kapsam
    sorgusu istek başına İKİ KEZ koşardı (işveren H4 denetimi O3).
    """
    context = await service.create(session, user, contract_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.subcontractor_progress_payment_created(
            context.project.name, context.contract.subcontractor_name, context.payment.sequence_no
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, context)


@router.patch(
    "/subcontractor-progress-payments/{payment_id}",
    response_model=SubcontractorProgressPaymentDetail,
    dependencies=[_DRAFT],
)
async def update_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    data: SubcontractorProgressPaymentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """Yalnız `status=draft` (spec §5); aksi 409 `INVALID_STATUS_TRANSITION`."""
    context = await service.update(session, user, payment_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_updated(
            context.project.name, context.contract.subcontractor_name, context.payment.sequence_no
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, context)


@router.put(
    "/subcontractor-progress-payments/{payment_id}/lines",
    response_model=SubcontractorProgressPaymentDetail,
    dependencies=[_DRAFT],
)
async def save_subcontractor_progress_payment_lines_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    data: SubcontractorProgressPaymentLinesSave,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """O formunun tek "Taslak Kaydet" gövdesi — **DEĞİŞTİRME** semantiği.

    ⚠️ Gövdede geçmeyen satır SİLİNİR (`PUT …/contract/distribution`
    BİRLEŞTİRMESİNİN tersi). Yalnız `status=draft` (409); kalem sahipliği, fiyat
    guard'ı ve kota tavanı (spec §4) her yazımda koşar.

    Kalemi silinmiş satırlar gövdeden adreslenemediği için düşer; sayıları
    yanıtın `dropped_orphan_count` alanında BİLDİRİLİR (sessiz atlama yok).
    Detay `build_detail`den KAPSAM SORGUSU TEKRARLANMADAN kurulur.
    """
    context, dropped_orphan_count = await service.save_lines(session, user, payment_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_lines_saved(
            context.project.name,
            context.contract.subcontractor_name,
            context.payment.sequence_no,
            len(context.payment.lines),
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    detail = await read.build_detail(session, context)
    return detail.model_copy(update={"dropped_orphan_count": dropped_orphan_count})


@router.post(
    "/subcontractor-progress-payments/{payment_id}/refresh-prices",
    response_model=SubcontractorRefreshPricesResponse,
    dependencies=[_DRAFT],
)
async def refresh_subcontractor_progress_payment_prices_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorRefreshPricesResponse:
    """Yalnız `draft`ta snapshot beşlisini + yüzde üçlüsünü bilinçli tazeler.

    Yanıt YALNIZ `{refreshed_count}`tur (işveren deseni): güncel ekran ayrı bir
    `GET` ile okunur, tek gövdede sayaç + tam detay BİRLEŞTİRİLMEZ.
    """
    context, refreshed_count = await service.refresh_prices(session, user, payment_id)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_prices_refreshed(
            context.project.name,
            context.contract.subcontractor_name,
            context.payment.sequence_no,
            refreshed_count,
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return SubcontractorRefreshPricesResponse(refreshed_count=refreshed_count)


@router.delete(
    "/subcontractor-progress-payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_DRAFT],
)
async def delete_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Kapı `_DRAFT`tir (işveren silme ucunun aynı gerekçesi): `_ADMIN` olsaydı
    taslağı üreten şef/saha rollerinin KENDİ taslağını silme istisnası ölü kural
    olurdu. Kesin karar `service.delete_payment`tadır."""
    summary = await service.delete_payment(session, user, payment_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=messages.subcontractor_progress_payment_deleted(
            summary.project_name,
            summary.subcontractor_name,
            summary.sequence_no,
            summary.status_label,
            summary.amount,
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
