import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import DomainError, NotFoundError, PermissionLockedError
from app.modules.roles import repository, service
from app.modules.roles.models import Role, RolePermission
from app.modules.roles.schemas import RoleCreate


async def test_create_custom_role_seeds_full_matrix(seeded_db):
    role = await service.create_custom_role(
        seeded_db, RoleCreate(key="saha_amiri", name="Saha Amiri", emoji="🚧", description="")
    )
    assert role.is_system is False
    count = (
        await seeded_db.execute(
            select(func.count())
            .select_from(RolePermission)
            .where(RolePermission.role_id == role.id)
        )
    ).scalar_one()
    assert count == 20  # her modul icin bir hucre (none/all)


async def test_create_custom_role_duplicate_key_raises(seeded_db):
    with pytest.raises(DomainError):
        await service.create_custom_role(
            seeded_db, RoleCreate(key="patron", name="X", emoji="", description="")
        )


async def test_delete_system_role_locked(seeded_db):
    sysadmin = (
        await seeded_db.execute(select(Role).where(Role.key == "system_admin"))
    ).scalar_one()
    with pytest.raises(PermissionLockedError):
        await service.delete_role(seeded_db, sysadmin.id)


async def test_delete_unknown_role_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.delete_role(seeded_db, uuid.uuid4())


async def test_delete_role_in_use_rejected(seeded_db, user_factory):
    role = await service.create_custom_role(
        seeded_db, RoleCreate(key="gecici_rol", name="Geçici", emoji="", description="")
    )
    await user_factory(email="ru@t.co", password="parola1234", role_key="gecici_rol")
    with pytest.raises(DomainError):
        await service.delete_role(seeded_db, role.id)


async def test_get_role_matrix_returns_all_modules(seeded_db):
    patron = (await seeded_db.execute(select(Role).where(Role.key == "patron"))).scalar_one()
    matrix = await repository.get_role_matrix(seeded_db, patron.id)
    assert len(matrix) == 20
