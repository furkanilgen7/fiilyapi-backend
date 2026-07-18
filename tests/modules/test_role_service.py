import uuid

import pytest
from sqlalchemy import select

from app.core.access import AccessLevel, Scope
from app.core.errors import NotFoundError, PermissionLockedError
from app.modules.roles.models import Role
from app.modules.roles.service import rename_role, update_role_permission


async def _role(session, key: str) -> Role:
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one()


async def test_permission_can_be_raised_for_normal_role(seeded_db):
    role = await _role(seeded_db, "site_chief")
    updated = await update_role_permission(
        seeded_db, role.id, "progress_payments", AccessLevel.approve, Scope.all
    )
    assert updated.access_level is AccessLevel.approve


async def test_permission_can_be_lowered_for_normal_role(seeded_db):
    role = await _role(seeded_db, "patron")
    updated = await update_role_permission(
        seeded_db, role.id, "payroll", AccessLevel.view, Scope.all
    )
    assert updated.access_level is AccessLevel.view


async def test_system_admin_permissions_are_locked(seeded_db):
    """Kilitlenme koruması: system_admin izin satırları hiç kimse tarafından değiştirilemez."""
    role = await _role(seeded_db, "system_admin")
    with pytest.raises(PermissionLockedError):
        await update_role_permission(seeded_db, role.id, "settings", AccessLevel.none, Scope.all)


async def test_system_admin_can_still_be_renamed(seeded_db):
    """Ad/emoji/açıklama düzenlenebilir; kilitli olan yalnızca izinlerdir."""
    role = await _role(seeded_db, "system_admin")
    renamed = await rename_role(
        seeded_db, role.id, name="Süper Yönetici", emoji="⚡", description=""
    )
    assert renamed.name == "Süper Yönetici"
    assert renamed.key == "system_admin"


async def test_renaming_never_changes_key(seeded_db):
    """Yetki kontrolü key'e dayanır; ad değişince yetkiler kaymamalı."""
    role = await _role(seeded_db, "field_engineer")
    renamed = await rename_role(seeded_db, role.id, name="Teknik Ofis", emoji="📐", description="")
    assert renamed.key == "field_engineer"


async def test_rename_unknown_role_raises_not_found(seeded_db):
    with pytest.raises(NotFoundError):
        await rename_role(seeded_db, uuid.uuid4(), "X", "", "")


async def test_update_permission_missing_row_raises_not_found(seeded_db):
    patron = await _role(seeded_db, "patron")
    with pytest.raises(NotFoundError):
        await update_role_permission(
            seeded_db, patron.id, "olmayan_modul", AccessLevel.view, Scope.all
        )


async def test_update_permission_unknown_role_raises_not_found(seeded_db):
    with pytest.raises(NotFoundError):
        await update_role_permission(
            seeded_db, uuid.uuid4(), "dashboard", AccessLevel.view, Scope.all
        )


async def test_update_permission_system_admin_still_locked(seeded_db):
    sysadmin = await _role(seeded_db, "system_admin")
    with pytest.raises(PermissionLockedError):
        await update_role_permission(
            seeded_db, sysadmin.id, "dashboard", AccessLevel.view, Scope.all
        )
