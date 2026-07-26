import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.projects import repository
from app.modules.projects.schemas import ProjectDetailResponse

# GECICI: Task 3-5 arasi app.main import zincirinin calisir kalmasi icin minimal
# yama. Bu router Task 6'da 4 uc + "projects" izniyle tamamen yeniden yazilacak.

router = APIRouter(prefix="/projects", tags=["projects"], responses=COMMON_ERROR_RESPONSES)


@router.get(
    "",
    response_model=list[ProjectDetailResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_projects_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectDetailResponse]:
    projects = await repository.list_projects(session)
    return [ProjectDetailResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    project = await repository.get_project(session, project_id)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return ProjectDetailResponse.model_validate(project)
