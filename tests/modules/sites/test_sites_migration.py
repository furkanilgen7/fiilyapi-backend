"""T2 — santiye formu genislemesi migration'inin upgrade → downgrade → upgrade tur donusu.

Neden ayri ve maliyetli bir test: yanlislikla `NOT NULL` konan tek bir kolon hem
TASLAK kaydini imkansiz kilar (yarim doldurulmus form kaydedilemez) hem mevcut
satirlarda deploy'u kilitler; `downgrade`de dusurulmeyen bir `CHECK` kisiti ikinci
upgrade'i patlatir. Ikisi de yalniz canlida gorulurdu.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ. Alembic alt surecte kosturulur cunku
`alembic/env.py` kendi `asyncio.run()` dongusunu kurar ve calisan bir
pytest-asyncio dongusunun icinden cagrilamaz.
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
# `python -m alembic`: yerelde `.venv/bin/python`, CI'da sistem Python'u. Sabit
# `.venv/bin/alembic` yolu CI'da YOKTUR ve testi yalniz orada kirardi.
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "f1b2c3d4e5a6"  # T1 — site_status enum takasi
# Bu revizyona ACIKCA cikilir; `head` KULLANILMAZ. Sonraki dilimler revizyon
# ekledikce `head`/`-1` bu revizyonu degil onlari olcerdi.
FORM_REVISION = "a7c9e1f3b5d2"
CHECK_CONSTRAINT = "ck_sites_safety_officer"

NEW_SITE_COLUMNS = (
    "site_manager_user_id",
    "safety_officer_user_id",
    "safety_officer_name",
    "safety_officer_is_outsourced",
    "neighborhood",
    "parcel",
    "gps_coordinates",
    "land_area_m2",
    "floor_info",
    "budget",
    "has_closed_warehouse",
    "has_open_storage",
    "has_cold_storage",
    "has_site_office",
    "has_canteen",
    "has_changing_room_wc",
    "has_dormitory",
    "has_infirmary",
    "electricity_subscription_no",
    "water_subscription_no",
    "planned_worker_count",
    "is_draft",
)

FACILITY_COLUMNS = (
    "has_closed_warehouse",
    "has_open_storage",
    "has_cold_storage",
    "has_site_office",
    "has_canteen",
    "has_changing_room_wc",
    "has_dormitory",
    "has_infirmary",
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


async def _column_exists(conn: asyncpg.Connection, table: str, column: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2)",
        table,
        column,
    )


async def _constraint_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"sites_form_{uuid.uuid4().hex[:8]}"
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


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FORM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for column in NEW_SITE_COLUMNS:
                assert await _column_exists(conn, "sites", column), (
                    f"sites.{column} upgrade sonrasi yok"
                )
            assert await _column_exists(conn, "sections", "manager_user_id")
            assert await _constraint_exists(conn, CHECK_CONSTRAINT)
            assert await _current_revision(conn) == FORM_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for column in NEW_SITE_COLUMNS:
                assert not await _column_exists(conn, "sites", column), (
                    f"sites.{column} downgrade sonrasi duruyor"
                )
            assert not await _column_exists(conn, "sections", "manager_user_id")
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", FORM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for column in NEW_SITE_COLUMNS:
                assert await _column_exists(conn, "sites", column), (
                    f"sites.{column} ikinci upgrade sonrasi yok"
                )
            assert await _constraint_exists(conn, CHECK_CONSTRAINT)
            assert await _current_revision(conn) == FORM_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_drops_check_constraint():
    """`CHECK` kisiti tabloda kalirsa ikinci upgrade "already exists" ile patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FORM_REVISION, database=database)
        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert not await _constraint_exists(conn, CHECK_CONSTRAINT)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_existing_rows_survive_upgrade():
    """Spec §11.2 kaniti: upgrade ONCESI yazilmis EKSIK ALANLI satir duruyor ve
    tesisleri `false` — hicbir kolon `NOT NULL` + varsayilansiz degil (taslak destegi)."""
    database = await _create_scratch_database()
    try:
        # T1'in revizyonuna kadar cik: `sites` var ama 22 kolon henuz yok.
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            project_id = uuid.uuid4()
            site_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
                "VALUES ($1, 'P-LEGACY', 'Eski Proje', 'active', 0, 0)",
                project_id,
            )
            # Sef, il/ilce, insaat alani, tarihler — hepsi BOS (canli veri gercegi).
            await conn.execute(
                "INSERT INTO sites (id, project_id, code, name) "
                "VALUES ($1, $2, 'A-BLOK', 'A-Blok')",
                site_id,
                project_id,
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", FORM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            row = await conn.fetchrow("SELECT * FROM sites WHERE id = $1", site_id)
            assert row is not None, "eksik alanli canli satir upgrade'de kayboldu"
            assert row["code"] == "A-BLOK", "mevcut kod degistirildi (UPDATE yazilmis)"
            for column in FACILITY_COLUMNS:
                assert row[column] is False, f"{column} varsayilani false degil"
            assert row["is_draft"] is False, "mevcut satirlar yayinda sayilir (spec §11.3/4)"
            assert row["safety_officer_is_outsourced"] is False
            assert row["neighborhood"] is None
            assert row["budget"] is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
