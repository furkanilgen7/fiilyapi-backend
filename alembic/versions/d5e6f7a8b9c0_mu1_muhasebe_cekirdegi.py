"""mu1 muhasebe cekirdegi

MU-1 T2 — UC yeni tablo (`chart_of_accounts` / `journal_entries` /
`journal_lines`) ve IKI yeni enum (`chart_account_type` /
`journal_entry_status`). Spec:
`docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §3, §4.

IZIN MIGRATION'I YOKTUR (spec §2/K8): `accounting` ("Muhasebe") izin modulu
seed'de ZATEN VARDIR ve matris satiri da mevcuttur (`roles/seed_data.py:99`) —
yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

BASKA HICBIR TABLOYA DOKUNULMAZ: bu dilim ADDITIVE kolon eklemez. Fatura /
hazine / bordro kayitlarindan otomatik yevmiye fisi URETILMEZ (MU-3).

🔴 IKI ENUM DA DOWNGRADE'DE DUSER. Biri bile kalirsa ikinci `upgrade`
"type already exists" ile patlar (`d4e5f6a7b8c9` dersi) ve bu YALNIZ CANLIDA
gorulurdu: `Dockerfile` acilista `alembic upgrade head` kosar, patlarsa uvicorn
hic baslamaz (tam kesinti).

🔴 K1'in DB katmani BURADA kurulur — servis 422 vermeyi unutsa bile:
  * `ck_journal_lines_single_side`   — `(0,0)` ve cift-dolu satir giremez,
  * `ck_journal_lines_amounts_non_negative` — negatif tutar `Σ`yi dengeleyemez,
  * `debit`/`credit` NOT NULL       — NULL tutar `SUM` tarafindan yutulamaz,
  * `ck_journal_entries_posted_balanced` — dengesiz fis `posted` OLAMAZ,
  * `total_debit`/`total_credit` NOT NULL — nullable olsalardi `NULL = NULL`
    NULL uretir ve denge CHECK'i SESSIZCE GECERDI.

`ck_journal_entries_period_matches_date` donem kolonlarini `entry_date`e
baglar: kolon VARDIR (MU-2 donem kilidi icin) ve KAYAMAZ. `EXTRACT` bir `date`
kolonu uzerinde IMMUTABLE'dir, CHECK'te yasaldir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# HP:60 `Tur` sutununun KAPALI kumesi birebir — Aktif/Pasif/Gelir/Gider.
# Besinci uye ICAT EDILMEZ.
chart_account_type_enum = sa.Enum(
    "asset", "liability", "revenue", "expense", name="chart_account_type"
)
# K2 durum makinesi: draft → posted → reversed (`reversed` TERMINAL).
journal_entry_status_enum = sa.Enum("draft", "posted", "reversed", name="journal_entry_status")

NEW_ENUMS = (chart_account_type_enum, journal_entry_status_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Iki yeni enum tipi.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. chart_of_accounts — tekduzen hesap plani katalogu (HP:58-62).
    #    🔴 Proje/santiye FK'si YOKTUR: katalog SIRKET GENELIDIR, erisim
    #    `accounting` izin moduluyle denetlenir (spec §3 kapsam karari).
    #    🔴 `parent_id` YOKTUR: hiyerarsi KODUN icindedir (K4).
    #    🔴 Bakiye KOLON DEGILDIR: `balance.py`de turetilir (K3).
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "account_type",
            postgresql.ENUM(name="chart_account_type", create_type=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # K4 kod dilbilgisi: grup `NN` · ana hesap `NNN` · alt hesap `NNN.NN`.
        # Ilk hane `0` olamaz; UCUNCU KIRILIM (`NNN.NN.NNN`) yapisal olarak
        # reddedilir — hicbir mockup cizmiyor.
        sa.CheckConstraint(
            r"code ~ '^[1-9][0-9]$' OR code ~ '^[1-9][0-9]{2}(\.[0-9]{2})?$'",
            name="ck_chart_of_accounts_code_format",
        ),
        # Ayni kod iki kez acilsaydi yevmiye satirlari iki karta bolunur ve
        # bakiye (K3) ikiye ayrilirdi.
        sa.UniqueConstraint("code", name="uq_chart_of_accounts_code"),
        sa.PrimaryKeyConstraint("id"),
    )
    # HP:60 tur suzgeci bu sutundan gecer. `is_active` indekslenmez (iki
    # degerli, secicilik yok).
    op.create_index("ix_chart_of_accounts_account_type", "chart_of_accounts", ["account_type"])

    # 3. journal_entries — yevmiye fisi basligi.
    #    🔴 `entry_no` YOKTUR (hicbir mockup sutunu cizmiyor); kimlik `id`dir.
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detail_note", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="journal_entry_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "total_debit",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_credit",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("reversal_of_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # K9 drift-proof: donem kolonlari `entry_date`ten KAYAMAZ.
        sa.CheckConstraint(
            "period_year = EXTRACT(YEAR FROM entry_date)::int AND "
            "period_month = EXTRACT(MONTH FROM entry_date)::int",
            name="ck_journal_entries_period_matches_date",
        ),
        # 🔴 K1 baslik ayagi: taslak dengesiz BIRAKILABILIR, `posted` OLAMAZ.
        sa.CheckConstraint(
            "status <> 'posted' OR total_debit = total_credit",
            name="ck_journal_entries_posted_balanced",
        ),
        sa.CheckConstraint(
            "total_debit >= 0 AND total_credit >= 0",
            name="ck_journal_entries_totals_non_negative",
        ),
        # Bir fisin en fazla BIR stornosu olur. PG'de cok sayida NULL
        # serbesttir → stornosu OLMAYAN fis sayisi sinirsizdir.
        sa.UniqueConstraint("reversal_of_id", name="uq_journal_entries_reversal_of"),
        # RESTRICT: stornosu olan fis ve fisi giren kullanici silinemez.
        sa.ForeignKeyConstraint(["reversal_of_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"])
    # E8:75 ay penceresi + MU-2 donem kilidi bu ciftten gecer.
    op.create_index("ix_journal_entries_period", "journal_entries", ["period_year", "period_month"])
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])

    # 4. journal_lines — fisin bacaklari (E8 tablosu SATIR bazlidir).
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        # `server_default` YOK: her yazma yolu degeri acikca doldurmalidir.
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column(
            "debit",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "credit",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "debit >= 0 AND credit >= 0", name="ck_journal_lines_amounts_non_negative"
        ),
        # 🔴 E8'in her satirinin bos tarafi `—`dir: cift-dolu ve `(0,0)` satir
        # REDDEDILIR.
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_journal_lines_single_side",
        ),
        # entry_id CASCADE: satirin omru basliga baglidir.
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        # 🔴 account_id RESTRICT: fis satiri olan hesap SILINEMEZ. CASCADE
        # olsaydi turetilmis bakiye (K3) kaydigi fark edilmeden kayardi.
        sa.ForeignKeyConstraint(["account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # journal_lines ONCE duser: iki tabloya da FK ile baglidir.
    op.drop_index("ix_journal_lines_account_id", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry_id", table_name="journal_lines")
    op.drop_table("journal_lines")

    op.drop_index("ix_journal_entries_status", table_name="journal_entries")
    op.drop_index("ix_journal_entries_period", table_name="journal_entries")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_index("ix_chart_of_accounts_account_type", table_name="chart_of_accounts")
    op.drop_table("chart_of_accounts")

    # 🔴 Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa
    # ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
