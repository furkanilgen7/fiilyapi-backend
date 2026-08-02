"""Taşeron hakedişi durum aksiyonları (T4, spec §5) — beş uç.

`router.py`den AYRI dosyadadır (dosya başına ~400 satır kuralı); tek bir
`APIRouter` olarak kalması için `router.py` sonunda `include_router` ile
BAĞLANIR — yön tek taraflıdır (`router` → `router_transitions`), ters import
açılmaz ve modül dışına tek bir router çıkar.

Beş uç da TEK yoldan (`transitions.perform`) geçer; geçiş tablosu, kilit ve
kotanın onay anındaki yeniden doğrulaması ORADA tek kopyadır. Router'ın tek işi
KAPIYI seçmek ve denetim satırını yazmaktır — durum kontrolü BURADA
TEKRARLANMAZ (işveren `progress_payments/router.py` deseninin birebiri).

Kapı seviyeleri işverenle AYNIDIR (aynı izin modülü, aynı ekran ailesi):
`submit` → `_DRAFT` · `approve`/`reject`/`mark-paid` → `_APPROVE` ·
`unapprove` → `_ADMIN`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
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
from app.modules.subcontractor_progress_payments import read, transitions
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentDetail,
    SubcontractorRejectBody,
)
from app.modules.subcontractor_progress_payments.service import PaymentContext
from app.modules.users.models import User

router = APIRouter(tags=["subcontractor-progress-payments"], responses=COMMON_ERROR_RESPONSES)

_DRAFT = require_permission("progress_payments", AccessLevel.draft)
_APPROVE = require_permission("progress_payments", AccessLevel.approve)
_ADMIN = require_permission("progress_payments", AccessLevel.admin)

_PATH = "/subcontractor-progress-payments/{payment_id}"


def _context(result: transitions.TransitionResult) -> PaymentContext:
    """Yanıt `read.build_detail`den KAPSAM SORGUSU TEKRARLANMADAN kurulur:
    `perform` kapsam kararını çoktan vermiş ve üçlüyü döndürmüştür (işveren
    ucunun `get_detail` çağrısı kapsamı istek başına İKİ KEZ sorgular)."""
    return PaymentContext(payment=result.payment, contract=result.contract, project=result.project)


@router.post(
    f"{_PATH}/submit", response_model=SubcontractorProgressPaymentDetail, dependencies=[_DRAFT]
)
async def submit_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """`draft → pending_approval`. Zorunluluk kuralları (dönem + Σmiktar>0)
    YALNIZ burada koşar: taslak eksik veriyle serbestçe saklanır.

    "Revize Gerekli" damgası (`rejected_at`/`rejection_reason`) burada TEMİZLENİR.
    """
    result = await transitions.perform(session, user, payment_id, transitions.PaymentAction.submit)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_submitted(
            result.project.name, result.contract.subcontractor_name, result.payment.sequence_no
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, _context(result))


@router.post(
    f"{_PATH}/approve", response_model=SubcontractorProgressPaymentDetail, dependencies=[_APPROVE]
)
async def approve_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """`pending_approval → approved`; kota KİLİT ALTINDA sırasız TAM küme
    üzerinden YENİDEN doğrulanır (spec §4) — aşım 422, onay GERÇEKLEŞMEZ."""
    result = await transitions.perform(session, user, payment_id, transitions.PaymentAction.approve)
    # `AuditAction.approve` TAM BU UÇ için ayrılmıştır; diğer geçişler `update`.
    await record_audit(
        session,
        action=AuditAction.approve,
        detail=messages.subcontractor_progress_payment_approved(
            result.project.name, result.contract.subcontractor_name, result.payment.sequence_no
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, _context(result))


@router.post(
    f"{_PATH}/reject", response_model=SubcontractorProgressPaymentDetail, dependencies=[_APPROVE]
)
async def reject_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    data: SubcontractorRejectBody,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """`pending_approval → draft` — ret BEŞİNCİ durum DEĞİLDİR (spec §5).

    İşverenden AYRILAN nokta: gövde ZORUNLUDUR ve gerekçe `rejection_reason`
    KOLONUNA yazılır; `rejected_at` ile birlikte L177 "Revize Gerekli" rozetinin
    (`is_revision_required` türevi) kaynağıdır.
    """
    result = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.reject, reason=data.reason
    )
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_rejected(
            result.project.name,
            result.contract.subcontractor_name,
            result.payment.sequence_no,
            result.payment.rejection_reason or data.reason,
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, _context(result))


@router.post(
    f"{_PATH}/mark-paid", response_model=SubcontractorProgressPaymentDetail, dependencies=[_APPROVE]
)
async def mark_paid_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """`approved → paid`. Ödeme detayı formu mockup'ta YOK → tek tıkla
    işaretleme, yalnız `paid_at` damgalanır (fatura/ödeme bağı mali dilimlere)."""
    result = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.mark_paid
    )
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_paid(
            result.project.name, result.contract.subcontractor_name, result.payment.sequence_no
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, _context(result))


@router.post(
    f"{_PATH}/unapprove", response_model=SubcontractorProgressPaymentDetail, dependencies=[_ADMIN]
)
async def unapprove_subcontractor_progress_payment_endpoint(
    request: Request,
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorProgressPaymentDetail:
    """`approved → pending_approval` (geri çek) — YALNIZ `admin`.

    `paid` kaynak DEĞİLDİR: ödenmiş hakedişin geri dönüşü yoktur, denemesi 409.
    Denetim mesajı ESKİ onaylayanı taşır — `transitions.perform` bu ikisini
    damgalar NULL'lanmadan ÖNCE yakalar, router yeniden sorgulayamaz.
    """
    result = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.unapprove
    )
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.subcontractor_progress_payment_unapproved(
            result.project.name,
            result.contract.subcontractor_name,
            result.payment.sequence_no,
            result.previous_approver_name,
            result.previous_approved_at,
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await read.build_detail(session, _context(result))
