from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.modules.settings import service
from app.modules.settings.schemas import PreferencesRead, PreferencesUpdate
from app.modules.users.models import User

router = APIRouter(prefix="/settings", tags=["settings"], responses=COMMON_ERROR_RESPONSES)


@router.get("/preferences", response_model=PreferencesRead)
async def get_preferences_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesRead:
    return await service.get_preferences(session, user)


@router.put("/preferences", response_model=PreferencesRead)
async def update_preferences_endpoint(
    data: PreferencesUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesRead:
    return await service.update_preferences(session, user, data)
