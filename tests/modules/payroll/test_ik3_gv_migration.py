"""IK3-GV — (B) GERÇEK ZİNCİR: `b3c4d5e6f7a8` migration'ı, canlı PostgreSQL'de.

`test_ik3_gv_iki_katman.py`nin (A) sembolik eşitliğinin gerçek DB davranışıyla
örtüştüğünü kanıtlar. Kendi TEK KULLANIMLIK veritabanını açar ve sonunda
düşürür; `.env` ve `TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte
koşturulur çünkü `alembic/env.py` kendi `asyncio.run()` döngüsünü kurar
(İK-3/SA/P11/IK3-RATE-FIX deseni).

🔴 **REVİZYONLARA AÇIKÇA ÇIKILIR — `head` / `-1` KULLANILMAZ.** Sonraki
dilimler revizyon ekledikçe `head` sessizce başka bir şeyi ölçerdi.

🔴 **BU TEST "benim migration'ım head'dir" DİYE KİMLİK İDDİA ETMEZ.** MU-SEED
turunda FRM-1'in testi tam bu yüzden kırılmıştı. Korunan iki değişmez:
**alembic tek head kalır** ve **bu revizyon zincirden düşmez** (atası
`f6a7b8c9d0e1`dir). Bir sonraki dilim üste yeni bir revizyon koyduğunda bu
dosya KIRILMAMALIDIR.
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
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
    TAX_BRACKETS_2026_WAGE,
)

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

GV_REVISION = "b3c4d5e6f7a8"
#: Düzeltmenin ATASI. Kimlik değil ATALIK iddia edilir (modül docstring'i).
GV_PARENT = "f6a7b8c9d0e1"

#: 🔴 KASTEN LİTERAL, migration'dan import EDİLMEZ. Bu imza operatörün Railway
#: deploy günlüğünde gözle/grep ile aradığı SÖZLEŞMEDİR; import edilseydi
#: yeniden adlandırma testi yeşil bırakır ve sözleşme sessizce koparadı.
SKIP_LOG_PREFIX = "IK3-GV ATLANDI"

SEEDED_INCOME_TAX_PCT = Decimal("10.000")
BRACKET_REGIME_SOURCES = ("company", "subcontractor")


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
    database = f"ik3gv_{uuid.uuid4().hex[:8]}"
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


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _income_tax_pcts(conn: asyncpg.Connection) -> dict[str, Decimal | None]:
    rows = await conn.fetch(
        "SELECT personnel_source::text AS src, income_tax_pct FROM payroll_rates WHERE year = 2026"
    )
    return {row["src"]: row["income_tax_pct"] for row in rows}


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


def test_ik3gv_zincirden_dusmez():
    """🔴 ATALIK iddiası — "head'im" DEĞİL (MU-SEED/FRM-1 dersi)."""
    result = subprocess.run(
        [*ALEMBIC_CMD, "history"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert f"{GV_PARENT} -> {GV_REVISION}" in result.stdout, (
        f"{GV_REVISION} zincirde {GV_PARENT} üzerinde değil:\n{result.stdout}"
    )


# --------------------------------------------------------------------------- #
# Tohum + rejim gecisi
# --------------------------------------------------------------------------- #


async def test_tarife_TOHUMU_ve_REJIM_GECISI_uygulanir():
    """🔴 (B) Gerçek zincirin sonundaki DB durumu = uygulama katmanının sabiti.

    Önce ATA revizyonda `income_tax_pct = 10` olduğu DOĞRULANIR (yoksa test
    neyi düzelttiğini bilmeden yeşil yanardı), sonra IK3-GV koşturulur.

    🔴 Satır sayıları AÇIKÇA iddia edilir: boş tablo SESSİZCE geçemez.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            once = await _income_tax_pcts(conn)
            for source in BRACKET_REGIME_SOURCES:
                assert once[source] == SEEDED_INCOME_TAX_PCT, source
        finally:
            await conn.close()

        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == GV_REVISION

            # --- tarife tohumu ---
            assert await conn.fetchval("SELECT count(*) FROM payroll_tax_brackets") == 5
            dilimler = await conn.fetch(
                "SELECT ordinal, upper_bound, rate_pct, income_kind::text AS kind, is_active "
                "FROM payroll_tax_brackets WHERE year = 2026 ORDER BY ordinal"
            )
            for row, (ordinal, upper_bound, rate_pct) in zip(
                dilimler, TAX_BRACKETS_2026_WAGE, strict=True
            ):
                assert row["ordinal"] == ordinal
                assert row["upper_bound"] == upper_bound
                assert row["rate_pct"] == rate_pct
                assert row["kind"] == "wage"
                assert row["is_active"] is True

            # --- asgari ücret ---
            assert await conn.fetchval("SELECT count(*) FROM payroll_minimum_wages") == 1
            assert (
                await conn.fetchval(
                    "SELECT gross_amount FROM payroll_minimum_wages WHERE year = 2026"
                )
                == MINIMUM_WAGE_GROSS_2026
            )

            # --- K3 rejim geçişi ---
            sonra = await _income_tax_pcts(conn)
            for source in BRACKET_REGIME_SOURCES:
                assert sonra[source] is None, f"{source} dilimli motora GEÇMEDİ"
            # 🔴 Düz oran rejimindekiler DOKUNULMADAN kalır.
            assert sonra["freelance"] == Decimal("20.000")
            assert sonra["intern"] == Decimal("0.000")
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_vergi_snapshot_kolonlari_NULLABLE_ve_SUNUCU_VARSAYILANSIZ():
    """🔴 S4 fail-closed: var olan satırlarda üç vergi kolonu `NULL` KALIR.

    Sunucu varsayılanı `0` olsaydı "vergisi 0" ile "IK3-GV öncesinde
    hesaplandı" AYIRT EDİLEMEZ olurdu ve `sgk.py` ikisini aynı sayarak eksik
    bir vergi toplamını doğru gibi basardı.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            rows = await conn.fetch(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'payroll_lines' AND column_name = ANY($1)",
                ["tax_base_amount", "cumulative_tax_base", "income_tax_amount"],
            )
            assert len(rows) == 3
            for row in rows:
                assert row["is_nullable"] == "YES", row["column_name"]
                assert row["column_default"] is None, row["column_name"]

            # K7 devir kolonu: varsayılan 0 VARDIR (davranış değişmez) ve yıl
            # niteleyicisi nullable'dır (fail-closed: yıl yoksa devir yok).
            devir = await conn.fetch(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'personnel' AND column_name = ANY($1)",
                ["opening_tax_base", "opening_tax_base_year"],
            )
            alanlar = {row["column_name"]: row for row in devir}
            assert alanlar["opening_tax_base"]["is_nullable"] == "NO"
            assert alanlar["opening_tax_base"]["column_default"] is not None
            assert alanlar["opening_tax_base_year"]["is_nullable"] == "YES"
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kullanicinin_kendi_orani_EZILMEZ():
    """🔴 `= 10` koşulunun bekçisi — mutasyon.

    Kullanıcı `PUT /payroll/rates/2026/company` ile kendi oranını (örn. 12)
    girmişse rejim geçişi ona DOKUNMAZ: onu `NULL`a çekmek, kullanıcının
    AÇIKÇA seçtiği düz oran rejimini sessizce dilimliye çevirirdi. Koşul
    kaldırılırsa bu test kırmızı olur.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "UPDATE payroll_rates SET income_tax_pct = 12 "
                "WHERE year = 2026 AND personnel_source = 'company'"
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            sonra = await _income_tax_pcts(conn)
            assert sonra["company"] == Decimal("12.000"), (
                "kullanıcının elle girdiği oran EZİLDİ — `= 10` koşulu kayıp"
            )
            assert sonra["subcontractor"] is None  # dokunulmamış tohum yine geçti
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def _kilitli_yil_kur(database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(database))
    try:
        await conn.execute(
            "INSERT INTO payroll_periods (id, year, month, status) "
            "VALUES ($1, 2026, 3, 'approved')",
            uuid.uuid4(),
        )
    finally:
        await conn.close()


async def test_kilitli_donemde_REJIM_GECISI_ATLANIR_ama_SEMA_UYGULANIR():
    """🔴 YÖNETİM KARARI — kilitli yılda VERİ düzeltmesi atlanır, migration DURMAZ.

    Migration'ın durması `alembic upgrade head`i patlatır ve **uygulama hiç
    açılmaz** — bir korkuluk, koruduğu şeyden büyük hasar üretemez
    (IK3-RATE-FIX kanonu). KK-8 ("geçmiş dönemler donmuş kalır") ile tutarlı
    olan davranış ATLAMAKTIR.

    🔴 **AMA ŞEMA ATLANMAZ.** Üç iddia birden: revizyon İLERLER ·
    `income_tax_pct` **10'da KALIR** · tarife tohumu ve yeni kolonlar YİNE DE
    UYGULANIR. Şema da atlansaydı `Base.metadata` ile DB kalıcı olarak ayrışır
    ve uygulama açıldıktan sonra her `compute` 500 verirdi.

    🔴 Bu test `SKIP_LOG_PREFIX` sinyaline BAKMAZ — o AYRI bir kusur sınıfıdır
    ve `..._BAGIRIR` ile ayrıca çakılıdır.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_PARENT, database=database)
        await _kilitli_yil_kur(database)

        # `_run_alembic` sifir olmayan cikista `pytest.fail` eder — bu cagrinin
        # kendisi "migration PATLAMADI" iddiasidir.
        _run_alembic("upgrade", GV_REVISION, database=database)

        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == GV_REVISION
            sonra = await _income_tax_pcts(conn)
            for source in BRACKET_REGIME_SOURCES:
                assert sonra[source] == SEEDED_INCOME_TAX_PCT, (
                    f"{source} kilitli yılda dilimli motora GEÇTİ — atlama koşulu kayıp; "
                    "onaylanmış dönemin raporlanmış kesintileri geriye dönük değişirdi"
                )
            # 🔴 SEMA + tohum UYGULANDI.
            assert await conn.fetchval("SELECT count(*) FROM payroll_tax_brackets") == 5
            assert await conn.fetchval("SELECT count(*) FROM payroll_minimum_wages") == 1
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'payroll_lines' AND column_name = 'income_tax_amount'"
                )
                == 1
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kilitli_donem_atlamasi_BAGIRIR():
    """🔴 SESSİZ ATLAMA YASAK — atlama ERROR düzeyinde iz bırakır.

    "Aynı yeşil iki anlam taşır": atlanmış bir düzeltme ile hiç gerek
    duyulmamış bir düzeltme, günlükte AYIRT EDİLEBİLİR olmalıdır. Bu test
    atlamanın KENDİSİNE bakmaz — yalnız SİNYALE. İkisi ayrı mutasyon sınıfıdır
    (biri "atlamayı kaldır", öteki "sinyali sustur").
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_PARENT, database=database)
        await _kilitli_yil_kur(database)

        result = _run_alembic("upgrade", GV_REVISION, database=database)
        ciktilar = result.stdout + result.stderr

        assert SKIP_LOG_PREFIX in ciktilar, (
            f"atlama SESSİZ geçti — `{SKIP_LOG_PREFIX}` imzası günlükte yok:\n{ciktilar}"
        )
        assert "2026-03 (approved)" in ciktilar, ciktilar
        assert "BIR DAHA CALISMAYACAK" in ciktilar, ciktilar
    finally:
        await _drop_scratch_database(database)


async def test_kilitsiz_donem_kapiyi_ACMAZ():
    """`draft`/`pending_approval` dönem geçişi ENGELLEMEZ — kapı KİLİDE bakar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO payroll_periods (id, year, month, status) "
                "VALUES ($1, 2026, 4, 'pending_approval')",
                uuid.uuid4(),
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (await _income_tax_pcts(conn))["company"] is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_upgrade_downgrade_upgrade_turu():
    """🔴 DEPLOY = OTOMATİK MİGRATION: tur dönüşü yerelde kanıtlanır.

    Downgrade NO-OP DEĞİLDİR (IK3-RATE-FIX'ten farklı): `income_tax_pct`
    yeniden `NOT NULL` olacağı için `NULL` satırlar önce tohumun `10`una GERİ
    YAZILIR — bir tercih değil, şemanın ZORUNLU KILDIĞI adım. Geri yazılmasaydı
    `ALTER COLUMN … SET NOT NULL` patlar ve downgrade yolu tamamen kapanırdı.

    İkinci `upgrade` de PATLAMAZ: enum tipi downgrade'de AÇIKÇA `DROP` edilir
    (`d4e5f6a7b8c9` dersi — yoksa "type already exists" ile patlardı ve bu
    YALNIZ CANLIDA görülürdü) ve tohum `ON CONFLICT DO NOTHING`tir.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert (await _income_tax_pcts(conn))["company"] is None
        finally:
            await conn.close()

        _run_alembic("downgrade", GV_PARENT, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == GV_PARENT
            assert (await _income_tax_pcts(conn))["company"] == SEEDED_INCOME_TAX_PCT
            # Tablolar, kolonlar ve enum tipi TAMAMEN kalkmalı.
            for tablo in ("payroll_tax_brackets", "payroll_minimum_wages"):
                assert await conn.fetchval("SELECT to_regclass($1)", tablo) is None, tablo
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM pg_type WHERE typname = 'payroll_income_kind'"
                )
                == 0
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'payroll_lines' AND column_name = ANY($1)",
                    ["tax_base_amount", "cumulative_tax_base", "income_tax_amount"],
                )
                == 0
            )
        finally:
            await conn.close()

        _run_alembic("upgrade", GV_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _current_revision(conn) == GV_REVISION
            assert await conn.fetchval("SELECT count(*) FROM payroll_tax_brackets") == 5
            assert (await _income_tax_pcts(conn))["company"] is None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
