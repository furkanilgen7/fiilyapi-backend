"""İK-1 T1 — migration tur dönüşü: `a1b2c3d4e5f6` upgrade → downgrade → upgrade.

SA emsali (`tests/modules/procurement/test_procurement_migration.py`): dört
YENİ enum tipi (`gender`/`marital_status`/`wage_type`/`payment_method`)
downgrade'de açıkça `DROP TYPE` edilmezse ikinci `upgrade` "type already
exists" ile patlar (d4e5f6a7b8c9 dersi) — bu yalnız CANLIDA görülür. Bu test
YAKALAR.

`worker_source` PAYLAŞILAN tiptir (site_diary dilimi b5c6d7e8f9a0'da açıldı) —
downgrade'de DÜŞMEMELİDİR; test bunu ayrıca doğrular.

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

PARENT_REVISION = "f3a4b5c6d7e8"  # SA satinalma cekirdegi
IK1_REVISION = "a1b2c3d4e5f6"

NEW_TABLES = ("personnel_document_types", "personnel_documents")
NEW_ENUMS = ("gender", "marital_status", "wage_type", "payment_method")
NEW_PERSONNEL_COLUMNS = (
    "tc_no",
    "birth_date",
    "gender",
    "marital_status",
    "phone",
    "email",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "hire_date",
    "wage_type",
    "wage_amount",
    "payment_method",
    "iban",
    "sgk_no",
    "assigned_project_id",
    "assigned_section_id",
    "is_draft",
)


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


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"ik1_t1_{uuid.uuid4().hex[:8]}"
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
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar)."""
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
    assert heads[0].split()[0] == IK1_REVISION, (
        f"tek head {IK1_REVISION} olmali, bulunan: {heads[0]}"
    )


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", IK1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
            for column in NEW_PERSONNEL_COLUMNS:
                assert await _column_exists(conn, "personnel", column), column
            # `worker_source` bu dilimde ACILMADI ama HALA MEVCUT olmali.
            assert await _enum_exists(conn, "worker_source")

            seed_count = await conn.fetchval("SELECT count(*) FROM personnel_document_types")
            assert seed_count == 6, "seed 6 sabit tip olmali (spec §2)"
            zorunlu_count = await conn.fetchval(
                "SELECT count(*) FROM personnel_document_types WHERE is_mandatory = true"
            )
            assert zorunlu_count == 3, "Kimlik/Saglik/ISG zorunlu 3 tip olmali"

            assert await _current_revision(conn) == IK1_REVISION
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
            # Paylasilan tip DUSURULMEMELI.
            assert await _enum_exists(conn, "worker_source"), (
                "worker_source PAYLASILAN tiptir, İK-1 downgrade'i dusurmemeliydi"
            )
            for column in NEW_PERSONNEL_COLUMNS:
                assert not await _column_exists(conn, "personnel", column), column
            assert await _table_exists(conn, "personnel"), "personnel tablosu dusurulmus"
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", IK1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in NEW_TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
            seed_count = await conn.fetchval("SELECT count(*) FROM personnel_document_types")
            assert seed_count == 6
            assert await _current_revision(conn) == IK1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
