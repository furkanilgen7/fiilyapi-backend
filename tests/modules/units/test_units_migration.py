"""B1 — p3 units/blocks migration'inin upgrade → downgrade → upgrade tur donusu.

Neden ayri ve maliyetli bir test: Postgres'te `ENUM` tipi tabloyla birlikte
SILINMEZ. `downgrade()` icinde `DROP TYPE` unutulursa ilk tur sessizce gecer,
ikinci `upgrade` "type already exists" ile patlar — ve bu yalniz canlida gorulur
(plan §0 / spec §10.3). Bu yuzden downgrade sonrasi iki enum tipinin `pg_type`'da
KALMADIGI ayrica dogrulanir.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ (plan §0.1). Alembic alt surecte
kosturulur cunku `alembic/env.py` kendi `asyncio.run()` dongusunu kurar ve
calisan bir pytest-asyncio dongusunun icinden cagrilamaz.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[3]
# Alembic `python -m alembic` ile cagrilir: yerelde `.venv/bin/python`, CI'da
# sistem Python'u — iki ortamda da AYNI yorumlayicinin ortami kullanilir.
# Sabit `.venv/bin/alembic` yolu CI'da YOKTUR (orada venv kurulmaz) ve testi
# yalniz CI'da kirardi.
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "e3a8b4a5b93b"
NEW_TABLES = ("blocks", "units")
NEW_ENUM_TYPES = ("unit_kind", "unit_owner_side")


def _asyncpg_dsn(database: str) -> str:
    """settings.test_database_url'i asyncpg'nin anladigi duz DSN'e cevirir."""
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _run_alembic(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    result = subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")
    return result


async def _table_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = $1)",
        name,
    )


async def _type_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = $1)", name)


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def test_upgrade_downgrade_upgrade_round_trip():
    database = f"p3_units_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", "head", database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), f"{enum_type} upgrade sonrasi yok"
            head_revision = await _current_revision(conn)
            assert head_revision is not None
            assert head_revision != PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", "-1", database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert not await _table_exists(conn, table), f"{table} downgrade sonrasi duruyor"
            # KRITIK: enum tipi tabloyla birlikte SILINMEZ; DROP TYPE unutulursa
            # ikinci upgrade patlar (spec §10.3).
            for enum_type in NEW_ENUM_TYPES:
                assert not await _type_exists(conn, enum_type), (
                    f"{enum_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", "head", database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} ikinci upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), (
                    f"{enum_type} ikinci upgrade sonrasi yok"
                )
            assert await _current_revision(conn) == head_revision
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()
