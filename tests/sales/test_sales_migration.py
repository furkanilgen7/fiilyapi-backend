"""P8 T1 — `f2a3b4c5d6e7` migration'inin upgrade → downgrade → upgrade tur donusu.

Neden ayri ve maliyetli bir test: Postgres'te `ENUM` tipi tabloyla birlikte
SILINMEZ. `downgrade()` icinde `DROP TYPE` unutulursa ilk tur sessizce gecer,
ikinci `upgrade` "type already exists" ile patlar — ve bu yalniz canlida gorulur.
Bu dilim ALTI yeni enum acar, dolayisiyla risk altidir.

Revizyonlar ACIK id'leriyle olculur; `head` / `-1` KULLANILMAZ — sonraki
dilimler revizyon ekledikce bu test onlari olcmeye baslardi.

Test kendi TEK KULLANIMLIK veritabanini acar ve basarisizlikta da dusurur;
`.env`deki veritabani ELLENMEZ. Alembic alt surecte kosturulur cunku
`alembic/env.py` kendi `asyncio.run()` dongusunu kurar ve calisan bir
pytest-asyncio dongusunun icinden cagrilamaz.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[2]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "c3d4e5f6a7b8"
SALES_REVISION = "f2a3b4c5d6e7"

NEW_TABLES = ("customers", "unit_sales", "sale_installments")
NEW_ENUM_TYPES = (
    "customer_type",
    "sale_type",
    "unit_sale_status",
    "deed_condition",
    "payment_plan_type",
    "installment_payment_method",
)
NEW_INDEXES = {
    "customers": ("uq_customers_national_id", "uq_customers_tax_number", "ix_customers_name"),
    "unit_sales": ("uq_unit_sales_open_unit",),
    "sale_installments": ("ix_sale_installments_sale_id",),
}


def _asyncpg_dsn(database: str) -> str:
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
        timeout=300,
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


async def _index_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        name,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


@asynccontextmanager
async def _temp_database(prefix: str) -> AsyncIterator[str]:
    database = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        yield database
    finally:
        admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()


@asynccontextmanager
async def _connect(database: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_asyncpg_dsn(database))
    try:
        yield conn
    finally:
        await conn.close()


async def test_upgrade_downgrade_upgrade_round_trip():
    async with _temp_database("p8_sales_mig") as database:
        _run_alembic("upgrade", SALES_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _current_revision(conn) == SALES_REVISION
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} upgrade sonrasi yok"
            for enum_name in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_name), f"{enum_name} tipi olusmadi"
            for indexes in NEW_INDEXES.values():
                for index in indexes:
                    assert await _index_exists(conn, index), f"{index} indeksi olusmadi"
            # 19. izin modulu + 8 satiri
            assert await conn.fetchval("SELECT count(*) FROM modules WHERE key = 'sales'") == 1
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM role_permissions rp JOIN modules m "
                    "ON m.id = rp.module_id WHERE m.key = 'sales'"
                )
                == 8
            )
            assert await conn.fetchval("SELECT count(*) FROM modules") == 19
            assert await conn.fetchval("SELECT count(*) FROM role_permissions") == 152

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _current_revision(conn) == PARENT_REVISION
            for table in NEW_TABLES:
                assert not await _table_exists(conn, table), f"{table} downgrade sonrasi duruyor"
            for enum_name in NEW_ENUM_TYPES:
                assert not await _type_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade sonrasi duruyor — DROP TYPE unutulmus"
                )
            assert await conn.fetchval("SELECT count(*) FROM modules WHERE key = 'sales'") == 0
            assert await conn.fetchval("SELECT count(*) FROM modules") == 18
            assert await conn.fetchval("SELECT count(*) FROM role_permissions") == 144

        # Ikinci upgrade: "type already exists" patlamasini yakalar.
        _run_alembic("upgrade", SALES_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _current_revision(conn) == SALES_REVISION
            for table in NEW_TABLES:
                assert await _table_exists(conn, table)
            assert await conn.fetchval("SELECT count(*) FROM role_permissions") == 152


async def test_downgrade_diger_modulleri_kaydirmaz():
    """`sales` sona eklendigi icin hicbir modulun sort_order'i degismemeli."""
    async with _temp_database("p8_sales_sort") as database:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        async with _connect(database) as conn:
            once = dict(await conn.fetch("SELECT key, sort_order FROM modules"))  # type: ignore[arg-type]

        _run_alembic("upgrade", SALES_REVISION, database=database)
        async with _connect(database) as conn:
            sonra = dict(await conn.fetch("SELECT key, sort_order FROM modules"))  # type: ignore[arg-type]
            assert sonra.pop("sales") == 19
            assert sonra == once
