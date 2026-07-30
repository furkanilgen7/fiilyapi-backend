import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.units import service
from app.modules.units.models import UnitKind
from app.modules.units.schemas import (
    BlockCreate,
    BlockListResponse,
    BlockResponse,
    BlockUpdate,
    UnitCreate,
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
    project_id: uuid.UUID,
    data: BlockCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.2. Tek santiyeli projede `site_id` gonderilmezse otomatik atanir
    (§4.5) — mockup'ta santiye secici yoktur (KY 38 / KK 39)."""
    block = await service.create_block(session, user, project_id, data)
    return await service.block_response(session, block)


@router.patch("/blocks/{block_id}", response_model=BlockResponse, dependencies=[_FULL])
async def update_block_endpoint(
    block_id: uuid.UUID,
    data: BlockUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockResponse:
    """Spec §7.3. Kimlik YUKARI cozumlenir (blok → proje → gorunurluk);
    gorunmeyen projenin blogu 404 doner, 403 DEGIL."""
    block = await service.update_block(session, user, block_id, data)
    return await service.block_response(session, block)


@router.post(
    "/projects/{project_id}/units",
    response_model=UnitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_unit_endpoint(
    project_id: uuid.UUID,
    data: UnitCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.5. Govdedeki `block_id` bu projeye ait olmali (IDOR-9), aksi hâlde 404."""
    unit = await service.create_unit(session, user, project_id, data)
    return await service.unit_response(session, unit)


@router.patch("/units/{unit_id}", response_model=UnitResponse, dependencies=[_FULL])
async def update_unit_endpoint(
    unit_id: uuid.UUID,
    data: UnitUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UnitResponse:
    """Spec §7.6. Kimlik YUKARI cozumlenir (unite → proje → gorunurluk);
    `block_id` ile ayni proje icinde tasima serbesttir."""
    unit = await service.update_unit(session, user, unit_id, data)
    return await service.unit_response(session, unit)
