"""Ünite satışı uçları — P8 T3 (spec §4).

`units/router.py` deseninin aynısı: uçlar İKİ ayrı kök altına dağılır — proje
bağlamlı uçlar `/projects/{project_id}/sales`, kimliği yukarı çözümleyen tekil
uçlar `/sales/{sale_id}` altındadır; bu yüzden router prefix TAŞIMAZ.

**BFF TUZAĞI (frontend dilimi için):** kök `sales`tir ve `customers` (T2) ile
BİRLİKTE `src/app/api/backend/[...path]/route.ts` `ALLOWED_ROOTS` listesine
eklenmelidir — eklenmezse modül YALNIZ CANLIDA 404 verir, jsdom testleri görmez.

BU DİLİMDE OLMAYAN uçlar: `generate-plan` / `PUT installments` / `pay` (T4) ·
`activate` / `transfer-deed` / `cancel` / `summary` (T5).
"""

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
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.sales import service
from app.modules.sales.schemas import (
    UnitSaleCreate,
    UnitSaleListResponse,
    UnitSaleResponse,
    UnitSaleUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["sales"], responses=COMMON_ERROR_RESPONSES)

# Spec §8 S1 (kullanıcı kararı): satış yetkisi proje yetkisinden AYRILIR —
# `sales` kendi izin modülüdür (matris 19). Kapsam (`visible_projects`) yine
# `projects` üzerinden gelir: izin "yetki", `user_project_access` "kapsam"dır.
_VIEW = require_permission("sales", AccessLevel.view)
_FULL = require_permission("sales", AccessLevel.full)
# KALICI KARAR 2026-07-30: SİLME bir seviye yukarıdadır — `full` yazmayı
# kapsar, SİLMEYİ KAPSAMAZ (`app/core/access.py` §5.0).
_ADMIN = require_permission("sales", AccessLevel.admin)


async def _audit(
    request: Request, session: AsyncSession, user: User, action: AuditAction, detail: str
) -> None:
    """Denetim satırı (B5 deseni). Metin servis katmanından HAZIR gelir.

    Yalnız YAZMA uçları çağırır — okuma uçları denetim satırı ÜRETMEZ (P4 T7
    kuralı). `record_audit` commit etmez: satır asıl işlemle AYNI transaction'a
    girer, dolayısıyla reddedilen (409/422) bir istek denetim satırı bırakmaz.
    """
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get(
    "/projects/{project_id}/sales", response_model=UnitSaleListResponse, dependencies=[_VIEW]
)
async def list_sales_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitSaleListResponse:
    """S150-212. "Tahsil Edilen"/"Kalan" TÜREVDİR (`sale_installments`), kolon değil."""
    return await service.list_sales(session, user, project_id)


@router.post(
    "/projects/{project_id}/sales",
    response_model=UnitSaleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_sale_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitSaleCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitSaleResponse:
    """Üç kapı: ünite bu projeye ait olmalı (404) · `landowner` ünite satılamaz

    (422, spec §8 S3) · ünitede ikinci AÇIK kayıt olamaz (409).
    """
    sale, detail = await service.create_sale(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return sale


@router.get("/sales/{sale_id}", response_model=UnitSaleResponse, dependencies=[_VIEW])
async def get_sale_endpoint(
    sale_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitSaleResponse:
    """Kimlik YUKARI çözümlenir (satış → proje → görünürlük); görünmeyen projenin
    satışı 404 döner, 403 DEĞİL — üstelik var olmayanla AYNI gövdeyi verir."""
    return await service.get_sale(session, user, sale_id)


@router.patch("/sales/{sale_id}", response_model=UnitSaleResponse, dependencies=[_FULL])
async def update_sale_endpoint(
    request: Request,
    sale_id: uuid.UUID,
    data: UnitSaleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitSaleResponse:
    """Durum geçişleri BU UÇTAN YAPILMAZ: `status` şemada yoktur, `activate` /
    `transfer-deed` / `cancel` uçları T5'in işidir."""
    sale, detail = await service.update_sale(session, user, sale_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return sale


@router.delete("/sales/{sale_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_ADMIN])
async def delete_sale_endpoint(
    request: Request,
    sale_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §4: YALNIZ `reservation` silinir; `active`/`deed_transferred` 409 ile

    reddedilir ve iptal edilerek (T5 `cancel`) kapatılır. Kapı `_ADMIN`dir —
    `units`/`blocks` DELETE uçlarıyla tutarlı (kalıcı karar 2026-07-30). Yetki
    kapısı durum korkuluğundan ÖNCE çalışır: yetkisiz aktör 403 alır ve kaydın
    hangi durumda olduğunu ÖĞRENEMEZ.
    """
    detail = await service.delete_sale(session, user, sale_id)
    await _audit(request, session, user, AuditAction.delete, detail)
