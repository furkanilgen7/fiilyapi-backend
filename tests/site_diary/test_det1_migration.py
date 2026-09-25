"""DET-1.B — `submitted_by_user_id` migration tur dönüşü + canlı açılış güvenliği.

`Dockerfile` açılışta `alembic upgrade head` koşar; patlarsa uvicorn hiç başlamaz. Bu yüzden:
* upgrade → downgrade → upgrade temiz döner (downgrade FK'yi ADIYLA düşürür, ikinci upgrade
  "already exists" ile patlamaz);
* kolon NULL + VARSAYILANSIZ (tablo yeniden yazılmaz, mevcut satırlar NULL kalır — geri
  doldurma yok);
* FK `users(id) ON DELETE SET NULL` (kullanıcı silinince gönderim kaydı kaybolmaz).

Tek kullanımlık veritabanı; `TEST_DATABASE_URL` veritabanı ELLENMEZ (HZ-1 deseni).
"""

import asyncpg
import pytest

from tests.modules.treasury.test_hz1_migration import (
    _asyncpg_dsn,
    _create_scratch_database,
    _drop_scratch_database,
    _run_alembic,
)

pytestmark = pytest.mark.asyncio

PREVIOUS = "5b2637be627a"
DET1 = "c7d1e2f3a4b5"
FK = "fk_site_diary_entries_submitted_by_user_id_users"


async def _column(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT is_nullable, column_default, data_type FROM information_schema.columns "
        "WHERE table_name = 'site_diary_entries' AND column_name = 'submitted_by_user_id'"
    )


async def _fk(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT confdeltype::text AS confdeltype, confrelid::regclass::text AS target "
        "FROM pg_constraint "
        "WHERE conname = $1",
        FK,
    )


async def test_det1_migration_round_trip_and_live_safety() -> None:
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", DET1, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            col = await _column(conn)
            assert col is not None
            assert (col["is_nullable"], col["column_default"], col["data_type"]) == (
                "YES",
                None,
                "uuid",
            )
            fk = await _fk(conn)
            assert fk is not None and (fk["confdeltype"], fk["target"]) == ("n", "users")
        finally:
            await conn.close()

        _run_alembic("downgrade", PREVIOUS, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column(conn) is None
            assert await _fk(conn) is None
        finally:
            await conn.close()

        _run_alembic("upgrade", DET1, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column(conn) is not None
            assert await _fk(conn) is not None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
