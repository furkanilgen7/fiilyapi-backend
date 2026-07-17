import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.roles.models import Role


async def test_role_key_is_unique(db_session):
    db_session.add(Role(key="patron", name="Patron"))
    await db_session.flush()

    db_session.add(Role(key="patron", name="Baska Ad"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_defaults_to_non_system(db_session):
    role = Role(key="ozel_rol", name="Özel Rol")
    db_session.add(role)
    await db_session.flush()
    assert role.is_system is False
