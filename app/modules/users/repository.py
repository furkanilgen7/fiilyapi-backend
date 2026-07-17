import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.users.models import User, UserProjectAccess


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


async def get_project_access(session: AsyncSession, user_id: uuid.UUID) -> list[UserProjectAccess]:
    result = await session.execute(
        select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
    )
    return list(result.scalars().all())


async def replace_project_access(
    session: AsyncSession,
    user_id: uuid.UUID,
    all_projects: bool,
    project_ids: list[uuid.UUID],
) -> list[UserProjectAccess]:
    await session.execute(delete(UserProjectAccess).where(UserProjectAccess.user_id == user_id))
    rows: list[UserProjectAccess] = []
    if all_projects:
        rows.append(UserProjectAccess(user_id=user_id, project_id=None, all_projects=True))
    else:
        rows = [
            UserProjectAccess(user_id=user_id, project_id=pid, all_projects=False)
            for pid in project_ids
        ]
    for row in rows:
        session.add(row)
    await session.flush()
    return rows
