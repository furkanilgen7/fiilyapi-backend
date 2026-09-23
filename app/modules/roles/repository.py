import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, Scope
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


async def get_module(session: AsyncSession, module_key: str) -> Module | None:
    stmt = select(Module).where(Module.key == module_key)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_modules(session: AsyncSession) -> list[Module]:
    result = await session.execute(select(Module).order_by(Module.sort_order))
    return list(result.scalars().all())


async def get_role_matrix(
    session: AsyncSession, role_id: uuid.UUID
) -> list[tuple[Module, RolePermission]]:
    """Rolün matrisi — HER modül için bir hücre, izin satırı olmasa bile.

    🔴 Bu fonksiyon eskiden INNER JOIN'di ve `modules`ı değil `role_permissions`ı
    sürüyordu. Satırı olmayan modül matristen TAMAMEN DÜŞÜYORDU; belirti Ayarlar
    ekranı değil `/auth/me` idi — `permissions` haritasında anahtar HİÇ bulunmuyordu.

    Delik yapısaldır: `create_custom_role` yalnız o anda var olan modüller için
    hücre açar, uzantı migration'ları ise izin satırlarını `WHERE r.key = :role_key`
    süzgeciyle ve sabit `ROLE_ORDER` üzerinde yazar (tek istisna `ai`). Yani
    migration'dan ÖNCE açılmış her özel rol, sonradan inen her modülün dışında kalır.

    Artık sürücü `modules`tır (LEFT OUTER JOIN) ve eksik hücre yerine VARSAYILAN
    KAPALI bir hücre üretilir. Üretilen nesne `session.add` EDİLMEZ: okuma yolu
    yazmaz, yoksa `uq_role_module` yarışında çift satır doğardı. Kalıcı hücreyi
    yalnız `service.update_role_permission` açar.
    """
    stmt = (
        select(Module, RolePermission)
        .outerjoin(
            RolePermission,
            (RolePermission.module_id == Module.id) & (RolePermission.role_id == role_id),
        )
        .order_by(Module.sort_order)
    )
    result = await session.execute(stmt)
    return [
        (module, permission or varsayilan_hucre(role_id, module))
        for module, permission in result.all()
    ]


def varsayilan_hucre(role_id: uuid.UUID, module: Module) -> RolePermission:
    """İzin satırı olmayan (rol, modül) çifti için GEÇİCİ, kalıcılaşmayan hücre.

    Varsayılan `none`dur — `core/permissions.py` zaten satır yokken reddediyordu,
    bu hücre o davranışı AYNEN temsil eder; matrise görünürlük ekler, yetki eklemez.
    """
    return RolePermission(
        role_id=role_id,
        module_id=module.id,
        access_level=AccessLevel.none,
        scope=Scope.all,
    )
