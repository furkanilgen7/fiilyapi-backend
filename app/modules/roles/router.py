import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.roles import repository, service
from app.modules.roles.schemas import (
    ModuleResponse,
    PermissionCell,
    PermissionUpdate,
    RoleCreate,
    RoleRename,
    RoleResponse,
)
from app.modules.roles.service import update_role_permission

router = APIRouter(tags=["roles"])


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_roles_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoleResponse]:
    return [RoleResponse.model_validate(r) for r in await repository.list_roles(session)]


@router.get(
    "/modules",
    response_model=list[ModuleResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_modules_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ModuleResponse]:
    return [ModuleResponse.model_validate(m) for m in await repository.list_modules(session)]


@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[PermissionCell],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_role_permissions_endpoint(
    role_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PermissionCell]:
    if await repository.get_role(session, role_id) is None:
        raise NotFoundError("Rol bulunamadı")
    matrix = await repository.get_role_matrix(session, role_id)
    return [
        PermissionCell(module_key=module.key, access_level=perm.access_level, scope=perm.scope)
        for module, perm in matrix
    ]


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def create_role_endpoint(
    data: RoleCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    return RoleResponse.model_validate(await service.create_custom_role(session, data))


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def rename_role_endpoint(
    role_id: uuid.UUID,
    data: RoleRename,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    role = await service.rename_role(session, role_id, data.name, data.emoji, data.description)
    return RoleResponse.model_validate(role)


@router.put(
    "/roles/{role_id}/permissions/{module_key}",
    response_model=PermissionCell,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def update_permission_endpoint(
    role_id: uuid.UUID,
    module_key: str,
    data: PermissionUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionCell:
    # system_admin -> PermissionLockedError(403); satir/rol yok -> NotFoundError(404)
    perm = await update_role_permission(session, role_id, module_key, data.access_level, data.scope)
    return PermissionCell(module_key=module_key, access_level=perm.access_level, scope=perm.scope)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def delete_role_endpoint(
    role_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.delete_role(session, role_id)
