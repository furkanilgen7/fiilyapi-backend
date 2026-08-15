"""MU-1 T2 — muhasebe şeması: model katmanı + migration tur dönüşü.

Spec: `docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §3, §4.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration **İKİ** yeni Postgres enum tipi
getiriyor (`chart_account_type` / `journal_entry_status`). Birini bile
downgrade'de düşürmeyi unutmak ikinci `upgrade`i "type already exists" ile
patlatır (`d4e5f6a7b8c9` dersi) ve bu **yalnız canlıda** görülürdü — `Dockerfile`
açılışta `alembic upgrade head` koşar, patlarsa uvicorn hiç başlamaz (tam kesinti).

İkinci iddia kümesi DB SEMANTİĞİDİR ve bu dilimde **K1'in son savunmasıdır**:
tek taraflılık, negatif tutar yasağı, `debit`/`credit` NOT NULL, dengesiz fişin
`posted` olamaması, `total_*`ın NOT NULL olması (nullable olsalardı
`NULL = NULL` → NULL üretip denge CHECK'ini **geçerdi**), dönem–tarih kilidi,
kod dilbilgisi, iki UNIQUE ve üç FK davranışı. Servis 422/409 vermeyi unutsa
bile bozuk bir mali kayıt tabloya girmemelidir.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (HZ-1/FAT-1 deseni).

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — RESTRICT ihlali sürüme göre 23001 veya
23503 bildirir; iddialar bu yüzden DAR bir tuple ile iki sınıfı da kabul eder.
"""

import os
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.accounting.models import (
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
HZ1_REVISION = "c4d5e6f7a8b9"
MU1_REVISION = "d5e6f7a8b9c0"

TABLES = ("chart_of_accounts", "journal_entries", "journal_lines")

# Spec §3: İKİSİ DE YENİ — downgrade ikisini de düşürmek zorundadır.
NEW_ENUMS = ("chart_account_type", "journal_entry_status")

EXPECTED_ENUM_LABELS = {
    # HP:60 `Tür` sütununun KAPALI kümesi: Aktif · Pasif · Gelir · Gider.
    # Beşinci üye İCAT EDİLMEZ (K5).
    "chart_account_type": ["asset", "liability", "revenue", "expense"],
    # K2: draft → posted → reversed (`reversed` TERMİNAL).
    "journal_entry_status": ["draft", "posted", "reversed"],
}

INDEXES = (
    "uq_chart_of_accounts_code",
    "ix_chart_of_accounts_account_type",
    "uq_journal_entries_reversal_of",
    "ix_journal_entries_entry_date",
    "ix_journal_entries_period",
    "ix_journal_entries_status",
    # FK'ler otomatik indeks ÜRETMEZ: defter ve bakiye türetimi (K3) bu iki
    # sütundan geçer.
    "ix_journal_lines_entry_id",
    "ix_journal_lines_account_id",
)

CONSTRAINTS = (
    "ck_chart_of_accounts_code_format",
    "ck_journal_entries_period_matches_date",
    "ck_journal_entries_posted_balanced",
    "ck_journal_entries_totals_non_negative",
    "ck_journal_lines_amounts_non_negative",
    "ck_journal_lines_single_side",
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
    database = f"accounting_mu1_{uuid.uuid4().hex[:8]}"
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


async def _insert_account(
    conn: asyncpg.Connection,
    code: str,
    *,
    account_type: str = "asset",
    name: str = "Kasa",
) -> uuid.UUID:
    account_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO chart_of_accounts (id, code, name, account_type) VALUES ($1, $2, $3, $4)",
        account_id,
        code,
        name,
        account_type,
    )
    return account_id


async def _insert_entry(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    *,
    status: str = "draft",
    entry_date: str = "2026-07-17",
    period_year: int = 2026,
    period_month: int = 7,
    total_debit: str = "0",
    total_credit: str = "0",
    reversal_of_id: uuid.UUID | None = None,
) -> uuid.UUID:
    entry_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO journal_entries (id, entry_date, period_year, period_month, description, "
        "status, total_debit, total_credit, reversal_of_id, created_by_id) "
        "VALUES ($1, $2, $3, $4, 'Banka havalesi', $5, $6, $7, $8, $9)",
        entry_id,
        # asyncpg `date` kolonuna STR kabul etmez (`::date` cast'i de kurtarmaz:
        # tip cikarimi bind asamasinda yapilir) — gercek `date` nesnesi gecilir.
        date.fromisoformat(entry_date),
        period_year,
        period_month,
        status,
        total_debit,
        total_credit,
        reversal_of_id,
        user_id,
    )
    return entry_id


async def _insert_line(
    conn: asyncpg.Connection,
    entry_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    debit: str | None = "100.00",
    credit: str | None = "0",
    sort_order: int = 0,
) -> uuid.UUID:
    line_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO journal_lines (id, entry_id, sort_order, account_id, debit, credit) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        line_id,
        entry_id,
        sort_order,
        account_id,
        debit,
        credit,
    )
    return line_id


# --------------------------------------------------------------------------- #
# Model katmani — iki yeni enum
# --------------------------------------------------------------------------- #


def test_two_new_enums_match_spec_exactly():
    """Spec §3 birebir. Değerler DB'ye yazılır: sonradan düzeltmek bir enum
    TAKASI (migration) gerektirir, bu yüzden burada kilitli."""
    actual = {
        "chart_account_type": [e.value for e in ChartAccountType],
        "journal_entry_status": [e.value for e in JournalEntryStatus],
    }
    assert actual == EXPECTED_ENUM_LABELS


def test_account_type_has_no_invented_members():
    """🔴 K5: HP:60 yalnız dört rozet çiziyor (Aktif/Pasif/Gelir/Gider).
    Özkaynak/nazım/maliyet gibi beşinci bir tür AÇILSAYDI hiçbir ekranda
    karşılığı olmayan bir kümeyi kalıcı olarak DB'ye yazardık."""
    values = {e.value for e in ChartAccountType}
    for yasak in ("equity", "memorandum", "cost", "contra", "other", "class"):
        assert yasak not in values, yasak


def test_entry_status_has_no_invented_members():
    """K2 İKİ geçiş tanımlar; ara onay adımı (`request`/`approve`) hiçbir
    mockup'ta çizilmemiştir — `cancelled`/`deleted` de yoktur: kayıtlaştırılmış
    fiş defterden ÇIKMAZ, yalnız ters kaydıyla nötrlenir."""
    values = {e.value for e in JournalEntryStatus}
    for yasak in ("pending", "approved", "cancelled", "deleted", "closed", "locked"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_chart_account_columns_match_spec():
    """BİLEREK tam sayım: yeni bir kolon sessizce eklenemesin."""
    columns = ChartAccount.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "code",
        "name",
        "account_type",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert not columns["code"].nullable
    assert columns["code"].type.length == 20
    assert not columns["name"].nullable
    assert columns["name"].type.length == 200
    assert not columns["account_type"].nullable
    # HP:62 `Durum` — kaldırma bayrağı; varsayılan AÇIK.
    assert not columns["is_active"].nullable


def test_chart_account_has_no_parent_or_derived_columns():
    """🔴 K4 + K3 + K-Ş2. Hiyerarşi KODUN içindedir: `parent_id` açılsaydı
    türetilebilir bir şey saklanır ve kod düzeltildiğinde FK bayatlardı.
    Bakiye SAKLANMAZ (`balance.py` TEK KAYNAK) — kolonlaşsaydı kaydığını hiçbir
    kolon farkı ele vermezdi. `is_contra` da yoktur: `257`in parantezi bir SUNUM
    kuralıdır (adın `(-)` son eki), hiçbir form onay kutusu çizmemiştir.
    Proje/şantiye FK'sı YOKTUR: katalog ŞİRKET GENELİDİR (§3 kapsam kararı)."""
    columns = set(ChartAccount.__table__.columns.keys())
    for yasak in (
        "parent_id",
        "parent_code",
        "class_code",
        "level",
        "balance",
        "current_balance",
        "opening_balance",
        "is_contra",
        "project_id",
        "site_id",
        "currency",
    ):
        assert yasak not in columns, yasak


def test_journal_entry_columns_match_spec():
    columns = JournalEntry.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "entry_date",
        "period_year",
        "period_month",
        "description",
        "detail_note",
        "status",
        "total_debit",
        "total_credit",
        "reversal_of_id",
        "created_by_id",
        "created_at",
        "updated_at",
    }
    assert not columns["entry_date"].nullable
    assert not columns["period_year"].nullable
    assert not columns["period_month"].nullable
    assert not columns["description"].nullable
    # E8:113 alt satırı — `invoice_lines.detail_note` ile aynı ad/rol/ölçü.
    assert columns["detail_note"].nullable
    assert columns["detail_note"].type.length == 200
    # 🔴 NOT NULL ŞART: nullable olsalardı `NULL = NULL` NULL üretir ve
    # `ck_journal_entries_posted_balanced` sessizce devre dışı kalırdı.
    for kolon in ("total_debit", "total_credit"):
        assert not columns[kolon].nullable, kolon
        assert columns[kolon].type.precision == 18
        assert columns[kolon].type.scale == 2
    assert columns["reversal_of_id"].nullable
    assert not columns["created_by_id"].nullable


def test_journal_entry_has_no_entry_no_and_no_scope_columns():
    """🔴 `entry_no` AÇILMAZ: ne HP'de ne E8'de fiş numarası sütunu çizilidir
    (FAT-1'de vardı çünkü FY tablosunda çiziliydi). Kimlik `id`dir,
    `numbering.py` YOKTUR. Proje/şantiye alanı da yoktur — E8:28-30 topbar'daki
    `Güneşkent Konut` tabloda karşılığı olmayan bir bağlamdır."""
    columns = set(JournalEntry.__table__.columns.keys())
    for yasak in (
        "entry_no",
        "entry_number",
        "document_no",
        "entry_type",
        "project_id",
        "site_id",
        "cost_center_id",
        "posted_at",
        "note",
    ):
        assert yasak not in columns, yasak


def test_entry_date_is_a_date_not_timestamptz():
    """🔴 K6: `entry_date` bir `date`tir. `timestamptz` olsaydı üzerinde
    `.date()` çağırmak UTC gününü verir ve TR gecesi 21:00-24:00 arasında bir
    gün geriye kayardı (`tests/test_local_calendar_guard.py` 3. kalıbı)."""
    from sqlalchemy import Date, DateTime

    entry_date_type = JournalEntry.__table__.columns["entry_date"].type
    assert isinstance(entry_date_type, Date)
    assert not isinstance(entry_date_type, DateTime)


def test_journal_line_columns_match_spec():
    """🔴 K1: `debit` ve `credit` AYRI İKİ KOLONDUR. Tek `amount` + `side`
    seçilseydi `SUM(borç)` bir `CASE` içine gizlenir ve
    `ck_journal_lines_single_side` DB'de YAZILAMAZDI."""
    columns = JournalLine.__table__.columns
    assert set(columns.keys()) == {"id", "entry_id", "sort_order", "account_id", "debit", "credit"}
    assert not columns["entry_id"].nullable
    assert not columns["account_id"].nullable
    assert not columns["sort_order"].nullable
    # `server_default` YOK: her yazma yolu sırayı açıkça doldurmalıdır
    # (varsayılan 0 olsaydı eksik doldurulan bir yol tüm satırları aynı sıraya
    # koyar ve koşan bakiye keyfî dizilirdi).
    assert columns["sort_order"].server_default is None
    # 🔴 NOT NULL: NULL tutar `SUM` tarafından YUTULUR ve dengesiz fiş dengede
    # sayılırdı.
    for kolon in ("debit", "credit"):
        assert not columns[kolon].nullable, kolon
        assert columns[kolon].type.precision == 18
        assert columns[kolon].type.scale == 2


def test_journal_line_has_no_description_or_timestamp():
    """Bir fişin iki bacağı AYNI işlemi anlatır; açıklama satıra taşınsaydı aynı
    metin tekrarlanır ve ayrışabilirdi. Satırın ömrü başlığa bağlıdır (CASCADE),
    kendi zaman damgası yoktur."""
    columns = set(JournalLine.__table__.columns.keys())
    for yasak in (
        "description",
        "detail_note",
        "note",
        "created_at",
        "updated_at",
        "amount",
        "side",
        "project_id",
        "site_id",
    ):
        assert yasak not in columns, yasak


def test_foreign_key_ondelete_behaviours():
    """CASCADE ile RESTRICT'in AYRIMI mali izin kendisidir: satır başlığın
    parçasıdır (CASCADE), hesap ise başka bir varlıktır ve satırı varken
    silinemez (RESTRICT) — CASCADE olsaydı hesabın silinmesi yevmiye satırlarını
    sessizce yok eder ve türetilmiş bakiye (K3) kaydığı fark edilmeden kayardı."""
    line_columns = JournalLine.__table__.columns
    (entry_fk,) = tuple(line_columns["entry_id"].foreign_keys)
    assert entry_fk.target_fullname == "journal_entries.id"
    assert entry_fk.ondelete == "CASCADE"

    (account_fk,) = tuple(line_columns["account_id"].foreign_keys)
    assert account_fk.target_fullname == "chart_of_accounts.id"
    assert account_fk.ondelete == "RESTRICT"

    entry_columns = JournalEntry.__table__.columns
    (reversal_fk,) = tuple(entry_columns["reversal_of_id"].foreign_keys)
    assert reversal_fk.target_fullname == "journal_entries.id"
    assert reversal_fk.ondelete == "RESTRICT"

    (user_fk,) = tuple(entry_columns["created_by_id"].foreign_keys)
    assert user_fk.target_fullname == "users.id"
    assert user_fk.ondelete == "RESTRICT"


def test_module_does_not_import_other_modules():
    """P10'un `cost_cards` import çemberi tekrarlanmaz: FK hedefleri STRING
    tablo adıyla verilir, `app.modules.users` import EDİLMEZ."""
    source = (BACKEND_DIR / "app" / "modules" / "accounting" / "models.py").read_text()
    assert "from app.modules." not in source
    assert "import app.modules." not in source


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
    # Head'in KİMLİĞİ iddia EDİLMEZ (repo kanonu): sonraki dilim head'i ileri
    # taşıdığında bu test ilgisiz yere kırılırdı.
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


def test_migration_parent_is_the_expected_revision():
    """🔴 Ebeveyn `c4d5e6f7a8b9` (HZ-1). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(MU1_REVISION)
    assert revision.down_revision == HZ1_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 İKİ yeni enum downgrade'de DÜŞER; düşmezse ikinci upgrade patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
                assert await _enum_labels(conn, enum_name) == EXPECTED_ENUM_LABELS[enum_name]
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            for constraint in CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert await _current_revision(conn) == MU1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", HZ1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # Komşu modüller AYAKTA: MU-1 hiçbir tabloya ADDITIVE kolon eklemez
            # (fatura/hazine → otomatik fiş MU-3'ün işidir).
            for komsu in ("invoices", "payments", "bank_accounts", "users"):
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == HZ1_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
            assert await _current_revision(conn) == MU1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


# --------------------------------------------------------------------------- #
# DB semantigi — K1'in SON savunmasi
# --------------------------------------------------------------------------- #


async def test_db_level_line_semantics():
    """🔴 K1 KATMAN 2 — satır ayağı. Servis 422 vermeyi unutsa bile:
    çift-dolu satır, `(0,0)` satırı, negatif tutar ve NULL tutar DB'ye GİREMEZ.

    NULL'ın ayrı iddia edilmesinin sebebi: `debit=NULL, credit=NULL` olan satır
    `SUM` tarafından YUTULUR, iki toplam da değişmez ve **dengesiz fiş dengede
    sayılır**. `single_side` CHECK'i bunu YAKALAMAZ (NULL karşılaştırması NULL
    üretir ve CHECK'i geçer) — kapatan şey `nullable=False`tır."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            account_id = await _insert_account(conn, "100")
            entry_id = await _insert_entry(conn, user_id)

            # Tek taraflı satırlar KABUL: borç bacağı ve alacak bacağı.
            await _insert_line(conn, entry_id, account_id, debit="100.00", credit="0")
            await _insert_line(conn, entry_id, account_id, debit="0", credit="100.00", sort_order=1)

            # Sunucu varsayılanları: iki taraf da 0 (satır tek taraflı CHECK'e
            # takılır, yani varsayılan tek başına bir satır AÇAMAZ).
            row = await conn.fetchrow(
                "SELECT debit, credit FROM journal_lines WHERE entry_id = $1 AND sort_order = 0",
                entry_id,
            )
            assert row["debit"] == 100
            assert row["credit"] == 0

            # 🔴 ÇİFT DOLU satır: E8'in her satırının boş tarafı `—`dir.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="50.00", credit="50.00")

            # 🔴 `(0,0)`: toplama katkısı olmayan satır fişi şişiremez.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="0", credit="0")

            # 🔴 NEGATİF tutar: bir borç satırına `-100` yazıp sahte denge
            # kurmak yapısal olarak imkânsızdır.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="-100.00", credit="0")
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line(conn, entry_id, account_id, debit="0", credit="-100.00")

            # 🔴 NULL tutar (fail-closed'un YAPISAL garantisi).
            for debit, credit in ((None, "100.00"), ("100.00", None), (None, None)):
                with pytest.raises(asyncpg.NotNullViolationError):
                    await _insert_line(conn, entry_id, account_id, debit=debit, credit=credit)

            # `account_id` RESTRICT: fiş satırı olan hesap SİLİNEMEZ.
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM chart_of_accounts WHERE id = $1", account_id)

            # `entry_id` CASCADE: başlık silinince satırlar gider.
            await conn.execute("DELETE FROM journal_entries WHERE id = $1", entry_id)
            kalan = await conn.fetchval(
                "SELECT count(*) FROM journal_lines WHERE entry_id = $1", entry_id
            )
            assert kalan == 0
            # Satırı kalmayan hesap artık silinebilir.
            await conn.execute("DELETE FROM chart_of_accounts WHERE id = $1", account_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_entry_semantics():
    """🔴 K1 KATMAN 2 — başlık ayağı + K9 dönem kilidi + K2 storno tekilliği.

    `total_*` NOT NULL'ın AYRI iddiası: nullable olsalardı `NULL = NULL` **NULL**
    üretir, `ck_journal_entries_posted_balanced` NULL sonucu REDDETMEZ ve
    dengesiz bir fiş `posted` damgalanabilirdi."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)

            # 🔴 Taslak DENGESİZ bırakılabilir: K1 kapısı kayıtlaştırma anında
            # yeniden koşar, taslak hâlâ yazılırken dengesiz olabilir.
            draft_id = await _insert_entry(
                conn, user_id, status="draft", total_debit="100.00", total_credit="0"
            )
            assert draft_id is not None

            # 🔴 DENGESİZ fiş `posted` OLAMAZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(
                    conn, user_id, status="posted", total_debit="100.00", total_credit="90.00"
                )

            # Dengeli fiş `posted` olur.
            posted_id = await _insert_entry(
                conn, user_id, status="posted", total_debit="100.00", total_credit="100.00"
            )

            # 🔴 `total_*` NOT NULL — nullable olsalardı denge CHECK'i sessizce
            # devre dışı kalırdı.
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    "UPDATE journal_entries SET total_credit = NULL WHERE id = $1", posted_id
                )

            # Negatif toplam REDDEDİLİR.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(
                    conn, user_id, total_debit="-1.00", total_credit="-1.00", status="draft"
                )

            # 🔴 K9: `entry_date` 2026-07-17 iken `period_month = 8` KAYAMAZ.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(conn, user_id, entry_date="2026-07-17", period_month=8)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_entry(conn, user_id, entry_date="2026-07-17", period_year=2025)
            # Doğru dönem KABUL (yıl sınırı dahil).
            await _insert_entry(
                conn, user_id, entry_date="2026-12-31", period_year=2026, period_month=12
            )

            # 🔴 Bir fişin en fazla BİR stornosu olur.
            await _insert_entry(
                conn,
                user_id,
                status="posted",
                total_debit="100.00",
                total_credit="100.00",
                reversal_of_id=posted_id,
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_entry(
                    conn,
                    user_id,
                    status="posted",
                    total_debit="100.00",
                    total_credit="100.00",
                    reversal_of_id=posted_id,
                )

            # 🔴 …ama stornosu OLMAYAN fiş sayısı SINIRSIZDIR: PG çok sayıda
            # NULL'a izin verir. Bu ayrıca iddia edilir, yoksa kısıt "her fişin
            # bir stornosu olmalı" diye yanlış anlaşılırdı.
            for _ in range(3):
                await _insert_entry(conn, user_id, reversal_of_id=None)
            null_sayisi = await conn.fetchval(
                "SELECT count(*) FROM journal_entries WHERE reversal_of_id IS NULL"
            )
            assert null_sayisi >= 4

            # RESTRICT: stornosu olan fiş ve fişi giren kullanıcı silinemez.
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM journal_entries WHERE id = $1", posted_id)
            with pytest.raises(RESTRICT_ERRORS):
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_account_code_semantics():
    """🔴 K4 kod dilbilgisi DB'de zorlanır. `NNN.NN.NNN` (üçüncü kırılım)
    hiçbir mockup'ta YOKTUR ve YAPISAL olarak reddedilir — açılsaydı mizanın
    (MU-2) hiç görmediği bir düzey doğardı. İlk hane `0` olamaz: sınıfsız hesap
    yoktur."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MU1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            # KABUL: grup `NN` · ana hesap `NNN` · alt hesap `NNN.NN`.
            for kod in ("10", "100", "120.01", "19", "191", "257", "600", "730", "999.99"):
                await _insert_account(conn, kod)

            # RET: tek hane (sınıf KAYIT DEĞİLDİR) · sıfırla başlayan · dört
            # hane · tek haneli kırılım · üçüncü kırılım · harf.
            for kod in (
                "0",
                "1",
                "01",
                "0.01",
                "1200",
                "120.1",
                "120.011",
                "120.01.001",
                "abc",
                "12a",
                "120,01",
                "",
                " 120",
            ):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_account(conn, kod)

            # 🔴 Aynı kod iki kez giremez: yevmiye satırları iki karta bölünür
            # ve bakiye (K3) ikiye ayrılırdı.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_account(conn, "100", name="Kasa 2")

            # `is_active` sunucu varsayılanı AÇIK (HP:62 yeşil nokta).
            aktif = await conn.fetchval(
                "SELECT is_active FROM chart_of_accounts WHERE code = '100'"
            )
            assert aktif is True

            # Dört tür de yazılabilir (HP:78/154/192/199).
            for i, tur in enumerate(("asset", "liability", "revenue", "expense")):
                await _insert_account(conn, f"{i + 2}00.01", account_type=tur)
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
