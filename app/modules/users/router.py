import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.users import repository, service
from app.modules.users.schemas import PasswordReset, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=list[UserResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_users_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserResponse]:
    users = await repository.list_users(session)
    return [UserResponse.model_validate(u) for u in users]


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_user_endpoint(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    return UserResponse.model_validate(user)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def create_user_endpoint(
    data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await service.create_user(session, data)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def update_user_endpoint(
    user_id: uuid.UUID,
    data: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await service.update_user(session, user_id, data)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def reset_password_endpoint(
    user_id: uuid.UUID,
    data: PasswordReset,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.set_user_password(session, user_id, data.new_password)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def delete_user_endpoint(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.delete_user(session, user_id)
