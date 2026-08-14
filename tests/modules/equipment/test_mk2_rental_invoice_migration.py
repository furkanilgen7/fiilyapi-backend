"""MK-2 T1 — kira hakedişi şeması: model katmanı + migration tur dönüşü.

Spec: `docs/superpowers/specs/2026-08-14-mk2-kira-hakedisi-design.md` §2.1, §2.2, §5.

NEDEN AYRI BİR TUR DÖNÜŞÜ TESTİ: bu migration İKİ YENİ ENUM getiriyor ama
ÜÇÜNCÜ bir tipi (`equipment_rate_period`, MK-1'in malı) YALNIZCA KULLANIYOR.
Downgrade'in bu ayrımı karıştırması iki ayrı canlı kazası üretir:

* yeni tipleri düşürmeyi unutursa → ikinci `upgrade` "type already exists"
  (d4e5f6a7b8c9 dersi),
* MK-1'in tipini düşürürse → `equipment.rate_period` kolonu altından tip
  çekilir, MK-1'e downgrade bile edilemez.

İkisi de YALNIZ CANLIDA görülürdü; bu yüzden ikisi de burada iddia edilir.

Test kendi TEK KULLANIMLIK veritabanını açar ve sonunda düşürür; `.env` ve
`TEST_DATABASE_URL` veritabanı ELLENMEZ. Alembic alt süreçte koşturulur çünkü
`alembic/env.py` kendi `asyncio.run()` döngüsünü kurar (MK-1/İK-3/SA deseni).
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.core.config import settings
from app.modules.equipment.models import (
    DEFAULT_VAT_RATE,
    EquipmentRentalInvoice,
    EquipmentRentalInvoiceLine,
    RentalInvoiceStatus,
    RentalLineKind,
)

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
MK1_REVISION = "d7e8f9a0b1c2"
MK2_REVISION = "e8f9a0b1c2d3"

TABLES = ("equipment_rental_invoices", "equipment_rental_invoice_lines")

# Spec §5: İKİSİ DE YENİ — downgrade ikisini de düşürmek zorundadır.
NEW_ENUMS = ("rental_invoice_status", "rental_line_kind")

# 🔴 MK-1'in malı: MK-2 bu tipi KULLANIR, yaratmaz ve DÜŞÜRMEZ.
INHERITED_ENUM = "equipment_rate_period"

EXPECTED_ENUM_LABELS = {
    "rental_invoice_status": ["draft", "pending_verification", "approved", "paid"],
    "rental_line_kind": ["rented", "owned", "breakdown"],
}

INDEXES = (
    "ix_equipment_rental_invoices_supplier_id",
    "ix_equipment_rental_invoices_site_id",
    "ix_equipment_rental_invoices_status",
    "ix_equipment_rental_invoices_period",
    "ix_equipment_rental_invoice_lines_invoice_id",
    "ix_equipment_rental_invoice_lines_equipment_id",
)

UNIQUE_CONSTRAINTS = (
    "uq_equipment_rental_invoices_supplier_invoice_no",
    "uq_equipment_rental_invoice_lines_equipment_kind",
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
    database = f"equipment_mk2_{uuid.uuid4().hex[:8]}"
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


async def _seed_supplier(conn: asyncpg.Connection, name: str = "Kiralama A.Ş.") -> uuid.UUID:
    supplier_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO suppliers (id, name, payment_terms) VALUES ($1, $2, 'days_30')",
        supplier_id,
        name,
    )
    return supplier_id


async def _seed_equipment(conn: asyncpg.Connection, name: str = "Kule Vinç KV-01") -> uuid.UUID:
    equipment_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment (id, name, category) VALUES ($1, $2, 'crane')",
        equipment_id,
        name,
    )
    return equipment_id


async def _seed_invoice(
    conn: asyncpg.Connection,
    supplier_id: uuid.UUID,
    invoice_no: str | None = "FT-2026-001",
) -> uuid.UUID:
    invoice_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO equipment_rental_invoices "
        "(id, supplier_id, invoice_no, period_year, period_month, rate_period) "
        "VALUES ($1, $2, $3, 2026, 8, 'monthly')",
        invoice_id,
        supplier_id,
        invoice_no,
    )
    return invoice_id


# --------------------------------------------------------------------------- #
# Model katmani — iki yeni enum
# --------------------------------------------------------------------------- #


def test_two_new_enums_match_spec_exactly():
    """Spec §5 tablosu birebir. Değerler DB'ye yazılır: sonradan düzeltmek bir
    enum TAKASI (migration) gerektirir, bu yüzden burada kilitli."""
    actual = {
        "rental_invoice_status": [e.value for e in RentalInvoiceStatus],
        "rental_line_kind": [e.value for e in RentalLineKind],
    }
    assert actual == EXPECTED_ENUM_LABELS
    # K5: ayrı bir `rejected` durumu YOKTUR — reddetme `approved` →
    # `pending_verification` geri geçişidir (İK-3'ün red deseni).
    assert "rejected" not in {e.value for e in RentalInvoiceStatus}
    # K3: `owned`/`breakdown` HİÇBİR toplamın kaynağı değildir; üç değer de
    # ayrı satır tipi olduğu için tek bir "hariç" bayrağına indirgenemez.
    assert len(RentalLineKind) == 3


def test_rate_period_enum_is_not_redefined():
    """🔴 Spec §5: `equipment_rate_period` YENİDEN TANIMLANMAZ — MK-1'in tipi
    import edilir. İkinci bir Python enum'u aynı DB tipine iki farklı değer
    listesi iddia edebilirdi (`worker_source` dersi)."""
    from app.modules.equipment import models

    assert not hasattr(models, "RentalRatePeriod")
    column = EquipmentRentalInvoice.__table__.columns["rate_period"]
    assert column.type.name == "equipment_rate_period"


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_invoice_columns_match_spec():
    columns = EquipmentRentalInvoice.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "supplier_id",
        "invoice_no",
        "invoice_amount",
        "period_year",
        "period_month",
        "site_id",
        "rate_period",
        "vat_rate",
        "status",
        "approved_by_id",
        "approved_at",
        "paid_at",
        "created_at",
        "updated_at",
    }
    # K8: bir fatura TEK tedarikçiye aittir — tedarikçisiz fatura anlamsızdır.
    assert not columns["supplier_id"].nullable
    # M5:59/63 — taslakta fatura no ve tutar henüz bilinmeyebilir.
    assert columns["invoice_no"].nullable
    assert columns["invoice_amount"].nullable
    # M5:72 — dönem HER ZAMAN bilinir; dönemsiz fatura hiçbir aya düşmezdi.
    assert not columns["period_year"].nullable
    assert not columns["period_month"].nullable
    # M5:73 "Tüm Projeler" = NULL.
    assert columns["site_id"].nullable
    assert not columns["rate_period"].nullable
    # K1: oran VERİDİR, koda gömülmez (İK-3 `payroll_rates` dersi) — geçmiş
    # fatura KENDİ oranıyla okunabilir kalır.
    assert not columns["vat_rate"].nullable
    assert columns["vat_rate"].type.precision == 5
    assert columns["vat_rate"].type.scale == 2
    assert columns["vat_rate"].default.arg == DEFAULT_VAT_RATE
    # K10: para `Numeric`, asla `float`; kuruş hassasiyeti.
    assert columns["invoice_amount"].type.precision == 18
    assert columns["invoice_amount"].type.scale == 2


def test_invoice_foreign_keys_match_spec():
    """🔴 Mali iz: tedarikçi RESTRICT (faturası olan firma silinemez) · şantiye
    ve onaylayan kullanıcı SET NULL (bağ kopar, para izi ayakta kalır)."""
    columns = EquipmentRentalInvoice.__table__.columns
    (supplier_fk,) = tuple(columns["supplier_id"].foreign_keys)
    assert supplier_fk.target_fullname == "suppliers.id"
    assert supplier_fk.ondelete == "RESTRICT"

    (site_fk,) = tuple(columns["site_id"].foreign_keys)
    assert site_fk.target_fullname == "sites.id"
    assert site_fk.ondelete == "SET NULL"

    (approver_fk,) = tuple(columns["approved_by_id"].foreign_keys)
    assert approver_fk.target_fullname == "users.id"
    assert approver_fk.ondelete == "SET NULL"


def test_invoice_unique_constraint_is_supplier_and_invoice_no():
    """Aynı faturayı iki kez ödemeyi YAPISAL olarak engeller. `invoice_no` NULL
    iken Postgres'in varsayılan `NULLS DISTINCT` semantiği altında taslaklar
    serbesttir (`personnel.tc_no` emsali)."""
    (uq,) = [
        c
        for c in EquipmentRentalInvoice.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert uq.name == "uq_equipment_rental_invoices_supplier_invoice_no"
    assert [c.name for c in uq.columns] == ["supplier_id", "invoice_no"]


def test_line_columns_match_spec():
    columns = EquipmentRentalInvoiceLine.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "invoice_id",
        "equipment_id",
        "line_kind",
        "worked_hours",
        "breakdown_hours",
        "rate_amount",
        "invoiced_hours",
        "created_at",
        "updated_at",
    }
    # K2: SNAPSHOT — satır kurulurken kopyalanır, her okumada NOT NULL'dır.
    assert not columns["worked_hours"].nullable
    assert not columns["breakdown_hours"].nullable
    # M5:93/95 — ikisi de DÜZENLENEBİLİR ve boş bırakılabilir; boş `rate_amount`
    # maliyeti `null` yapar (MK-1 K16 fail-closed), 0 DEĞİL.
    assert columns["rate_amount"].nullable
    assert columns["invoiced_hours"].nullable
    for saat in ("worked_hours", "breakdown_hours", "invoiced_hours"):
        assert columns[saat].type.precision == 8, saat
        assert columns[saat].type.scale == 2, saat
    assert columns["rate_amount"].type.precision == 18
    assert columns["rate_amount"].type.scale == 2


def test_line_foreign_keys_match_spec():
    """Fatura CASCADE (yetim satır bırakılmaz) · ekipman RESTRICT (para izi olan
    makine silinemez, `payroll_lines`→`personnel` emsali)."""
    columns = EquipmentRentalInvoiceLine.__table__.columns
    (invoice_fk,) = tuple(columns["invoice_id"].foreign_keys)
    assert invoice_fk.target_fullname == "equipment_rental_invoices.id"
    assert invoice_fk.ondelete == "CASCADE"

    (equipment_fk,) = tuple(columns["equipment_id"].foreign_keys)
    assert equipment_fk.target_fullname == "equipment.id"
    assert equipment_fk.ondelete == "RESTRICT"


def test_line_unique_constraint_allows_two_kinds_per_equipment():
    """M5 aynı makineyi `rented` ve `breakdown` olarak İKİ AYRI satır çiziyor;
    UQ `line_kind`i içermeseydi arıza satırı sessizce reddedilirdi."""
    (uq,) = [
        c
        for c in EquipmentRentalInvoiceLine.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert uq.name == "uq_equipment_rental_invoice_lines_equipment_kind"
    assert [c.name for c in uq.columns] == ["invoice_id", "equipment_id", "line_kind"]


def test_forbidden_columns_are_absent():
    """K4/K6 — para ve fark TÜREVDİR, kolonlaşmaz (P10 "tek formül" kanonu).

    Kolon açılsaydı iki gerçek kaynak doğar ve biri güncellenmediğinde ödenecek
    tutar sessizce ayrışırdı.
    """
    line_columns = set(EquipmentRentalInvoiceLine.__table__.columns.keys())
    for yasak in (
        # 🔴 K4: `worked_hours × saatlik bedel` her okumada MK-1'in `cost.py`sinden
        # türetilir.
        "our_amount",
        "amount",
        "total_amount",
        # K6: fark bir DURUM değil, TÜREV alandır.
        "hours_variance",
        "variance_status",
        # K3: katılım `line_kind`ten okunur — ikinci bir bayrak çelişebilirdi.
        "is_excluded",
        "is_billable",
    ):
        assert yasak not in line_columns, yasak

    invoice_columns = set(EquipmentRentalInvoice.__table__.columns.keys())
    for yasak in (
        # K1: KDV tutarı ve ödenecek toplam `invoice_amount` + `vat_rate`ten türer.
        "vat_amount",
        "payable_total",
        # MK-1 K15: toplamlar SATIRLARDAN türer.
        "our_total",
        "owned_total",
        "excluded_breakdown_amount",
        # K5: ayrı bir red durumu/kolonu YOKTUR.
        "rejected_at",
        "is_rejected",
    ):
        assert yasak not in invoice_columns, yasak


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
    # Head'in KİMLİĞİ iddia EDİLMEZ (repo kanonu — P11/ST dersi): sonraki dilim
    # head'i ileri taşıdığında bu test ilgisiz yere kırılırdı. MK-2'nin kendi
    # revizyonu aşağıdaki tur dönüşünde AÇIKÇA kullanılır.
    assert len(heads) == 1, f"tek head bekleniyordu, çıktı:\n{result.stdout}"


async def test_upgrade_downgrade_upgrade_round_trip():
    """🔴 İki YENİ enum downgrade'de DÜŞER, `equipment_rate_period` DÜŞMEZ."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert await _enum_exists(conn, enum_name), enum_name
                assert await _enum_labels(conn, enum_name) == EXPECTED_ENUM_LABELS[enum_name]
            for index in INDEXES:
                assert await _index_exists(conn, index), index
            for constraint in UNIQUE_CONSTRAINTS:
                assert await _constraint_exists(conn, constraint), constraint
            assert await _current_revision(conn) == MK2_REVISION
        finally:
            await conn.close()

        _run_alembic("downgrade", MK1_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                # Kalan bir tablo İKİNCİ upgrade'i "already exists" ile patlatırdı.
                assert not await _table_exists(conn, table), table
            for enum_name in NEW_ENUMS:
                assert not await _enum_exists(conn, enum_name), (
                    f"{enum_name} tipi downgrade'de kalmış — ikinci upgrade patlar"
                )
            # 🔴 MK-1'in tipi AYAKTA: `equipment.rate_period` kolonu ona bağlı,
            # düşürülseydi MK-1'e downgrade bile edilemezdi.
            assert await _enum_exists(conn, INHERITED_ENUM), (
                f"{INHERITED_ENUM} MK-1'in malıdır, MK-2 downgrade'i ona DOKUNMAZ"
            )
            assert await _table_exists(conn, "equipment")
            assert await _current_revision(conn) == MK1_REVISION
        finally:
            await conn.close()

        _run_alembic("upgrade", MK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            for table in TABLES:
                assert await _table_exists(conn, table), table
            assert await _current_revision(conn) == MK2_REVISION
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)


async def test_db_level_semantics():
    """DB seviyesinde: UQ'lar (NULLS DISTINCT dahil) · CASCADE · RESTRICT ·
    `vat_rate` sunucu varsayılanı · dönem ayı aralığı."""
    database = await _create_scratch_database()
    try:
        _run_alembic("upgrade", MK2_REVISION, database=database)
        conn = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            supplier_id = await _seed_supplier(conn)
            equipment_id = await _seed_equipment(conn)
            invoice_id = await _seed_invoice(conn, supplier_id)

            # K1: oran sunucu varsayılanından gelir (%20) ve KOLONDUR.
            assert (
                await conn.fetchval(
                    "SELECT vat_rate FROM equipment_rental_invoices WHERE id = $1", invoice_id
                )
            ) == DEFAULT_VAT_RATE
            # K5: varsayılan durum `draft`.
            assert (
                await conn.fetchval(
                    "SELECT status::text FROM equipment_rental_invoices WHERE id = $1", invoice_id
                )
            ) == "draft"

            # 🔴 Aynı tedarikçiden aynı fatura no İKİ KEZ giremez.
            with pytest.raises(asyncpg.UniqueViolationError):
                await _seed_invoice(conn, supplier_id)

            # …ama `invoice_no` NULL iken çok taslak serbesttir (NULLS DISTINCT).
            await _seed_invoice(conn, supplier_id, invoice_no=None)
            await _seed_invoice(conn, supplier_id, invoice_no=None)

            # Dönem ayı 1..12 dışına çıkamaz — 13. ay hiçbir dönemde okunamazdı.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "INSERT INTO equipment_rental_invoices "
                    "(id, supplier_id, period_year, period_month, rate_period) "
                    "VALUES ($1, $2, 2026, 13, 'monthly')",
                    uuid.uuid4(),
                    supplier_id,
                )

            # M5: aynı makine hem `rented` hem `breakdown` satırı taşıyabilir.
            for kind in ("rented", "breakdown"):
                await conn.execute(
                    "INSERT INTO equipment_rental_invoice_lines "
                    "(id, invoice_id, equipment_id, line_kind, worked_hours) "
                    "VALUES ($1, $2, $3, $4, 186)",
                    uuid.uuid4(),
                    invoice_id,
                    equipment_id,
                    kind,
                )
            # …ama aynı türden İKİNCİ satır taşıyamaz.
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO equipment_rental_invoice_lines "
                    "(id, invoice_id, equipment_id, line_kind, worked_hours) "
                    "VALUES ($1, $2, $3, 'rented', 12)",
                    uuid.uuid4(),
                    invoice_id,
                    equipment_id,
                )

            # K2 taban değeri: `breakdown_hours` sunucu varsayılanı 0'dır (M5:92).
            assert (
                await conn.fetchval(
                    "SELECT breakdown_hours FROM equipment_rental_invoice_lines "
                    "WHERE invoice_id = $1 AND line_kind = 'rented'",
                    invoice_id,
                )
            ) == 0

            # Negatif saat/bedel hiçbir okumada anlamlı değildir.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "INSERT INTO equipment_rental_invoice_lines "
                    "(id, invoice_id, equipment_id, line_kind, worked_hours) "
                    "VALUES ($1, $2, $3, 'owned', -1)",
                    uuid.uuid4(),
                    invoice_id,
                    equipment_id,
                )

            # 🔴 RESTRICT: satırı olan ekipman silinemez (para izi). DAR tuple:
            # PG RESTRICT'i 23001, NO ACTION'ı 23503 bildirir (yerel 18 / CI 16).
            with pytest.raises((asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)):
                await conn.execute("DELETE FROM equipment WHERE id = $1", equipment_id)

            # 🔴 RESTRICT: faturası olan tedarikçi silinemez (mali iz).
            with pytest.raises((asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)):
                await conn.execute("DELETE FROM suppliers WHERE id = $1", supplier_id)

            # CASCADE: fatura düşünce satırları düşer — yetim satır kalmaz.
            await conn.execute("DELETE FROM equipment_rental_invoices WHERE id = $1", invoice_id)
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM equipment_rental_invoice_lines WHERE invoice_id = $1",
                    invoice_id,
                )
            ) == 0
        finally:
            await conn.close()
    finally:
        await _drop_scratch_database(database)
