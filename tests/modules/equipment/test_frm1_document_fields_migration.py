"""FRM-1 — `equipment_documents` üç yeni kolonu: model katmanı + migration turu.

`test_mk2_document_migration.py`nin AYNI kalıbı: kendi TEK KULLANIMLIK
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
from app.modules.equipment.models import EquipmentDocument

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

MT1_REVISION = "c8d9e0f1a2b3"
"""FRM-1'den ÖNCEKİ tek head — yeni migration'ın `down_revision`'ı."""

FRM1_REVISION = "d3e4f5a6b7c8"

NEW_COLUMNS = ("document_no", "issued_at", "note")


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


async def _columns(conn: asyncpg.Connection) -> dict[str, asyncpg.Record]:
    rows = await conn.fetch(
        "SELECT column_name, data_type, is_nullable, character_maximum_length "
        "FROM information_schema.columns WHERE table_name = 'equipment_documents'"
    )
    return {r["column_name"]: r for r in rows}


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"equipment_frm1_{uuid.uuid4().hex[:8]}"
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


# --------------------------------------------------------------------------- #
# Model katmani
# --------------------------------------------------------------------------- #


def test_uc_yeni_kolon_modelde_nullable():
    columns = EquipmentDocument.__table__.columns
    for name in NEW_COLUMNS:
        assert name in columns, name
        assert columns[name].nullable, name
    # K1 — emsalle bağlı uzunluk (contract_no / serial_no / invoice_no).
    assert columns["document_no"].type.length == 100


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


def test_alembic_tek_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar).

    🔴 `DATABASE_URL` override'ı ŞARTTIR: `.env` UZAK Railway'i gösterir ve
    alembic'in bir alt komutunun motor kurması hiçbir uyarı vermeden canlıya
    bağlanmak demektir. Kural tek cümledir: **hiçbir alembic komutu
    override'sız koşmaz** (emsal `test_mt1_ozkaynak_kontra_migration.py`).

    🔴 **BURADA `FRM1_REVISION`in HEAD OLDUĞU İDDİA EDİLMEZ** (MU-SEED T7
    bulgusu). Eskiden `assert FRM1_REVISION in heads[0]` yazıyordu; bu, "FRM-1
    en yeni migration'dır" demekti ve **kendisinden sonra gelen İLK dilimde
    kaçınılmaz olarak kırmızıya döndü** (MU-SEED `e5f6a7b8c9d0` head'i aldı).
    Repodaki 18 migration testinin diğer 17'si yalnız `len(heads) == 1` iddia
    eder; kimlik iddiası bu dosyaya özgü bir tuzaktı.

    Korunması GEREKEN asıl özellik zincirden düşmemektir: kötü bir re-parent
    FRM-1'i öksüz bırakırsa kolonları canlıda HİÇ oluşmaz. Bu yüzden iddia
    **atalık** iddiasına çevrildi — FRM-1 head'in atalarının arasında OLMALI.
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": _asyncpg_dsn("postgres")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    atalar = {rev.revision for rev in script.iterate_revisions(heads[0].split()[0], "base")}
    assert FRM1_REVISION in atalar, (
        f"{FRM1_REVISION} head'in zincirinde DEĞİL — re-parent onu öksüz bırakmış olabilir; "
        f"head: {heads[0]}"
    )


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FRM1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            cols = await _columns(conn)
            assert await _current_revision(conn) == FRM1_REVISION
            for name in NEW_COLUMNS:
                assert name in cols, name
                assert cols[name]["is_nullable"] == "YES", name
            assert cols["document_no"]["data_type"] == "character varying"
            assert cols["document_no"]["character_maximum_length"] == 100
            assert cols["issued_at"]["data_type"] == "date"
            assert cols["note"]["data_type"] == "text"
        finally:
            await conn.close()

        _run_alembic("downgrade", MT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == MT1_REVISION
            cols = await _columns(conn)
            for name in NEW_COLUMNS:
                assert name not in cols, name
            # Tablo ve mevcut kolonları AYAKTA kalmalı.
            assert "valid_until" in cols
            assert "content" in cols
        finally:
            await conn.close()

        _run_alembic("upgrade", FRM1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == FRM1_REVISION
            cols = await _columns(conn)
            for name in NEW_COLUMNS:
                assert name in cols, name
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_mevcut_satirlar_uc_kolonsuz_yazilabilir():
    """Üç kolon nullable: eski INSERT biçimi (kolonsuz) HÂLÂ geçerli olmalı."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FRM1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO equipment (id, name, category) VALUES ($1, 'Kule Vinç', 'crane')",
                equipment_id,
            )
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
            row = await conn.fetchrow(
                "SELECT document_no, issued_at, note FROM equipment_documents WHERE id = $1",
                doc_id,
            )
            assert row["document_no"] is None
            assert row["issued_at"] is None
            assert row["note"] is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
