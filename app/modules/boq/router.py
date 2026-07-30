import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
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
from app.modules.boq import service
from app.modules.boq.export import build_boq_workbook
from app.modules.boq.schemas import (
    BoqGroupCreate,
    BoqGroupResponse,
    BoqGroupUpdate,
    BoqItemCreate,
    BoqItemResponse,
    BoqItemUpdate,
    BoqListResponse,
)
from app.modules.users.models import User

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Spec §4 karari: BOQ okuma/yazma uclari "sites" degil kendi "boq" iznine
# baglidir — site_chief/field_engineer'i ayirmanin tek yolu budur. Yazma
# uclari (T5/T6) "_FULL" kullanir (view yetmez).
# Uc kokleri bilincli karisiktir (plan §Frontend notu): GET + POST'lar
# `/sites/...` altinda, PATCH'lar `/boq/...` kokunde (dolayli kimlik
# cozumlemesi kullandiklari icin yol parametreleri farkli).
router = APIRouter(tags=["boq"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("boq", AccessLevel.view)
_FULL = require_permission("boq", AccessLevel.full)


@router.get("/sites/{site_id}/boq", response_model=BoqListResponse, dependencies=[_VIEW])
async def get_boq_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqListResponse:
    return await service.get_boq_for_site(session, user, site_id)


def _content_disposition(filename: str) -> str:
    """Spec §5.3: dosya adi santiye kodundan turer, Turkce karakter icerebilir.

    RFC 5987 `filename*` UTF-8 parametresiyle birlikte ASCII-guvenli bir
    `filename` da yollanir (eski istemciler icin dusus): Turkce karakterler
    ASCII'ye yaklastirilir/atlanir, tirnak kacisi yapilir.
    """
    ascii_fallback = filename.encode("ascii", errors="ignore").decode("ascii").replace('"', "")
    if not ascii_fallback:
        ascii_fallback = "is-kalemleri.xlsx"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.get(
    "/sites/{site_id}/boq/export",
    dependencies=[_VIEW],
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "Excel dosyasi"}},
)
async def export_boq_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Spec §5.3: BOQ'yu xlsx olarak indirir. Okuma ucudur — `record_audit`
    cagirmaz (T7 kurali: okumalar denetim gunlugune yazmaz)."""
    site, boq = await service.get_boq_export_for_site(session, user, site_id)
    buffer = build_boq_workbook(boq)
    filename = f"is-kalemleri-{site.code}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.post(
    "/sites/{site_id}/boq/groups",
    response_model=BoqGroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_boq_group_endpoint(
    request: Request,
    site_id: uuid.UUID,
    data: BoqGroupCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqGroupResponse:
    group = await service.create_group(session, user, site_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.boq_group_created(group.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return service.to_group(group)


@router.post(
    "/sites/{site_id}/boq/items",
    response_model=BoqItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_boq_item_endpoint(
    request: Request,
    site_id: uuid.UUID,
    data: BoqItemCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqItemResponse:
    item = await service.create_item(session, user, site_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.boq_item_created(item.code, item.description),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return service.to_item(item)


@router.patch("/boq/groups/{group_id}", response_model=BoqGroupResponse, dependencies=[_FULL])
async def update_boq_group_endpoint(
    request: Request,
    group_id: uuid.UUID,
    data: BoqGroupUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqGroupResponse:
    group = await service.update_group(session, user, group_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.boq_group_updated(group.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return service.to_group(group)


@router.patch("/boq/items/{item_id}", response_model=BoqItemResponse, dependencies=[_FULL])
async def update_boq_item_endpoint(
    request: Request,
    item_id: uuid.UUID,
    data: BoqItemUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqItemResponse:
    item = await service.update_item(session, user, item_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.boq_item_updated(item.code, item.description),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return service.to_item(item)
