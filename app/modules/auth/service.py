import logging
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, needs_rehash, verify_password
from app.modules.users.models import User, UserStatus

logger = logging.getLogger(__name__)


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
        await run_in_threadpool(verify_password, password, _DUMMY_HASH)
        raise AuthError("Kimlik bilgileri hatalı")

    if not await run_in_threadpool(verify_password, password, user.password_hash):
        raise AuthError("Kimlik bilgileri hatalı")

    if user.status is not UserStatus.active:
        raise AuthError("Kimlik bilgileri hatalı")

    await _yeniden_hashle_gerekiyorsa(user, password)

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user


async def _yeniden_hashle_gerekiyorsa(user: User, password: str) -> None:
    """Özet eski maliyet parametreleriyle üretilmişse güncel parametrelerle yeniden yazar.

    🔴 Bu, düz parolanın elde olduğu TEK andır. Parametreler yükseltildiğinde eski
    özetler doğrulanmaya devam ettiği için hiçbir şey kırılmaz — toplu dönüştürme de
    imkânsızdır (düz parolalar yok). Yani giriş anında yapılmazsa HİÇ yapılmaz.

    🔴 Üç sınır: (a) yalnız doğrulama başarılıysa çağrılır — çağıranın sözleşmesi;
    (b) burada oluşan HİÇBİR hata girişi düşürmez, yoksa bir kütüphane/bellek arızası
    kullanıcıyı kendi hesabından kilitler — rehash bir kolaylıktır, giriş yolunun bekası
    değil; (c) düz parola loglanmaz.
    """
    try:
        if not await run_in_threadpool(needs_rehash, user.password_hash):
            return
        user.password_hash = await run_in_threadpool(hash_password, password)
    except Exception:  # noqa: BLE001 — giriş yolu bu yüzden ASLA düşmemeli (bkz. sınır b)
        # Parola ve özet KASITLI olarak loglanmaz; yalnız kullanıcı kimliği yazılır.
        logger.exception("Parola özeti yeniden yazılamadı (user_id=%s)", user.id)
