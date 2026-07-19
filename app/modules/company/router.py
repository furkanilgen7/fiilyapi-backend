from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import NotFoundError
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


@router.post(
    "/logo",
    response_model=CompanyRead,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def upload_logo_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> CompanyRead:
    if file.content_type not in settings.allowed_logo_content_type_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Desteklenmeyen logo bicimi (izinli: PNG, JPEG, SVG, WEBP)",
        )
    if file.size is not None and file.size > settings.logo_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo boyutu cok buyuk (en fazla 1 MB)",
        )
    content = await file.read()
    if len(content) > settings.logo_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo boyutu cok buyuk (en fazla 1 MB)",
        )
    if not service.logo_signature_matches(file.content_type, content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Logo icerigi bildirilen bicimle uyusmuyor",
        )
    company = await service.set_logo(session, file.content_type, file.filename, content)
    return CompanyRead.from_model(company)


@router.get("/logo")
async def get_logo_endpoint(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    company = await service.get_company(session)
    if company.logo_data is None:
        raise NotFoundError("Logo yuklenmemis")
    return Response(
        content=company.logo_data,
        media_type=company.logo_content_type or "application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{company.logo_filename or "logo"}"',
        },
    )


@router.delete(
    "/logo",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def delete_logo_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.clear_logo(session)
