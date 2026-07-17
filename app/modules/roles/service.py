import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, Scope
from app.core.errors import PermissionLockedError
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Role, RolePermission
from app.modules.roles.repository import get_permission


async def update_role_permission(
    session: AsyncSession,
    role_id: uuid.UUID,
    module_key: str,
    level: AccessLevel,
    scope: Scope,
) -> RolePermission:
    """Matrisin bir hücresini günceller.

    system_admin rolünün hiçbir hücresi değiştirilemez — aktör kim olursa olsun.
    """
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one()

    if role.key == SYSTEM_ADMIN_KEY:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    permission = await get_permission(session, role_id, module_key)
    if permission is None:
        raise PermissionLockedError("İzin satırı bulunamadı")

    permission.access_level = level
    permission.scope = scope
    await session.flush()
    return permission


async def rename_role(
    session: AsyncSession,
    role_id: uuid.UUID,
    name: str,
    emoji: str,
    description: str,
) -> Role:
    """Rolün görünen bilgilerini günceller. key asla değişmez — kod ona dayanır."""
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one()
    role.name = name
    role.emoji = emoji
    role.description = description
    await session.flush()
    return role
