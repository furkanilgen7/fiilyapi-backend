from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app

test_engine = create_async_engine(settings.test_database_url, pool_pre_ping=True)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Her test kendi transaction'ında koşar ve sonunda geri alınır — testler birbirini kirletmez.

    Session, dış transaction'ın üstünde bir SAVEPOINT (nested transaction) üzerinde çalışır.
    Test altındaki kod `await session.commit()` çağırsa bile bu yalnızca SAVEPOINT'i kapatır;
    dış transaction etkilenmez.

    `join_transaction_mode="create_savepoint"` tek başına yeterli: session'ın kendi "autobegin"
    davranışı, her yeni işlemden (execute/flush) önce bağlantının hâlâ açık bir dış transaction
    içinde olduğunu görüp otomatik olarak YENİ bir SAVEPOINT açar — commit sonrası da dahil.
    Bu ampirik olarak doğrulandı: `connection.begin_nested()` çağrısını session oluşturulmadan
    önce elle yapmak ve/veya bir `after_transaction_end` dinleyicisiyle SAVEPOINT'i elle yeniden
    başlatmak denendi; elle `begin_nested()` çağrısı SAVEPOINT'i session'dan bağımsız olarak
    kalıcı şekilde açık tuttuğu için dinleyicinin "yeniden başlat" dalı hiçbir zaman çalışmıyordu
    (her seferinde no-op). Elle `begin_nested()` çağrısı kaldırılınca dinleyici gerçekten
    tetiklenip SAVEPOINT'i yeniden açtı, fakat art arda üç `commit()` içeren bir stres testi
    dinleyici tamamen kaldırıldığında da (yalnızca `join_transaction_mode` ile) sızıntısız
    geçti. Yani koruma tamamen `join_transaction_mode`'dan geliyor; elle `begin_nested()` ve
    `after_transaction_end` dinleyicisi gereksizdi ve kaldırıldı.

    Teardown'da dış transaction her zaman geri alınır, dolayısıyla hiçbir yazı `fiil_erp_test`
    veritabanına kalıcı olarak sızmaz.
    (SQLAlchemy'nin resmi "joining a session into an external transaction" tarifi.)
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = TestSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()
