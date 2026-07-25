from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.dashboard.schemas import DashboardSummaryResponse
from app.modules.dashboard.service import build_summary
from app.modules.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=COMMON_ERROR_RESPONSES)


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    dependencies=[require_permission("dashboard", AccessLevel.view)],
)
async def get_dashboard_summary_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardSummaryResponse:
    return await build_summary(session, user)
