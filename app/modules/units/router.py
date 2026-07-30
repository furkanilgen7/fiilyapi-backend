import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import UnitValidationError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.units import batch, importer, service
from app.modules.units.models import UnitKind
from app.modules.units.schemas import (
    BlockCreate,
    BlockListResponse,
    BlockResponse,
    BlockUpdate,
    UnitAllocationRequest,
    UnitBulkCreate,
    UnitCreate,
    UnitImportResult,
    UnitListResponse,
    UnitOwnerSideFilter,
    UnitResponse,
    UnitUpdate,
)
from app.modules.users.models import User

# Uclar iki ayri kok altina dagilir (P4 deseni): proje baglamli uclar
# `/projects/...`, kimligi yukari cozumleyen tekil uclar `/blocks/...` ve
# `/units/...` altindadir — bu yuzden router prefix TASIMAZ.
#
# BFF TUZAGI (frontend dilimi icin): IKI kok var, `units` VE `blocks`. Ikisi de
# `src/app/api/backend/[...path]/route.ts` ALLOWED_ROOTS listesine eklenmezse
# ilgili modul YALNIZ CANLIDA 404 verir.
router = APIRouter(tags=["units"], responses=COMMON_ERROR_RESPONSES)

# Spec §8: YENI IZIN MODULU ACILMAZ — blok ve unite projenin alt kayitlaridir,
# `projects` modulunun seviyeleri kullanilir. Modul sayisi 17'de kalir.
_VIEW = require_permission("projects", AccessLevel.view)
# Yazma uclari `full` ister (spec §8): `view` yetmez (IDOR-13).
_FULL = require_permission("projects", AccessLevel.full)


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satiri (spec §9, B5 deseni).

    Metin servis katmanindan HAZIR gelir: silme uclarinda adlar kayit yok
    olmadan once okunmak zorundadir ve router onlari sonradan hicbir sorguyla
    geri getiremez (bkz. `service.py` §9 notu). Yalniz YAZMA uclari cagirir —
    okuma uclari denetim satiri URETMEZ (P4 T7 kurali).

    `record_audit` commit etmez: satir asil islemle AYNI transaction'a girer,
    dolayisiyla reddedilen (409/422) bir istek denetim satiri da birakmaz.
    """
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get("/projects/{project_id}/blocks", response_model=BlockListResponse, dependencies=[_VIEW])
async def list_blocks_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockListResponse:
    """Spec §7.1. Blok seciciler (unite formu, toplu uretim formu) bu ucu kullanir."""
    return await service.list_blocks(session, user, project_id)


@router.get("/projects/{project_id}/units", response_model=UnitListResponse, dependencies=[_VIEW])
async def list_units_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    block_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    kind: Annotated[UnitKind | None, Query()] = None,
    owner_side: Annotated[UnitOwnerSideFilter | None, Query()] = None,
) -> UnitListResponse:
    """Spec §7.4. Suzgecler YALNIZ listeyi daraltir; `totals` daima projenin
    tamamini sayar. `site_id` blok uzerinden cozulur (`units`'te `site_id` yok)."""
    return await service.list_units(
        session,
        user,
        project_id,
        block_id=block_id,
        site_id=site_id,
        kind=kind,
        owner_side=owner_side,
    )


@router.post(
    "/projects/{project_id}/blocks",
    response_model=BlockResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_block_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: BlockCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.2. Tek santiyeli projede `site_id` gonderilmezse otomatik atanir
    (§4.5) — mockup'ta santiye secici yoktur (KY 38 / KK 39)."""
    block, detail = await service.create_block(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.block_response(session, block)


@router.patch("/blocks/{block_id}", response_model=BlockResponse, dependencies=[_FULL])
async def update_block_endpoint(
    request: Request,
    block_id: uuid.UUID,
    data: BlockUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.3. Kimlik YUKARI cozumlenir (blok → proje → gorunurluk);
    gorunmeyen projenin blogu 404 doner, 403 DEGIL."""
    block, detail = await service.update_block(session, user, block_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.block_response(session, block)


@router.post(
    "/projects/{project_id}/units",
    response_model=UnitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_unit_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.5. Govdedeki `block_id` bu projeye ait olmali (IDOR-9), aksi hâlde 404."""
    unit, detail = await service.create_unit(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return await service.unit_response(session, unit)


@router.patch("/units/{unit_id}", response_model=UnitResponse, dependencies=[_FULL])
async def update_unit_endpoint(
    request: Request,
    unit_id: uuid.UUID,
    data: UnitUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.6. Kimlik YUKARI cozumlenir (unite → proje → gorunurluk);
    `block_id` ile ayni proje icinde tasima serbesttir."""
    unit, detail = await service.update_unit(session, user, unit_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return await service.unit_response(session, unit)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_FULL])
async def delete_unit_endpoint(
    request: Request,
    unit_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.9. Unite silme kosulsuzdur (P3'te uniteye bagli tablo yok, §1.3).
    Gorunmeyen projenin unitesi 404 doner, 403 DEGIL."""
    detail = await service.delete_unit(session, user, unit_id)
    await _audit(request, session, user, AuditAction.delete, detail)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_FULL])
async def delete_block_endpoint(
    request: Request,
    block_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.9. CASCADE YOK: unitesi olan blok 409 ile reddedilir — 24 daireyi
    tek istekte silmek geri alinamaz veri kaybidir."""
    detail = await service.delete_block(session, user, block_id)
    await _audit(request, session, user, AuditAction.delete, detail)


@router.post(
    "/projects/{project_id}/units/bulk",
    response_model=UnitListResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def bulk_create_units_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitBulkCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitListResponse:
    """Spec §7.7. HEP-YA-HIC: uretilen numaralardan biri bile blokta varsa
    HICBIRI yazilmaz (409). Yanit guncel tam listedir — ekran tabloyu yeniden
    cizer, ikinci bir GET'e gerek kalmaz.

    Denetim: 24 unite uretilse de ISTEK BASINA TEK satir yazilir (spec §9)."""
    result, detail = await batch.bulk_create_units(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return result


@router.patch(
    "/projects/{project_id}/units/allocation",
    response_model=UnitListResponse,
    dependencies=[_FULL],
)
async def update_allocation_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: UnitAllocationRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitListResponse:
    """Spec §7.10 (KKP 25). Paylar TOPLU URETIMDE atanmaz, SONRADAN bu ucla
    girilir: paylasim noterden sonra belli olur (KKP 78).

    ATOMIK: tek satir bile reddedilirse hicbiri yazilmaz. Listedeki bir unite
    BASKA projeye aitse 404 doner (IDOR-8) ve bu projenin hicbir satiri
    degismez. Yanit guncel tam listedir — ekran tabloyu yeniden cizer.

    Denetim: 42 unitelik bir kayit TEK satir yazar (spec §9) — satir basina
    gunluk, denetim gunlugunu okunamaz hâle getirirdi.
    """
    result, detail = await batch.update_allocation(session, user, project_id, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return result


@router.post(
    "/projects/{project_id}/units/import",
    response_model=UnitImportResult,
    dependencies=[_FULL],
)
async def import_units_endpoint(
    request: Request,
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> UnitImportResult:
    """Spec §7.8. BELGE SAKLAMA ALTYAPISI GEREKMEZ ve kurulmayacaktir: dosya
    bellekte okunur, uniteler yaratilir, dosya ATILIR. Diske, S3'e, veritabanina
    hicbir sey yazilmaz — P3'e sigmasinin tek sebebi budur.

    Boyut IKI KEZ olculur: once istemcinin bildirdigi `size` ile (henuz govde
    bellege alinmadan), sonra GERCEKTEN okunan `bytes` uzunluguyla
    (`parse_units_file`) — istemci basligina guvenilmez.
    """
    try:
        importer.ensure_xlsx(file.filename)
        importer.ensure_size(file.size)
    except importer.ImportFileError as exc:
        raise UnitValidationError(str(exc)) from exc
    result, detail = await batch.import_units(session, user, project_id, await file.read())
    await _audit(request, session, user, AuditAction.create, detail)
    return result
