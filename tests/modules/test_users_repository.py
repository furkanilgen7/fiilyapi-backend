from sqlalchemy import select

from app.core.security import hash_password
from app.modules.roles.models import Role
from app.modules.users import repository
from app.modules.users.models import User


async def _role_id(session, key: str):
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one().id


async def test_add_and_get_user_loads_role(seeded_db):
    user = User(
        email="a@t.co",
        password_hash=hash_password("parola1234"),
        full_name="Ahmet Yılmaz",
        role_id=await _role_id(seeded_db, "patron"),
    )
    await repository.add_user(seeded_db, user)

    loaded = await repository.get_user(seeded_db, user.id)
    assert loaded is not None
    assert loaded.role.key == "patron"  # joinedload — lazy="raise" patlamaz


async def test_get_user_by_email(seeded_db):
    user = User(
        email="b@t.co",
        password_hash=hash_password("parola1234"),
        full_name="B",
        role_id=await _role_id(seeded_db, "accounting"),
    )
    await repository.add_user(seeded_db, user)
    found = await repository.get_user_by_email(seeded_db, "b@t.co")
    assert found is not None and found.email == "b@t.co"
    assert await repository.get_user_by_email(seeded_db, "yok@t.co") is None
