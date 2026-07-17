import uuid

import pytest
from sqlalchemy import select

from app.core.errors import DomainError, NotFoundError
from app.core.security import verify_password
from app.modules.roles.models import Role
from app.modules.users import service
from app.modules.users.models import User, UserStatus
from app.modules.users.schemas import UserCreate, UserUpdate


async def _role_id(session, key):
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one().id


async def test_create_user_hashes_password(seeded_db):
    data = UserCreate(
        email="a@t.co",
        password="parola1234",
        full_name="Ahmet",
        role_id=await _role_id(seeded_db, "patron"),
    )
    user = await service.create_user(seeded_db, data)
    assert user.password_hash != "parola1234"
    assert verify_password("parola1234", user.password_hash)


async def test_create_user_duplicate_email_raises(seeded_db):
    rid = await _role_id(seeded_db, "patron")
    await service.create_user(
        seeded_db, UserCreate(email="d@t.co", password="parola1234", full_name="A", role_id=rid)
    )
    with pytest.raises(DomainError):
        await service.create_user(
            seeded_db,
            UserCreate(email="d@t.co", password="parola1234", full_name="B", role_id=rid),
        )


async def test_create_user_unknown_role_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.create_user(
            seeded_db,
            UserCreate(email="x@t.co", password="parola1234", full_name="X", role_id=uuid.uuid4()),
        )


async def test_update_user_changes_status(seeded_db, user_factory):
    user = await user_factory(email="u@t.co", password="parola1234", role_key="site_chief")
    updated = await service.update_user(seeded_db, user.id, UserUpdate(status=UserStatus.passive))
    assert updated.status is UserStatus.passive


async def test_set_password(seeded_db, user_factory):
    user = await user_factory(email="p@t.co", password="parola1234", role_key="patron")
    await service.set_user_password(seeded_db, user.id, "yeniParola9")
    refreshed = (await seeded_db.execute(select(User).where(User.id == user.id))).scalar_one()
    assert verify_password("yeniParola9", refreshed.password_hash)


async def test_delete_user(seeded_db, user_factory):
    user = await user_factory(email="del@t.co", password="parola1234", role_key="accounting")
    await service.delete_user(seeded_db, user.id)
    result = await seeded_db.execute(select(User).where(User.id == user.id))
    assert result.scalar_one_or_none() is None


async def test_delete_unknown_user_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.delete_user(seeded_db, uuid.uuid4())
