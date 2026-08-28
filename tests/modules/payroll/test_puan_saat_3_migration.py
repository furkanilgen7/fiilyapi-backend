"""PUAN-SAAT-3 — `ca19424d7118` migration'i GERCEK PostgreSQL'de.

`test_ik3_gv_migration.py` deseni birebir: kendi TEK KULLANIMLIK veritabanini
acar ve sonunda dusurur; `.env` ve `TEST_DATABASE_URL` veritabani ELLENMEZ.
Alembic alt surecte kosturulur cunku `alembic/env.py` kendi `asyncio.run()`
dongusunu kurar.

🔴 **REVIZYONLARA ACIKCA CIKILIR — `head` / `-1` KULLANILMAZ.** Sonraki dilimler
revizyon ekledikce `head` sessizce baska bir seyi olcerdi.

🔴 **BU TEST "benim migration'im head'dir" DIYE KIMLIK IDDIA ETMEZ** (MU-SEED /
FRM-1 dersi). Korunan iki degismez: **alembic tek head kalir** ve **bu revizyon
zincirden dusmez** (atasi `d3f8a1c60b27`).

## Olculen asil sey: GECMIS BORDRO DEGISMEZ

`integer -> numeric(6,1)` bir GENISLEMEDIR. Test bunu SEMBOLIK degil GERCEK
veriyle kanitlar: ata revizyonda `days = 22` yazilir, gec kosturulur, deger
`22` olarak (ve `numeric` tipinde) YERINDE bulunur.
"""

import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

PS3_REVISION = "ca19424d7118"
#: Atasi PUAN-SAAT-1'dir. Kimlik degil ATALIK iddia edilir.
PS3_PARENT = "d3f8a1c60b27"

SEED_YEAR = 2026
SEED_MULTIPLIER = Decimal("1.500")


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


async def _create_scratch_database() -> str:
    database = f"ps3_{uuid.uuid4().hex[:8]}"
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


async def _days_type(conn: asyncpg.Connection) -> str:
    return await conn.fetchval(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'payroll_lines' AND column_name = 'days'"
    )


async def _bir_satir_yaz(conn: asyncpg.Connection) -> uuid.UUID:
    """Ata revizyonda `days = 22` tasiyan GERCEK bir bordro satiri."""
    period_id, personnel_id, line_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO payroll_periods (id, year, month) VALUES ($1, $2, $3)",
        period_id,
        SEED_YEAR,
        7,
    )
    await conn.execute(
        "INSERT INTO personnel (id, full_name, source) VALUES ($1, $2, 'company')",
        personnel_id,
        "Gecmis Bordro",
    )
    await conn.execute(
        "INSERT INTO payroll_lines "
        "(id, payroll_period_id, personnel_id, personnel_source, days, gross_amount, status) "
        "VALUES ($1, $2, $3, 'company', 22, 39600.00, 'paid')",
        line_id,
        period_id,
        personnel_id,
    )
    return line_id


# --------------------------------------------------------------------------- #
# Zincir kimligi — ATALIK, kimlik DEGIL
# --------------------------------------------------------------------------- #


def test_alembic_tek_head():
    """Iki head = `alembic upgrade head` patlar = canlida uygulama HIC acilmaz."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, cikti:\n{result.stdout}"


def test_puan_saat_3_zincirden_dusmez():
    """🔴 ATALIK iddiasi — "head'im" DEGIL."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "history"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert f"{PS3_PARENT} -> {PS3_REVISION}" in result.stdout, (
        f"{PS3_REVISION} zincirde {PS3_PARENT} uzerinde degil:\n{result.stdout}"
    )


# --------------------------------------------------------------------------- #
# Gercek zincir
# --------------------------------------------------------------------------- #


async def test_gecmis_bordro_satiri_DEGISMEZ_ve_FM_carpani_tohumlanir():
    """🔴 (B) Gercek zincir: tip genisler, VERI yerinde kalir, tohum duser.

    Once ATA revizyonda `days` kolonunun `integer` oldugu ve
    `payroll_overtime_rates` tablosunun HIC OLMADIGI dogrulanir — yoksa test
    neyi degistirdigini bilmeden yesil yanardi.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PS3_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _days_type(conn) == "integer"
            assert await conn.fetchval("SELECT to_regclass('payroll_overtime_rates')") is None
            line_id = await _bir_satir_yaz(conn)
        finally:
            await conn.close()

        _run_alembic("upgrade", PS3_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == PS3_REVISION
            assert await _days_type(conn) == "numeric"

            # 🔴 GECMIS BORDRO DEGISMEDI: ayni satir, ayni gun, ayni brut.
            row = await conn.fetchrow(
                "SELECT days, gross_amount, status::text AS status "
                "FROM payroll_lines WHERE id = $1",
                line_id,
            )
            assert row["days"] == Decimal("22")
            assert row["gross_amount"] == Decimal("39600.00")
            assert row["status"] == "paid"

            # Tohum: yilin FM carpani.
            carpanlar = await conn.fetch(
                "SELECT year, multiplier, is_active FROM payroll_overtime_rates"
            )
            assert len(carpanlar) == 1, "tohum TEK satir olmali (bos tablo sessizce gecemez)"
            assert carpanlar[0]["year"] == SEED_YEAR
            assert carpanlar[0]["multiplier"] == SEED_MULTIPLIER
            assert carpanlar[0]["is_active"] is True

            # CHECK: carpan 1'in ALTINA inemez (zam, indirim degil).
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await conn.execute(
                    "INSERT INTO payroll_overtime_rates (id, year, multiplier) "
                    "VALUES ($1, 2099, 0.900)",
                    uuid.uuid4(),
                )
            # UQ: yil basina TEK satir.
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO payroll_overtime_rates (id, year, multiplier) "
                    "VALUES ($1, $2, 1.250)",
                    uuid.uuid4(),
                    SEED_YEAR,
                )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
