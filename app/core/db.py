from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, settings


class Base(DeclarativeBase):
    pass


def build_engine(cfg: Settings):
    """Yapılandırılmış zaman aşımlarıyla async engine kurar.

    connect_args asyncpg'ye iletilir: `timeout` bağlantı açma, `command_timeout` ise tek
    bir sorgunun üst sınırıdır. Böylece asılı bir sorgu instance'ı süresiz kilitleyemez.
    """
    return create_async_engine(
        cfg.database_url,
        pool_pre_ping=True,
        connect_args={
            "timeout": cfg.db_connect_timeout,
            "command_timeout": cfg.db_command_timeout,
        },
    )


engine = build_engine(settings)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """İstek başına bir session açar; hattın ucundaki yazıları garanti eder.

    `async with SessionLocal()` yalnızca session'ı kapatır, commit ETMEZ — hâlâ açık bir
    transaction varsa SQLAlchemy bunu session kapanırken sessizce geri alır (rollback).
    Bu yüzden burada temiz çıkışta açıkça commit ediyoruz; bir istisna oluşursa rollback
    yapıp yeniden fırlatıyoruz. Aksi halde örn. `last_login_at` gibi flush edilmiş ama
    commit edilmemiş yazılar prod'da sessizce kaybolur.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
