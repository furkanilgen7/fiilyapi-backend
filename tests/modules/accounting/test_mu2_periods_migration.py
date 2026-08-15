"""MU-2 T2 — `accounting_periods` şeması: model katmanı + migration tur dönüşü.

MU-1 `accounting_periods`i BİLEREK açmamıştı (models.py "AÇILMAYANLAR" listesi:
*"dönem kapanışı / `accounting_periods` (yapı hazır: `period_year/month` +
indeks)"*). MU-2 o yapıyı kullanır: dönem kaydı BURADA doğar.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration **YENİ** bir Postgres enum tipi
getiriyor (`accounting_period_status`). Downgrade'de düşürmeyi unutmak ikinci
`upgrade`i "type already exists" ile patlatır (`d4e5f6a7b8c9` dersi) ve bu
**yalnız canlıda** görülürdü — `Dockerfile` açılışta `alembic upgrade head`
koşar, patlarsa uvicorn hiç başlamaz (tam kesinti).

🔴 İkinci iddia kümesi DB SEMANTİĞİDİR ve bu dilimin ASIL bekçisidir:
`ck_accounting_periods_closed_stamp`. "Kapalı ama kimin/ne zaman kapattığı yok"
hâli mali izi bozar — N-ÇARPANLI SNAPSHOT kanonunun (MK-2) kardeşidir: bir
durum damgası N parçadan oluşuyorsa N'in HEPSİ birlikte yazılmalıdır. Ters yön
de kilitlidir: `open` bir dönemde `closed_at`/`closed_by_id` DOLU OLAMAZ, yoksa
"tekrar açılmış" bir dönem eski kapatma damgasını taşır ve denetim izi yalan
söyler.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (HZ-1/FAT-1/MU-1 deseni).

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — RESTRICT ihlali sürüme göre 23001 veya
23503 bildirir; iddialar bu yüzden DAR bir tuple ile iki sınıfı da kabul eder.
"""

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.accounting.models import AccountingPeriod, AccountingPeriodStatus

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
MU1_REVISION = "d5e6f7a8b9c0"
MU2_REVISION = "c7d8e9f0a1b2"

TABLE = "accounting_periods"
NEW_ENUM = "accounting_period_status"

# K2'nin dönem karşılığı: dönem YA açıktır YA kapalıdır. Üçüncü üye
# (`locked`/`archived`/`reopened`) İCAT EDİLMEZ.
EXPECTED_ENUM_LABELS = ["open", "closed"]

INDEXES = ("uq_accounting_periods_year_month",)

CONSTRAINTS = (
    "uq_accounting_periods_year_month",
    "ck_accounting_periods_month_range",
    "ck_accounting_periods_year_range",
    "ck_accounting_periods_closed_stamp",
)

# PG RESTRICT'i 23001, NO ACTION'ı 23503 bildirir (yerel 18 / CI 16). Ata
# sınıfa (`PostgresError`) gevşetilmez — DAR tuple.
RESTRICT_ERRORS = (asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)


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


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")


async def _enum_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = $1 AND typtype = 'e')", name
    )


async def _enum_labels(conn: asyncpg.Connection, name: str) -> list[str]:
    return await conn.fetchval("SELECT enum_range(NULL::" + name + ")::text[]")


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
    database = f"accounting_mu2_{uuid.uuid4().hex[:8]}"
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
# Seed yardimcilari — yalnizca FK hedefi olsun diye, en dar kolon kumesiyle.
# --------------------------------------------------------------------------- #


async def _seed_user(conn: asyncpg.Connection) -> uuid.UUID:
    role_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO roles (id, key, name, emoji, description, is_system) "
        "VALUES ($1, $2, 'Muhasebe', '#', 'test', false)",
        role_id,
        f"role_{uuid.uuid4().hex[:8]}",
    )
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, full_name, title, role_id, status) "
        "VALUES ($1, $2, 'x', 'Ayse Demir', 'Muhasebe', $3, 'active')",
        user_id,
        f"{uuid.uuid4().hex[:8]}@fiil.test",
        role_id,
    )
    return user_id


async def _insert_period(
    conn: asyncpg.Connection,
    *,
    year: int = 2026,
    month: int = 7,
    status: str = "open",
    closed_at: datetime | None = None,
    closed_by_id: uuid.UUID | None = None,
) -> uuid.UUID:
    period_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO accounting_periods (id, year, month, status, closed_at, closed_by_id) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        period_id,
        year,
        month,
        status,
        closed_at,
        closed_by_id,
    )
    return period_id


# --------------------------------------------------------------------------- #
# Model katmani — enum
# --------------------------------------------------------------------------- #


def test_period_status_enum_matches_spec_exactly():
    """Değerler DB'ye yazılır: sonradan düzeltmek bir enum TAKASI (migration)
    gerektirir, bu yüzden burada kilitli."""
    assert [e.value for e in AccountingPeriodStatus] == EXPECTED_ENUM_LABELS


def test_period_status_has_no_invented_members():
    """🔴 Dönem YA açıktır YA kapalıdır. `locked`/`archived`/`reopened` gibi bir
    üçüncü üye AÇILSAYDI `ck_accounting_periods_closed_stamp` ikili mantığını
    kaybeder (üçüncü değerde damganın ne olması gerektiği TANIMSIZ kalırdı) ve
    hiçbir ekranda karşılığı olmayan bir kümeyi kalıcı olarak DB'ye yazardık."""
    values = {e.value for e in AccountingPeriodStatus}
    for yasak in ("locked", "archived", "reopened", "pending", "draft", "partial"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_accounting_period_columns_match_spec():
    """BİLEREK tam sayım: yeni bir kolon sessizce eklenemesin."""
    columns = AccountingPeriod.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "year",
        "month",
        "status",
        "closed_at",
        "closed_by_id",
        "created_at",
        "updated_at",
    }
    assert not columns["year"].nullable
    assert not columns["month"].nullable
    assert not columns["status"].nullable
    # Damga İKİ PARÇADIR ve ikisi de nullable'dır: `open` dönemde İKİSİ DE
    # NULL olmak ZORUNDADIR (CHECK). NOT NULL yapılsalardı açık dönem hiç
    # yazılamazdı.
    assert columns["closed_at"].nullable
    assert columns["closed_by_id"].nullable


def test_accounting_period_has_no_scope_or_derived_columns():
    """🔴 Kapsam (IDOR) yapısal olarak YOKTUR — MU-1'in üç tablosuyla aynı
    gerekçe: hesap planı ve yevmiye ŞİRKET GENELİDİR, dönem de öyle. Proje
    bazlı dönem açılsaydı aynı ay bir projede kapalı bir projede açık olur ve
    "dönem kapalı" ifadesi ANLAMINI KAYBEDERDİ.

    Türev alanlar da yoktur: dönemin toplamları/mizanı SAKLANMAZ, yevmiyeden
    TÜRETİLİR (K3'ün kardeşi) — saklansaydı kaydığını hiçbir kolon farkı ele
    vermezdi. `reopened_at`/`is_locked` de yoktur: durum TEK kolondur."""
    columns = set(AccountingPeriod.__table__.columns.keys())
    for yasak in (
        "project_id",
        "site_id",
        "cost_center_id",
        "total_debit",
        "total_credit",
        "entry_count",
        "is_locked",
        "is_closed",
        "reopened_at",
        "reopened_by_id",
        "note",
    ):
        assert yasak not in columns, yasak


def test_closed_by_fk_is_restrict():
    """RESTRICT: dönemi kapatan kullanıcı, mali izi sahipsiz bırakacak şekilde
    silinemez (`journal_entries.created_by_id` ile aynı gerekçe). SET NULL
    olsaydı `ck_accounting_periods_closed_stamp` DB tarafından ihlal edilir —
    kapalı dönem damgasız kalırdı."""
    (user_fk,) = tuple(AccountingPeriod.__table__.columns["closed_by_id"].foreign_keys)
    assert user_fk.target_fullname == "users.id"
    assert user_fk.ondelete == "RESTRICT"


def test_no_redundant_year_month_index():
    """🔴 UNIQUE ZATEN bir indeks üretir. Ayrıca `ix_accounting_periods_year_
    month` açmak AYNI iki sütun üzerinde İKİNCİ bir B-tree demektir: her yazma
    iki kez maliyetlenir, hiçbir okuma hızlanmaz."""
    index_names = {ix.name for ix in AccountingPeriod.__table__.indexes}
    assert index_names == set(), f"gereksiz indeks: {index_names}"
    constraint_names = {c.name for c in AccountingPeriod.__table__.constraints}
    assert "uq_accounting_periods_year_month" in constraint_names


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


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `d5e6f7a8b9c0` (MU-1). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(MU2_REVISION)
    assert revision.down_revision == MU1_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 Yeni enum downgrade'de DÜŞER; düşmezse ikinci upgrade patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _table_exists(conn, TABLE)
            assert await _enum_exists(conn, NEW_ENUM)
            assert await _enum_labels(conn, NEW_ENUM) == EXPECTED_ENUM_LABELS
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            for constraint in CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert await _current_revision(conn) == MU2_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
            assert not await _table_exists(conn, TABLE)
            assert not await _enum_exists(conn, NEW_ENUM), (
                f"{NEW_ENUM} tipi downgrade'de kalmış — ikinci upgrade patlar"
            )
            # MU-1 tabloları AYAKTA: bu dilim hiçbir mevcut tabloya ADDITIVE
            # kolon eklemez, yalnız YENİ bir tablo getirir.
            for komsu in ("chart_of_accounts", "journal_entries", "journal_lines", "users"):
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == MU1_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _table_exists(conn, TABLE)
            assert await _enum_exists(conn, NEW_ENUM)
            assert await _current_revision(conn) == MU2_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# DB semantigi — donem kaydinin SON savunmasi
# --------------------------------------------------------------------------- #


async def test_db_level_year_month_uniqueness():
    """🔴 Aynı `(yıl, ay)` İKİ KEZ açılamaz. Açılabilseydi biri `open` biri
    `closed` iki satır doğar ve "2026/07 kapalı mı?" sorusunun İKİ cevabı
    olurdu — dönem kilidi (T3) hangi satıra bakacağını bilemezdi.

    İddia SQLSTATE'e göre DEĞİL, `UniqueViolationError` ile yapılır: yerel
    PG 18 / CI PG 16 arasında sürüme özgü kod iddia edilmez."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await _insert_period(conn, year=2026, month=7)

            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_period(conn, year=2026, month=7)

            # AYNI yılın başka ayı ve BAŞKA yılın aynı ayı SERBEST: kısıt
            # ÇİFT üzerindedir, tek sütun üzerinde değil.
            await _insert_period(conn, year=2026, month=8)
            await _insert_period(conn, year=2025, month=7)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_month_and_year_ranges():
    """🔴 `month` 1-12 dışına ÇIKAMAZ. `month = 0` ya da `13` girseydi UNIQUE
    çifti bozulmadan var olmayan bir dönem doğar, mizan (T3) o ayı hiçbir
    takvimde bulamazdı. `year` bandı da aynı gerekçeyle kapalıdır: `year = 26`
    ya da `20026` gibi bir yazım hatası sessizce kalıcı olurdu."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # Sınırlar DAHİLDİR.
            await _insert_period(conn, year=2026, month=1)
            await _insert_period(conn, year=2026, month=12)
            await _insert_period(conn, year=2000, month=3)
            await _insert_period(conn, year=2100, month=3)

            for yasak_ay in (0, 13, -1, 99):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_period(conn, year=2027, month=yasak_ay)

            for yasak_yil in (1999, 2101, 26, 20026):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_period(conn, year=yasak_yil, month=5)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_closed_stamp_is_all_or_nothing():
    """🔴 BU DİLİMİN ASIL BEKÇİSİ — `ck_accounting_periods_closed_stamp`.

    N-ÇARPANLI SNAPSHOT kanonunun (MK-2) kardeşi: bir durum damgası N parçadan
    oluşuyorsa N'in HEPSİ birlikte yazılmalıdır. "Kapalı ama kim/ne zaman
    kapattı belli değil" hâli mali izi bozar — denetim günlüğü (B5) o dönemi
    kimin kilitlediğini SORAMAZ hâle gelir.

    Ters yön de kilitlidir: `open` bir dönem eski kapatma damgasını TAŞIYAMAZ.
    Taşısaydı yeniden açılmış bir dönem hâlâ "12 Ağustos'ta Ayşe kapattı" derdi
    ve iz YALAN SÖYLERDİ."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            now = datetime.now(UTC)

            # GEÇER: açık dönem, iki damga da NULL.
            await _insert_period(conn, year=2026, month=1)
            # GEÇER: kapalı dönem, İKİ damga da dolu.
            await _insert_period(
                conn,
                year=2026,
                month=2,
                status="closed",
                closed_at=now,
                closed_by_id=user_id,
            )

            # 🔴 `closed` + eksik damga — üç kombinasyonun ÜÇÜ DE reddedilir.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(
                    conn, year=2026, month=3, status="closed", closed_by_id=user_id
                )
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(conn, year=2026, month=4, status="closed", closed_at=now)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(conn, year=2026, month=5, status="closed")

            # 🔴 `open` + artık damga — üç kombinasyonun ÜÇÜ DE reddedilir.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(conn, year=2026, month=6, status="open", closed_at=now)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(conn, year=2026, month=7, status="open", closed_by_id=user_id)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_period(
                    conn,
                    year=2026,
                    month=8,
                    status="open",
                    closed_at=now,
                    closed_by_id=user_id,
                )

            # 🔴 UPDATE yolu da kapalıdır: kapalı dönemin damgası SÖKÜLEMEZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "UPDATE accounting_periods SET closed_at = NULL WHERE year = 2026 AND month = 2"
                )
            # Ve açık bir dönem damga yazılmadan `closed` DAMGALANAMAZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "UPDATE accounting_periods SET status = 'closed' "
                    "WHERE year = 2026 AND month = 1"
                )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_status_server_default_is_open():
    """🔴 `server_default` FİİLEN çalışıyor mu — ham SQL ile `status` HİÇ
    verilmeden INSERT edilir. Yalnız Python tarafı `default=` verilseydi ORM
    dışı her yazma yolu (migration data-fix, elle SQL, `COPY`) NOT NULL ihlali
    alırdı; sunucu varsayılanı olmadan yeni dönem satırı DB'de doğamaz."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            await conn.execute(
                "INSERT INTO accounting_periods (id, year, month) VALUES ($1, 2026, 9)",
                uuid.uuid4(),
            )
            row = await conn.fetchrow(
                "SELECT status::text AS status, closed_at, closed_by_id, created_at, updated_at "
                "FROM accounting_periods WHERE year = 2026 AND month = 9"
            )
            assert row["status"] == "open"
            # Yeni dönem DAMGASIZ doğar (CHECK'in `open` ayağıyla tutarlı).
            assert row["closed_at"] is None
            assert row["closed_by_id"] is None
            # Zaman damgaları da sunucudan gelir (repo deseni).
            assert row["created_at"] is not None
            assert row["updated_at"] is not None
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_closed_by_restrict():
    """🔴 Dönemi kapatan kullanıcı SİLİNEMEZ. CASCADE/SET NULL olsaydı kullanıcı
    silindiğinde kapalı dönem ya tamamen kaybolur ya da damgasız kalırdı —
    ikinci hâlde `ck_accounting_periods_closed_stamp` DB'nin KENDİSİ tarafından
    ihlal edilirdi."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            period_id = await _insert_period(
                conn,
                year=2026,
                month=10,
                status="closed",
                closed_at=datetime.now(UTC),
                closed_by_id=user_id,
            )

            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)

            # Dönem kaydı gidince kullanıcı serbest kalır.
            await conn.execute("DELETE FROM accounting_periods WHERE id = $1", period_id)
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
