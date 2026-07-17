import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.core.security import hash_password
from app.modules.roles.models import Role
from app.modules.users import repository
from app.modules.users.models import User, UserProjectAccess
from app.modules.users.schemas import ProjectAccessInput, UserCreate, UserUpdate


async def _require_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    return role


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    if await repository.get_user_by_email(session, data.email) is not None:
        raise DomainError("Bu e-posta zaten kayıtlı")
    await _require_role(session, data.role_id)

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        title=data.title,
        role_id=data.role_id,
        status=data.status,
    )
    return await repository.add_user(session, user)


async def update_user(session: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    if data.role_id is not None:
        await _require_role(session, data.role_id)
        user.role_id = data.role_id
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.title is not None:
        user.title = data.title
    if data.status is not None:
        user.status = data.status
    await session.flush()
    return user


async def set_user_password(
    session: AsyncSession, user_id: uuid.UUID, new_password: str
) -> None:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    user.password_hash = hash_password(new_password)
    await session.flush()


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    await session.delete(user)
    await session.flush()


async def set_project_access(
    session: AsyncSession, user_id: uuid.UUID, data: ProjectAccessInput
) -> list[UserProjectAccess]:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    return await repository.replace_project_access(
        session, user_id, data.all_projects, data.project_ids
    )
