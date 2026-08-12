"""Personel kartoteksi uçları — puantaj T2 (spec §3).

`customers/router.py`nin birebiri: kapı sabitleri modül düzeyinde tanımlanır,
denetim metinleri `audit/messages.py`den gelir.

Kapılar `personnel` iznidir (seed'de HAZIR, matris DEĞİŞMEZ): okuma `view`,
yazma `full`. Bu ayrım **şantiye şefini SALT OKUR yapar** (matriste
`personnel=_V`) — işçiyi İK ekler (spec §5 bilinçli sınır).

**`visible_projects` süzgeci yok, ama `?project_id=` süzgeci VAR** (İK-1 spec §5
K4): `personnel` yine şirket-geneli bir İK varlığıdır ve tüm projelerde görünür.
Puantaj diliminin "proje süzgeci EKLEMESİN" notu `assigned_project_id` atama
kolonu YOKKEN geçerliydi; §5 K4 kararı bunu güncelledi — kolon açıldığından
`?project_id=` meşru bir DARALTMA süzgecidir, yetki genişletmez (IDOR açığı
DEĞİLDİR: kapsam denetimi yine `personnel` iznidir).

**DELETE ucu AÇILMAZ** (spec §3): puantaj kayıtları personele RESTRICT ile
bağlıdır; kartoteksten çıkarma `PATCH {"is_active": false}` ile yapılır.
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
from app.modules.personnel import repository, service
from app.modules.personnel.schemas import (
    PersonnelCreate,
    PersonnelListResponse,
    PersonnelResponse,
    PersonnelUpdate,
)
from app.modules.site_diary.models import WorkerSource
from app.modules.users.models import User

router = APIRouter(tags=["personnel"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)


@router.get("/personnel", response_model=PersonnelListResponse, dependencies=[_VIEW])
async def list_personnel_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    project_id: uuid.UUID | None = None,
    is_draft: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PersonnelListResponse:
    """`q` YALNIZ ada kısmi bakar (spec §3); süzgeçler AND'lidir.

    `is_active` GÖNDERİLMEZSE süzgeç uygulanmaz — pasif personel sessizce
    gizlenmez; ekran hangi kümeyi istediğini açıkça söyler. `project_id`
    (İK-1 §5 K4) `assigned_project_id`e göre DARALTIR — yetki genişletmez;
    `is_draft` taslakları ayıklamak için opsiyoneldir.
    """
    items = await repository.list_personnel(
        session,
        q=q,
        source=source,
        subcontractor_id=subcontractor_id,
        is_active=is_active,
        project_id=project_id,
        is_draft=is_draft,
        limit=limit,
        offset=offset,
    )
    total = await repository.count_personnel(
        session,
        q=q,
        source=source,
        subcontractor_id=subcontractor_id,
        is_active=is_active,
        project_id=project_id,
        is_draft=is_draft,
    )
    return PersonnelListResponse(
        items=[PersonnelResponse.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/personnel",
    response_model=PersonnelResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_personnel_endpoint(
    request: Request,
    data: PersonnelCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PersonnelResponse:
    personnel = await service.create_personnel(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.personnel_created(personnel.full_name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return PersonnelResponse.model_validate(personnel)


@router.get("/personnel/{personnel_id}", response_model=PersonnelResponse, dependencies=[_VIEW])
async def get_personnel_endpoint(
    personnel_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PersonnelResponse:
    personnel = await service.get_personnel(session, personnel_id)
    return PersonnelResponse.model_validate(personnel)


@router.patch("/personnel/{personnel_id}", response_model=PersonnelResponse, dependencies=[_FULL])
async def update_personnel_endpoint(
    request: Request,
    personnel_id: uuid.UUID,
    data: PersonnelUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PersonnelResponse:
    """Pasifleştirme de BURADAN geçer (`{"is_active": false}`) — DELETE ucu yoktur."""
    personnel = await service.update_personnel(session, personnel_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.personnel_updated(personnel.full_name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return PersonnelResponse.model_validate(personnel)
