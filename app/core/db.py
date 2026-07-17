from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
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
