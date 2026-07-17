import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.users.models import User


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(joinedload(User.role)).order_by(User.full_name)
    )
    return list(result.scalars().all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(
        select(User).options(joinedload(User.role)).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def add_user(session: AsyncSession, user: User) -> User:
    session.add(user)
    await session.flush()
    return user
