import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.models import Module, RolePermission


async def get_permission(
    session: AsyncSession, role_id: uuid.UUID, module_key: str
) -> RolePermission | None:
    stmt = (
        select(RolePermission)
        .join(Module, Module.id == RolePermission.module_id)
        .where(RolePermission.role_id == role_id, Module.key == module_key)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
