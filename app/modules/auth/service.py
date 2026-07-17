from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.modules.users.models import User, UserStatus


class AuthError(Exception):
    """Kimlik doğrulama başarısız."""


# Bilinmeyen e-postalarda argon2 doğrulaması hiç çalışmadığı için (kısa devre),
# bilinen-e-posta/yanlış-parola durumuna göre çok daha hızlı yanıt dönerdi — bu da
# zamanlama farkından kullanıcı sayımına (user enumeration, CWE-208) yol açardı.
# Bu sahte hash'e karşı da bir doğrulama çalıştırarak iki yolun süresini eşitliyoruz.
# Modül yüklenirken BİR KEZ hesaplanır; istek başına tekrar hesaplamak amacı bozar.
# UYARI: Bu "ölü kod" değildir, silmeyin.
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalisation")


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """E-posta ve parolayı doğrular, aktif kullanıcıyı döner.

    Başarısızlığın nedeni (kullanıcı yok / parola yanlış / pasif) çağırana
    ayrıştırılmadan bildirilir — kullanıcı sayımını (user enumeration) engellemek için.
    """
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None:
        # Kullanıcı bulunamasa bile argon2 doğrulamasını çalıştır — aksi halde bu yol
        # gerçek parola doğrulamasından çok daha hızlı döner ve zamanlama farkı
        # saldırganın e-postanın var olup olmadığını anlamasına izin verir.
        verify_password(password, _DUMMY_HASH)
        raise AuthError("Kimlik bilgileri hatalı")

    if not verify_password(password, user.password_hash):
        raise AuthError("Kimlik bilgileri hatalı")

    if user.status is not UserStatus.active:
        raise AuthError("Kimlik bilgileri hatalı")

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user
