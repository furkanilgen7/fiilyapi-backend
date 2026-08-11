"""P11 T1 — `sections.depends_on_section_id` + `section_milestones`.

Neden ayri bir tur donusu testi: bu migration YENI BIR TABLO ve bir SELF-FK
getiriyor. Tabloyu dusurmeyi unutan bir `downgrade` ikinci upgrade'i
"relation already exists" ile patlatirdi ve bu yalniz CANLIDA gorulurdu.
Ayrica FK'lerin silme davranisi burada semantiktir: oncul bolum silinince
bagimli bolum SILINMEMELI (SET NULL), bolum silinince kilometre taslari
DUSMELIDIR (CASCADE) — ikisi de DB seviyesinde dogrulanir.

Test kendi TEK KULLANIMLIK veritabanini acar ve sonunda dusurur; `.env` ve
`TEST_DATABASE_URL` veritabani ELLENMEZ. Alembic alt surecte kosturulur cunku
`alembic/env.py` kendi `asyncio.run()` dongusunu kurar ve calisan bir
pytest-asyncio dongusunun icinden cagrilamaz.
"""

import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.modules.sites.models import Section, SectionMilestone, Site

BACKEND_DIR = Path(__file__).parents[3]
# `python -m alembic`: yerelde `.venv/bin/python`, CI'da sistem Python'u. Sabit
# `.venv/bin/alembic` yolu CI'da YOKTUR ve testi yalniz orada kirardi.
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara ACIKCA cikilir; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikce bu test sessizce yanlis seyi olcerdi.
PARENT_REVISION = "c9d0e1f2a3b4"  # P9 hissedar-unite
P11_REVISION = "d0e1f2a3b4c5"

DEPENDS_COLUMN = "depends_on_section_id"
DEPENDS_INDEX = "ix_sections_depends_on_section_id"
DEPENDS_FK = "sections_depends_on_section_id_fkey"
MILESTONE_TABLE = "section_milestones"
MILESTONE_INDEX = "ix_section_milestones_section_id"

# Kalici kararlar (spec §4/§6): bu kolonlar ACILMAZ. Isim listesi tesadufi degil —
# ileride "kucuk bir ekleme" diye geri sizmalarina karsi korkuluk.
FORBIDDEN_SECTION_COLUMNS = ("progress_pct", "include_in_timeline")
FORBIDDEN_MILESTONE_COLUMNS = ("status", "is_completed", "completed_at", "progress_pct")


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


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")


async def _index_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", name
    )


async def _constraint_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"sections_p11_{uuid.uuid4().hex[:8]}"
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


async def _seed_site(conn: asyncpg.Connection, code: str) -> uuid.UUID:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
        "VALUES ($1, $2, 'P11 Tur Donusu', 'active', 0, 0)",
        project_id,
        code,
    )
    await conn.execute(
        "INSERT INTO sites (id, project_id, code, name) VALUES ($1, $2, $3, 'P11 Santiye')",
        site_id,
        project_id,
        code,
    )
    return site_id


async def _seed_section(conn: asyncpg.Connection, site_id: uuid.UUID, name: str) -> uuid.UUID:
    section_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO sections (id, site_id, name, status) VALUES ($1, $2, $3, 'planned')",
        section_id,
        site_id,
        name,
    )
    return section_id


# --------------------------------------------------------------------------- #
# Model katmani
# --------------------------------------------------------------------------- #


def test_depends_on_section_id_is_nullable_self_fk():
    """Tek oncul, YALNIZ BILGI: zorunlu olsaydi mevcut her bolum gecersiz olurdu."""
    column = Section.__table__.columns[DEPENDS_COLUMN]
    assert column.nullable
    (foreign_key,) = tuple(column.foreign_keys)
    assert foreign_key.column.table.name == "sections", "self-FK degil"
    assert foreign_key.ondelete == "SET NULL"


def test_milestone_columns_match_spec():
    columns = SectionMilestone.__table__.columns
    assert set(columns.keys()) == {"id", "section_id", "title", "milestone_date", "sort_order"}
    assert columns["title"].type.length == 200
    assert not columns["title"].nullable
    assert not columns["milestone_date"].nullable
    assert not columns["sort_order"].nullable
    (foreign_key,) = tuple(columns["section_id"].foreign_keys)
    assert foreign_key.ondelete == "CASCADE"


def test_forbidden_columns_are_absent():
    """Kalici kararlar (spec §6 S1/S2/S5): ilerleme yuzdesi · timeline'a dahil et
    kutusu · milestone durum kolonu ACILMAZ. Geri sizarlarsa burada kirilir."""
    for name in FORBIDDEN_SECTION_COLUMNS:
        assert name not in Section.__table__.columns, f"sections.{name} acilmamaliydi"
    for name in FORBIDDEN_MILESTONE_COLUMNS:
        assert name not in SectionMilestone.__table__.columns, (
            f"section_milestones.{name} acilmamaliydi — 'Tamamlandi' TUREVDIR"
        )


async def test_milestones_are_ordered_and_cascade_from_section(db_session, project_factory):
    """Iliski sirasi deterministik (sort_order) ve delete-orphan calisiyor mu?"""
    project = await project_factory("P-P11")
    site = Site(project_id=project.id, code="P-P11", name="P11 Santiye")
    db_session.add(site)
    await db_session.flush()

    section = Section(site_id=site.id, name="Kaba Insaat")
    section.milestones = [
        SectionMilestone(title="Kat 14 dosemesi", milestone_date=date(2026, 9, 1), sort_order=2),
        SectionMilestone(title="Temel bitisi", milestone_date=date(2026, 8, 1), sort_order=1),
    ]
    db_session.add(section)
    await db_session.flush()
    db_session.expunge_all()

    loaded = (
        await db_session.execute(select(Section).where(Section.id == section.id))
    ).scalar_one()
    assert [m.title for m in loaded.milestones] == ["Temel bitisi", "Kat 14 dosemesi"]

    loaded.milestones.pop(0)
    await db_session.flush()
    remaining = (await db_session.execute(select(SectionMilestone))).scalars().all()
    assert [m.title for m in remaining] == ["Kat 14 dosemesi"]


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


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
    # Head'in KIMLIGI iddia EDILMEZ: her yeni dilim head'i ileri tasir ve bu
    # testi ilgisiz yere kirardi (repo deseni — P6/status-enum testleri de
    # yalniz SAYIYI olcer). P11'in kendi revizyonu asagidaki tur donusunde
    # ACIKCA kullanilir; olculen sey burada yalniz "catallanma yok"tur.
    assert len(heads) == 1, f"tek head bekleniyordu, cikti:\n{result.stdout}"


async def test_upgrade_downgrade_upgrade_round_trip():
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", P11_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column_exists(conn, "sections", DEPENDS_COLUMN)
            assert await _index_exists(conn, DEPENDS_INDEX)
            assert await _constraint_exists(conn, DEPENDS_FK)
            assert await _table_exists(conn, MILESTONE_TABLE)
            assert await _index_exists(conn, MILESTONE_INDEX)
            assert await _current_revision(conn) == P11_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert not await _column_exists(conn, "sections", DEPENDS_COLUMN)
            assert not await _index_exists(conn, DEPENDS_INDEX)
            assert not await _constraint_exists(conn, DEPENDS_FK)
            # Kalan bir tablo IKINCI upgrade'i "already exists" ile patlatirdi.
            assert not await _table_exists(conn, MILESTONE_TABLE)
            assert await _current_revision(conn) == PARENT_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", P11_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column_exists(conn, "sections", DEPENDS_COLUMN)
            assert await _table_exists(conn, MILESTONE_TABLE)
            assert await _current_revision(conn) == P11_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_existing_sections_survive_upgrade():
    """Upgrade ONCESI yazilmis bolum korunur ve yeni kolon NULL dogar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            site_id = await _seed_site(conn, "P-P11RT")
            section_id = await _seed_section(conn, site_id, "Eski Bolum")
        finally:
            await conn.close()

        _run_alembic("upgrade", P11_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            row = await conn.fetchrow("SELECT * FROM sections WHERE id = $1", section_id)
            assert row is not None, "mevcut bolum satiri upgrade'de kayboldu"
            assert row["name"] == "Eski Bolum"
            assert row[DEPENDS_COLUMN] is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_fk_delete_semantics_set_null_and_cascade():
    """Oncul silinince bagimli bolum KALIR (SET NULL); bolum silinince kilometre
    taslari DUSER (CASCADE). Ikisi de spec §2'nin veri kaybi sinirlaridir."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", P11_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            site_id = await _seed_site(conn, "P-P11FK")
            predecessor_id = await _seed_section(conn, site_id, "Temel")
            dependent_id = await _seed_section(conn, site_id, "Kaba Insaat")
            await conn.execute(
                f"UPDATE sections SET {DEPENDS_COLUMN} = $1 WHERE id = $2",
                predecessor_id,
                dependent_id,
            )
            await conn.execute(
                "INSERT INTO section_milestones (id, section_id, title, milestone_date, sort_order)"
                " VALUES ($1, $2, 'Kat 14 dosemesi', $3, 0)",
                uuid.uuid4(),
                dependent_id,
                date(2026, 9, 1),
            )

            # 1) Oncul silinir: bagimli bolum durur, bagi kopar.
            await conn.execute("DELETE FROM sections WHERE id = $1", predecessor_id)
            row = await conn.fetchrow("SELECT * FROM sections WHERE id = $1", dependent_id)
            assert row is not None, "oncul silinince bagimli bolum de silindi (CASCADE kacagi)"
            assert row[DEPENDS_COLUMN] is None

            # 2) Bolum silinir: kilometre tasi da duser.
            await conn.execute("DELETE FROM sections WHERE id = $1", dependent_id)
            assert await conn.fetchval("SELECT count(*) FROM section_milestones") == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
