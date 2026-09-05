"""BC-3 belge ↔ varlık bağı uçları — 1 katalog + 4 sahip × 4 uç = 17 operasyon.

## `documents_router`dan ÖNCE kaydedilir — ama ÖLÇÜLDÜ: bugün gölgeleme YOK

`GET /documents/slot-types` İKİ segmentli bir LİTERALDİR; `documents_router`ın
`/documents/{document_id}` yolu da İKİ segmentlidir — fakat o yol yalnız
PATCH/DELETE taşır, GET detay ucu YOKTUR (`/download` üç segmentlidir). FastAPI'de
sıra kısıtı yalnız AYNI metotta doğar (yol tutup metot tutmayan aday
`Match.PARTIAL` kalır, arama sürer) → bugün `slot-types` UUID SANILAMAZ, sıra
ters çevrilse bile. Bu, emirdeki "sıra bekçisi + mutasyon" beklentisinin
ÖLÇÜLEREK ÇÜRÜTÜLMESİDİR: sırayı ölçen bir bekçi eşdeğer mutant olurdu.

Bunun yerine ÖN KOŞUL kilitlenir (`test_TRIPWIRE_documents_routerda_GET_detay_YOK`):
biri `GET /documents/{document_id}` açtığı gün test kırmızıya döner ve sıra o gün
gerçekten zorunlu olur; pozitif kontrolü, böyle bir GET'in sentetik olarak
eklendiği uygulamada gölgelemenin GERÇEKTEN oluştuğunu gösterir (çözücü kör
değildir). Router yine de `app/core/router_registry.py`de `documents_router`dan
önce durur — sıfır maliyetli sigorta (`sites_flat_list_router` emsali).

Dört sahip kökü (`/sections` · `/units` · `/sales` · `/subcontractor-contracts`)
ile sahip router'ları arasında sıra tuzağı YOKTUR (ölçüldü): bağ uçları ÜÇ
segmentlidir ve son/orta segmenti LİTERALDİR (`documents`), sahip router'larının
`/{id}` yolları İKİ segmentlidir; üç segmentli komşular (`/sections/{id}/stock`,
`/subcontractor-contracts/items/{id}`, `/sales/{id}/installments`…) farklı
literal taşır.

## Sahip başına dört uç, TEK fabrika

`_register(spec)` dört sahibe aynı dört ucu açar; yol kökü, izin anahtarı ve
404 cümlesi `OwnerSpec`ten gelir. Dört router elle yazılsaydı IDOR kapısı ve
kapsam kuralı dört kez kopyalanırdı. `operation_id` sahip anahtarıyla
AÇIKÇA verilir — yoksa FastAPI dört özdeş fonksiyon adından çakışan
operasyon kimliği üretir.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez).
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
from app.modules.documents import link_service as service
from app.modules.documents.link_owners import OWNER_SPECS, OwnerSpec
from app.modules.documents.link_repository import LinkRow
from app.modules.documents.link_schemas import (
    EntityDocumentLinkCreate,
    EntityDocumentLinkListResponse,
    EntityDocumentLinkRead,
    EntityDocumentLinkUpdate,
    EntityDocumentTypeListResponse,
    EntityDocumentTypeRead,
)
from app.modules.documents.models.links import EntityDocumentScope
from app.modules.documents.schemas import DocumentRead
from app.modules.users.models import User

router = APIRouter(tags=["entity-documents"], responses=COMMON_ERROR_RESPONSES)

#: Katalog okuma kapısı: `documents` modülünde hiçbir rol `none` değildir
#: (spec §6) — slot listesini her rol görebilir.
_CATALOG_VIEW = require_permission("documents", AccessLevel.view)

_OWNER_404 = {404: {"description": "Kayıt bulunamadı (görünmeyen dahil)"}}
_LINK_404 = {404: {"description": "Belge bağı bulunamadı (görünmeyen kaydın bağı dahil)"}}


def _to_read(spec: OwnerSpec, row: LinkRow) -> EntityDocumentLinkRead:
    link = row.link
    return EntityDocumentLinkRead(
        id=link.id,
        owner_id=getattr(link, spec.owner_column.key),
        scope=link.scope,
        type_id=row.doc_type.id,
        type_code=row.doc_type.code,
        type_name=row.doc_type.name,
        is_required=row.doc_type.is_required,
        document_id=link.document_id,
        document=None if row.document is None else DocumentRead.model_validate(row.document),
        issued_at=link.issued_at,
        valid_until=link.valid_until,
        note=link.note,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


async def _audit(
    request: Request, session: AsyncSession, user: User, action: AuditAction, detail: str
) -> None:
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get(
    "/documents/slot-types",
    response_model=EntityDocumentTypeListResponse,
    dependencies=[_CATALOG_VIEW],
)
async def list_slot_types_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    scope: EntityDocumentScope | None = None,
) -> EntityDocumentTypeListResponse:
    """18 sabit slot (3+3+6+6), `scope` ile süzülür. CRUD ucu YOK."""
    types = await service.list_slot_types(session, scope)
    return EntityDocumentTypeListResponse(
        items=[EntityDocumentTypeRead.model_validate(t) for t in types]
    )


def _register(spec: OwnerSpec) -> None:
    view = require_permission(spec.permission_module, AccessLevel.view)
    full = require_permission(spec.permission_module, AccessLevel.full)
    owner_path = f"{spec.route_root}/{{owner_id}}/documents"
    link_path = f"{spec.route_root}/documents/{{link_id}}"

    @router.get(
        owner_path,
        response_model=EntityDocumentLinkListResponse,
        responses=_OWNER_404,
        dependencies=[view],
        operation_id=f"list_{spec.key}_documents",
        summary=f"{spec.label} belgeleri",
    )
    async def list_endpoint(
        owner_id: uuid.UUID,
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> EntityDocumentLinkListResponse:
        rows = await service.list_links(session, user, spec, owner_id)
        return EntityDocumentLinkListResponse(items=[_to_read(spec, r) for r in rows])

    @router.post(
        owner_path,
        response_model=EntityDocumentLinkRead,
        status_code=status.HTTP_201_CREATED,
        responses={
            **_OWNER_404,
            422: {"description": "Slot bu kayıt için geçersiz ya da belge bu projede değil"},
        },
        dependencies=[full],
        operation_id=f"attach_{spec.key}_document",
        summary=f"{spec.label} belgesi bağla",
    )
    async def attach_endpoint(
        request: Request,
        owner_id: uuid.UUID,
        data: EntityDocumentLinkCreate,
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> EntityDocumentLinkRead:
        row, detail = await service.attach(session, user, spec, owner_id, data)
        await _audit(request, session, user, AuditAction.create, detail)
        return _to_read(spec, row)

    @router.patch(
        link_path,
        response_model=EntityDocumentLinkRead,
        responses=_LINK_404,
        dependencies=[full],
        operation_id=f"update_{spec.key}_document",
        summary=f"{spec.label} belgesi künyesi",
    )
    async def update_endpoint(
        request: Request,
        link_id: uuid.UUID,
        data: EntityDocumentLinkUpdate,
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> EntityDocumentLinkRead:
        row, detail = await service.update(session, user, spec, link_id, data)
        await _audit(request, session, user, AuditAction.update, detail)
        return _to_read(spec, row)

    @router.delete(
        link_path,
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_LINK_404,
        dependencies=[full],
        operation_id=f"detach_{spec.key}_document",
        summary=f"{spec.label} belgesi bağını kaldır",
    )
    async def detach_endpoint(
        request: Request,
        link_id: uuid.UUID,
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        detail = await service.detach(session, user, spec, link_id)
        await _audit(request, session, user, AuditAction.delete, detail)


for _spec in OWNER_SPECS:
    _register(_spec)
