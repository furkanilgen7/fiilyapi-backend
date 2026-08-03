"""santiye gunlugu cekirdegi

Uc yeni tablo (`site_diary_entries` / `_lines` / `_worker_counts`), uc yeni enum
(`weather` / `diary_status` / `worker_source`) ve isveren hakedis satirina
`quantity_source` kolonu (site_diary spec §2 ve §4, Task T1).

PAYLASILAN ENUM: `progress_payment_lines.quantity_source` YENI bir tip ACMAZ —
taseron hakedisi diliminde (`a3b4c5d6e7f8`) yaratilan `quantity_source` tipini
yeniden kullanir. Bu yuzden `create_type=False` ile baglanir ve `downgrade` bu
tipi DUSURMEZ: taseron satirinda halen kullanimdadir.

Izin migration'i YOKTUR: `site_diary` modulu seed'de zaten var
(`app/modules/roles/seed_data.py`) — matris DEGISMEZ.

Fotograf / planlama / malzeme tablolari ACILMAZ (spec §5 pending).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b5c6d7e8f9a0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# E7'nin BESLISI (GK'nin dortlusu alt kume — `snowy` orada yok).
weather_enum = sa.Enum("sunny", "partly_cloudy", "cloudy", "rainy", "snowy", name="weather")
# Iki durum: hakedisin dort durumlu onay makinesi gunlukte YOK.
diary_status_enum = sa.Enum("draft", "submitted", name="diary_status")
worker_source_enum = sa.Enum("company", "subcontractor", "general", name="worker_source")

NEW_ENUMS = (weather_enum, diary_status_enum, worker_source_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum'lar (paylasilan `quantity_source` BURADA YARATILMAZ).
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. site_diary_entries — UQ (site_id, entry_date): gunde TEK kayit.
    op.create_table(
        "site_diary_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("weather", postgresql.ENUM(name="weather", create_type=False), nullable=True),
        sa.Column("temperature_c", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("work_done", sa.Text(), nullable=True),
        sa.Column("chief_note", sa.Text(), nullable=True),
        sa.Column(
            "safety_meeting_held",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("ppe_checked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_incident", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("incident_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="diary_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "entry_date", name="uq_site_diary_entries_site_date"),
        sa.CheckConstraint(
            "temperature_c IS NULL OR temperature_c BETWEEN -60 AND 60",
            name="ck_site_diary_entries_temperature_range",
        ),
    )
    op.create_index("ix_site_diary_entries_site_id", "site_diary_entries", ["site_id"])
    op.create_index("ix_site_diary_entries_project_id", "site_diary_entries", ["project_id"])
    op.create_index("ix_site_diary_entries_section_id", "site_diary_entries", ["section_id"])

    # 3. site_diary_lines — poz kaynagi BOQ; kumulatif/₺ TUREV, kolon yok.
    op.create_table(
        "site_diary_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("boq_item_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
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
        sa.ForeignKeyConstraint(["entry_id"], ["site_diary_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["boq_item_id"], ["boq_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 0", name="ck_site_diary_lines_quantity_nonneg"),
        sa.CheckConstraint("unit_price >= 0", name="ck_site_diary_lines_unit_price_nonneg"),
    )
    op.create_index("ix_site_diary_lines_entry_id", "site_diary_lines", ["entry_id"])
    op.create_index("ix_site_diary_lines_boq_item_id", "site_diary_lines", ["boq_item_id"])
    # Kismi benzersiz indeks: bagi kopmus (NULL) satirlar coklanabilir.
    op.create_index(
        "uq_site_diary_lines_boq_item",
        "site_diary_lines",
        ["entry_id", "boq_item_id"],
        unique=True,
        postgresql_where=sa.text("boq_item_id IS NOT NULL"),
    )

    # 4. site_diary_worker_counts — toplam TUREV, kolon yok.
    op.create_table(
        "site_diary_worker_counts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("trade", sa.String(length=100), nullable=False),
        sa.Column(
            "source", postgresql.ENUM(name="worker_source", create_type=False), nullable=False
        ),
        sa.Column("count", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["entry_id"], ["site_diary_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entry_id", "trade", "source", name="uq_site_diary_worker_counts_entry_trade_source"
        ),
        sa.CheckConstraint("count >= 0", name="ck_site_diary_worker_counts_count_nonneg"),
    )
    op.create_index(
        "ix_site_diary_worker_counts_entry_id", "site_diary_worker_counts", ["entry_id"]
    )

    # 5. Isveren hakedis satirina `quantity_source` (spec §4 asimetri kapanisi).
    #    Mevcut satirlar `manual` alir — gecmis veri gunlukten gelmedi.
    op.add_column(
        "progress_payment_lines",
        sa.Column(
            "quantity_source",
            postgresql.ENUM(name="quantity_source", create_type=False),
            server_default="manual",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_column("progress_payment_lines", "quantity_source")
    # `quantity_source` TIPI DUSURULMEZ: taseron hakedis satirinda kullanimda.

    op.drop_index("ix_site_diary_worker_counts_entry_id", table_name="site_diary_worker_counts")
    op.drop_table("site_diary_worker_counts")

    op.drop_index("uq_site_diary_lines_boq_item", table_name="site_diary_lines")
    op.drop_index("ix_site_diary_lines_boq_item_id", table_name="site_diary_lines")
    op.drop_index("ix_site_diary_lines_entry_id", table_name="site_diary_lines")
    op.drop_table("site_diary_lines")

    op.drop_index("ix_site_diary_entries_section_id", table_name="site_diary_entries")
    op.drop_index("ix_site_diary_entries_project_id", table_name="site_diary_entries")
    op.drop_index("ix_site_diary_entries_site_id", table_name="site_diary_entries")
    op.drop_table("site_diary_entries")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
