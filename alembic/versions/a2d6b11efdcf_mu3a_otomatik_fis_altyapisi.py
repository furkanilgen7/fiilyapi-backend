"""mu3a otomatik fis altyapisi

MU-3A — muhasebe modülü canlıdaydı ama KENDİ KENDİNE DOLMUYORDU: `JournalEntry`
yalnız İKİ yerde üretiliyordu (elle kayıt + storno) ve fişte BELGE KİMLİĞİ TUTAN
HİÇBİR ALAN YOKTU. Sonucu iki katlıydı: (1) aynı fatura iki kez onaylansaydı
İKİ FİŞ doğar ve hiçbir kısıt engellemezdi, (2) *"bu belge fişlendi mi?"* sorusu
SORULAMAZDI.

Bu migration ÜÇ şey açar:
  1. `journal_source_type` enum tipi + `journal_entries.source_type`/`source_id`;
  2. `uq_journal_entries_source` (idempotanlığın DB düzeyindeki son savunması) ve
     `ck_journal_entries_source_pair` (çift BÜTÜNDÜR);
  3. `posting_rules` — belge ailesi + bacak rolü → hesap eşlemesi.

## 🔴 `NOT VALID` / `CONCURRENTLY` DANSI BURADA YAPILMAZ — ve bu ÖLÇÜLMÜŞTÜR

Depo kanonu, mevcut veri taşıyan bir tabloya UNIQUE eklerken "ACCESS EXCLUSIVE
altında SAY → 0 ise EKLE → ihlalde WARNING düş, başarıyla bit" der. Buradaki
UNIQUE o hâle GİRMEZ ve dansı taklit etmek YANILTICI olurdu:

  * `NOT VALID` yalnız `CHECK`/`FK` içindir; `UNIQUE` onu KABUL ETMEZ.
  * `CREATE UNIQUE INDEX CONCURRENTLY` transaction'da koşamaz (alembic ile
    çatışır).
  * Asıl nokta: iki kolon BU MIGRATION'DA doğuyor ve her mevcut satırda
    `NULL`/`NULL` oluyor. PG'de UNIQUE NULL'ları ayrık sayar → ihlal SAYISI
    yapısal olarak SIFIRDIR, bir `SELECT count(*)` sorabileceği bir soru yoktur.
    `ADD COLUMN` tabloyu zaten `ACCESS EXCLUSIVE` ile kilitler; ekleme aynı
    kilidin altındadır.

`ck_journal_entries_source_pair` de aynı sebeple `NOT VALID` almaz: doğrulanacak
mevcut satır kümesi `NULL`/`NULL`dur ve CHECK'i geçer.

## 🔴 DOWNGRADE ENUM TİPİNİ DÜŞÜRMEK ZORUNDA

`d4e5f6a7b8c9` dersi: düşürmeyi unutan bir downgrade, ikinci `upgrade`i
`type "journal_source_type" already exists` ile patlatır ve bu YALNIZ CANLIDA
görülür. Tip İKİ tablo tarafından kullanılır (`journal_entries` + `posting_rules`),
bu yüzden `DROP TYPE` her ikisinin de kolonları düştükten SONRA gelir.

Üye SIRASI kilitlidir: `ALTER TYPE … ADD VALUE` üyeyi SONA ekler ve `enum_range`
o sırayı döner; migration testi bunu ölçer.

## ÜRÜN VERİSİ TOHUMLANMAZ

Hiçbir `posting_rules` satırı yazılmaz. MU-3A hiçbir belge ailesini bağlamaz
(bağlama işi MU-3B/C/D/E'dir); bir seed hiçbir kodun okumadığı ÖLÜ VERİ üretirdi.
Temsilî eşleme (KARAR-1 `740` / KARAR-2 `320`) TESTLERDE kurulur.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: a2d6b11efdcf
Revises: b6c7d8e9f0a1
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2d6b11efdcf"
down_revision: str | Sequence[str] | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_TABLE = "journal_entries"
RULE_TABLE = "posting_rules"
SOURCE_ENUM = "journal_source_type"

#: 🔴 SIRA KİLİTLİDİR (bkz. modül docstring'i). Üye = TABLO, üye ≠ kavram:
#: `source_id` üyenin gösterdiği TABLONUN birincil anahtarıdır.
#: KARAR-7 gereği satınalma ve stok üyesi YOKTUR.
SOURCE_LABELS: tuple[str, ...] = (
    "invoice",
    "payment",
    "payroll_period",
    "progress_payment",
    "subcontractor_progress_payment",
)

SOURCE_PAIR_CHECK = (
    "(source_type IS NULL AND source_id IS NULL) OR "
    "(source_type IS NOT NULL AND source_id IS NOT NULL)"
)

ROLE_KEY_PATTERN = "^[a-z][a-z0-9_]*$"


def upgrade() -> None:
    kaynak_enum = postgresql.ENUM(*SOURCE_LABELS, name=SOURCE_ENUM, create_type=False)
    kaynak_enum.create(op.get_bind(), checkfirst=False)

    # `ADD COLUMN` tabloyu ACCESS EXCLUSIVE ile kilitler; kısıtlar AYNI kilidin
    # altında eklenir (ikinci bir kilit turu yok).
    op.add_column(ENTRY_TABLE, sa.Column("source_type", kaynak_enum, nullable=True))
    op.add_column(
        ENTRY_TABLE, sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_journal_entries_source", ENTRY_TABLE, ["source_type", "source_id"]
    )
    op.create_check_constraint("ck_journal_entries_source_pair", ENTRY_TABLE, SOURCE_PAIR_CHECK)

    op.create_table(
        RULE_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", kaynak_enum, nullable=False),
        sa.Column("role_key", sa.String(40), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # RESTRICT: eşlemesi olan hesap SİLİNEMEZ (`journal_lines.account_id` deseni).
        sa.ForeignKeyConstraint(
            ["account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_type", "role_key", name="uq_posting_rules_source_role"),
        sa.CheckConstraint(
            f"role_key ~ '{ROLE_KEY_PATTERN}'", name="ck_posting_rules_role_key_format"
        ),
    )


def downgrade() -> None:
    op.drop_table(RULE_TABLE)
    op.drop_constraint("ck_journal_entries_source_pair", ENTRY_TABLE, type_="check")
    op.drop_constraint("uq_journal_entries_source", ENTRY_TABLE, type_="unique")
    op.drop_column(ENTRY_TABLE, "source_id")
    op.drop_column(ENTRY_TABLE, "source_type")
    # 🔴 EN SONDA ve MUTLAKA: tip iki tablo tarafından kullanılıyordu; düşmezse
    # ikinci `upgrade` "type already exists" ile YALNIZ CANLIDA patlar.
    postgresql.ENUM(name=SOURCE_ENUM).drop(op.get_bind(), checkfirst=False)
