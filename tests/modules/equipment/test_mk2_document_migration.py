"""MK-2 T4 — ekipman belgeleri şeması: model katmanı + migration tur dönüşü.

Spec: `docs/superpowers/specs/2026-08-14-mk2-kira-hakedisi-design.md` §2.3, §5, K7.

`test_mk2_rental_invoice_migration.py`nin AYNI kalıbı: kendi TEK KULLANIMLIK
veritabanını açar, `.env`/`TEST_DATABASE_URL` ELLENMEZ. Revizyonlara AÇIKÇA
çıkılır (`head`/`-1` KULLANILMAZ).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.equipment.models import EquipmentDocument, EquipmentDocumentType

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

MK2_T3_REVISION = "e8f9a0b1c2d3"
MK2_T4_REVISION = "f9a0b1c2d3e4"

TABLES = ("equipment_document_types", "equipment_documents")

EXPECTED_SEED_CODES = {
    "invoice_or_contract",
    "periodic_inspection",
    "ce_certificate",
    "manual",
    "insurance_policy",
    "delivery_photos",
}
EXPECTED_REQUIRED_CODES = {"invoice_or_contract", "periodic_inspection"}

INDEXES = (
    "ix_equipment_documents_equipment_id",
    "ix_equipment_documents_type_id",
    "ix_equipment_documents_valid_until",
    "ix_equipment_documents_equipment_type",
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


async def _index_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"equipment_mk2t4_{uuid.uuid4().hex[:8]}"
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


async def _seed_equipment(conn: asyncpg.Connection, name: str = "Kule Vinç KV-01") -> uuid.UUID:
    equipment_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment (id, name, category) VALUES ($1, $2, 'crane')",
        equipment_id,
        name,
    )
    return equipment_id


# --------------------------------------------------------------------------- #
# Model katmani
# --------------------------------------------------------------------------- #


def test_document_type_columns_match_spec():
    columns = EquipmentDocumentType.__table__.columns
    assert set(columns.keys()) == {"id", "code", "name", "is_required", "sort_order", "created_at"}
    assert not columns["code"].nullable
    assert not columns["name"].nullable
    assert not columns["is_required"].nullable
    assert not columns["sort_order"].nullable


def test_document_columns_match_spec():
    columns = EquipmentDocument.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "equipment_id",
        "type_id",
        "filename",
        "mime_type",
        "size_bytes",
        "content",
        # FRM-1 (BOR-TEMIZ T2) — üç künye alanı, hepsi nullable.
        "document_no",
        "issued_at",
        "note",
        "valid_until",
        "created_at",
        "updated_at",
    }
    assert not columns["equipment_id"].nullable
    assert not columns["type_id"].nullable
    assert not columns["filename"].nullable
    assert not columns["mime_type"].nullable
    assert not columns["size_bytes"].nullable
    assert not columns["content"].nullable
    # K7 — onaylı sapma: nullable, ZORUNLU DEĞİL.
    assert columns["valid_until"].nullable


def test_document_foreign_keys_match_spec():
    columns = EquipmentDocument.__table__.columns
    (equipment_fk,) = tuple(columns["equipment_id"].foreign_keys)
    assert equipment_fk.target_fullname == "equipment.id"
    assert equipment_fk.ondelete == "CASCADE"

    (type_fk,) = tuple(columns["type_id"].foreign_keys)
    assert type_fk.target_fullname == "equipment_document_types.id"
    assert type_fk.ondelete == "RESTRICT"


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK2_T4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            assert await _current_revision(conn) == MK2_T4_REVISION

            # SEED: altı sabit tip, kodlar + zorunluluk M2:134-159 birebir.
            rows = await conn.fetch(
                "SELECT code, is_required FROM equipment_document_types ORDER BY sort_order"
            )
            codes = {r["code"] for r in rows}
            assert codes == EXPECTED_SEED_CODES
            required_codes = {r["code"] for r in rows if r["is_required"]}
            assert required_codes == EXPECTED_REQUIRED_CODES
            assert len(rows) == 6
        finally:
            await conn.close()

        _run_alembic("downgrade", MK2_T3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert not await _table_exists(conn, table), table
            assert await _current_revision(conn) == MK2_T3_REVISION
            # MK-2 T3'ün kendi tabloları AYAKTA kalmalı.
            assert await _table_exists(conn, "equipment_rental_invoices")
        finally:
            await conn.close()

        _run_alembic("upgrade", MK2_T4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            assert await _current_revision(conn) == MK2_T4_REVISION
            # İkinci upgrade'de seed YENİDEN eklenmiş olmalı (uuid4 çakışmaz).
            count = await conn.fetchval("SELECT count(*) FROM equipment_document_types")
            assert count == 6
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_semantics():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK2_T4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = await _seed_equipment(conn)
            type_id = await conn.fetchval(
                "SELECT id FROM equipment_document_types WHERE code = 'invoice_or_contract'"
            )

            doc_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO equipment_documents "
                "(id, equipment_id, type_id, filename, mime_type, size_bytes, content) "
                "VALUES ($1, $2, $3, 'fatura.pdf', 'application/pdf', 4, $4)",
                doc_id,
                equipment_id,
                type_id,
                b"data",
            )

            # Negatif boy hiçbir okumada anlamlı değildir.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "INSERT INTO equipment_documents "
                    "(id, equipment_id, type_id, filename, mime_type, size_bytes, content) "
                    "VALUES ($1, $2, $3, 'x.pdf', 'application/pdf', -1, $4)",
                    uuid.uuid4(),
                    equipment_id,
                    type_id,
                    b"x",
                )

            # 🔴 RESTRICT: kullanımda olan katalog tipi silinemez.
            with pytest.raises((asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)):
                await conn.execute("DELETE FROM equipment_document_types WHERE id = $1", type_id)

            # CASCADE: ekipman düşünce belgesi de düşer.
            await conn.execute("DELETE FROM equipment WHERE id = $1", equipment_id)
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM equipment_documents WHERE id = $1", doc_id
                )
            ) == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
