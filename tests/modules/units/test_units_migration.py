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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
# Bu revizyona ACIKCA cikilir; `head` KULLANILMAZ. Sonraki dilimler revizyon
# ekledikce `head`/`-1` bu revizyonu degil onlari olcerdi.
UNITS_REVISION = "a4c7f1d2e8b3"
NEW_TABLES = ("blocks", "units")
NEW_ENUM_TYPES = ("unit_kind", "unit_owner_side")

# --- P3.1 ---
# `head` / `-1` KULLANILMAZ (plan §0.A.3): her revizyon ACIK id'siyle olculur.
P31_R1_PARENT = "d2a32dcae735"
P31_R1_REVISION = "c1d2e3f4a5b6"
UNIT_KIND_LABELS_BEFORE = ["apartment", "shop"]
UNIT_KIND_LABELS_AFTER = ["apartment", "shop", "office", "warehouse", "parking"]
# Takas sirasinda kullanilan gecici tip adlari downgrade/upgrade sonrasi KALMAMALIDIR.
UNIT_KIND_TEMP_TYPES = ("unit_kind_new", "unit_kind_old")

P31_R2_PARENT = P31_R1_REVISION
P31_R2_REVISION = "c2d3e4f5a6b7"
P31_R2_TYPE_LABELS = {
    "block_roof_type": ["none", "duplex", "terrace"],
    "block_ground_usage": ["commercial", "apartment", "common"],
    "block_parking_type": ["closed", "open", "none"],
    "block_status": ["planning", "construction", "completed"],
    "unit_facing": ["south", "southwest", "east", "north", "west"],
    "unit_parking_right": ["none", "one_closed", "two"],
    "unit_sales_status": ["listed", "reserved", "sold", "closed"],
}
P31_R2_TYPES = tuple(P31_R2_TYPE_LABELS)


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


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = $1 ORDER BY e.enumsortorder",
        name,
    )
    return [row["enumlabel"] for row in rows]


async def _column_counts(conn: asyncpg.Connection) -> dict[str, int]:
    return {
        table: await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = $1",
            table,
        )
        for table in NEW_TABLES
    }


@asynccontextmanager
async def _temp_database(prefix: str) -> AsyncIterator[str]:
    """Tek kullanimlik yerel veritabani; basarisizlikta da dusurulur (plan §0.A.2)."""
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
    database = f"p3_units_mig_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()

    try:
        _run_alembic("upgrade", UNITS_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), f"{enum_type} upgrade sonrasi yok"
            assert await _current_revision(conn) == UNITS_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
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

        _run_alembic("upgrade", UNITS_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), f"{table} ikinci upgrade sonrasi yok"
            for enum_type in NEW_ENUM_TYPES:
                assert await _type_exists(conn, enum_type), (
                    f"{enum_type} ikinci upgrade sonrasi yok"
                )
            assert await _current_revision(conn) == UNITS_REVISION
        finally:
            await conn.close()
    finally:
        admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()


# --- P3.1 / R1: `unit_kind` enum takasi (izole revizyon) ---


async def test_r1_upgrade_downgrade_upgrade():
    """R1 tur donusu: 2 etiket → 5 etiket → 2 etiket → 5 etiket."""
    async with _temp_database("p31_r1_mig") as database:
        _run_alembic("upgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_BEFORE

        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_AFTER
            assert await _current_revision(conn) == P31_R1_REVISION

        _run_alembic("downgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_BEFORE
            assert await _current_revision(conn) == P31_R1_PARENT

        # IKINCI upgrade: `DROP TYPE` unutulmussa burasi "type already exists" ile patlar.
        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            assert await _enum_labels(conn, "unit_kind") == UNIT_KIND_LABELS_AFTER


async def test_r1_downgrade_eski_tipi_birakmaz():
    """Takasin gecici tipleri ne upgrade ne downgrade sonrasi `pg_type`'da kalir."""
    async with _temp_database("p31_r1_type") as database:
        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            for temp_type in UNIT_KIND_TEMP_TYPES:
                assert not await _type_exists(conn, temp_type), (
                    f"{temp_type} upgrade sonrasi pg_type'da duruyor"
                )

        _run_alembic("downgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            for temp_type in UNIT_KIND_TEMP_TYPES:
                assert not await _type_exists(conn, temp_type), (
                    f"{temp_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _type_exists(conn, "unit_kind")


async def test_r1_baska_sema_degisikligi_yok():
    """R1 IZOLEDIR: `units`/`blocks` kolon sayisi degismez (spec §10.2/R1)."""
    async with _temp_database("p31_r1_iso") as database:
        _run_alembic("upgrade", P31_R1_PARENT, database=database)
        async with _connect(database) as conn:
            before = {
                table: await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table,
                )
                for table in NEW_TABLES
            }

        _run_alembic("upgrade", P31_R1_REVISION, database=database)
        async with _connect(database) as conn:
            after = {
                table: await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table,
                )
                for table in NEW_TABLES
            }
        assert after == before


# --- P3.1 / R2: yedi yeni enum tipi (izole revizyon) ---


async def test_r2_yedi_tip_olusur():
    """R2 yedi tipi olusturur ve KOLON EKLEMEZ (spec §10.2/R2)."""
    async with _temp_database("p31_r2_mig") as database:
        _run_alembic("upgrade", P31_R2_PARENT, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert not await _type_exists(conn, enum_type), f"{enum_type} R2 oncesi var"
            before = await _column_counts(conn)

        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        async with _connect(database) as conn:
            for enum_type, labels in P31_R2_TYPE_LABELS.items():
                assert await _enum_labels(conn, enum_type) == labels
            assert await _current_revision(conn) == P31_R2_REVISION
            assert await _column_counts(conn) == before


async def test_r2_downgrade_yedi_tipi_de_dusurur():
    """`DROP TYPE` unutulan tek bir tip bile ikinci upgrade'i patlatir (plan §0.A.4)."""
    async with _temp_database("p31_r2_drop") as database:
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        _run_alembic("downgrade", P31_R2_PARENT, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert not await _type_exists(conn, enum_type), (
                    f"{enum_type} downgrade sonrasi pg_type'da duruyor"
                )
            assert await _current_revision(conn) == P31_R2_PARENT


async def test_r2_ikinci_upgrade_patlamaz():
    async with _temp_database("p31_r2_twice") as database:
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        _run_alembic("downgrade", P31_R2_PARENT, database=database)
        _run_alembic("upgrade", P31_R2_REVISION, database=database)
        async with _connect(database) as conn:
            for enum_type in P31_R2_TYPES:
                assert await _type_exists(conn, enum_type), (
                    f"{enum_type} ikinci upgrade sonrasi yok"
                )
