"""CLEAN-B2 — `temperature_c` DROP migration'ı: tur dönüşü + veri davranışı.

`Dockerfile` açılışta `alembic upgrade head` koşar; patlarsa uvicorn hiç başlamaz. Bu yüzden:
* upgrade kolonu VE CHECK'i düşürür; `temp_min_c`/`temp_max_c` ve satırlar yerinde kalır;
* downgrade kolonu `Numeric(4,1)` NULL + CHECK'i aynı adla geri açar ve `temp_max_c`den
  YENİDEN TÜRETİR — upgrade öncesi `temp_max_c`den FARKLI olan değer GERİ GELMEZ (bu test
  kaybın geri dönüşsüzlüğünü de sabitler);
* ikinci upgrade "does not exist" ile patlamaz.

Tek kullanımlık veritabanı; `TEST_DATABASE_URL` veritabanı ELLENMEZ (HZ-1 deseni).
"""

import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest

from tests.modules.inventory.test_inventory_migration import _seed_site
from tests.modules.treasury.test_hz1_migration import (
    _asyncpg_dsn,
    _create_scratch_database,
    _drop_scratch_database,
    _run_alembic,
    _seed_user,
)

pytestmark = pytest.mark.asyncio

PREVIOUS = "aab10fbf5471"
CLEAN_B2 = "b5858dd66531"
CHECK = "ck_site_diary_entries_temperature_range"


async def _column(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT is_nullable, data_type, numeric_precision, numeric_scale "
        "FROM information_schema.columns "
        "WHERE table_name = 'site_diary_entries' AND column_name = 'temperature_c'"
    )


async def _check(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", CHECK
    )


async def _seed_entry(
    conn: asyncpg.Connection,
    site_id: uuid.UUID,
    user_id: uuid.UUID,
    day: date,
    legacy: str | None,
    temp_max: str | None,
) -> uuid.UUID:
    entry_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO site_diary_entries "
        "(id, site_id, project_id, entry_date, created_by, temperature_c, temp_min_c, temp_max_c) "
        "SELECT $1, s.id, s.project_id, $2, $3, $4, $5, $5 FROM sites s WHERE s.id = $6",
        entry_id,
        day,
        user_id,
        None if legacy is None else Decimal(legacy),
        None if temp_max is None else Decimal(temp_max),
        site_id,
    )
    return entry_id


async def test_clean_b2_migration_round_trip_and_data() -> None:
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PREVIOUS, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column(conn) is not None
            assert await _check(conn) is not None
            user_id = await _seed_user(conn)
            site_id = await _seed_site(conn, f"CB2-{uuid.uuid4().hex[:6]}")
            # Eşit (kodun PLN-B2'den beri koruduğu değişmez) ve FARKLI (dağıtım penceresi
            # kalıntısı — DROP'un geri dönüşsüz kaybettireceği değer) iki satır.
            synced = await _seed_entry(conn, site_id, user_id, date(2026, 9, 1), "20", "20")
            diverged = await _seed_entry(conn, site_id, user_id, date(2026, 9, 2), "7", "12.5")
        finally:
            await conn.close()

        _run_alembic("upgrade", CLEAN_B2, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column(conn) is None
            assert await _check(conn) is None
            rows = await conn.fetch("SELECT id, temp_min_c, temp_max_c FROM site_diary_entries")
            assert {r["id"]: r["temp_max_c"] for r in rows} == {
                synced: Decimal("20"),
                diverged: Decimal("12.5"),
            }
        finally:
            await conn.close()

        _run_alembic("downgrade", PREVIOUS, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            col = await _column(conn)
            assert col is not None
            assert tuple(col) == ("YES", "numeric", 4, 1)
            definition = await _check(conn)
            assert definition is not None and "temperature_c" in definition
            restored = dict(await conn.fetch("SELECT id, temperature_c FROM site_diary_entries"))
            # Yeniden TÜRETİLDİ: farklı olan eski değer (7) GERİ GELMEDİ.
            assert restored == {synced: Decimal("20"), diverged: Decimal("12.5")}
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await conn.execute(
                    "UPDATE site_diary_entries SET temperature_c = 61 WHERE id = $1", synced
                )
        finally:
            await conn.close()

        _run_alembic("upgrade", CLEAN_B2, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column(conn) is None
            assert await _check(conn) is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
