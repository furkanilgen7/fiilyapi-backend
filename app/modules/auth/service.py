from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.modules.users.models import User, UserStatus


class AuthError(Exception):
    """Kimlik doğrulama başarısız."""


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """E-posta ve parolayı doğrular, aktif kullanıcıyı döner.

    Başarısızlığın nedeni (kullanıcı yok / parola yanlış / pasif) çağırana
    ayrıştırılmadan bildirilir — kullanıcı sayımını (user enumeration) engellemek için.
    """
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Kimlik bilgileri hatalı")

    if user.status is not UserStatus.active:
        raise AuthError("Kimlik bilgileri hatalı")

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user
