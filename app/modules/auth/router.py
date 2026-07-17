from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import TokenError, create_access_token, create_refresh_token, decode_token
from app.modules.auth.schemas import LoginRequest, MeResponse, RefreshRequest, TokenPair
from app.modules.auth.service import AuthError, authenticate
from app.modules.users.models import User, UserStatus

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    try:
        user = await authenticate(session, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Kimlik bilgileri hatalı"
        ) from exc

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: RefreshRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum süresi dolmuş"
        ) from exc

    # Kullanıcıyı yeniden yükleyip durumunu kontrol etmeden yeni token basmak,
    # pasife alınmış bir kullanıcının eski refresh token'ıyla 30 gün boyunca
    # yeni access token üretmeye devam etmesine izin verir. get_current_user ile
    # aynı kuralı burada da uyguluyoruz. Kullanıcı yok ile pasif arasında fark
    # göstermemek için ikisinde de aynı yanıtı dönüyoruz.
    user = await session.get(User, user_id)
    if user is None or user.status is not UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum süresi dolmuş"
        )

    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    """Token'lar durumsuzdur; oturumu sonlandırmak cookie'yi silen BFF katmanının işidir."""
    return None


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        title=user.title,
        role_key=user.role.key,
        status=user.status.value,
    )
