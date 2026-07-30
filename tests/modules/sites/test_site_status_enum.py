"""T1 — `site_status` enum'una `preparation` eklenmesi (izole revizyon).

Mockup satir 71 sirasi: Hazirlik · Aktif (secili) · Beklemede. Yeni enum sirasi
`preparation · active · on_hold · completed` (spec §3.1). `completed` KALIR:
`SiteCounts.completed`, `_remaining_days` ve P2 liste sekmesi ona baglidir.

Tip TAKAS edilir (`ALTER TYPE ... ADD VALUE` geri alinamaz). Downgrade'de ONCE
`preparation` satirlari `active`'e dusurulur, SONRA ters takas yapilir — sira
tersse `USING` cevrimi gecersiz degerde patlar.

Tur donusu testleri kendi TEK KULLANIMLIK veritabanini acar ve dusurur; `.env`
ve `TEST_DATABASE_URL` veritabani ELLENMEZ. Alembic alt surecte kosturulur
cunku `alembic/env.py` kendi `asyncio.run()` dongusunu kurar.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.sites.models import Site, SiteStatus

BACKEND_DIR = Path(__file__).parents[3]
# `python -m alembic`: yerelde `.venv/bin/python`, CI'da sistem Python'u. Sabit
# `.venv/bin/alembic` yolu CI'da YOKTUR ve testi yalniz orada kirardi.
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PARENT_REVISION = "a4c7f1d2e8b3"
# Bu revizyona ACIKCA cikilir; `head` KULLANILMAZ. Sonraki dilimler yeni revizyon
# ekledikce `downgrade -1` bu revizyonu degil onlari geri alirdi ve test sessizce
# yanlis seyi olcerdi.
ENUM_REVISION = "f1b2c3d4e5a6"
EXPECTED_LABELS = ("preparation", "active", "on_hold", "completed")
OLD_LABELS = ("active", "on_hold", "completed")


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


async def _enum_labels(conn: asyncpg.Connection, type_name: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = $1 ORDER BY e.enumsortorder",
        type_name,
    )
    return [row["enumlabel"] for row in rows]


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"site_status_{uuid.uuid4().hex[:8]}"
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
# 1-6: enum tanimi
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """Iki head = canlida deploy kilitlenmesi (plan §0.4). Otomatik ag."""
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


def test_site_status_enum_has_preparation():
    assert SiteStatus.preparation.value == "preparation"
    assert [s.value for s in SiteStatus] == list(EXPECTED_LABELS)


def test_site_status_completed_still_exists():
    """`completed` KALDIRILMADI — SiteCounts.completed ve P2 liste sekmesi ona bagli."""
    assert SiteStatus.completed.value == "completed"


async def test_site_can_be_created_with_preparation_status(db_session, project_factory):
    project = await project_factory("P-PREP")
    site = Site(
        project_id=project.id,
        code="SNT-PREP",
        name="Hazirlik Santiyesi",
        status=SiteStatus.preparation,
    )
    db_session.add(site)
    await db_session.flush()
    db_session.expunge_all()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.status is SiteStatus.preparation


async def test_site_status_default_is_active(db_session, project_factory):
    """Mockup 71'de `Aktif` secili — sunucu varsayilani degismez."""
    project = await project_factory("P-DEF")
    site = Site(project_id=project.id, code="SNT-DEF", name="Varsayilan")
    db_session.add(site)
    await db_session.flush()
    db_session.expunge_all()

    loaded = (await db_session.execute(select(Site).where(Site.id == site.id))).scalar_one()
    assert loaded.status is SiteStatus.active

    column = Site.__table__.columns["status"]
    assert column.server_default is not None
    assert "active" in str(column.server_default.arg)


async def test_pg_type_lists_four_labels(db_session):
    result = await db_session.execute(
        text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'site_status' ORDER BY e.enumsortorder"
        )
    )
    assert [row[0] for row in result] == list(EXPECTED_LABELS)


# --------------------------------------------------------------------------- #
# 7-8: migration tur donusu
# --------------------------------------------------------------------------- #


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", ENUM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, "site_status") == list(EXPECTED_LABELS)
            assert await _current_revision(conn) == ENUM_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            labels = await _enum_labels(conn, "site_status")
            assert labels == list(OLD_LABELS)
            assert "preparation" not in labels, "downgrade sonrasi preparation etiketi duruyor"
            # Takas tipinin artik bulunmadigi: ikinci upgrade "type already exists"
            # ile patlamasin (units diliminin dersi).
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'site_status_old')"
            )
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'site_status_new')"
            )
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", ENUM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _enum_labels(conn, "site_status") == list(EXPECTED_LABELS)
            assert await _current_revision(conn) == ENUM_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_moves_preparation_rows_to_active():
    """Spec §3.1 sira kaniti: satir KAYBOLMAZ, `active`'e tasinir."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", ENUM_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            project_id = uuid.uuid4()
            site_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
                "VALUES ($1, 'P-RT', 'Tur Donusu', 'active', 0, 0)",
                project_id,
            )
            await conn.execute(
                "INSERT INTO sites (id, project_id, code, name, status) "
                "VALUES ($1, $2, 'SNT-RT', 'Hazirlik', 'preparation')",
                site_id,
                project_id,
            )
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            status = await conn.fetchval("SELECT status::text FROM sites WHERE id = $1", site_id)
            assert status == "active", "preparation satiri downgrade'de kayboldu veya bozuldu"
            assert await conn.fetchval("SELECT count(*) FROM sites") == 1
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
