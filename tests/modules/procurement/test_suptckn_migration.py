"""SUP-TCKN — `suppliers.tax_no` `varchar(10)` -> `varchar(11)` tur donusu.

Kullanici karari 2026-08-25: **sahis tedarikcisi kaydedilebilmeli.** Sahis
sirketi vergi kimligi olarak 11 haneli TCKN kullanir; onceki 10'luk sinir onu
`422` ile reddediyordu.

## Bu dosya NICIN ayri bir tur donusu testi

`test_procurement_migration.py::test_supplier_columns_match_spec` yalnizca
**MODEL METADATA'sina** bakar (`Supplier.__table__.columns`). O iddia,
migration HIC YAZILMASAYDI BILE model satirini `String(11)` yapmak yesile
cevirirdi — yani DDL hakkinda **hicbir sey soylemez**. (`ARCHITECTURE` degil,
olculmus bir sinif: "iki katman birbirini maskeler" kanonunun sema/DDL hali.)
Buradaki iddialar `information_schema`dan ve GERCEK bir `INSERT`ten okunur.

Ayrica o dosyanin tur donusu testi yalnizca **SA revizyonuna kadar**
(`f3a4b5c6d7e8`) yukselir; SUP-TCKN ondan 20+ revizyon SONRADIR ve o turda hic
kosmaz.

## DONDURULAN KARARLAR

1. Kolon DB'de gercekten 11 genisliktedir ve 11 haneli deger KESILMEDEN iner.
2. 10 haneli VKN'ler AYNEN gecerlidir — genisletme regresyon degildir.
3. 🔴 **Downgrade VERI KAYBI URETMEZ:** 11 haneli bir satir varken daraltma
   ATLANIR (kolon 11'de kalir, satir korunur) ve migration BASARIYLA biter.
   Bu korkulugun kendisi burada kanitlanir — yoksa `if tasan:` dali hicbir
   testte kosmazdi.
4. Temiz (11 hane tasimayan) bir veritabaninda downgrade NORMAL daraltir ve
   `upgrade -> downgrade -> upgrade` dongusu kapanir (CI `alembic-cycle`).
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
# `python -m alembic`: yerelde `.venv/bin/python`, CI'da sistem Python'u
# (`test_procurement_migration.py` deseni — sabit `.venv/bin/alembic` CI'da YOK).
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara ACIKCA cikilir; `head`/`-1` KULLANILMAZ (WORKFLOW §4).
PARENT_REVISION = "d9e0f1a2b3c4"  # SA-KILIT siparis/talep tekilligi
SUPTCKN_REVISION = "a5b6c7d8e9f0"

TABLE = "suppliers"
COLUMN = "tax_no"

pytestmark = pytest.mark.asyncio


def _asyncpg_dsn(database: str) -> str:
    """🔴 YALNIZ `test_database_url` — `database_url`a DUSULMEZ.

    `.env`de `DATABASE_URL` UZAK RAILWAY'i gosterir. Bir `or settings.database_url`
    yedegi, `TEST_DATABASE_URL` unutuldugu anda bu dosyanin `CREATE DATABASE` /
    `DROP DATABASE ... WITH (FORCE)` cagrilarini CANLIYA yoneltirdi.
    `test_procurement_migration._asyncpg_dsn` de tam olarak bu yuzden yedeksizdir.
    """
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _run_alembic(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    """`test_procurement_migration._run_alembic` ile BIREBIR ayni desen."""
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    sonuc = subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if sonuc.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} basarisiz:\n{sonuc.stdout}\n{sonuc.stderr}")
    return sonuc


async def _create_scratch_database() -> str:
    database = f"suptckn_{uuid.uuid4().hex[:8]}"
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


async def _kolon_genisligi(conn: asyncpg.Connection) -> int | None:
    """Gercek DDL genisligi — model metadata'si DEGIL."""
    return await conn.fetchval(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2",
        TABLE,
        COLUMN,
    )


async def _tedarikci_ekle(conn: asyncpg.Connection, tax_no: str) -> uuid.UUID:
    supplier_id = uuid.uuid4()
    await conn.execute(
        f"INSERT INTO {TABLE} (id, name, {COLUMN}, payment_terms, is_active) "
        "VALUES ($1, $2, $3, 'days_30', true)",
        supplier_id,
        f"SUP-TCKN {tax_no}",
        tax_no,
    )
    return supplier_id


async def test_upgrade_kolonu_11_e_genisletir_ve_11_hane_KESILMEDEN_iner():
    """DDL 11'dir ve 11 haneli TCKN birebir geri okunur.

    `INSERT` iddiasi SARTTIR: kolon 10'da kalsaydi `information_schema`
    iddiasi zaten kirmizi olurdu, ama 11 haneli degerin BUDANMADAN indigini
    yalnizca gercek bir yazma-okuma kanitlar.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # TABAN: genisletmeden ONCE 10 — testin olctugu farkin gercek
            # oldugunu kanitlar (yoksa "zaten 11'di" ihtimali elenmez).
            assert await _kolon_genisligi(conn) == 10
        finally:
            await conn.close()

        _run_alembic("upgrade", SUPTCKN_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _kolon_genisligi(conn) == 11

            tckn = "12345678901"
            assert len(tckn) == 11
            supplier_id = await _tedarikci_ekle(conn, tckn)
            okunan = await conn.fetchval(f"SELECT {COLUMN} FROM {TABLE} WHERE id = $1", supplier_id)
            assert okunan == tckn

            # 10 haneli VKN AYNEN gecerlidir — genisletme regresyon degildir.
            vkn_id = await _tedarikci_ekle(conn, "1234567890")
            assert (
                await conn.fetchval(f"SELECT {COLUMN} FROM {TABLE} WHERE id = $1", vkn_id)
            ) == "1234567890"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_temiz_veritabaninda_donus_kapanir():
    """`upgrade -> downgrade -> upgrade` (CI `alembic-cycle` isinin gordugu yol)."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", SUPTCKN_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _kolon_genisligi(conn) == 11
        finally:
            await conn.close()

        _run_alembic("downgrade", PARENT_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 11 hane tasiyan satir YOK -> daraltma NORMAL kosar.
            assert await _kolon_genisligi(conn) == 10
        finally:
            await conn.close()

        _run_alembic("upgrade", SUPTCKN_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _kolon_genisligi(conn) == 11
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_downgrade_11_haneli_TCKN_VARKEN_daraltmaz_ve_VERIYI_KORUR():
    """🔴 VERI KAYBI KAPISI — `if tasan:` dalinin TEK bekcisi.

    Bu test olmasaydi o dal hicbir turda kosmazdi. Iddia UC parcalidir ve
    ucu de gereklidir:
      1. `alembic downgrade` BASARIYLA biter (`raise` YOK — `Dockerfile`daki
         `alembic upgrade head && uvicorn` zinciri kirilsaydi uygulama HIC
         ACILMAZDI);
      2. kolon 11'de KALIR (daraltma atlandi);
      3. 11 haneli deger BUDANMADAN yerinde durur — `USING left(tax_no, 10)`
         yazilsaydi bu iddia kirmizi olurdu (sessiz, geri alinamaz veri kaybi).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", SUPTCKN_REVISION, database=database)

        tckn = "12345678901"
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            supplier_id = await _tedarikci_ekle(conn, tckn)
        finally:
            await conn.close()

        # 1. Basariyla biter (`_run_alembic` returncode 0 iddia eder).
        _run_alembic("downgrade", PARENT_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 2. Kolon daraltilmadi.
            assert await _kolon_genisligi(conn) == 11
            # 3. TCKN budanmadi.
            assert (
                await conn.fetchval(f"SELECT {COLUMN} FROM {TABLE} WHERE id = $1", supplier_id)
            ) == tckn
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
