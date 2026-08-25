"""MU-1 T2 — muhasebe şeması testlerinin PAYLAŞILAN kurulumu.

Dosya 800 satır tavanını aştığı için bölündü (`_journal.py` emsali): yardımcılar
KOPYALANMADI, buraya alındı — iki kopya olsaydı biri güncellenip öteki kalır ve
iki dosya AYNI ismi taşıyan FARKLI gövdelerle koşardı.

Kullanan dosyalar: `test_mu1_migration.py` (model katmanı) ·
`test_mu1_migration_db.py` (migration tur dönüşü + DB semantiği).
Hiçbir testin iddiası bu bölmeyle değişmedi.
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

BACKEND_DIR = Path(__file__).parents[3]
ALEMBIC_CMD = (sys.executable, "-m", "alembic")

# Revizyonlara AÇIKÇA çıkılır; `head` / `-1` KULLANILMAZ — sonraki dilimler
# revizyon ekledikçe bu test sessizce yanlış şeyi ölçerdi.
HZ1_REVISION = "c4d5e6f7a8b9"
MU1_REVISION = "d5e6f7a8b9c0"

TABLES = ("chart_of_accounts", "journal_entries", "journal_lines")

# Spec §3: İKİSİ DE YENİ — downgrade ikisini de düşürmek zorundadır.
NEW_ENUMS = ("chart_account_type", "journal_entry_status")

#: 🔴 Bu sözlük **MU-1 REVİZYONUNDAKİ DB hâlini** tarif eder, modelin BUGÜNKÜ
#: hâlini DEĞİL. `d5e6f7a8b9c0`a çıkan bir veritabanında `chart_account_type`
#: hâlâ DÖRT üyelidir; beşinci üye (`equity`) MT-1'in `c8d9e0f1a2b3`
#: migration'ıyla gelir. İkisi karıştırılırsa bu test, ölçtüğünü sandığı şeyi
#: değil sonraki dilimlerin şemasını ölçmeye başlar.
EXPECTED_ENUM_LABELS = {
    # HP:60 `Tür` sütununun MU-1'deki kümesi: Aktif · Pasif · Gelir · Gider.
    "chart_account_type": ["asset", "liability", "revenue", "expense"],
    # K2: draft → posted → reversed (`reversed` TERMİNAL).
    "journal_entry_status": ["draft", "posted", "reversed"],
}

#: 🔑 MODEL katmanının BUGÜNKÜ hâli — MT-1/KK-1 (kullanıcı kararı, 2026-08-16)
#: `equity` üyesini açtı. Ayrıntı: `test_mt1_ozkaynak_kontra_migration.py`.
MODEL_ENUM_LABELS = {
    "chart_account_type": ["asset", "liability", "revenue", "expense", "equity"],
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
