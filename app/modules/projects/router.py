import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.projects import repository
from app.modules.projects.schemas import ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_projects_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectResponse]:
    projects = await repository.list_projects(session)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await repository.get_project(session, project_id)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return ProjectResponse.model_validate(project)
