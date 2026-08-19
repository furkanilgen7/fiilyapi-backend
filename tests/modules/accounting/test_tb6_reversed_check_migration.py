"""TB6 T2 — denge CHECK'ini genisleten migration turu (`e9f0a1b2c3d4`).

## 🔴 NEDEN AYRI BIR TUR DONUSU TESTI

`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar; migration
patlarsa `&&` kisa devre yapar ve **uvicorn HIC BASLAMAZ (tam kesinti)**.
Downgrade eski kisiti geri kurmazsa ikinci `upgrade` de patlar
("constraint already exists"). Bu yuzden tur `upgrade → downgrade → upgrade`
olarak KOSULUR, iddia edilmez.

## 🔴 MIGRATION'IN SESSIZ OLMAYAN OLCUMU

`upgrade()` kisiti eklemeden ONCE ihlal eden satirlari SAYAR ve varsa acik bir
`RuntimeError` ile durur. Bu test o dali da FIILEN kurar (dengesiz bir
`reversed` satir yazar, sonra upgrade'i kosar) — "olcum kodu var" demek
"olcum bekcilik ediyor" demek DEGILDIR.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ (`test_mt1_ozkaynak_kontra_migration`
deseni). Revizyonlara ACIKCA cikilir; `head` / `-1` KULLANILMAZ.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.accounting import balance
from app.modules.accounting.models import BALANCE_ENFORCED_STATUSES, POSTING_BALANCED_CHECK

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

FIN1_REVISION = "d8e9f0a1b2c3"
TB6_REVISION = "e9f0a1b2c3d4"

TABLE = "journal_entries"
OLD_NAME = "ck_journal_entries_posted_balanced"
NEW_NAME = "ck_journal_entries_posting_balanced"


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


def _run_alembic_expecting_failure(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    return subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


async def _constraint_sql(conn: asyncpg.Connection, name: str) -> str | None:
    return await conn.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"accounting_tb6_{uuid.uuid4().hex[:8]}"
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
# Sembolik katman — migration'in SQL'i ile modelin SQL'i BUGUN ESITTIR
# --------------------------------------------------------------------------- #


def test_migration_parent_is_the_expected_revision():
    """Iki head = canlida deploy kilitlenmesi (`alembic upgrade head` patlar)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(TB6_REVISION).down_revision == FIN1_REVISION
    assert [h for h in script.get_heads()] == [TB6_REVISION]


def test_migration_SQL_i_modelin_SQL_i_ile_AYNI():
    """🔴 Migration modelden ITHAL ETMEZ (gecmis donmus olmalidir) — o hâlde
    ikisinin BUGUN esit oldugu AYRICA olculur. Ayrisirlarsa `create_all` ile
    kurulan test semasi ile `alembic upgrade` ile kurulan canli sema FARKLI
    davranir ve suite bunu HIC gormez."""
    import importlib.util

    yol = BACKEND_DIR / "alembic" / "versions" / "e9f0a1b2c3d4_tb6_dengesiz_reversed_check.py"
    spec = importlib.util.spec_from_file_location("tb6_mig", yol)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    assert modul.NEW_SQL == POSTING_BALANCED_CHECK
    assert modul.NEW_NAME == NEW_NAME
    for durum in BALANCE_ENFORCED_STATUSES:
        assert f"'{durum}'" in modul.NEW_SQL
    assert {d.value for d in balance.POSTING_STATUSES} == set(BALANCE_ENFORCED_STATUSES)


# --------------------------------------------------------------------------- #
# Gercek zincir
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_round_trip():
    """Kisit ADI da degisti: downgrade eskisini geri kurmazsa ikinci upgrade
    `drop_constraint` asamasinda "does not exist" ile patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", TB6_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == TB6_REVISION
            yeni = await _constraint_sql(conn, NEW_NAME)
            assert yeni is not None
            # PG kisit metnini yeniden yazar; kume uyeligi yine de okunabilir.
            assert "reversed" in yeni and "posted" in yeni
            assert await _constraint_sql(conn, OLD_NAME) is None
        finally:
            await conn.close()

        _run_alembic("downgrade", FIN1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == FIN1_REVISION
            eski = await _constraint_sql(conn, OLD_NAME)
            assert eski is not None
            assert "reversed" not in eski
            assert await _constraint_sql(conn, NEW_NAME) is None
        finally:
            await conn.close()

        _run_alembic("upgrade", TB6_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == TB6_REVISION
            assert await _constraint_sql(conn, NEW_NAME) is not None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.asyncio
async def test_DENGESIZ_reversed_SATIR_VARSA_upgrade_ACIK_MESAJLA_DURUR():
    """🔴 Migration'in olcum dali FIILEN kurulur.

    Kisit eklenmeden once ihlal sayilmasaydi kullanici ham bir
    `CheckViolationError` gorurdu; burada `alembic` ciktisinda satir SAYISININ
    ve tablonun adinin GECTIGI iddia edilir.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FIN1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            kullanici_id = await conn.fetchval(
                "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status) "
                "SELECT gen_random_uuid(), 'tb6@mig.co', 'x', 'TB6', 'Test', id, 'active' "
                "FROM roles LIMIT 1 RETURNING id"
            )
            await conn.execute(
                "INSERT INTO journal_entries "
                "(id, entry_date, period_year, period_month, description, status, "
                " total_debit, total_credit, created_by_id) "
                "VALUES (gen_random_uuid(), DATE '2026-07-17', 2026, 7, 'dengesiz', "
                " 'reversed', 500.00, 0.00, $1)",
                kullanici_id,
            )
        finally:
            await conn.close()

        sonuc = _run_alembic_expecting_failure("upgrade", TB6_REVISION, database=database)
        assert sonuc.returncode != 0
        cikti = sonuc.stdout + sonuc.stderr
        assert "TB6 T2: 1 adet DENGESIZ" in cikti

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Migration DURDU: sema FIN-1'de kaldi, yarim bir gecis YOK.
            assert await _current_revision(conn) == FIN1_REVISION
            assert await _constraint_sql(conn, OLD_NAME) is not None
            assert await _constraint_sql(conn, NEW_NAME) is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
