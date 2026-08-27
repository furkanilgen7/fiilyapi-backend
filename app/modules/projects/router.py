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
from app.modules.projects import cost_summary, land_share, service, timeline
from app.modules.projects.land_share_schemas import (
    LandShareSummaryResponse,
    LandShareUnitListResponse,
)
from app.modules.projects.models import ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    EmployerCreate,
    EmployerListResponse,
    EmployerResponse,
    ProjectCostsResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectTimelineResponse,
    ProjectUpdate,
)
from app.modules.units.schemas import UnitOwnerSideFilter
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"], responses=COMMON_ERROR_RESPONSES)

# K7 sayfalama standardi (`accounting`/`invoicing`/duz `GET /sites` ile birebir):
# varsayilan 50, tavan 200; tavan asimi SESSIZCE KIRPILMAZ → 422.
_LIMIT = Annotated[int, Query(ge=1, le=200)]
_OFFSET = Annotated[int, Query(ge=0)]

# İşveren kartoteksi YENİ İZİN MODÜLÜ AÇMAZ (spec §2.5/§7.6): `projects`
# view/admin ile korunur. Ayrı bir router yalnız yol farkı içindir (/employers).
employers_router = APIRouter(
    prefix="/employers", tags=["employers"], responses=COMMON_ERROR_RESPONSES
)


@employers_router.get(
    "",
    response_model=EmployerListResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def list_employers_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    active_only: bool = True,
) -> EmployerListResponse:
    employers = await service.list_employers(session, q, active_only)
    return EmployerListResponse(items=[EmployerResponse.model_validate(e) for e in employers])


@employers_router.post(
    "",
    response_model=EmployerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("projects", AccessLevel.admin)],
)
async def create_employer_endpoint(
    request: Request,
    data: EmployerCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerResponse:
    employer = await service.create_employer(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.employer_created(employer.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return EmployerResponse.model_validate(employer)


@router.get(
    "",
    response_model=ProjectListResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def list_projects_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    type: ProjectType | None = None,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> ProjectListResponse:
    """Proje listesi (SITE-1b sonrası sayfalı).

    `counts` süzgeçten de sayfadan da ETKİLENMEZ (sekme rakamları);
    `total` SÜZGEÇLENMİŞ kümenin boyutudur (sayfa çubuğu). Ayrıntı:
    `ProjectListResponse` docstring'i.
    """
    return await service.list_projects_overview(session, user, type, status_filter, limit, offset)


# DIKKAT — ROTA SIRASI: bu STATIK yol, `/{project_id}` parametreli yolundan
# ONCE tanimlanmak ZORUNDA. Sonra tanimlanirsa FastAPI "timeline"i bir proje
# kimligi sanar ve uc hic calismadan 422 (uuid_parsing) doner.
@router.get(
    "/timeline",
    response_model=ProjectTimelineResponse,
    # OKUMA ucu: `view` yeter (spec §3). Yeni izin modulu ACILMAZ. Audit
    # YAZILMAZ — turev okuma hicbir sey degistirmez (costs ucuyla ayni karar).
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def get_projects_timeline_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectTimelineResponse:
    """Portfoy Gantt'i (P11). HAM veri — ay/zoom parametresi YOKTUR (spec §6 S4)."""
    return await timeline.get_timeline(session, user)


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    return await service.get_project_detail(session, user, project_id)


@router.get(
    "/{project_id}/costs",
    response_model=ProjectCostsResponse,
    # OKUMA ucu: `view` yeter (P10 spec §3). Audit YAZILMAZ — türev okuma hiçbir
    # şey değiştirmez, denetim günlüğünü kart açılışlarıyla şişirmek anlamsızdır.
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def get_project_costs_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCostsResponse:
    return await cost_summary.get_project_costs(session, user, project_id)


# --- P-KK: kat karşılığı paylaşım (OKUMA) ---
#
# Yol `/{project_id}/land-share/...`tır ve ayrı bir router AÇILMAZ: iki uç da
# proje bağlamındadır ve `projects` izinleriyle korunur — yeni izin modülü
# açmak (`roles/seed_data.py`) migration doğururdu (K9).


@router.get(
    "/{project_id}/land-share/summary",
    response_model=LandShareSummaryResponse,
    # OKUMA ucu: `view` yeter; audit YAZILMAZ (`/costs` ucuyla aynı karar —
    # türev okuma hiçbir şey değiştirmez).
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def get_land_share_summary_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> LandShareSummaryResponse:
    return await land_share.get_summary(session, user, project_id)


@router.get(
    "/{project_id}/land-share/units",
    response_model=LandShareUnitListResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def list_land_share_units_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    owner_side: UnitOwnerSideFilter | None = None,
    block_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> LandShareUnitListResponse:
    return await land_share.list_units(
        session,
        user,
        project_id,
        owner_side=owner_side,
        block_id=block_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    # Proje olusturma ADMIN isidir (kullanici karari 2026-07-28). `full` kasitli
    # olarak YETMEZ: olusturana otomatik UserProjectAccess yazilmadigi icin,
    # kapsamli bir `full` kullanicisi goremedigi bir proje yaratirdi. Admin
    # gorunurluk suzgecini zaten atlar (spec §5.2), boylece bu bosluk kapanir.
    dependencies=[require_permission("projects", AccessLevel.admin)],
)
async def create_project_endpoint(
    request: Request,
    data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    project = await service.create_project(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.project_created(project.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return await service.build_project_detail(session, project, current_user)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    dependencies=[require_permission("projects", AccessLevel.full)],
)
async def update_project_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    project = await service.update_project(session, current_user, project_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.project_updated(project.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return await service.build_project_detail(session, project, current_user)
