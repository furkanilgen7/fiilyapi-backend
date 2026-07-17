import pytest
from sqlalchemy.exc import IntegrityError

from app.core.permissions import AccessLevel, Scope
from app.modules.roles.models import Module, ModuleGroup, Role, RolePermission


async def test_one_permission_row_per_role_and_module(db_session):
    role = Role(key="test_rol", name="Test Rol")
    module = Module(key="test_modul", name="Test Modül", group=ModuleGroup.GENEL, sort_order=1)
    db_session.add_all([role, module])
    await db_session.flush()

    db_session.add(
        RolePermission(
            role_id=role.id, module_id=module.id, access_level=AccessLevel.view, scope=Scope.all
        )
    )
    await db_session.flush()

    db_session.add(
        RolePermission(
            role_id=role.id, module_id=module.id, access_level=AccessLevel.full, scope=Scope.all
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_module_key_is_unique(db_session):
    db_session.add(Module(key="ayni", name="Bir", group=ModuleGroup.GENEL, sort_order=1))
    await db_session.flush()

    db_session.add(Module(key="ayni", name="Iki", group=ModuleGroup.MALI, sort_order=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
