"""İK-2 T1 — migration tur dönüşü: `b2c3d4e5f6a7` upgrade → downgrade → upgrade.

İK-1 emsali (`test_ik1_migration_round.py`): YENİ enum tipi (`leave_status`)
downgrade'de açıkça `DROP TYPE` edilmezse ikinci `upgrade` "type already
exists" ile patlar (d4e5f6a7b8c9 dersi) — bu yalnız CANLIDA görülür. Bu test
YAKALAR.

Ayrıca doğrulanır: 3 tip SEED (Yıllık/Hastalık/Mazeret, spec §1) ·
`leave_balances` UQ(personnel_id, year) · `annual_entitlement` KOLONU AÇILMAMIŞ
(spec §5 K1 — kıdemden TÜREV) · downgrade seed'i temizler.

Revizyonlara AÇIKÇA çıkılır; `head`/`-1` KULLANILMAZ (WORKFLOW §4).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[2]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "a1b2c3d4e5f6"  # İK-1 personel kartı + belge takibi
IK2_REVISION = "b2c3d4e5f6a7"

NEW_TABLES = ("leave_types", "leave_requests", "leave_balances")
NEW_ENUMS = ("leave_status",)


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
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{result.stdout}\n{result.stderr}")
    return result


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")


async def _column_exists(conn: asyncpg.Connection, table: str, column: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2)",
        table,
        column,
    )


async def _enum_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = $1 AND typtype = 'e')", name
    )


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = $1 ORDER BY e.enumsortorder",
        name,
    )
    return [row["enumlabel"] for row in rows]


async def _constraint_exists(conn: asyncpg.Connection, table: str, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
        "WHERE r.relname = $1 AND c.conname = $2)",
        table,
        name,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"ik2_t1_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _drop_scratch_database(database: str) -> None:
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.close()


def test_alembic_has_single_head():
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar).

    Head ID'si de dogrulanir: İK-2 zincirin EN UCU olmalidir (yoksa yeni
    migration hicbir zaman kosmaz).
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, cikti:\n{result.stdout}"
    assert heads[0].split()[0] == IK2_REVISION, (
        f"tek head {IK2_REVISION} olmali, bulunan: {heads[0]}"
    )


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", IK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
            assert await _enum_labels(conn, "leave_status") == ["pending", "approved", "rejected"]

            # spec §5 K1: yillik hak KOLON DEGIL, kidemden TUREV.
            assert not await _column_exists(conn, "leave_balances", "annual_entitlement"), (
                "annual_entitlement KOLON OLMAMALI (spec §5 K1 — kidemden turev)"
            )
            assert await _constraint_exists(
                conn, "leave_balances", "uq_leave_balances_personnel_year"
            )

            seed = await conn.fetch(
                "SELECT name, deducts_from_annual, is_paid, requires_document "
                "FROM leave_types ORDER BY sort_order"
            )
            assert [row["name"] for row in seed] == ["Yıllık İzin", "Hastalık İzni", "Mazeret İzni"]
            assert [row["deducts_from_annual"] for row in seed] == [True, False, False]
            assert [row["requires_document"] for row in seed] == [False, True, False]

            assert await _current_revision(conn) == IK2_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmis — ikinci upgrade patlar"
                )
            # İK-1 tablolari AYAKTA kalmali.
            assert await _table_exists(conn, "personnel")
            assert await _table_exists(conn, "personnel_documents")
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", IK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), table
            assert await _enum_exists(conn, "leave_status")
            seed_count = await conn.fetchval("SELECT count(*) FROM leave_types")
            assert seed_count == 3, "seed 3 sabit tip olmali (spec §1)"
            assert await _current_revision(conn) == IK2_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
