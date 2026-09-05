"""BC-3 — migration tur dönüşü: `b4d7e1c9f2a3` → `c5d8e2f1a4b7` → geri → ileri.

`test_mk2_document_migration.py` kalıbı: kendi TEK KULLANIMLIK veritabanını
açar, `.env`/`TEST_DATABASE_URL` ELLENMEZ (yalnız DSN'in veritabanı adı
değişir). Revizyonlara AÇIKÇA çıkılır (`head`/`-1` KULLANILMAZ).

Ölçülenler: beş tablo + enum var · 18 seed satırı (3/3/6/6, dört zorunlu) ·
üç indeks × dört tablo · bileşik FK + CHECK PG kataloğunda · downgrade sonrası
tablolar VE enum gider (ikinci upgrade "type already exists" ile patlamaz) ·
ikinci upgrade seed'i yeniden yazar.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from tests.documents.conftest import load_bc3_migration

BACKEND_DIR = Path(__file__).parents[2]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PREV_REVISION = "b4d7e1c9f2a3"
BC3_REVISION = "c5d8e2f1a4b7"

LINK_TABLES = (
    "section_documents",
    "unit_documents",
    "unit_sale_documents",
    "subcontractor_contract_documents",
)
TABLES = ("entity_document_types", *LINK_TABLES)

#: tablo -> (scope sabiti, sahip kolonu) — gövde denetiminin beklentisi.
LINK_SCOPE = {
    "section_documents": "section",
    "unit_documents": "unit",
    "unit_sale_documents": "unit_sale",
    "subcontractor_contract_documents": "subcontractor_contract",
}
LINK_OWNER = {
    "section_documents": "section_id",
    "unit_documents": "unit_id",
    "unit_sale_documents": "unit_sale_id",
    "subcontractor_contract_documents": "subcontractor_contract_id",
}


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _run_alembic(*args: str, database: str) -> None:
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


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")


async def _enum_exists(conn: asyncpg.Connection) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entity_document_scope')"
    )


async def _index_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", name
    )


async def _constraint_type(conn: asyncpg.Connection, name: str) -> str | None:
    return await conn.fetchval("SELECT contype::text FROM pg_constraint WHERE conname = $1", name)


async def _constraint_def(conn: asyncpg.Connection, name: str) -> str | None:
    """🔴 Kısıtın GÖVDESİ. Yalnız ada + `contype`a bakan bir bekçi, adı doğru
    ama gövdesi yanlış (örn. `scope = 'unit'` yazan bir `ck_section_documents_scope`
    ya da yalnız `id`ye bakan bir bileşik FK) bir migration'ı YEŞİL geçirirdi —
    migration↔model ayrışması bugün başka HİÇBİR kapıda konuşmuyor
    (`alembic-cycle` metadata karşılaştırmaz)."""
    return await conn.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", name
    )


async def _sahip_fk_def(conn: asyncpg.Connection, table: str, column: str) -> str | None:
    """Adı migration'da verilmeyen FK'ler (sahip + arşiv) — kolonundan bulunur."""
    return await conn.fetchval(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
        "WHERE c.conrelid = $1::regclass AND c.contype = 'f' AND a.attname = $2",
        f"public.{table}",
        column,
    )


async def _create_scratch_database() -> str:
    database = f"bc3_links_{uuid.uuid4().hex[:8]}"
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


async def _assert_bc3_schema(conn: asyncpg.Connection) -> None:
    for table in TABLES:
        assert await _table_exists(conn, table), table
    assert await _enum_exists(conn)

    rows = await conn.fetch(
        "SELECT scope::text, code, is_required, sort_order FROM entity_document_types "
        "ORDER BY scope, sort_order"
    )
    assert len(rows) == 18
    seed = load_bc3_migration().SLOT_SEED
    beklenen = sorted((s, c, r, o) for s, c, _n, r, o in seed)
    assert sorted((r[0], r[1], r[2], r[3]) for r in rows) == beklenen

    for table in LINK_TABLES:
        for suffix in ("type_id", "document_id", "owner_type"):
            assert await _index_exists(conn, f"ix_{table}_{suffix}"), (table, suffix)
        assert await _constraint_type(conn, f"fk_{table}_type_scope") == "f", table
        assert await _constraint_type(conn, f"ck_{table}_scope") == "c", table

        # 🔴 GÖVDE denetimi (ad + contype YETMEZ):
        scope = LINK_SCOPE[table]
        ck = await _constraint_def(conn, f"ck_{table}_scope")
        assert ck is not None and f"'{scope}'" in ck, (table, ck)
        assert "scope" in ck, (table, ck)

        fk = await _constraint_def(conn, f"fk_{table}_type_scope")
        assert fk is not None, table
        # Bileşik: İKİ kolon da adıyla geçmeli ve hedef katalogun (id, scope) çifti olmalı.
        assert "type_id" in fk and "scope" in fk, (table, fk)
        assert "entity_document_types" in fk, (table, fk)
        assert "id" in fk and "ON DELETE RESTRICT" in fk, (table, fk)

        sahip_fk = await _sahip_fk_def(conn, table, LINK_OWNER[table])
        assert sahip_fk is not None and "ON DELETE CASCADE" in sahip_fk, (table, sahip_fk)
        belge_fk = await _sahip_fk_def(conn, table, "document_id")
        assert belge_fk is not None and "ON DELETE SET NULL" in belge_fk, (table, belge_fk)

    assert await _constraint_type(conn, "uq_entity_document_types_id_scope") == "u"
    uq = await _constraint_def(conn, "uq_entity_document_types_id_scope")
    assert uq is not None and "id" in uq and "scope" in uq, uq


async def test_migration_tur_donusu_upgrade_downgrade_upgrade() -> None:
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PREV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert not await _table_exists(conn, table), f"{table} tabandan ONCE var olamaz"
            assert not await _enum_exists(conn)
        finally:
            await conn.close()

        _run_alembic("upgrade", BC3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _assert_bc3_schema(conn)
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == BC3_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PREV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert not await _table_exists(conn, table), f"{table} downgrade sonrasi kaldi"
            assert not await _enum_exists(conn), "enum tipi downgrade'de DUSURULMELI"
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == PREV_REVISION
        finally:
            await conn.close()

        # İkinci upgrade: enum yeniden yaratılır, seed yeniden yazılır.
        _run_alembic("upgrade", BC3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _assert_bc3_schema(conn)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
