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
from app.modules.projects import service
from app.modules.projects.models import ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    EmployerCreate,
    EmployerListResponse,
    EmployerResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectUpdate,
)
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"], responses=COMMON_ERROR_RESPONSES)

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
) -> ProjectListResponse:
    return await service.list_projects_overview(session, user, type, status_filter)


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
    return service.to_detail(project)


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
    return service.to_detail(project)
