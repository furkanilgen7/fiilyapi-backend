"""MK-3 T1 — kira hakedişi satırına `capacity_hours` snapshot kolonu.

Spec: `docs/superpowers/specs/2026-08-14-mk3-kapasite-snapshot-design.md` K1/K2/K4.

NEDEN AYRI BİR MIGRATION TESTİ: bu kolonun tek işi bir PARA girdisinin geriye
dönük oynamasını engellemektir. İki ayrı kaza yalnız canlıda görülürdü:

* kolon `NOT NULL` yapılsaydı → mevcut satırı olan bir kurulumda migration
  patlar (varsayılan uydurmak da K2'nin yasakladığı şeydir),
* kolon eklenip mevcut satırlar DOLDURULMASAYDI (K4) → bugüne kadar doğru
  hesaplanan onaylanmış bir aylık kira faturası, deploy anında `null` tutara
  düşerdi. Sessiz, geriye dönük ve tam olarak kapatmaya çalıştığımız sınıf.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (MK-1/MK-2 deseni).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.equipment.models import EquipmentRentalInvoiceLine

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
MK2_REVISION = "f9a0b1c2d3e4"
MK3_REVISION = "a0b1c2d3e4f5"

LINE_TABLE = "equipment_rental_invoice_lines"
CAPACITY_COLUMN = "capacity_hours"
CAPACITY_CHECK = "ck_equipment_rental_invoice_lines_capacity_hours_non_negative"

# K4 doldurma senaryosunda kullanılan kapasite: 200 (ekipman sunucu varsayılanı)
# DEĞİL — varsayılanla çakışsaydı test "doldurdu" ile "varsayılan geldi"yi
# ayırt edemezdi.
SEED_CAPACITY_HOURS = 173


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


async def _column_info(conn: asyncpg.Connection, table: str, column: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2",
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
    database = f"equipment_mk3_{uuid.uuid4().hex[:8]}"
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


async def _seed_line(
    conn: asyncpg.Connection, *, capacity_hours: int = SEED_CAPACITY_HOURS
) -> tuple[uuid.UUID, uuid.UUID]:
    """MK-2 şemasında (kolon HENÜZ YOKKEN) bir kira satırı kurar.

    K4'ün ölçtüğü tam olarak budur: migration ÖNCESİ var olan satır.
    """
    supplier_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO suppliers (id, name, payment_terms) VALUES ($1, 'Kiralama A.Ş.', 'days_30')",
        supplier_id,
    )
    equipment_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment (id, name, category, monthly_capacity_hours) "
        "VALUES ($1, 'Kule Vinç KV-01', 'crane', $2)",
        equipment_id,
        capacity_hours,
    )
    invoice_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment_rental_invoices "
        "(id, supplier_id, invoice_no, period_year, period_month, rate_period) "
        "VALUES ($1, $2, 'FT-2026-001', 2026, 8, 'monthly')",
        invoice_id,
        supplier_id,
    )
    line_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment_rental_invoice_lines "
        "(id, invoice_id, equipment_id, line_kind, worked_hours, rate_amount) "
        "VALUES ($1, $2, $3, 'rented', 186, 120000)",
        line_id,
        invoice_id,
        equipment_id,
    )
    return line_id, equipment_id


# --------------------------------------------------------------------------- #
# Model katmani
# --------------------------------------------------------------------------- #


def test_line_has_nullable_capacity_hours_snapshot():
    """🔴 K1 — snapshot'lanan şey GİRDİdir (kapasite), TÜREV değil.

    K2 — nullable'dır ve fail-closed'dur: değer yoksa saatlik bedel HESAPLANAMAZ
    (`our_amount` `null`). `NOT NULL` + uydurma varsayılan, bilinmeyen bir
    paydayı bilinir gibi göstererek yanlış bir tutar basardı.
    """
    columns = EquipmentRentalInvoiceLine.__table__.columns
    assert CAPACITY_COLUMN in columns
    column = columns[CAPACITY_COLUMN]
    assert column.nullable, "K2: kapasitesi bilinmeyen satır `null` tutara düşer, 0'a DEĞİL"
    assert column.type.python_type is int


def test_hourly_rate_is_not_columnized():
    """🔴 K1 — çözülmüş saatlik bedel KOLONLAŞTIRILMAZ (MK-2 K4 "tek formül").

    Kolonlaşsaydı aynı para için iki gerçek kaynak doğar, biri güncellenmediğinde
    ödenecek tutar sessizce ayrışırdı.
    """
    line_columns = set(EquipmentRentalInvoiceLine.__table__.columns.keys())
    for yasak in ("hourly_rate", "resolved_hourly_rate", "our_amount"):
        assert yasak not in line_columns, yasak


def test_capacity_hours_has_non_negative_check():
    """Negatif kapasite hiçbir okumada anlamlı değildir — `rate_amount` deseni."""
    names = {
        c.name
        for c in EquipmentRentalInvoiceLine.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert CAPACITY_CHECK in names


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar)."""
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
    """Kolon + check gelir, downgrade'de İKİSİ DE gider, ikinci upgrade temiz koşar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            info = await _column_info(conn, LINE_TABLE, CAPACITY_COLUMN)
            assert info is not None, f"{CAPACITY_COLUMN} kolonu yok"
            assert info["data_type"] == "integer"
            assert info["is_nullable"] == "YES"
            assert await _constraint_exists(conn, CAPACITY_CHECK)
            assert await _current_revision(conn) == MK3_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", MK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column_info(conn, LINE_TABLE, CAPACITY_COLUMN) is None, (
                "kolon downgrade'de kalmış — ikinci upgrade 'already exists' ile patlar"
            )
            assert not await _constraint_exists(conn, CAPACITY_CHECK)
            # Tablo AYAKTA: bu migration yalnız bir kolon ekler.
            assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{LINE_TABLE}")
            assert await _current_revision(conn) == MK2_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MK3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column_info(conn, LINE_TABLE, CAPACITY_COLUMN) is not None
            assert await _current_revision(conn) == MK3_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_existing_lines_are_backfilled_from_equipment():
    """🔴 K4 — mevcut satırlar `equipment`ten DOLDURULUR.

    `NULL` bırakılsaydı, bugüne kadar doğru hesaplanan ONAYLANMIŞ bir aylık kira
    faturası deploy anında `null` tutara düşerdi (K2 fail-closed doğru davranıştır
    ama burada bilgi KAYIP değildir — ekipman kartında durmaktadır).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            line_id, equipment_id = await _seed_line(conn)
        finally:
            await conn.close()

        _run_alembic("upgrade", MK3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            filled = await conn.fetchval(
                f"SELECT {CAPACITY_COLUMN} FROM {LINE_TABLE} WHERE id = $1", line_id
            )
            expected = await conn.fetchval(
                "SELECT monthly_capacity_hours FROM equipment WHERE id = $1", equipment_id
            )
            assert expected == SEED_CAPACITY_HOURS
            assert filled == expected, (
                "K4: migration mevcut satırı ekipmandan doldurmalı — NULL kalırsa "
                "onaylanmış faturanın tutarı deploy anında `null` olurdu"
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_capacity_hours_rejects_negative_values():
    """DB seviyesinde: negatif kapasite yazılamaz; NULL serbesttir (K2)."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            line_id, _ = await _seed_line(conn)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    f"UPDATE {LINE_TABLE} SET {CAPACITY_COLUMN} = -1 WHERE id = $1", line_id
                )
            # NULL kabul edilir: "bilinmiyor" yazılabilir bir durumdur.
            await conn.execute(
                f"UPDATE {LINE_TABLE} SET {CAPACITY_COLUMN} = NULL WHERE id = $1", line_id
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
