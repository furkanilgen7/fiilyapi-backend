import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, Scope
from app.core.errors import DomainError, NotFoundError, PermissionLockedError
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Module, Role, RolePermission
from app.modules.roles.repository import get_permission
from app.modules.roles.schemas import RoleCreate


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
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")

    if role.key == SYSTEM_ADMIN_KEY:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    permission = await get_permission(session, role_id, module_key)
    if permission is None:
        raise NotFoundError("İzin satırı bulunamadı")

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
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    role.name = name
    role.emoji = emoji
    role.description = description
    await session.flush()
    return role


async def create_custom_role(session: AsyncSession, data: RoleCreate) -> Role:
    """Yeni özel rol oluşturur; tüm modüller için none/all izin satırı seedler."""
    existing = (
        await session.execute(select(Role).where(Role.key == data.key))
    ).scalar_one_or_none()
    if existing is not None:
        raise DomainError("Bu rol anahtarı zaten kullanılıyor")

    role = Role(
        key=data.key,
        name=data.name,
        emoji=data.emoji,
        description=data.description,
        is_system=False,
    )
    session.add(role)
    await session.flush()

    modules = (await session.execute(select(Module))).scalars().all()
    for module in modules:
        session.add(
            RolePermission(
                role_id=role.id,
                module_id=module.id,
                access_level=AccessLevel.none,
                scope=Scope.all,
            )
        )
    await session.flush()
    return role


async def delete_role(session: AsyncSession, role_id: uuid.UUID) -> None:
    """Özel rolü siler. Sistem rolleri kilitlidir."""
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    if role.is_system:
        raise PermissionLockedError("Sistem rolleri silinemez")

    from app.modules.users.models import User  # fonksiyon ici import (dongu riskini onler)

    in_use = (
        await session.execute(select(func.count()).select_from(User).where(User.role_id == role_id))
    ).scalar_one()
    if in_use > 0:
        raise DomainError("Bu role atanmış kullanıcılar var; önce onları başka role taşıyın")

    await session.delete(role)  # role_permissions CASCADE ile silinir
    await session.flush()
