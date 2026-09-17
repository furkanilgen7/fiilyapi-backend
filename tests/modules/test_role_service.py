import uuid

import pytest
from sqlalchemy import select

from app.core.access import AccessLevel, Scope
from app.core.errors import NotFoundError, PermissionLockedError
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Module, Role, RolePermission
from app.modules.roles.repository import get_permission
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


async def _non_all_scope_cell(session) -> tuple[Role, str, Scope]:
    """Seed'de `all` DIŞI kapsam taşıyan ilk hücreyi (rol, modül, kapsam) döner."""
    row = (
        await session.execute(
            select(Role, Module.key, RolePermission.scope)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Module, Module.id == RolePermission.module_id)
            .where(RolePermission.scope != Scope.all, Role.key != SYSTEM_ADMIN_KEY)
            .order_by(Role.key, Module.key)
            .limit(1)
        )
    ).first()
    assert row is not None, "Seed'de all dışı kapsam kalmamış — bu testin dayanağı yok"
    return row[0], row[1], row[2]


async def test_uygulanmayan_kapsam_YAZILAMAZ(seeded_db):
    """🔴 `Scope` karar mekanizmasına HİÇ bağlı değil: `app/core/permissions.py`de

    `scope` kelimesi GEÇMEZ ve `projects.service.visible_projects` yalnız
    `AccessLevel.admin` + `user_project_access` satırlarına bakar. Buna rağmen
    İzin Matrisi ekranı "Kendi / Sınırlı / Mali" etiketlerini yazıyla vaat eder.
    Yeni bir yalan KALICI olarak yazılamamalı: `all` dışı bir kapsam yazma
    denemesi reddedilir ve satır DEĞİŞMEDEN kalır.
    """
    role = await _role(seeded_db, "site_chief")
    before = await get_permission(seeded_db, role.id, "personnel")
    eski_seviye, eski_kapsam = before.access_level, before.scope

    with pytest.raises(PermissionLockedError):
        await update_role_permission(seeded_db, role.id, "personnel", AccessLevel.view, Scope.own)

    after = await get_permission(seeded_db, role.id, "personnel")
    assert (after.access_level, after.scope) == (eski_seviye, eski_kapsam)


async def test_seed_kapsami_korunurken_seviye_degistirilebilir(seeded_db):
    """Seed satırları AYNEN kalır (veri göçü yok): mevcut kapsam geri gönderilirse

    seviye değişimi geçer. Aksi hâlde `all` dışı kapsam taşıyan hücrelerin
    seviyesi hiçbir yerden düzenlenemez hâle gelirdi.
    """
    role, module_key, mevcut_kapsam = await _non_all_scope_cell(seeded_db)

    updated = await update_role_permission(
        seeded_db, role.id, module_key, AccessLevel.none, mevcut_kapsam
    )

    assert (updated.access_level, updated.scope) == (AccessLevel.none, mevcut_kapsam)


async def test_kapsam_all_a_cekilebilir(seeded_db):
    """Yalanı GERİ ALMAK her zaman serbesttir: `all` yazmak reddedilmez."""
    role, module_key, _ = await _non_all_scope_cell(seeded_db)

    updated = await update_role_permission(
        seeded_db, role.id, module_key, AccessLevel.view, Scope.all
    )

    assert updated.scope is Scope.all
