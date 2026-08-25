"""MK-4 T1 — `equipment` tablosuna ON detay kolonu (migration turu).

🔴 **SAHTE-YEŞİLİN 8. HÂLİ BU DOSYANIN VAR OLMA SEBEBİDİR** (SUP-TCKN ölçümü,
2026-08-25): API testleri şemayı **model metadata'sından** (`create_all`) kurar
ve migration'ı HİÇ KOŞMAZ. Bir migration'ın `add_column`u silinse bile o testler
YEŞİL kalır — çünkü kolon modelden gelir. Gerçekte canlıda kolon yoktur ve ilk
istek 500 verir.

👉 Bu yüzden buradaki iddiaların HİÇBİRİ `__table__.columns`a bakmaz:
`information_schema` okunur ve **gerçek bir `INSERT`** koşulur. İkisi de yalnız
fiilen koşmuş DDL'i görür.

Model katmanının kendi iddiaları (ad, tip, nullable) `test_mk4_detail_api.py`de
uçtan uca kapanır; burada ölçülen şey DDL'in KENDİSİDİR.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ (MK-3 deseni).
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
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ.
ONCEKI_REVISION = "a5b6c7d8e9f0"
MK4_REVISION = "b6c7d8e9f0a1"

TABLE = "equipment"

#: (kolon, beklenen `information_schema.columns.data_type`).
BEKLENEN_KOLONLAR: tuple[tuple[str, str], ...] = (
    ("engine_power_kw", "numeric"),
    ("capacity_description", "character varying"),
    ("hourmeter_hours", "numeric"),
    ("rental_contract_no", "character varying"),
    ("rental_start_date", "date"),
    ("rental_end_date", "date"),
    ("rental_min_monthly_hours", "integer"),
    ("rental_payment_terms", "character varying"),
    ("last_service_date", "date"),
    ("last_service_hourmeter", "numeric"),
)

BEKLENEN_KISITLAR = (
    "ck_equipment_engine_power_positive",
    "ck_equipment_hourmeter_non_negative",
    "ck_equipment_last_service_hourmeter_non_negative",
    "ck_equipment_rental_min_monthly_hours_non_negative",
    "ck_equipment_rental_period_order",
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


async def _column_info(conn: asyncpg.Connection, column: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2",
        TABLE,
        column,
    )


async def _constraint_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"equipment_mk4_{uuid.uuid4().hex[:8]}"
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


async def _seed_equipment(conn: asyncpg.Connection) -> uuid.UUID:
    """MK-4 ÖNCESİ şemada bir ekipman kartı (kolonlar HENÜZ YOKKEN)."""
    equipment_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment (id, name, category) VALUES ($1, 'Tower Crane TC-48', 'crane')",
        equipment_id,
    )
    return equipment_id


# --------------------------------------------------------------------------- #
# DDL — yalnız `information_schema` ve `pg_constraint`
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
    """🔴 ON kolon ve BEŞ kısıt gelir, downgrade'de HEPSİ gider, ikinci upgrade
    temiz koşar. Kolonlardan biri downgrade'de kalsaydı ikinci upgrade
    `already exists` ile patlar ve canlı deploy HİÇ AÇILMAZDI."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for kolon, tip in BEKLENEN_KOLONLAR:
                info = await _column_info(conn, kolon)
                assert info is not None, f"{kolon} kolonu information_schema'da YOK"
                assert info["data_type"] == tip, f"{kolon}: {info['data_type']}"
                assert info["is_nullable"] == "YES", (
                    f"{kolon} NOT NULL — mevcut satırların bu alanı BİLİNMİYOR"
                )
            for kisit in BEKLENEN_KISITLAR:
                assert await _constraint_exists(conn, kisit), kisit
            assert await _current_revision(conn) == MK4_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", ONCEKI_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for kolon, _ in BEKLENEN_KOLONLAR:
                assert await _column_info(conn, kolon) is None, f"{kolon} downgrade'de KALDI"
            for kisit in BEKLENEN_KISITLAR:
                assert not await _constraint_exists(conn, kisit), kisit
            # Tablo AYAKTA: bu migration yalnız kolon ekler.
            assert await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{TABLE}")
            assert await _current_revision(conn) == ONCEKI_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _column_info(conn, "hourmeter_hours") is not None
            assert await _current_revision(conn) == MK4_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# GERÇEK YAZMA — modelden değil DB'den okunan davranış
# --------------------------------------------------------------------------- #


async def test_mevcut_satir_migrationi_gecer_ve_alanlari_NULL_kalir():
    """Migration ÖNCESİ var olan kart ayakta kalır ve yeni alanları `NULL`dur.

    Uydurma bir varsayılan (0 kW / 0 saat) konsaydı `%57` çubuğu bilinmeyen bir
    hourmeter'ı bilinir sayıp YANLIŞ hesaplanırdı (K16 fail-closed).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", ONCEKI_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = await _seed_equipment(conn)
        finally:
            await conn.close()

        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            satir = await conn.fetchrow(
                "SELECT engine_power_kw, hourmeter_hours, rental_contract_no, "
                "rental_min_monthly_hours, last_service_date, last_service_hourmeter "
                f"FROM {TABLE} WHERE id = $1",
                equipment_id,
            )
            assert satir is not None, "mevcut kart migration'da KAYBOLDU"
            assert all(deger is None for deger in satir.values()), dict(satir)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_yeni_kolonlara_gercek_deger_YAZILIP_okunabilir():
    """🔴 Kolonun VAR OLDUĞUNU `information_schema` söyler; KULLANILABİLDİĞİNİ
    yalnız gerçek bir `INSERT` + `SELECT` söyler (ölçek/tip hataları burada
    çıkar: `Numeric(10, 2)` 14.286,50'yi taşımalı)."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = uuid.uuid4()
            await conn.execute(
                f"INSERT INTO {TABLE} (id, name, category, engine_power_kw, "
                "capacity_description, hourmeter_hours, rental_contract_no, "
                "rental_start_date, rental_end_date, rental_min_monthly_hours, "
                "rental_payment_terms, last_service_date, last_service_hourmeter) "
                "VALUES ($1, 'Tower Crane TC-48', 'crane', 45, '8 Ton · 60 m yükseklik', "
                "14286.50, 'LT-KRA-2026-004', '2026-03-01', '2026-12-31', 160, "
                "'Aylık — fatura üzerinden', '2026-05-18', 14000)",
                equipment_id,
            )
            satir = await conn.fetchrow(
                "SELECT engine_power_kw, capacity_description, hourmeter_hours, "
                "rental_min_monthly_hours, last_service_hourmeter "
                f"FROM {TABLE} WHERE id = $1",
                equipment_id,
            )
            assert satir["engine_power_kw"] == 45
            assert satir["capacity_description"] == "8 Ton · 60 m yükseklik"
            assert str(satir["hourmeter_hours"]) == "14286.50"
            assert satir["rental_min_monthly_hours"] == 160
            assert satir["last_service_hourmeter"] == 14000
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


@pytest.mark.parametrize(
    ("kolon", "deger"),
    [
        ("engine_power_kw", "0"),
        ("engine_power_kw", "-1"),
        ("hourmeter_hours", "-1"),
        ("last_service_hourmeter", "-1"),
        ("rental_min_monthly_hours", "-1"),
    ],
)
async def test_kisitlar_anlamsiz_degerleri_DB_duzeyinde_reddeder(kolon: str, deger: str):
    """Motor gücü AYRICA 0 olamaz (0 kW bir ölçüm değil giriş hatasıdır);
    saat/asgari alanlarda 0 GEÇERLİDİR ve ayrıca doğrulanır."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = await _seed_equipment(conn)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    f"UPDATE {TABLE} SET {kolon} = {deger} WHERE id = $1", equipment_id
                )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_sifir_saat_ve_sifir_asgari_KABUL_edilir():
    """Sıfırın yasak olduğu TEK alan motor gücüdür: sıfır saatte teslim alınmış
    yeni bir makine ve asgari saati olmayan bir sözleşme GERÇEKTİR."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = await _seed_equipment(conn)
            await conn.execute(
                f"UPDATE {TABLE} SET hourmeter_hours = 0, last_service_hourmeter = 0, "
                "rental_min_monthly_hours = 0 WHERE id = $1",
                equipment_id,
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kira_donemi_TERS_olamaz_esit_gun_kabul_edilir():
    """🔴 Kural DB'dedir, serviste değil: servise bırakılsaydı yalnız HTTP'den
    geçen yazmalar korunur, seed/SQL düzeltmesi kuralı atlardı. İki taraftan
    biri NULL iken kısıt SUSAR — bitişi henüz belli olmayan sözleşme gerçektir.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK4_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            equipment_id = await _seed_equipment(conn)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    f"UPDATE {TABLE} SET rental_start_date = '2026-12-31', "
                    "rental_end_date = '2026-03-01' WHERE id = $1",
                    equipment_id,
                )
            # Sınır: aynı gün başlayıp biten sözleşme GEÇERLİDİR.
            await conn.execute(
                f"UPDATE {TABLE} SET rental_start_date = '2026-03-01', "
                "rental_end_date = '2026-03-01' WHERE id = $1",
                equipment_id,
            )
            # Yarım girilmiş sözleşme de geçerlidir.
            await conn.execute(
                f"UPDATE {TABLE} SET rental_end_date = NULL WHERE id = $1", equipment_id
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
