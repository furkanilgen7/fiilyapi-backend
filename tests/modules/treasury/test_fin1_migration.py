"""FIN-1 T2 — çek/senet şeması: model katmanı + migration tur dönüşü.

Görev emri K1/K2/K3/K4. Kardeşi `test_hz1_migration.py`dır ve ondan İKİ noktada
ayrılır:

1. **ÜÇ yeni Postgres enum tipi** gelir (`financial_instrument_kind` ·
   `financial_instrument_direction` · `financial_instrument_status`). Birini bile
   downgrade'de düşürmeyi unutmak ikinci `upgrade`i "type already exists" ile
   patlatır (`d4e5f6a7b8c9` dersi) ve bu YALNIZ canlıda görülürdü — `Dockerfile`
   açılışta `alembic upgrade head` koşar, patlarsa uvicorn hiç başlamaz.
2. Bu migration **var olan bir tabloya kolon EKLER** (`payments.
   financial_instrument_id`, K4). Downgrade o kolonu DÜŞÜRMEK zorundadır; kalırsa
   ikinci upgrade "column already exists" ile patlar. Kolonun `SET NULL` ve
   **nullable** olduğu ayrıca iddia edilir: K4'ün asıl kararı budur — zorunlu
   kılınsaydı bugünkü (hepsi boş) ödeme kayıtları geçersizleşirdi.

⚠️ PG SÜRÜM TUZAĞI: yerel 18, CI 16 — kısıt ihlalleri sürüme göre farklı SQLSTATE
bildirebilir; iddialar bu yüzden DAR tuple'larla iki sınıfı da kabul eder.
"""

import os
import subprocess
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.treasury.models import (
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    Payment,
)

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ (repo kanonu).
# 🔴 Arada başka bir dilim merge edilirse re-parent ŞART ve bu sabit de
# migration ile BİRLİKTE güncellenir — tek satır YETMEZ (P8/TH dersi).
BOQSEC_REVISION = "b4c5d6e7f8a9"
FIN1_REVISION = "d8e9f0a1b2c3"

NEW_TABLE = "financial_instruments"

#: ÜÇÜ DE YENİ — downgrade üçünü de düşürmek zorundadır.
NEW_ENUMS = (
    "financial_instrument_kind",
    "financial_instrument_direction",
    "financial_instrument_status",
)

EXPECTED_ENUM_LABELS = {
    # K1: E10 sekmesi "Senetler" — iki üye, başka tip İCAT EDİLMEZ.
    "financial_instrument_kind": ["cheque", "promissory_note"],
    # E10:94-96 sekmeleri: "Alınan Çekler" / "Verilen Çekler".
    "financial_instrument_direction": ["received", "issued"],
    # K2 birebir. 🔴 `due`/`overdue` YOKTUR — "Vadede" bir DURUM DEĞİL TÜREVDİR.
    "financial_instrument_status": ["portfolio", "collected", "paid", "returned", "cancelled"],
}

INDEXES = (
    # Emir K1: liste sekmeleri (Alınan/Verilen) + durum süzgeci bu ikiliden geçer.
    "ix_financial_instruments_direction_status",
    # Vade penceresi (`is_due`, `due_this_month`) ve `due_before/after` süzgeci.
    "ix_financial_instruments_due_date",
    # "Senetler" sekmesi.
    "ix_financial_instruments_instrument_kind",
    # 🔴 EMRİN LİSTESİNE EK: kapsam süzgeci (`project_id IS NULL OR IN (...)`)
    # HER liste/sayım sorgusunda koşar (`invoicing.scope_clause` emsali) —
    # FK'ler otomatik indeks ÜRETMEZ.
    "ix_financial_instruments_project_id",
    # K4: ödeme satırından çeke bağ; `payments` büyük bir tablodur.
    "ix_payments_financial_instrument_id",
)

CONSTRAINTS = (
    "ck_financial_instruments_amount_positive",
    "ck_financial_instruments_due_after_issue",
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


async def _constraint_exists(conn: asyncpg.Connection, name: str) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = $1)", name
    )


async def _column_names(conn: asyncpg.Connection, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
    )
    return {row["column_name"] for row in rows}


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"treasury_fin1_{uuid.uuid4().hex[:8]}"
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


async def _seed_project(conn: asyncpg.Connection) -> uuid.UUID:
    project_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, code, name, status, budget, progress_pct, project_type) "
        "VALUES ($1, $2, 'Guneskent Konut', 'active', 1000000, 0, 'taahhut')",
        project_id,
        f"FIN{uuid.uuid4().hex[:6].upper()}",
    )
    return project_id


async def _seed_bank_account(conn: asyncpg.Connection) -> uuid.UUID:
    account_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO bank_accounts (id, bank_name, account_type, iban) "
        "VALUES ($1, 'Ziraat Bank', 'checking', $2)",
        account_id,
        f"TR{uuid.uuid4().int % 10**24:024d}",
    )
    return account_id


async def _insert_instrument(
    conn: asyncpg.Connection,
    *,
    amount: str = "1200000.00",
    issue_date: str = "2026-07-01",
    due_date: str = "2026-07-25",
    project_id: uuid.UUID | None = None,
    bank_account_id: uuid.UUID | None = None,
    serial_no: str = "0123456789",
) -> uuid.UUID:
    instrument_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO financial_instruments (id, instrument_kind, direction, serial_no, "
        "drawer_name, issue_date, due_date, amount, status, project_id, bank_account_id) "
        "VALUES ($1, 'cheque', 'received', $2, 'Guneskent A.S.', $3, $4, $5, "
        "'portfolio', $6, $7)",
        instrument_id,
        serial_no,
        date.fromisoformat(issue_date),
        date.fromisoformat(due_date),
        Decimal(amount),
        project_id,
        bank_account_id,
    )
    return instrument_id


# --------------------------------------------------------------------------- #
# Model katmani — uc yeni enum
# --------------------------------------------------------------------------- #


def test_three_new_enums_match_spec_exactly():
    """K1/K2 birebir. Değerler DB'ye yazılır: sonradan düzeltmek bir enum TAKASI
    (migration) gerektirir, bu yüzden burada kilitli."""
    actual = {
        "financial_instrument_kind": [e.value for e in FinancialInstrumentKind],
        "financial_instrument_direction": [e.value for e in FinancialInstrumentDirection],
        "financial_instrument_status": [e.value for e in FinancialInstrumentStatus],
    }
    assert actual == EXPECTED_ENUM_LABELS


def test_status_enum_has_no_derived_member():
    """🔴 K2'nin ASIL kararı: mockup'ın "Vadede" rozeti (E10:121,148) bir enum
    üyesi DEĞİL TÜREVDİR.

    Enum'a konsaydı her gün bir cron'un satırları güncellemesi gerekirdi;
    zamanla değişen bir olguyu kalıcı kolona yazmak BAYATLAR — ertesi gün yanlış
    rozet basar ve kimse fark etmez. `overdue`/`due_soon` da aynı sınıftır.
    """
    values = {e.value for e in FinancialInstrumentStatus}
    for yasak in ("due", "due_soon", "overdue", "in_due", "vadede", "pending"):
        assert yasak not in values, yasak


def test_kind_enum_matches_payment_method_labels_but_is_a_separate_type():
    """`PaymentMethodKind` ile ETİKET kümesi çakışır, TİP çakışmaz.

    Ödeme şekli dört üyelidir (`transfer`/`cheque`/`promissory_note`/`cash`);
    çek/senet varlığı yalnız ikisini taşır. Tek tipte birleştirmek portföye
    "Nakit çek" gibi bir üye vaat ederdi.
    """
    from app.modules.treasury.models import PaymentMethodKind

    assert {e.value for e in FinancialInstrumentKind} < {e.value for e in PaymentMethodKind}
    assert FinancialInstrumentKind is not PaymentMethodKind


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_financial_instrument_columns_match_the_order():
    """BİLEREK tam sayım (K1 tablosu): yeni bir kolon sessizce eklenemesin."""
    columns = FinancialInstrument.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "instrument_kind",
        "direction",
        "serial_no",
        "drawer_name",
        "description",
        "bank_name",
        "issue_date",
        "due_date",
        "amount",
        "status",
        "project_id",
        "bank_account_id",
        "created_at",
        "updated_at",
    }
    # E10:105 "Keşideci" — satırın kimliğidir, boş bırakılamaz.
    assert not columns["drawer_name"].nullable
    # E10:116 keşidecinin altındaki gri satır ("Proje iş avansı") — opsiyonel.
    assert columns["description"].nullable
    # Senette BANKA olmayabilir (E10:106 sütunu çekler için doludur).
    assert columns["bank_name"].nullable
    assert not columns["issue_date"].nullable
    assert not columns["due_date"].nullable
    # Para `Numeric(18, 2)` — asla `float`.
    assert not columns["amount"].nullable
    assert columns["amount"].type.precision == 18
    assert columns["amount"].type.scale == 2
    # Bilgi bağları: ikisi de opsiyoneldir (K1).
    assert columns["project_id"].nullable
    assert columns["bank_account_id"].nullable


def test_financial_instrument_has_no_derived_columns():
    """🔴 K2: "Vadede" TÜREVDİR — kolonlaşsaydı ertesi gün bayatlardı.

    KPI toplamları (K8) da kolonlaşmaz: dördü de sorgudan türer ve saklanan bir
    kopya ilk durum geçişinde sessizce ayrışırdı (`bank_accounts.balance`
    kanonunun aynısı).
    """
    columns = set(FinancialInstrument.__table__.columns.keys())
    for yasak in (
        "is_due",
        "due_flag",
        "days_remaining",
        "is_overdue",
        "collected_at",
        "currency",
        "exchange_rate",
    ):
        assert yasak not in columns, yasak


def test_information_links_are_set_null_not_cascade():
    """🔴 K4'ün kardeşi: proje/hesap bir BİLGİ BAĞIDIR, varlığın parçası değil.

    CASCADE olsaydı bir projenin silinmesi elimizdeki ÇEKİ de yok ederdi —
    portföy bir envanterdir ve projeden bağımsız yaşar (BOQ-SEC-B'deki
    varlık-parçası → CASCADE ayrımının öbür tarafı).
    """
    columns = FinancialInstrument.__table__.columns
    for kolon, hedef in (("project_id", "projects.id"), ("bank_account_id", "bank_accounts.id")):
        (fk,) = tuple(columns[kolon].foreign_keys)
        assert fk.target_fullname == hedef, kolon
        assert fk.ondelete == "SET NULL", kolon


def test_serial_no_has_no_unique_constraint():
    """🔴 K3 — ve bu BİLİNÇLİDİR.

    Farklı bankaların çek numaraları çakışabilir; aynı numara alınan ve verilen
    tarafta ayrı ayrı bulunabilir. Mükerrer uyarısı bir ÜRÜN kararıdır, veri
    kısıtı değil. UNIQUE konsaydı meşru bir kayıt hiç girilemezdi.
    """
    tablo = FinancialInstrument.__table__
    tekil_indeksler = [i.name for i in tablo.indexes if i.unique]
    assert tekil_indeksler == [], tekil_indeksler
    serial_kisitlari = [
        c.name
        for c in tablo.constraints
        if "serial_no" in {col.name for col in getattr(c, "columns", [])}
    ]
    assert serial_kisitlari == [], serial_kisitlari


def test_payments_gains_optional_instrument_link():
    """🔴 K4: FK açılır — SET NULL, **nullable**, indeksli.

    Nullable olması kararın TA KENDİSİDİR: `method='cheque'` iken doluluğu
    ZORUNLU kılmak bugünkü kayıtların hepsini (migration onları dolduramaz)
    geçersizleştirirdi. Ödeme kaydı çekten bağımsız bir olgudur; çek silinse de
    ödeme ayakta kalmalıdır → SET NULL.
    """
    kolon = Payment.__table__.columns["financial_instrument_id"]
    assert kolon.nullable
    (fk,) = tuple(kolon.foreign_keys)
    assert fk.target_fullname == "financial_instruments.id"
    assert fk.ondelete == "SET NULL"


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #


def test_alembic_has_single_head():
    """İki head = canlıda deploy kilitlenmesi (`alembic upgrade head` patlar ve
    `Dockerfile`ın `&&` zinciri uvicorn'u hiç başlatmaz)."""
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
    """🔴 Ebeveyn `b4c5d6e7f8a9` (BOQ-SEC-B). Arada başka bir dilim merge
    edilirse re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(FIN1_REVISION)
    assert revision.down_revision == BOQSEC_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 ÜÇ yeni enum + EKLENEN KOLON downgrade'de DÜŞER.

    Enum kalırsa ikinci upgrade "type already exists", kolon kalırsa "column
    already exists" ile patlar — ikisi de YALNIZ canlıda görülürdü.
    """
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FIN1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _table_exists(conn, NEW_TABLE)
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
                assert await _enum_labels(conn, enum_name) == EXPECTED_ENUM_LABELS[enum_name]
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            for constraint in CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert "financial_instrument_id" in await _column_names(conn, "payments")
            assert await _current_revision(conn) == FIN1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", BOQSEC_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert not await _table_exists(conn, NEW_TABLE)
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # 🔴 EKLENEN KOLON da düşmeli.
            assert "financial_instrument_id" not in await _column_names(conn, "payments")
            # Komşu tablolar AYAKTA: FIN-1 `payments`ı düşürmez, yalnız kolonunu geri alır.
            for komsu in ("payments", "bank_accounts", "invoices", "projects"):
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == BOQSEC_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", FIN1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            assert await _table_exists(conn, NEW_TABLE)
            assert "financial_instrument_id" in await _column_names(conn, "payments")
            assert await _current_revision(conn) == FIN1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_semantics():
    """DB SON SAVUNMADIR: pozitif tutar · `due_date >= issue_date` · SET NULL
    davranışı · `serial_no`nun MÜKERRER olabilmesi · durum varsayılanı."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FIN1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            project_id = await _seed_project(conn)
            account_id = await _seed_bank_account(conn)
            instrument_id = await _insert_instrument(
                conn, project_id=project_id, bank_account_id=account_id
            )

            # 🔴 K3: AYNI numara ikinci kez girebilir (farklı banka / öbür yön).
            await _insert_instrument(conn, serial_no="0123456789")

            # 🔴 Sıfır/negatif tutar: sıfır hiçbir şey ifade etmez, negatif gizli
            # bir ters kayıt olurdu.
            for bozuk in ("0", "-1"):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_instrument(conn, amount=bozuk)

            # 🔴 Vade keşide tarihinden ÖNCE olamaz — sessizce kabul edilseydi
            # vade raporu bozulurdu (servis 422 vermeyi unutsa bile DB tutar).
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_instrument(conn, issue_date="2026-07-25", due_date="2026-07-01")

            # Aynı gün MEŞRUDUR: görüldüğünde ödenen çek.
            await _insert_instrument(conn, issue_date="2026-07-25", due_date="2026-07-25")

            # 🔴 SET NULL: proje silinince ÇEK AYAKTA KALIR, yalnız bağ kopar.
            await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
            kalan = await conn.fetchrow(
                "SELECT project_id, status FROM financial_instruments WHERE id = $1", instrument_id
            )
            assert kalan is not None, "proje silinince çek de silindi — CASCADE kaçağı"
            assert kalan["project_id"] is None
            assert kalan["status"] == "portfolio"

            # Banka hesabı da aynı sınıftır.
            await conn.execute("DELETE FROM bank_accounts WHERE id = $1", account_id)
            assert (
                await conn.fetchval(
                    "SELECT bank_account_id FROM financial_instruments WHERE id = $1",
                    instrument_id,
                )
                is None
            )
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
