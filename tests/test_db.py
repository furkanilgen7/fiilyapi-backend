import pytest
from sqlalchemy import text

from tests.conftest import test_engine

LEAK_PROBE_TABLE = "test_isolation_leak_probe"


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


async def test_commit_inside_db_session_then_leak_is_checked_by_next_test(db_session):
    """db_session icinde commit cagrilsa bile, degisiklikler test sonunda geri alinmali
    (SAVEPOINT korumasi). Bu test sadece degisikligi yapar; sizinti kontrolu bir
    SONRAKI testte yapilir, cunku sizinti tanimi geregi baska bir testin gorebilmesidir.
    """
    await db_session.execute(
        text(f"CREATE TABLE IF NOT EXISTS {LEAK_PROBE_TABLE} (id serial primary key)")
    )
    await db_session.execute(text(f"INSERT INTO {LEAK_PROBE_TABLE} DEFAULT VALUES"))
    await db_session.commit()


async def test_previous_test_commit_did_not_leak_into_this_session(db_session):
    """Bir onceki testin commit'i, bu testin ayri transaction'inda GORUNMEMELI.
    Gorunuyorsa, izolasyon kirilmis demektir (fixture'daki SAVEPOINT korumasi eksik/bozuk).
    """
    result = await db_session.execute(text(f"SELECT to_regclass('{LEAK_PROBE_TABLE}')"))
    assert result.scalar() is None, (
        "Onceki testin commit'i sizdi: tablo hala mevcut. "
        "db_session fixture'i SAVEPOINT ile korunmuyor olabilir."
    )
