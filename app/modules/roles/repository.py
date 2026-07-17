import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.models import Module, Role, RolePermission


async def get_permission(
    session: AsyncSession, role_id: uuid.UUID, module_key: str
) -> RolePermission | None:
    stmt = (
        select(RolePermission)
        .join(Module, Module.id == RolePermission.module_id)
        .where(RolePermission.role_id == role_id, Module.key == module_key)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    return list(result.scalars().all())


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    return await session.get(Role, role_id)


async def list_modules(session: AsyncSession) -> list[Module]:
    result = await session.execute(select(Module).order_by(Module.sort_order))
    return list(result.scalars().all())


async def get_role_matrix(
    session: AsyncSession, role_id: uuid.UUID
) -> list[tuple[Module, RolePermission]]:
    stmt = (
        select(Module, RolePermission)
        .join(RolePermission, RolePermission.module_id == Module.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Module.sort_order)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]
