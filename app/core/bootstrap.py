import logging

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Role
from app.modules.users.models import User, UserProjectAccess, UserStatus

logger = logging.getLogger(__name__)


async def ensure_first_admin() -> None:
    """DB'de hiç kullanıcı yoksa env'deki bilgilerle ilk sistem yöneticisini oluşturur.

    Kullanıcı oluşturma ucu `user_management` admin yetkisi ister; ilk kurulumda hiçbir
    yetkili kullanıcı olmadığından (tavuk-yumurta) tohumlama buradan yapılır.
    `ADMIN_EMAIL`/`ADMIN_PASSWORD` boşsa ya da DB'de zaten kullanıcı varsa hiçbir şey yapılmaz;
    böylece açılışta tekrar tekrar çalışsa da yalnızca bir kez etki eder.
    """
    if not settings.admin_email or not settings.admin_password:
        return

    async with SessionLocal() as session:
        existing = await session.scalar(select(func.count()).select_from(User))
        if existing:
            return

        role = await session.scalar(select(Role).where(Role.key == SYSTEM_ADMIN_KEY))
        if role is None:
            logger.warning(
                "İlk admin oluşturulamadı: '%s' rolü seed edilmemiş.", SYSTEM_ADMIN_KEY
            )
            return

        admin = User(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            full_name="Sistem Yöneticisi",
            title="Sistem Yöneticisi",
            role_id=role.id,
            status=UserStatus.active,
        )
        session.add(admin)
        await session.flush()
        session.add(UserProjectAccess(user_id=admin.id, all_projects=True))
        await session.commit()
        logger.info("İlk sistem yöneticisi oluşturuldu: %s", settings.admin_email)
