"""OK-1A T2 — onay zinciri migration'ının tur ve HİJYEN bekçileri.

Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
revizyon ekledikçe bu test sessizce YANLIŞ şeyi ölçerdi (`test_fisno_migration.py`
emsali).

🔴 **ENUM `DROP TYPE`**: Postgres enum tipleri tabloyla birlikte SİLİNMEZ.
`downgrade` onları açıkça düşürmezse ikinci `upgrade` "type already exists" ile
patlar — ve bu YALNIZ CANLIDA görülür: konteyner açılışta
`alembic upgrade head && uvicorn …` koşar, `&&` kısa devre yapar, uvicorn HİÇ
BAŞLAMAZ (tam kesinti).

Alembic alt süreçte koşturulur ve test KENDİ TEK KULLANIMLIK veritabanını açar;
`.env` ve `TEST_DATABASE_URL` veritabanı ELLENMEZ.

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — sürüme özgü SQLSTATE iddia edilmez.
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

TB6_REVISION = "e9f0a1b2c3d4"
OK1A_REVISION = "f1a2b3c4d5e6"

YENI_TABLOLAR = ("user_approval_roles", "approval_chains", "approval_steps")
YENI_ENUMLAR = ("approval_role", "approval_document_type")
KOMSU_TABLOLAR = ("users", "company", "purchase_requests", "progress_payments")


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
    database = f"ok1a_mig_{uuid.uuid4().hex[:8]}"
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


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")


async def _type_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = $1)", name)


async def _column_exists(conn: asyncpg.Connection, table: str, column: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2)",
        table,
        column,
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


def test_alembic_has_single_head() -> None:
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar).

    🔴 `DATABASE_URL` override'ı BURADA DA verilir: `.env` UZAK Railway'i
    gösterir — hiçbir alembic komutu override'sız koşmaz.
    """
    result = subprocess.run(
        [*ALEMBIC_CMD, "heads"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": _asyncpg_dsn("postgres")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"tek head bekleniyordu, cikti:\n{result.stdout}"

    # 🔴 BURADA `OK1A_REVISION`in HEAD OLDUGU IDDIA EDILMEZ (FRM-1 dersi,
    # `test_frm1_document_fields_migration.py:100-138`): "bu dilim en yeni
    # migration'dir" iddiasi, kendisinden SONRA gelen ILK dilimde kacinilmaz
    # olarak kirmiziya doner ve o dilimin sahibine, kendi isiyle ilgisi olmayan
    # bir kirmizi birakir. TB6'nin ayni tuzagi bu turda FIILEN kirildi ve
    # uyarlandi. Korunmasi GEREKEN ozellik zincirden dusmemektir: kotu bir
    # re-parent bu migration'i oksuz birakirsa tablolar canlida HIC olusmaz.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    atalar = {rev.revision for rev in script.iterate_revisions(heads[0].split()[0], "base")}
    assert OK1A_REVISION in atalar, (
        f"{OK1A_REVISION} head'in zincirinde DEGIL — re-parent onu oksuz birakmis olabilir; "
        f"head: {heads[0]}"
    )


def test_migration_parent_is_the_expected_revision() -> None:
    """🔴 Ebeveyn `e9f0a1b2c3d4` (TB6). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    assert script.get_revision(OK1A_REVISION).down_revision == TB6_REVISION


async def test_upgrade_downgrade_upgrade_round_trip() -> None:
    """🔴 Downgrade TABLOLARI, KOLONU **ve ENUM TİPLERİNİ** düşürür.

    Enum kalırsa ikinci `upgrade` "type already exists" ile patlar (modül
    docstring'i) — asıl iddia son adımdaki ikinci `upgrade`in GEÇMESİDİR.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", OK1A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for tablo in YENI_TABLOLAR:
                assert await _table_exists(conn, tablo), tablo
            for tip in YENI_ENUMLAR:
                assert await _type_exists(conn, tip), tip
            assert await _column_exists(conn, "company", "approval_threshold_try")
            assert await _current_revision(conn) == OK1A_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", TB6_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for tablo in YENI_TABLOLAR:
                assert not await _table_exists(conn, tablo), tablo
            for tip in YENI_ENUMLAR:
                assert not await _type_exists(conn, tip), (
                    f"`{tip}` enum tipi downgrade'de KALMIŞ — ikinci upgrade "
                    '"type already exists" ile patlardı'
                )
            assert not await _column_exists(conn, "company", "approval_threshold_try")
            for komsu in KOMSU_TABLOLAR:
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == TB6_REVISION
        finally:
            await conn.close()

        # 🔴 ASIL IDDIA: ikinci upgrade PATLAMADAN gecer.
        _run_alembic("upgrade", OK1A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for tablo in YENI_TABLOLAR:
                assert await _table_exists(conn, tablo), tablo
            assert await _current_revision(conn) == OK1A_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_kisitlar_SEMADA_gercekten_var() -> None:
    """Model katmanındaki kısıtlar migration'a YANSIMAMIŞ olabilir: ikisi ayrı
    dosyalardır ve autogenerate KULLANILMIYOR. Ham SQL ile sınanır."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", OK1A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for ad in (
                "uq_user_approval_roles_user_role",
                "uq_approval_chains_document",
                "uq_approval_steps_chain_step_no",
            ):
                assert await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", ad
                ), ad

            # 🔴 EŞİK NOT NULL + server_default: mevcut satır migration'dan sonra
            # da bir eşiğe sahiptir (canlıda `company` satırı ZATEN vardır).
            nullable = await conn.fetchval(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'company' AND column_name = 'approval_threshold_try'"
            )
            assert nullable == "NO"
            varsayilan = await conn.fetchval(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'company' AND column_name = 'approval_threshold_try'"
            )
            assert varsayilan is not None and "500000" in varsayilan, varsayilan

            # 🔴 `amount_snapshot` NULL kabul EDER (fail-closed "belirlenemez"),
            # `threshold_snapshot` ETMEZ.
            assert (
                await conn.fetchval(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'approval_chains' AND column_name = 'amount_snapshot'"
                )
                == "YES"
            )
            assert (
                await conn.fetchval(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'approval_chains' AND column_name = 'threshold_snapshot'"
                )
                == "NO"
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_adimlar_zincirle_birlikte_CASCADE_ile_gider() -> None:
    """K2'nin DB tarafı: zincir silinince adımlar da gider (`ON DELETE CASCADE`).

    Servis katmanı bunu `test_ok1a_reject.py`de iddia eder; burada ölçülen şey
    kısıtın ŞEMADA gerçekten CASCADE olduğudur — servis testi, ORM'in kendi
    ilişki temizliğiyle de yeşil geçebilirdi.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", OK1A_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            chain_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO approval_chains "
                "(id, document_type, document_id, threshold_snapshot, amount_snapshot, created_at) "
                "VALUES ($1, 'purchase_request', gen_random_uuid(), 500000, 100, now())",
                chain_id,
            )
            await conn.execute(
                "INSERT INTO approval_steps (id, chain_id, step_no, approval_role) "
                "VALUES (gen_random_uuid(), $1, 1, 'procurement')",
                chain_id,
            )
            await conn.execute("DELETE FROM approval_chains WHERE id = $1", chain_id)
            assert await conn.fetchval("SELECT count(*) FROM approval_steps") == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
