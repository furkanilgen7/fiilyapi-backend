"""HZ-1 T1 — hazine şeması: model katmanı + migration tur dönüşü.

Spec: `docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md` §2, §6.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration **İKİ** yeni Postgres enum tipi
getiriyor (`bank_account_type` / `payment_method_kind`). Birini bile downgrade'de
düşürmeyi unutmak ikinci `upgrade`i "type already exists" ile patlatır
(`d4e5f6a7b8c9` dersi) ve bu **yalnız canlıda** görülürdü — `Dockerfile` açılışta
`alembic upgrade head` koşar, patlarsa uvicorn hiç başlamaz (tam kesinti).

İkinci iddia kümesi DB SEMANTİĞİDİR: kısmi UNIQUE IBAN indeksi (Kasa satırları
NULL IBAN'ı çoklayabilir, dolu IBAN tekildir), `cash` tipinin ad zorunluluğu,
pozitif tutar CHECK'i ve iki RESTRICT FK'sı. Bunlar servis katmanının SON
savunmasıdır — servis 422/409 vermeyi unutsa bile para kaydı bozulmamalıdır.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (FAT-1/MK-1/SA deseni).

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — RESTRICT ihlali sürüme göre 23001 veya
23503 bildirir; iddialar bu yüzden DAR bir tuple ile iki sınıfı da kabul eder.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.treasury.models import BankAccount, BankAccountType, Payment, PaymentMethodKind

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
FAT1_REVISION = "b1c2d3e4f5a6"
HZ1_REVISION = "c4d5e6f7a8b9"

TABLES = ("bank_accounts", "payments")

# Spec §6: İKİSİ DE YENİ — downgrade ikisini de düşürmek zorundadır.
NEW_ENUMS = ("bank_account_type", "payment_method_kind")

EXPECTED_ENUM_LABELS = {
    # K1: E9'da YALNIZ `Vadesiz` ve `Kasa` çizili — `Vadeli`/`Kredi`/`POS`/
    # `Döviz` İCAT EDİLMEZ.
    "bank_account_type": ["checking", "cash"],
    # FGI:225-228 birebir: Banka Havalesi/EFT · Çek · Senet · Nakit.
    "payment_method_kind": ["transfer", "cheque", "promissory_note", "cash"],
}

INDEXES = (
    # Kısmi UNIQUE: Kasa satırlarının NULL IBAN'ı çoklanabilir.
    "uq_bank_accounts_iban",
    # Spec §2.2: `paid_on` indekslidir (nakit akışı ay penceresi buradan süzer).
    "ix_payments_paid_on",
    # FK'ler otomatik indeks ÜRETMEZ: fatura ödemeleri ve bakiye türetimi
    # (K2) bu iki sütundan geçer.
    "ix_payments_invoice_id",
    "ix_payments_bank_account_id",
)

CONSTRAINTS = (
    "ck_bank_accounts_cash_has_name",
    "ck_payments_amount_positive",
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


async def _index_definition(conn: asyncpg.Connection, name: str) -> str:
    return await conn.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname = $1", name)


async def _constraint_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", name
    )


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"treasury_hz1_{uuid.uuid4().hex[:8]}"
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


async def _seed_invoice(conn: asyncpg.Connection, user_id: uuid.UUID) -> uuid.UUID:
    invoice_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO invoices (id, direction, invoice_no, document_type, status, issue_date, "
        "party_name, subtotal, tax_base, vat_amount, total, created_by_id) "
        "VALUES ($1, 'outgoing', $2, 'einvoice', 'sent', DATE '2026-08-14', 'Guneskent', "
        "1000, 1000, 200, 1200, $3)",
        invoice_id,
        f"FIL{uuid.uuid4().hex[:10]}",
        user_id,
    )
    return invoice_id


async def _seed_bank_account(
    conn: asyncpg.Connection,
    *,
    account_type: str = "checking",
    iban: str | None = "TR330006100519786457841326",
    display_name: str | None = None,
) -> uuid.UUID:
    account_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO bank_accounts (id, bank_name, account_type, iban, display_name) "
        "VALUES ($1, 'Ziraat Bank', $2, $3, $4)",
        account_id,
        account_type,
        iban,
        display_name,
    )
    return account_id


# --------------------------------------------------------------------------- #
# Model katmani — iki yeni enum
# --------------------------------------------------------------------------- #


def test_two_new_enums_match_spec_exactly():
    """Spec §2 birebir. Değerler DB'ye yazılır: sonradan düzeltmek bir enum
    TAKASI (migration) gerektirir, bu yüzden burada kilitli."""
    actual = {
        "bank_account_type": [e.value for e in BankAccountType],
        "payment_method_kind": [e.value for e in PaymentMethodKind],
    }
    assert actual == EXPECTED_ENUM_LABELS


def test_account_type_has_no_invented_members():
    """🔴 K1: E9 yalnız `Vadesiz` (checking) ve `Kasa` (cash) çiziyor. Mockup'ın
    çizmediği hesap tipi İCAT EDİLMEZ — açılsaydı hiçbir ekranda karşılığı
    olmayan bir kümeyi kalıcı olarak DB'ye yazardık."""
    values = {e.value for e in BankAccountType}
    for yasak in ("time_deposit", "credit", "pos", "fx", "savings", "loan"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_bank_account_columns_match_spec():
    """BİLEREK tam sayım: yeni bir kolon sessizce eklenemesin."""
    columns = BankAccount.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "bank_name",
        "account_type",
        "iban",
        "display_name",
        "opening_balance",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert not columns["bank_name"].nullable
    assert columns["bank_name"].type.length == 100
    # E9:83 — Kasa satırında IBAN YOKTUR.
    assert columns["iban"].nullable
    assert columns["iban"].type.length == 34
    # E9:83 `Merkez Kasa` — Kasa'da IBAN yerine bu basılır.
    assert columns["display_name"].nullable
    assert columns["display_name"].type.length == 100
    # K2: bakiye SAKLANMAZ; saklanan TEK para alanı açılış bakiyesidir.
    assert not columns["opening_balance"].nullable
    assert columns["opening_balance"].type.precision == 18
    assert columns["opening_balance"].type.scale == 2
    # DELETE ucu servis düzeyinde 409 verir; kullanımdan kaldırma bayraktır.
    assert not columns["is_active"].nullable


def test_bank_account_has_no_derived_or_scope_columns():
    """🔴 K2 + K3. Bakiye TÜRETİLİR (`balance.py`) — kolonlaşsaydı iki eşzamanlı
    yazma/yarım rollback onu kaçınılmaz olarak kaydırırdı. Proje/şantiye FK'sı
    YOKTUR: E9'da hiçbir alan şantiye göstermiyor, hesap ŞİRKET GENELİDİR
    (`suppliers`/`customers` emsali) — erişim `treasury` izniyle denetlenir."""
    columns = set(BankAccount.__table__.columns.keys())
    for yasak in (
        "balance",
        "current_balance",
        "available_balance",
        "blocked_balance",
        "project_id",
        "site_id",
        # Şube / hesap no / SWIFT / kart rengi hiçbir yerde çizilmemiş.
        "branch",
        "account_no",
        "swift",
        "color",
        # Para birimi/kur: `₺` metne gömülü sabittir, seçici YOK.
        "currency",
        "exchange_rate",
    ):
        assert yasak not in columns, yasak


def test_payment_columns_match_spec():
    columns = Payment.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "invoice_id",
        "bank_account_id",
        "method",
        "amount",
        "paid_on",
        "note",
        "created_by_id",
        "created_at",
        "updated_at",
    }
    assert not columns["invoice_id"].nullable
    assert not columns["bank_account_id"].nullable
    # FGI:232-233 `Tahsil Edilen Tutar` — para `Numeric`, asla `float`.
    assert not columns["amount"].nullable
    assert columns["amount"].type.precision == 18
    assert columns["amount"].type.scale == 2
    # FGI:236-237 `Tahsilat Tarihi`.
    assert not columns["paid_on"].nullable
    assert columns["note"].nullable
    assert not columns["created_by_id"].nullable


def test_payment_has_no_direction_and_no_cheque_columns():
    """🔴 K4: yön AYRI KOLON DEĞİLDİR — bağlı faturanın `direction`'ından gelir;
    iki gerçek kaynak olsaydı biri diğerinden sapabilirdi. K11/spec §2.2:
    `method='cheque'` yalnız bir ETİKETTİR, çek VARLIĞI HZ-2'nin işidir —
    `cheque_id` açılsaydı olmayan bir tabloya bağ vaat ederdi."""
    columns = set(Payment.__table__.columns.keys())
    for yasak in ("direction", "kind", "cheque_id", "promissory_note_id", "cheque_no", "due_date"):
        assert yasak not in columns, yasak


def test_payment_foreign_keys_are_restrict():
    """Mali iz: ödemesi olan fatura/hesap/kullanıcı SİLİNEMEZ. CASCADE olsaydı
    bir cari kaydın silinmesi tahsilat geçmişini sessizce yok eder ve bakiye
    (K2) kendiliğinden kayardı."""
    columns = Payment.__table__.columns
    beklenen = {
        "invoice_id": "invoices.id",
        "bank_account_id": "bank_accounts.id",
        "created_by_id": "users.id",
    }
    for kolon, hedef in beklenen.items():
        (fk,) = tuple(columns[kolon].foreign_keys)
        assert fk.target_fullname == hedef, kolon
        assert fk.ondelete == "RESTRICT", kolon


def test_iban_unique_index_is_partial():
    """Kısmi olmasaydı İKİNCİ Kasa hesabı (NULL IBAN) açılamazdı — E9 tek Kasa
    çiziyor ama şirket birden çok kasa tutabilir (`customers.national_id`
    emsali)."""
    (index,) = [i for i in BankAccount.__table__.indexes if i.name == "uq_bank_accounts_iban"]
    assert index.unique
    assert [c.name for c in index.columns] == ["iban"]
    where = str(index.dialect_options["postgresql"]["where"])
    assert "iban IS NOT NULL" in where


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
    """🔴 Ebeveyn `b1c2d3e4f5a6` (FAT-1). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(HZ1_REVISION)
    assert revision.down_revision == FAT1_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 İKİ yeni enum downgrade'de DÜŞER; düşmezse ikinci upgrade patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", HZ1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
                assert await _enum_labels(conn, enum_name) == EXPECTED_ENUM_LABELS[enum_name]
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            # 🔴 Kısmilik YAPISAL olarak iddia edilir: PG'de düz bir UNIQUE
            # indeks de NULL'ları AYRI sayar (`NULLS DISTINCT` varsayılanı), bu
            # yüzden "iki NULL IBAN girebildi" testi kısmi ile tam UNIQUE'i
            # AYIRT ETMEZ — migration'dan `postgresql_where` düşse test yeşil
            # kalırdı. İddia bu yüzden indeks TANIMINA bakar.
            iban_indexdef = await _index_definition(conn, "uq_bank_accounts_iban")
            assert "UNIQUE" in iban_indexdef, iban_indexdef
            assert "WHERE (iban IS NOT NULL)" in iban_indexdef, iban_indexdef
            for constraint in CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert await _current_revision(conn) == HZ1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", FAT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # Komşu modüller AYAKTA: HZ-1 hiçbir tabloya ADDITIVE kolon eklemez
            # (K5: `invoices.paid_amount` AÇILMAZ).
            for komsu in ("invoices", "invoice_lines", "users"):
                assert await _table_exists(conn, komsu), komsu
            invoice_columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'invoices'"
            )
            assert "paid_amount" not in {row["column_name"] for row in invoice_columns}
            assert await _current_revision(conn) == FAT1_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", HZ1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            assert await _current_revision(conn) == HZ1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_semantics():
    """DB SON SAVUNMADIR: kısmi UNIQUE IBAN · Kasa'nın ad zorunluluğu · pozitif
    tutar · RESTRICT FK'ları · `opening_balance`/`is_active` varsayılanları."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", HZ1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            invoice_id = await _seed_invoice(conn, user_id)
            account_id = await _seed_bank_account(conn)

            # Sunucu varsayılanları: açılış 0, hesap aktif.
            row = await conn.fetchrow(
                "SELECT opening_balance, is_active FROM bank_accounts WHERE id = $1", account_id
            )
            assert row["opening_balance"] == 0
            assert row["is_active"] is True

            # 🔴 Aynı IBAN iki kez giremez — aynı hesap iki kart olarak açılırsa
            # bakiye (K2) iki yere birden düşerdi.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _seed_bank_account(conn)

            # …ama NULL IBAN ÇOKLANABİLİR: kısmi indeksin bütün amacı budur.
            await _seed_bank_account(
                conn, account_type="cash", iban=None, display_name="Merkez Kasa"
            )
            await _seed_bank_account(
                conn, account_type="cash", iban=None, display_name="Santiye Kasasi"
            )

            # 🔴 Kasa'nın adı ZORUNLUDUR: E9:83 IBAN yerine onu basar, boşsa
            # kart tamamen isimsiz görünürdü.
            with pytest.raises(asyncpg.CheckViolationError):
                await _seed_bank_account(conn, account_type="cash", iban=None, display_name=None)

            # Vadesiz hesapta ad OPSİYONELDİR (banka adı zaten basılır).
            await _seed_bank_account(conn, iban="TR100006200119000006672315", display_name=None)

            async def _insert_payment(amount: str, *, method: str = "transfer") -> uuid.UUID:
                payment_id = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO payments (id, invoice_id, bank_account_id, method, amount, "
                    "paid_on, created_by_id) VALUES ($1, $2, $3, $4, $5, DATE '2026-08-14', $6)",
                    payment_id,
                    invoice_id,
                    account_id,
                    method,
                    amount,
                    user_id,
                )
                return payment_id

            payment_id = await _insert_payment("1200.00")
            # Dört ödeme şeklinin dördü de yazılabilir (FGI:225-228).
            for method in ("cheque", "promissory_note", "cash"):
                await _insert_payment("0.01", method=method)

            # 🔴 Sıfır/negatif tahsilat: sıfır hiçbir şey ifade etmez, negatif
            # gizli bir iade olurdu (iade/avans kavramı MODELLENMEMİŞTİR).
            for bozuk in ("0", "-1"):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_payment(bozuk)

            # 🔴 RESTRICT: ödemesi olan fatura/hesap silinemez. DAR tuple —
            # PG RESTRICT'i 23001, NO ACTION'ı 23503 bildirir (yerel 18 / CI 16).
            restrict_hatalari = (asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)
            with pytest.raises(restrict_hatalari):
                await conn.execute("DELETE FROM invoices WHERE id = $1", invoice_id)
            with pytest.raises(restrict_hatalari):
                await conn.execute("DELETE FROM bank_accounts WHERE id = $1", account_id)
            with pytest.raises(restrict_hatalari):
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)

            # Ödeme silinince kısıt kalkar (uç 8: yanlış tahsilat geri alınabilir).
            await conn.execute("DELETE FROM payments WHERE invoice_id = $1", invoice_id)
            await conn.execute("DELETE FROM invoices WHERE id = $1", invoice_id)
            kalan = await conn.fetchval("SELECT count(*) FROM payments WHERE id = $1", payment_id)
            assert kalan == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
