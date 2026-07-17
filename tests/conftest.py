from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import SessionTransaction

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
    dış transaction etkilenmez. `after_transaction_end` olay dinleyicisi, SAVEPOINT her
    kapandığında (commit sonrası dahil) yenisini hemen açar, böylece sonraki her `commit()`
    çağrısı da aynı korumadan yararlanır. Teardown'da dış transaction her zaman geri alınır,
    dolayısıyla hiçbir yazı `fiil_erp_test` veritabanına kalıcı olarak sızmaz.
    (SQLAlchemy'nin resmi "joining a session into an external transaction" tarifi.)
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        await connection.begin_nested()
        session = TestSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(
            sync_session: SyncSession, sync_transaction: SessionTransaction
        ) -> None:
            if connection.closed:
                return
            if not connection.sync_connection.in_nested_transaction():
                connection.sync_connection.begin_nested()

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
