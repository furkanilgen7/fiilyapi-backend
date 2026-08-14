"""FAT-1 T1 — fatura şeması: model katmanı + migration tur dönüşü.

Spec: `docs/superpowers/specs/2026-08-14-fat1-fatura-cekirdegi-design.md` §2, §10.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration **DÖRT** yeni Postgres enum tipi
getiriyor. Bir tanesini bile downgrade'de düşürmeyi unutmak ikinci `upgrade`i
"type already exists" ile patlatır (`d4e5f6a7b8c9` dersi) ve bu **yalnız canlıda**
görülürdü — `Dockerfile` açılışta `alembic upgrade head` koşar, patlarsa uvicorn
hiç başlamaz (tam kesinti).

İkinci iddia kümesi DB SEMANTİĞİDİR: iki "en fazla biri dolu" CHECK'i (taraf ve
kaynak), yön içi numara tekilliği ve FK davranışları. Bunlar servis katmanının
SON savunmasıdır — servis 422 vermeyi unutsa bile para kaydı bozulmamalıdır.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (MK-1/MK-2/SA deseni).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceLine,
    InvoicePaymentMethod,
    InvoiceStatus,
)

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
MK3_REVISION = "a0b1c2d3e4f5"
FAT1_REVISION = "b1c2d3e4f5a6"

TABLES = ("invoices", "invoice_lines")

# Spec §10: DÖRDÜ DE YENİ — downgrade dördünü de düşürmek zorundadır.
NEW_ENUMS = (
    "invoice_direction",
    "invoice_document_type",
    "invoice_status",
    "invoice_payment_method",
)

EXPECTED_ENUM_LABELS = {
    "invoice_direction": ["outgoing", "incoming"],
    "invoice_document_type": ["einvoice", "earchive", "refund", "withholding"],
    # K1: "Vadeli" AYRI BİR DURUM DEĞİLDİR — `sent`in `due_date` doluyken
    # ekrandaki gösterimidir. K2: `draft` yalnız giden tarafta anlamlıdır.
    "invoice_status": ["draft", "sent", "collected", "pending", "approved", "disputed"],
    "invoice_payment_method": ["transfer", "cheque", "cash", "credit_card"],
}

INDEXES = (
    "ix_invoices_issue_date",
    "ix_invoices_project_id",
    "ix_invoices_status",
    # FK otomatik indeks üretmez; detay ucu her okumada kalemleri buradan süzer.
    "ix_invoice_lines_invoice_id",
)

CONSTRAINTS = (
    "uq_invoices_no_direction",
    "ck_invoices_single_party",
    "ck_invoices_single_source",
    "ck_invoices_amounts_non_negative",
    "ck_invoices_rates_percentage",
    "ck_invoice_lines_quantity_positive",
    "ck_invoice_lines_unit_price_non_negative",
    "ck_invoice_lines_vat_rate_percentage",
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


async def _current_revision(conn: asyncpg.Connection) -> str | None:
    return await conn.fetchval("SELECT version_num FROM alembic_version")


async def _create_scratch_database() -> str:
    database = f"invoicing_fat1_{uuid.uuid4().hex[:8]}"
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


async def _seed_project(conn: asyncpg.Connection) -> uuid.UUID:
    project_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
        "VALUES ($1, $2, 'Guneskent', 'active', 0, 0)",
        project_id,
        f"PRJ-{uuid.uuid4().hex[:6]}",
    )
    return project_id


async def _seed_employer(conn: asyncpg.Connection) -> uuid.UUID:
    employer_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO employers (id, name) VALUES ($1, 'Guneskent Gayrimenkul A.S.')",
        employer_id,
    )
    return employer_id


async def _seed_customer(conn: asyncpg.Connection) -> uuid.UUID:
    customer_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO customers (id, customer_type, name) VALUES ($1, 'person', 'Ali Veli')",
        customer_id,
    )
    return customer_id


async def _seed_supplier(conn: asyncpg.Connection) -> uuid.UUID:
    supplier_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO suppliers (id, name, payment_terms) VALUES ($1, 'Liebherr', 'days_30')",
        supplier_id,
    )
    return supplier_id


async def _seed_rental_invoice(conn: asyncpg.Connection, supplier_id: uuid.UUID) -> uuid.UUID:
    rental_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment_rental_invoices "
        "(id, supplier_id, period_year, period_month, rate_period) "
        "VALUES ($1, $2, 2026, 8, 'monthly')",
        rental_id,
        supplier_id,
    )
    return rental_id


async def _seed_purchase_order(
    conn: asyncpg.Connection,
    supplier_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    order_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO purchase_orders "
        "(id, order_no, supplier_id, project_id, total_amount, created_by_user_id) "
        "VALUES ($1, $2, $3, $4, 1000, $5)",
        order_id,
        f"SP-{uuid.uuid4().hex[:8]}",
        supplier_id,
        project_id,
        user_id,
    )
    return order_id


_INVOICE_INSERT = (
    "INSERT INTO invoices (id, direction, invoice_no, document_type, status, issue_date, "
    "party_name, subtotal, tax_base, vat_amount, total, created_by_id{extra_cols}) "
    "VALUES ($1, $2, $3, 'einvoice', $4, DATE '2026-08-14', 'Guneskent', "
    "0, 0, 0, 0, $5{extra_vals})"
)


async def _insert_invoice(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    *,
    direction: str = "outgoing",
    invoice_no: str = "FIL2026000184",
    status: str = "draft",
    extra: dict[str, object] | None = None,
) -> uuid.UUID:
    extra = extra or {}
    invoice_id = uuid.uuid4()
    names = list(extra)
    sql = _INVOICE_INSERT.format(
        extra_cols="".join(f", {n}" for n in names),
        extra_vals="".join(f", ${i}" for i in range(6, 6 + len(names))),
    )
    await conn.execute(sql, invoice_id, direction, invoice_no, status, user_id, *extra.values())
    return invoice_id


# --------------------------------------------------------------------------- #
# Model katmani — dort yeni enum
# --------------------------------------------------------------------------- #


def test_four_new_enums_match_spec_exactly():
    """Spec §2.1 birebir. Değerler DB'ye yazılır: sonradan düzeltmek bir enum
    TAKASI (migration) gerektirir, bu yüzden burada kilitli."""
    actual = {
        "invoice_direction": [e.value for e in InvoiceDirection],
        "invoice_document_type": [e.value for e in InvoiceDocumentType],
        "invoice_status": [e.value for e in InvoiceStatus],
        "invoice_payment_method": [e.value for e in InvoicePaymentMethod],
    }
    assert actual == EXPECTED_ENUM_LABELS


def test_status_enum_has_no_invented_members():
    """K1: `overdue`/`vadeli` AYRI DURUM DEĞİLDİR (türetilebilen SAKLANMAZ).
    Kapsam dışı olanlar da kolonlaşmaz: iptal/iade geçişi ve ödeme durumu
    (Hazine dilimi) bu dilimde YOKTUR."""
    values = {e.value for e in InvoiceStatus}
    for yasak in ("overdue", "due", "cancelled", "canceled", "refunded", "paid", "partial"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_invoice_columns_match_spec():
    """BİLEREK tam sayım: yeni bir kolon sessizce eklenemesin."""
    columns = Invoice.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "direction",
        "invoice_no",
        "document_type",
        "status",
        "issue_date",
        "due_date",
        "payment_method",
        "note",
        # K7 taraf snapshot'ı — canlı cari kartından OKUNMAZ.
        "party_name",
        "party_tax_number",
        "party_tax_office",
        "party_address",
        # Taraf izi (en fazla biri dolu).
        "employer_id",
        "customer_id",
        "supplier_id",
        "subcontractor_id",
        # Kaynak izi (en fazla biri dolu).
        "progress_payment_id",
        "subcontractor_progress_payment_id",
        "equipment_rental_invoice_id",
        "purchase_order_id",
        "project_id",
        "site_id",
        # Para — hepsi SAKLANIR (K7: okumada yeniden hesaplanmaz).
        "subtotal",
        "advance_rate",
        "advance_amount",
        "retention_rate",
        "retention_amount",
        "tax_base",
        "vat_amount",
        "withholding_rate",
        "withholding_amount",
        "total",
        "created_by_id",
        "created_at",
        "updated_at",
    }
    # FY:111 / FGE:72 — numara HER faturada vardır (giden'de sunucu, gelen'de
    # satıcı üretir); numarasız fatura hiçbir listede aranamazdı.
    assert not columns["invoice_no"].nullable
    assert columns["invoice_no"].type.length == 30
    assert not columns["issue_date"].nullable
    # FGI:68 vade opsiyoneldir; "kalan gün" TÜRETİLİR, saklanmaz.
    assert columns["due_date"].nullable
    # FK formunda ödeme şekli seçilmemiş olabilir.
    assert columns["payment_method"].nullable
    # K7: ünvan HER faturada donmuştur; cari kartı silinse bile fatura okunur.
    assert not columns["party_name"].nullable
    assert columns["party_name"].type.length == 200
    # TCKN 11 / VKN 10 — `customers` emsali.
    assert columns["party_tax_number"].type.length == 11
    assert columns["party_tax_office"].type.length == 100
    # §6: şirket geneli faturanın projesi YOKTUR (yalnız modül izniyle görünür).
    assert columns["project_id"].nullable
    assert columns["site_id"].nullable
    # RESTRICT değil CASCADE: görünürlük süzgecinin kolonu projeye BAĞLIDIR.
    assert not columns["created_by_id"].nullable


def test_invoice_money_columns_are_numeric_18_2_and_not_null():
    """K5: para `Numeric`, asla `float` — kuruş hassasiyeti. Hepsi NOT NULL'dır
    çünkü sunucu her yazmada hesaplar; NULL bir toplam "bilinmiyor" ile "sıfır"ı
    aynı yere düşürürdü (NULL-EŞİK kanonu)."""
    columns = Invoice.__table__.columns
    for para in (
        "subtotal",
        "advance_amount",
        "retention_amount",
        "tax_base",
        "vat_amount",
        "withholding_amount",
        "total",
    ):
        assert columns[para].type.precision == 18, para
        assert columns[para].type.scale == 2, para
        assert not columns[para].nullable, para

    # Oranlar NULLABLE'dır: FK:223/229/235 checkbox İŞARETSİZ olabilir — "kesinti
    # yok" ile "oran %0" farklı şeylerdir ve ekran ikisini ayrı basar.
    for oran in ("advance_rate", "retention_rate", "withholding_rate"):
        assert columns[oran].type.precision == 5, oran
        assert columns[oran].type.scale == 2, oran
        assert columns[oran].nullable, oran


def test_invoice_foreign_keys_match_spec():
    """Mali iz: cari/kaynak kayıtları RESTRICT (faturası olan kayıt silinemez) ·
    proje CASCADE (görünürlük kolonu) · şantiye SET NULL (bilgi alanı)."""
    columns = Invoice.__table__.columns
    beklenen = {
        "employer_id": ("employers.id", "RESTRICT"),
        "customer_id": ("customers.id", "RESTRICT"),
        "supplier_id": ("suppliers.id", "RESTRICT"),
        "subcontractor_id": ("subcontractors.id", "RESTRICT"),
        "progress_payment_id": ("progress_payments.id", "RESTRICT"),
        "subcontractor_progress_payment_id": (
            "subcontractor_progress_payments.id",
            "RESTRICT",
        ),
        "equipment_rental_invoice_id": ("equipment_rental_invoices.id", "RESTRICT"),
        "purchase_order_id": ("purchase_orders.id", "RESTRICT"),
        "project_id": ("projects.id", "CASCADE"),
        "site_id": ("sites.id", "SET NULL"),
        "created_by_id": ("users.id", "RESTRICT"),
    }
    for kolon, (hedef, ondelete) in beklenen.items():
        (fk,) = tuple(columns[kolon].foreign_keys)
        assert fk.target_fullname == hedef, kolon
        assert fk.ondelete == ondelete, kolon


def test_invoice_unique_is_direction_scoped():
    """Giden seri sunucunun, gelen seri satıcınındır — ikisi ÇAKIŞABİLİR.
    Global UNIQUE olsaydı satıcının `FIL…` serisi bizim numaramızı bloklardı."""
    (uq,) = [c for c in Invoice.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert uq.name == "uq_invoices_no_direction"
    assert [c.name for c in uq.columns] == ["direction", "invoice_no"]


def test_line_columns_match_spec():
    columns = InvoiceLine.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "invoice_id",
        "sort_order",
        "description",
        "unit",
        "quantity",
        "unit_price",
        "vat_rate",
        "line_total",
        "detail_note",
    }
    # FGI:116 — sırasız liste kullanıcı girdisini karıştırır (SA/T3 dersi).
    assert not columns["sort_order"].nullable
    assert not columns["description"].nullable
    # S3: birim SERBEST METİNDİR, enum değil (FK:169 input).
    assert columns["unit"].nullable
    assert columns["unit"].type.length == 20
    assert columns["quantity"].type.precision == 14
    assert columns["quantity"].type.scale == 3
    assert columns["unit_price"].type.precision == 18
    assert columns["unit_price"].type.scale == 2
    # 🔴 KDV SATIR BAZINDADIR (FGI:121) — başlıkta tek oran varsayılamaz (K3).
    assert not columns["vat_rate"].nullable
    assert columns["vat_rate"].type.precision == 5
    assert columns["vat_rate"].type.scale == 2
    # FK:183 salt okunur hesaplanan → sunucu yazar, NULL bırakılmaz.
    assert not columns["line_total"].nullable
    assert columns["detail_note"].type.length == 200


def test_line_invoice_fk_cascades():
    (fk,) = tuple(InvoiceLine.__table__.columns["invoice_id"].foreign_keys)
    assert fk.target_fullname == "invoices.id"
    assert fk.ondelete == "CASCADE"


def test_forbidden_columns_are_absent():
    """Spec §1 kapsam dışı + türev olan hiçbir şey KOLONLAŞMAZ.

    Hiçbir yazma yolu olmayan kolon her zaman NULL döner ve uydurma bir alan
    olur (spec §1). Türev kolon açılsaydı iki gerçek kaynak doğardı.
    """
    invoice_columns = set(Invoice.__table__.columns.keys())
    for yasak in (
        # FAT-3 e-Fatura: GİB/ETTN/zarf alanlarının YAZMA YOLU YOK.
        "uuid",
        "ettn",
        "envelope_no",
        "gib_status",
        # Hazine dilimi: tahsilat kaydı bu dilimde YOKTUR.
        "collected_amount",
        "paid_amount",
        "bank_account_id",
        # Para birimi/kur: TRY sabittir (madde 6).
        "currency",
        "exchange_rate",
        # TÜREV: "kalan gün" `due_date`ten, KDV farkı özet ucundan okunur.
        "remaining_days",
        "is_overdue",
        # İskonto üç kalem tablosunun hiçbirinde çizili değildir.
        "discount_rate",
        "discount_amount",
    ):
        assert yasak not in invoice_columns, yasak

    line_columns = set(InvoiceLine.__table__.columns.keys())
    for yasak in (
        # S2: poz AYRI ALAN DEĞİLDİR — açıklamaya gömülüdür (FK:178).
        "boq_item_id",
        "pos_no",
        "item_code",
        # İskonto sütunu YOK.
        "discount_rate",
        "discount_amount",
        # Satır KDV TUTARI türevdir; K3 dağıtımı başlıkta yapılır.
        "vat_amount",
    ):
        assert yasak not in line_columns, yasak


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
    """🔴 Ebeveyn `a0b1c2d3e4f5` (MK-3). Arada başka bir dilim merge edilirse
    re-parent ŞART — bu sabit ve migration BİRLİKTE güncellenir (P8/TH dersi)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    revision = script.get_revision(FAT1_REVISION)
    assert revision.down_revision == MK3_REVISION


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 DÖRT yeni enum downgrade'de DÜŞER; düşmezse ikinci upgrade patlar."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FAT1_REVISION, database=database)
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
            assert await _current_revision(conn) == FAT1_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", MK3_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # Komşu modüllerin tabloları AYAKTA: FAT-1 onlara DOKUNMAZ (bu dilim
            # hiçbir tabloya ADDITIVE kolon eklemez).
            for komsu in ("progress_payments", "equipment_rental_invoices", "purchase_orders"):
                assert await _table_exists(conn, komsu), komsu
            assert await _current_revision(conn) == MK3_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", FAT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            assert await _current_revision(conn) == FAT1_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_semantics():
    """DB SON SAVUNMADIR: yön içi tekillik · iki "en fazla biri" CHECK'i ·
    negatif tutar · oran aralığı · CASCADE/RESTRICT."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", FAT1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            user_id = await _seed_user(conn)
            project_id = await _seed_project(conn)
            employer_id = await _seed_employer(conn)
            customer_id = await _seed_customer(conn)
            supplier_id = await _seed_supplier(conn)
            rental_id = await _seed_rental_invoice(conn, supplier_id)
            order_id = await _seed_purchase_order(conn, supplier_id, project_id, user_id)

            invoice_id = await _insert_invoice(
                conn, user_id, extra={"employer_id": employer_id, "project_id": project_id}
            )

            # 🔴 Aynı YÖNDE aynı numara iki kez giremez (çift fatura kaydı).
            with pytest.raises(asyncpg.UniqueViolationError):
                await _insert_invoice(conn, user_id)

            # …ama TERS yönde aynı numara serbesttir: satıcının serisi bizimkini
            # bloklayamaz (S5).
            await _insert_invoice(conn, user_id, direction="incoming", status="pending")

            # 🔴 Taraf izi: en fazla BİRİ dolu. İkisi birden dolsaydı faturanın
            # cari karşılığı belirsizleşir, mali tablo iki yere birden düşerdi.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_invoice(
                    conn,
                    user_id,
                    invoice_no="FIL2026000185",
                    extra={"employer_id": employer_id, "customer_id": customer_id},
                )

            # 🔴 Kaynak izi: en fazla BİRİ dolu.
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_invoice(
                    conn,
                    user_id,
                    invoice_no="FIL2026000186",
                    extra={
                        "equipment_rental_invoice_id": rental_id,
                        "purchase_order_id": order_id,
                    },
                )

            # …tek kaynak serbesttir.
            await _insert_invoice(
                conn,
                user_id,
                invoice_no="FIL2026000187",
                extra={"purchase_order_id": order_id},
            )

            # Negatif tutar hiçbir okumada anlamlı değildir.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "UPDATE invoices SET total = -1 WHERE id = $1",
                    invoice_id,
                )

            # Oran %0..%100 dışına çıkamaz — %120 avans kesintisi matrahı negatife
            # düşürürdü.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "UPDATE invoices SET advance_rate = 120 WHERE id = $1", invoice_id
                )
            # NULL oran SERBESTTİR: kesinti işaretlenmemiş demektir.
            await conn.execute("UPDATE invoices SET advance_rate = NULL WHERE id = $1", invoice_id)

            # Kalem kısıtları.
            async def _insert_line(quantity: str, unit_price: str, vat_rate: str) -> None:
                await conn.execute(
                    "INSERT INTO invoice_lines "
                    "(id, invoice_id, sort_order, description, quantity, unit_price, "
                    "vat_rate, line_total) VALUES ($1, $2, 0, 'Beton', $3, $4, $5, 0)",
                    uuid.uuid4(),
                    invoice_id,
                    quantity,
                    unit_price,
                    vat_rate,
                )

            await _insert_line("12.5", "1850.00", "20")
            for bozuk in (("0", "1850.00", "20"), ("-1", "1850.00", "20")):
                with pytest.raises(asyncpg.CheckViolationError):
                    await _insert_line(*bozuk)
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line("1", "-1", "20")
            with pytest.raises(asyncpg.CheckViolationError):
                await _insert_line("1", "1", "101")

            # 🔴 RESTRICT: faturası olan işveren silinemez (mali iz). DAR tuple:
            # PG RESTRICT'i 23001, NO ACTION'ı 23503 bildirir (yerel 18 / CI 16).
            with pytest.raises((asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)):
                await conn.execute("DELETE FROM employers WHERE id = $1", employer_id)

            # CASCADE: fatura düşünce kalemleri düşer — yetim satır kalmaz.
            await conn.execute("DELETE FROM invoices WHERE id = $1", invoice_id)
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM invoice_lines WHERE invoice_id = $1", invoice_id
                )
            ) == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
