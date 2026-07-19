from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.company import service
from app.modules.company.schemas import CompanyRead, CompanyUpdate
from app.modules.users.models import User

router = APIRouter(prefix="/company", tags=["company"], responses=COMMON_ERROR_RESPONSES)


@router.get("", response_model=CompanyRead)
async def get_company_endpoint(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    company = await service.get_company(session)
    return CompanyRead.from_model(company)


@router.put(
    "",
    response_model=CompanyRead,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def update_company_endpoint(
    data: CompanyUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    company = await service.update_company(session, data)
    return CompanyRead.from_model(company)
