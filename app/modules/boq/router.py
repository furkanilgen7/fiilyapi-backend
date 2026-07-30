import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
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
