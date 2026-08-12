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
    PersonnelDocumentCreate,
    PersonnelDocumentResponse,
    PersonnelDocumentUpdate,
    PersonnelListResponse,
    PersonnelResponse,
    PersonnelUpdate,
)
from app.modules.site_diary.models import WorkerSource
from app.modules.users.models import User

router = APIRouter(tags=["personnel"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)
# SİLME yazmadan BİR SEVİYE YUKARIDADIR (`documents`/`sites` deseni):
# `app/core/access.py` "full yazmayı kapsar, SİLMEYİ KAPSAMAZ" der. Belge silme
# İK kaydını yok eder (BC arşiv künyesi SET NULL ile durur) — yanlış açılan bir
# kaydı yalnız `admin` temizleyebilir.
_ADMIN = require_permission(service.PERMISSION_MODULE, AccessLevel.admin)


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


# --- İK-1 T3: belge alt-kaynağı (spec §3) ------------------------------------
#
# Rota kökleri BİLİNÇLİ olarak İKİYE AYRILIR (`documents` deseni): liste/ekleme
# personele bağlıdır (`/personnel/{id}/documents`), güncelleme/silme belgenin
# kendi kimliğiyledir (`/personnel/documents/{doc_id}`) — belgeyi düzenlemek için
# personel kimliğini de taşımak gereksizdir ve iki kimlikli yol çelişki riski açar.


@router.get(
    "/personnel/{personnel_id}/documents",
    response_model=list[PersonnelDocumentResponse],
    dependencies=[_VIEW],
)
async def list_personnel_documents_endpoint(
    personnel_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PersonnelDocumentResponse]:
    """O personelin belgeleri (tip künyeli, N+1 yok). Personel yok → 404.

    `status`/`days_left` TÜREVdir (`status.py` tek kaynağı); GET denetlenmez.
    """
    return await service.list_personnel_documents(session, personnel_id)


@router.post(
    "/personnel/{personnel_id}/documents",
    response_model=PersonnelDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_personnel_document_endpoint(
    request: Request,
    personnel_id: uuid.UUID,
    data: PersonnelDocumentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PersonnelDocumentResponse:
    """Belge kaydı. `type_id` XOR `free_label`; pasif tip → 422, yok → 404;

    görünmez/var olmayan BC belgesi (`document_id`) → 404 (IDOR korkuluğu).
    """
    response, detail = await service.create_personnel_document(session, user, personnel_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return response


@router.patch(
    "/personnel/documents/{document_id}",
    response_model=PersonnelDocumentResponse,
    dependencies=[_FULL],
)
async def update_personnel_document_endpoint(
    request: Request,
    document_id: uuid.UUID,
    data: PersonnelDocumentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PersonnelDocumentResponse:
    """Kısmi güncelleme. Belge yok → 404; `document_id` değişimi aynı BC görünürlük
    denetiminden geçer."""
    response, detail = await service.update_personnel_document(session, user, document_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return response


@router.delete(
    "/personnel/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ADMIN],
)
async def delete_personnel_document_endpoint(
    request: Request,
    document_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """İK takip kaydını siler (`admin`; `full` silmeyi KAPSAMAZ). SET NULL: bağlı
    BC arşiv künyesi DURUR (dosya arşivde kalır). Yanıt 204, gövdesiz."""
    detail = await service.delete_personnel_document(session, document_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
