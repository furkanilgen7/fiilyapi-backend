import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.db as db_module
from app.core.config import settings
from tests.conftest import db_session, test_engine

LEAK_PROBE_TABLE = "test_isolation_leak_probe"
GET_DB_PROBE_TABLE = "test_get_db_commit_probe"


async def test_db_session_executes_query(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_db_session_runs_on_a_savepoint(db_session):
    """db_session, disaridaki transaction'in ustunde bir SAVEPOINT (nested transaction)
    uzerinde calismali. Bu olmadan, test altindaki kod `commit()` cagirdiginda disaridaki
    transaction'in gercekten sonlanip sonlanmadigi SQLAlchemy'nin ic implementasyonuna
    (join_transaction_mode fallback davranisina) kalir — acik/garantili degildir.
    """
    connection = await db_session.connection()
    await db_session.execute(text("SELECT 1"))
    assert connection.in_nested_transaction() is True, (
        "db_session bir SAVEPOINT uzerinde calismiyor: fixture, testi disaridaki "
        "transaction'a savunmasiz birakiyor olabilir."
    )


@pytest.fixture(autouse=True)
async def _cleanup_leak_probe_table():
    """Sizinti testi basarisiz olup tabloyu commit'lese bile, sonraki calismalari kirletmesin."""
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {LEAK_PROBE_TABLE}"))


async def test_commit_in_one_session_does_not_leak_into_a_later_session():
    """Bir db_session'da yapilan commit, AYNI TEST icinde alinan sonraki bir db_session'a
    sizmamali (SAVEPOINT korumasi).

    Onceki halde bu iki adim iki AYRI test fonksiyonuydu ve ikinci test yalnizca birincinin
    dosya icindeki sirada ONCE calismis olmasi sayesinde anlamliydi: testler `-k` ile
    filtrelenirse, rastgele siraya sokan bir plugin'le calisirsa ya da baska bir dosyadan
    calistirilirsa, ikinci test probe tablosunu hic gormez ve BOSUNA yesil gecerdi (hicbir
    sey kanitlamadan). Bu tek test, fixture'in generator'ini ELLE surerek iki ayri db_session
    ornegini AYNI test icinde art arda uretir; boylece bagimlilik olay sirasina degil, kod
    yapisina dayanir ve dosya/siralama degisikliklerinden etkilenmez.
    """
    first_session_gen = db_session.__wrapped__()
    first_db_session = await anext(first_session_gen)
    try:
        await first_db_session.execute(
            text(f"CREATE TABLE IF NOT EXISTS {LEAK_PROBE_TABLE} (id serial primary key)")
        )
        await first_db_session.execute(text(f"INSERT INTO {LEAK_PROBE_TABLE} DEFAULT VALUES"))
        await first_db_session.commit()
    finally:
        # fixture'in finally/teardown blogunu (session.close + outer rollback) calistirir.
        with pytest.raises(StopAsyncIteration):
            await anext(first_session_gen)

    second_session_gen = db_session.__wrapped__()
    second_db_session = await anext(second_session_gen)
    try:
        result = await second_db_session.execute(
            text(f"SELECT to_regclass('{LEAK_PROBE_TABLE}')")
        )
        assert result.scalar() is None, (
            "Onceki session'in commit'i sizdi: tablo hala mevcut. "
            "db_session fixture'i SAVEPOINT ile korunmuyor olabilir."
        )
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(second_session_gen)


@pytest.fixture
async def get_db_scratch_sessionmaker(monkeypatch):
    """`app.core.db.get_db`, modul seviyesindeki `SessionLocal`i kullanir; bu da normalde
    prod `DATABASE_URL`ine bagli engine'e isaret eder. Bu testte `client` fixture'inin
    `get_db` override'ini DEGIL, gercek `get_db` fonksiyonunu dogrudan calistirmak
    istiyoruz — ama prod veritabanina asla dokunmadan. Bu yuzden `SessionLocal`i, yalnizca
    bu test suresince, TEST_DATABASE_URL'e bagli ayri (izole) bir engine/sessionmaker ile
    degistiriyoruz. Kendi olusturup kendi drop ettigimiz bir scratch tablo disinda hicbir
    seye dokunulmuyor; seed edilmis semaya karisilmiyor.
    """
    scratch_engine = create_async_engine(settings.test_database_url, pool_pre_ping=True)
    scratch_session_local = async_sessionmaker(
        scratch_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(db_module, "SessionLocal", scratch_session_local)

    async with scratch_engine.begin() as conn:
        await conn.execute(
            text(f"CREATE TABLE IF NOT EXISTS {GET_DB_PROBE_TABLE} (id serial primary key)")
        )

    try:
        yield scratch_session_local
    finally:
        async with scratch_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {GET_DB_PROBE_TABLE}"))
        await scratch_engine.dispose()


async def _count_probe_rows(session_local: async_sessionmaker[AsyncSession]) -> int:
    async with session_local() as verify_session:
        result = await verify_session.execute(text(f"SELECT count(*) FROM {GET_DB_PROBE_TABLE}"))
        return result.scalar_one()


async def test_get_db_commits_on_clean_exit(get_db_scratch_sessionmaker):
    """get_db'nin GERCEK jeneratorunu (client fixture'inin override'ini degil) elle
    suruyoruz: normal (istisnasiz) bitiste yazi commit edilmis olmali. Duzeltmeden once bu
    test KIRMIZI: `async with SessionLocal() as session: yield session` commit etmedigi
    icin session kapanirken SQLAlchemy transaction'i sessizce geri aliyordu.
    """
    gen = db_module.get_db()
    session = await anext(gen)
    await session.execute(text(f"INSERT INTO {GET_DB_PROBE_TABLE} DEFAULT VALUES"))

    with pytest.raises(StopAsyncIteration):
        await anext(gen)  # generator'i normal sonlandirir -> get_db'nin commit yolu calisir

    assert await _count_probe_rows(get_db_scratch_sessionmaker) == 1, (
        "get_db temiz cikiste commit etmedi: yazi kayboldu."
    )


async def test_get_db_rolls_back_on_exception(get_db_scratch_sessionmaker):
    """Endpoint kodu `yield` noktasinda bir istisna firlatirsa get_db, yariya kalmis
    yaziyi commit etmemeli, geri almali."""
    gen = db_module.get_db()
    session = await anext(gen)
    await session.execute(text(f"INSERT INTO {GET_DB_PROBE_TABLE} DEFAULT VALUES"))

    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("simulated endpoint failure"))

    assert await _count_probe_rows(get_db_scratch_sessionmaker) == 0, (
        "get_db, istisna sonrasi yariya kalmis yaziyi geri almadi."
    )
