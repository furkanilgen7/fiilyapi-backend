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
from app.modules.sites import repository, service
from app.modules.sites.models import Section, Site
from app.modules.sites.schemas import (
    SectionCreate,
    SectionListResponse,
    SectionResponse,
    SectionUpdate,
    SiteCreate,
    SiteDetailResponse,
    SiteListResponse,
    SiteUpdate,
)
from app.modules.users.models import User

# Uclar uc ayri kok altina dagildigi icin (/projects/../sites, /sites, /sections)
# router prefix TASIMAZ; yollar tam yazilir. Bolum uclari da "sites" iznine
# baglidir — bolum santiyenin ic kirilimidir, ayri modul degildir (spec §4).
router = APIRouter(tags=["sites"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("sites", AccessLevel.view)
_FULL = require_permission("sites", AccessLevel.full)
# KULLANICI KARARI 2026-07-30 ("silme = sistem yoneticisi"): SILME uclari yazma
# uclarindan BIR SEVIYE YUKARIDADIR. Neden `_FULL` DEGIL: `app/core/access.py`
# "full yazmayi kapsar, SILMEYI KAPSAMAZ" der; `units`/`blocks`/`boq` DELETE
# uclariyla birebir ayni desen (`units/router.py:181,206`).
#
# BILINEN SONUC (kabul edildi): seed matrisinde `sites:admin` yalniz
# `system_admin`'dedir — proje muduru dahil kimse santiye/bolum silemez.
_ADMIN = require_permission("sites", AccessLevel.admin)


async def _detail_of(session: AsyncSession, site: Site) -> SiteDetailResponse:
    """Yazma uclarinin yaniti da okuma ucuyla ayni zarfi tasir."""
    await session.refresh(site, attribute_names=["sections", "project"])
    return service.to_detail(site, site.project)


@router.get("/projects/{project_id}/sites", response_model=SiteListResponse, dependencies=[_VIEW])
async def list_sites_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SiteListResponse:
    return await service.list_sites_overview(session, user, project_id)


@router.post(
    "/projects/{project_id}/sites",
    response_model=SiteDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_site_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: SiteCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailResponse:
    site = await service.create_site(session, current_user, project_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.site_created(site.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return await _detail_of(session, site)


@router.get("/sites/{site_id}", response_model=SiteDetailResponse, dependencies=[_VIEW])
async def get_site_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailResponse:
    return await service.get_site_detail(session, user, site_id)


@router.patch("/sites/{site_id}", response_model=SiteDetailResponse, dependencies=[_FULL])
async def update_site_endpoint(
    request: Request,
    site_id: uuid.UUID,
    data: SiteUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SiteDetailResponse:
    site = await service.update_site(session, current_user, site_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.site_updated(site.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return await _detail_of(session, site)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_ADMIN])
async def delete_site_endpoint(
    site_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.1. CASCADE KORKULUGU servistedir — bolum/poz/blok varsa 409.

    Yetki kapisi korkuluktan ONCE calisir: yetkisiz aktor 403 alir ve santiyenin
    bagli kayit tasiyip tasimadigini OGRENEMEZ. Gorunmeyen santiye 404 doner ve
    govdesi var olmayan UUID'ninkiyle BIREBIR AYNIDIR.

    Yanit `204 No Content`, GOVDESIZ. Denetim cagrisi T12'de eklenir; servis
    silinen kaydin ad anlik goruntusunu silmeden ONCE alir.
    """
    await service.delete_site(session, current_user, site_id)


@router.get("/sites/{site_id}/sections", response_model=SectionListResponse, dependencies=[_VIEW])
async def list_sections_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SectionListResponse:
    return await service.list_sections_for_site(session, user, site_id)


async def _owning_site_name(session: AsyncSession, section: Section) -> str:
    """Denetim metni icin santiye adi. Santiye yetki kontrolu sirasinda zaten
    yuklendigi icin bu cagri kimlik haritasindan doner, ek sorgu uretmez."""
    site = await repository.get_site(session, section.site_id)
    return site.name if site is not None else ""


@router.post(
    "/sites/{site_id}/sections",
    response_model=SectionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_section_endpoint(
    request: Request,
    site_id: uuid.UUID,
    data: SectionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SectionResponse:
    section = await service.create_section(session, current_user, site_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.section_created(await _owning_site_name(session, section), section.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return service.to_section(section)


@router.delete(
    "/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_ADMIN]
)
async def delete_section_endpoint(
    section_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7.1. Bolum silme KOSULSUZDUR: `sections.id`'yi hedefleyen FK yok.

    Kapi `_ADMIN`'dir — bolum santiyenin ic kirilimi oldugu icin `sites`
    modulunun seviyeleri kullanilir, AYRI izin modulu acilmaz.

    Yanit `204 No Content`, GOVDESIZ. Denetim cagrisi T12'de eklenir.
    """
    await service.delete_section(session, current_user, section_id)


@router.patch("/sections/{section_id}", response_model=SectionResponse, dependencies=[_FULL])
async def update_section_endpoint(
    request: Request,
    section_id: uuid.UUID,
    data: SectionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SectionResponse:
    section = await service.update_section(session, current_user, section_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.section_updated(await _owning_site_name(session, section), section.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return service.to_section(section)
