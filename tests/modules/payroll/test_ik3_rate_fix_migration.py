"""IK3-RATE-FIX İŞ 1 — `f6a7b8c9d0e1` migration'ı: gerçek zincir üzerinde ölçüm.

`test_ik3_rate_fix_iki_katman.py`nin (A) sembolik bileşkesinin GERÇEK
PostgreSQL davranışıyla örtüştüğünü kanıtlayan (B) katmanı. Kendi TEK
KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (İK-3/SA/P11 deseni).

🔴 **REVİZYONLARA AÇIKÇA ÇIKILIR — `head` / `-1` KULLANILMAZ.** Sonraki
dilimler revizyon ekledikçe `head` sessizce başka bir şeyi ölçerdi.

🔴 **BU TEST "benim migration'ım head'dir" DİYE KİMLİK İDDİA ETMEZ.** MU-SEED
turunda FRM-1'in testi tam bu yüzden kırılmıştı. Korunması gereken değişmez
ikisidir: **alembic tek head kalır** ve **bu revizyon zincirden düşmez**
(`f6a7b8c9d0e1`in ATASI `e5f6a7b8c9d0`dır). Bir sonraki dilim üste yeni bir
revizyon koyduğunda bu dosya kırılmamalıdır.
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
from app.modules.payroll.rate_seed_data import PAYROLL_RATES_2026, RATE_COLUMNS

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# İK-3 çekirdeği: 2026 tohumunu basar, `short_work_pct = 1`.
IK3_REVISION = "c5d6e7f8a9b0"
# IK3-RATE-FIX: KK-5 düzeltmesi, `short_work_pct` 1 → 0.
RATE_FIX_REVISION = "f6a7b8c9d0e1"
# Düzeltmenin ATASI. Kimlik değil ATALIK iddia edilir (modül docstring'i).
RATE_FIX_PARENT = "e5f6a7b8c9d0"

SEEDED_SHORT_WORK = Decimal("1.000")
CORRECTED_SHORT_WORK = Decimal("0.000")


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


def _run_alembic_expect_failure(*args: str, database: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": _asyncpg_dsn(database)}
    return subprocess.run(
        [*ALEMBIC_CMD, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


async def _create_scratch_database() -> str:
    database = f"ik3ratefix_{uuid.uuid4().hex[:8]}"
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


async def _rates(conn: asyncpg.Connection) -> dict[str, asyncpg.Record]:
    kolonlar = ", ".join(RATE_COLUMNS)
    rows = await conn.fetch(
        f"SELECT personnel_source::text AS src, {kolonlar}, is_active "
        "FROM payroll_rates WHERE year = 2026"
    )
    return {row["src"]: row for row in rows}


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


# --------------------------------------------------------------------------- #
# Zincir kimligi — ATALIK, kimlik DEGIL
# --------------------------------------------------------------------------- #


def test_alembic_tek_head():
    """İki head = `alembic upgrade head` patlar = canlıda uygulama HİÇ açılmaz."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


def test_rate_fix_zincirden_dusmez():
    """🔴 ATALIK iddiası — "head'im" DEĞİL.

    `f6a7b8c9d0e1`in atası `e5f6a7b8c9d0` olarak kalmalı ve revizyon
    `alembic history` çıktısında görünmelidir. Bir sonraki dilim üste yeni bir
    revizyon eklediğinde bu test KIRILMAZ; yalnızca bu düzeltme zincirden
    düşerse (ya da yeniden ebeveynlenirse) kırılır.
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "history"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert f"{RATE_FIX_PARENT} -> {RATE_FIX_REVISION}" in result.stdout, (
        f"{RATE_FIX_REVISION} zincirde {RATE_FIX_PARENT} üzerinde değil:\n{result.stdout}"
    )


# --------------------------------------------------------------------------- #
# Duzeltmenin kendisi
# --------------------------------------------------------------------------- #


async def test_kk5_duzeltmesi_uygulanir_ve_zincir_sabitle_ortusur():
    """🔴 (B) Gerçek zincirin sonundaki DB durumu = `PAYROLL_RATES_2026`.

    Önce `c5d6e7f8a9b0`da tohumun `1` bastığı DOĞRULANIR (yoksa test neyi
    düzelttiğini bilmeden yeşil yanardı), sonra düzeltme koşturulur.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", RATE_FIX_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            once = await _rates(conn)
            # Ara durum: tohum gercekten 1 basiyor (duzeltmenin hedefi var).
            assert once["company"]["short_work_pct"] == SEEDED_SHORT_WORK
            assert once["subcontractor"]["short_work_pct"] == SEEDED_SHORT_WORK
        finally:
            await conn.close()

        _run_alembic("upgrade", RATE_FIX_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == RATE_FIX_REVISION
            sonra = await _rates(conn)
            # 🔴 Bos tablo SESSIZCE gecemez: sayi ACIKCA iddia edilir.
            assert await conn.fetchval("SELECT count(*) FROM payroll_rates") == 4
            assert set(sonra) == set(PAYROLL_RATES_2026), sorted(sonra)
            for source, beklenen in PAYROLL_RATES_2026.items():
                row = sonra[source]
                assert row["is_active"] is True, source
                for alan in RATE_COLUMNS:
                    assert row[alan] == beklenen[alan], (
                        f"{source}.{alan}: DB {row[alan]} != sabit {beklenen[alan]}"
                    )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kullanicinin_kendi_degeri_EZILMEZ():
    """🔴 `= 1` koşulunun bekçisi — mutasyon (a).

    Kullanıcı `PUT /payroll/rates/2026/company` ile kendi değerini (örn. 3)
    girmişse düzeltme ona DOKUNMAZ. Koşul kaldırılırsa bu test kırmızı olur.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", RATE_FIX_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "UPDATE payroll_rates SET short_work_pct = 3 "
                "WHERE year = 2026 AND personnel_source = 'company'"
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", RATE_FIX_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            sonra = await _rates(conn)
            assert sonra["company"]["short_work_pct"] == Decimal("3.000"), (
                "kullanıcının elle girdiği oran EZİLDİ — `= 1` koşulu kayıp"
            )
            # Dokunulmamis tohum satiri yine de duzeltilir.
            assert sonra["subcontractor"]["short_work_pct"] == CORRECTED_SHORT_WORK
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kilitli_donem_kapisi_fail_loud():
    """🔴 Kilitli dönem kapısı — mutasyon (b).

    O yılda `approved`/`paid` dönem varsa migration DURUR ve şemayı BOZMADAN
    bırakır. Sessizce atlamak yasaktır: `service.upsert_rate` aynı durumda 409
    verir, migration o korkuluğu arkadan dolanmaz.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", RATE_FIX_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO payroll_periods (id, year, month, status) "
                "VALUES ($1, 2026, 3, 'approved')",
                uuid.uuid4(),
            )
        finally:
            await conn.close()

        result = _run_alembic_expect_failure("upgrade", RATE_FIX_REVISION, database=database)
        assert result.returncode != 0, (
            "kilitli dönem varken migration GEÇTİ — servis korkuluğu arkadan dolanıldı:\n"
            f"{result.stdout}"
        )
        ciktilar = result.stdout + result.stderr
        assert "IK3-RATE-FIX durduruldu" in ciktilar, ciktilar
        assert "2026-03 (approved)" in ciktilar, ciktilar

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # 🔴 Sema BOZULMADAN kaldi: revizyon DUZELTMEYE ILERLEMEDI,
            #    atasinda durdu ve oran degismedi.
            #    (`transaction_per_migration=True` her migration'i AYRI commit
            #    eder; bu yuzden beklenen deger atadir, kurulum revizyonu
            #    degil — ikisi ayni olmasaydi bu satir yanlis seyi olcerdi.)
            assert await _current_revision(conn) == RATE_FIX_PARENT
            assert await _current_revision(conn) != RATE_FIX_REVISION
            assert (await _rates(conn))["company"]["short_work_pct"] == SEEDED_SHORT_WORK
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kilitsiz_donem_kapiyi_ACMAZ():
    """`draft`/`pending_approval` dönem düzeltmeyi ENGELLEMEZ.

    Kapı YILA değil KİLİDE bakar; aksi hâlde herhangi bir taslak dönem
    KK-5'in uygulanmasını süresiz bloke ederdi.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", RATE_FIX_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO payroll_periods (id, year, month, status) "
                "VALUES ($1, 2026, 4, 'pending_approval')",
                uuid.uuid4(),
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", RATE_FIX_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (await _rates(conn))["company"]["short_work_pct"] == CORRECTED_SHORT_WORK
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_upgrade_downgrade_upgrade_turu():
    """🔴 DEPLOY = OTOMATİK MİGRATION: tur dönüşü yerelde kanıtlanır.

    Downgrade KASITLI NO-OP'tur (oranı `1`e geri yazmak, kullanıcının KK-5 ile
    reddettiği yanlış değeri geri getirmek olurdu) — bu test tam olarak bunu
    iddia eder. İkinci `upgrade` de PATLAMAZ: `= 1` koşulu ikinci koşuda
    hiçbir satır bulmaz (idempotent).
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", RATE_FIX_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (await _rates(conn))["company"]["short_work_pct"] == CORRECTED_SHORT_WORK
        finally:
            await conn.close()

        _run_alembic("downgrade", RATE_FIX_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == RATE_FIX_PARENT
            # 🔴 NO-OP: dogru deger KORUNUR, yanlis deger GERI GETIRILMEZ.
            assert (await _rates(conn))["company"]["short_work_pct"] == CORRECTED_SHORT_WORK
        finally:
            await conn.close()

        _run_alembic("upgrade", RATE_FIX_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == RATE_FIX_REVISION
            sonra = await _rates(conn)
            assert await conn.fetchval("SELECT count(*) FROM payroll_rates") == 4
            for source, beklenen in PAYROLL_RATES_2026.items():
                for alan in RATE_COLUMNS:
                    assert sonra[source][alan] == beklenen[alan], f"{source}.{alan}"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
