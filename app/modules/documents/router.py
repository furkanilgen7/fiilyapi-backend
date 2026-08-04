"""Klasör uçları (T2) — spec §3 birinci satırı.

Kapı `documents` iznidir (spec §7 S2, 20. modül): okuma `view`, klasör açma ve
adlandırma `full`, silme `admin`. Üç seviye üç ayrı bağımlılıktır ve BURADA
durur; servis katmanı yetkiye değil KAPSAMA (`visible_projects`) bakar.

`GET` `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez); üç yazma
ucunun üçü de tek denetim satırı yazar ve metni servis katmanında, kayıt
değişmeden/yok olmadan ÖNCE kurulur.

Router prefix TAŞIMAZ: uçlar iki ayrı kök altına dağılır (`/projects/{id}/
document-folders` ve `/document-folders/{id}`), `sites/router.py` deseninin
birebiri.

BELGE UÇLARI BURADA YOKTUR — yükleme/indirme/liste/silme T3'tür.
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
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.documents import service
from app.modules.documents.schemas import (
    DocumentFolderCreate,
    DocumentFolderListResponse,
    DocumentFolderRead,
    DocumentFolderUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["documents"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)
# SILME uclari yazma uclarindan BIR SEVIYE YUKARIDADIR (`sites`/`units`/`boq`
# deseni): `app/core/access.py` "full yazmayi kapsar, SILMEYI KAPSAMAZ" der.
# Sonucu (kabul edildi): seed matrisinde `documents:admin` yalniz
# `system_admin`dedir — patron dahil kimse klasor silemez.
_ADMIN = require_permission(service.PERMISSION_MODULE, AccessLevel.admin)


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satırı (B5 deseni). Metin PARAMETREDİR, burada kurulmaz."""
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get(
    "/projects/{project_id}/document-folders",
    response_model=DocumentFolderListResponse,
    dependencies=[_VIEW],
)
async def list_document_folders_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    site_id: Annotated[uuid.UUID | None, Query()] = None,
) -> DocumentFolderListResponse:
    """Bir KÖKÜN klasörleri — düz liste, hiyerarşiyi `parent_id` taşır.

    `site_id` bir SÜZGEÇTİR: verilmezse yalnız PROJE DÜZEYİ klasörler döner,
    verilirse yalnız o şantiyeninkiler. Gerekçe `service.list_folders`tadır
    (E12 kökü her an tek bir proje/şantiye ikilisidir).

    Görünmeyen proje 404 döner ve gövdesi var olmayan kimliğinkiyle AYNIDIR.
    """
    folders = await service.list_folders(session, user, project_id, site_id)
    return DocumentFolderListResponse(
        folders=[DocumentFolderRead.model_validate(f) for f in folders]
    )


@router.post(
    "/projects/{project_id}/document-folders",
    response_model=DocumentFolderRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Bu kapsamda aynı adlı klasör var"}},
    dependencies=[_FULL],
)
async def create_document_folder_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: DocumentFolderCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentFolderRead:
    """Yeni klasör. Kategori seti SERBESTTİR (spec §7 S3) — otomatik seed YOKTUR.

    * ad çakışması → 409 (kontrol UYGULAMA katmanındadır; T1 bulgusu: NULL'lı
      kapsamda DB kısıtı işlemez)
    * `site_id` başka projenin şantiyesi → 422
    * `parent_id` başka kapsamın klasörü → 422
    """
    folder, detail = await service.create_folder(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return DocumentFolderRead.model_validate(folder)


@router.patch(
    "/document-folders/{folder_id}",
    response_model=DocumentFolderRead,
    responses={409: {"description": "Bu kapsamda aynı adlı klasör var"}},
    dependencies=[_FULL],
)
async def rename_document_folder_endpoint(
    request: Request,
    folder_id: uuid.UUID,
    data: DocumentFolderUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentFolderRead:
    """YALNIZ ad değişir. Klasör TAŞIMA ucu yoktur (gerekçe `schemas`ta)."""
    context = await service.visible_folder(session, user, folder_id)
    folder, detail = await service.rename_folder(session, context, data.name)
    await _audit(request, session, user, AuditAction.update, detail)
    return DocumentFolderRead.model_validate(folder)


@router.delete(
    "/document-folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "Klasör boş değil"}},
    dependencies=[_ADMIN],
)
async def delete_document_folder_endpoint(
    request: Request,
    folder_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """YALNIZ BOŞ klasör silinir; belge ya da alt klasör varsa 409.

    Yetki kapısı korkuluktan ÖNCE koşar: yetkisiz aktör 403 alır ve klasörün
    dolu olup olmadığını ÖĞRENEMEZ. Görünmeyen klasör 404 döner.

    Yanıt `204 No Content`, gövdesizdir.
    """
    context = await service.visible_folder(session, user, folder_id)
    detail = await service.delete_folder(session, context)
    await _audit(request, session, user, AuditAction.delete, detail)
