"""PLN-B2 — saha: gunluk saat dagitimi + gun kilidi (EV) + gunluk genislemesi (cekirdek)

PLANLAMA-SPEC §2, §2.7, §3.12 (B2-1…B2-12). EV tarafi: 6 uzanti tablosu
(`ev_day_codes`, `ev_day_rows`, `ev_day_cells`, `ev_day_notes`, `ev_report_approvals`,
`ev_day_unlocks`). Cekirdek iyilestirmeler (§2.7 istisnasi, planlama import'u YOK):
* `weather` +5 deger (heavy_rain, drizzle, windy, dusty, foggy) — mevcut 5 aynen.
* `site_diary_entries` + temp_min_c / temp_max_c / wind_ms; `temperature_c` KALIR
  (genislet/daralt: Railway gecisinde eski konteyner o kolonu okur). Veri: eski deger
  iki yeni alana kopyalanir.
* `site_diary_lines` + section_id (RESTRICT; bolum silme korkulugu B2-10) + overrun_reason;
  tekillik (entry, kalem) → (entry, kalem, bolum) — NULL icin iki kismi indeks.
* `site_diary_worker_counts` + subcontractor_id (RESTRICT; B2-11) + hours; firma basina
  tekillik; eski (entry, trade, source) tekilligi ayni adla KISMI indekse doner.

`alembic revision --autogenerate` ile uretildi, elle duzeltildi: ilgisiz
`financial_instruments` NOT NULL suruklenmesi ALINMADI (B1'de de boyleydi); enum ADD VALUE
ve veri gocu elle; FK adlari acik (downgrade adla dusurur).

Revision ID: b877270195d8
Revises: 46a82e4b271c
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

NEW_WEATHER = ("heavy_rain", "drizzle", "windy", "dusty", "foggy")
#: Downgrade: yeni deger → eski 5'ten en yakini.
WEATHER_DOWNGRADE = {
    "heavy_rain": "rainy",
    "drizzle": "rainy",
    "windy": "cloudy",
    "dusty": "cloudy",
    "foggy": "cloudy",
}

# revision identifiers, used by Alembic.
revision: str = "b877270195d8"
down_revision: str | Sequence[str] | None = "46a82e4b271c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # B2-1: `weather` +5 deger. ADD VALUE ayni transaction'da KULLANILAMAZ → autocommit
    # blogu; IF NOT EXISTS: downgrade degerleri silemez (PG), CI'nin downgrade → upgrade
    # dongusu ikinci kez eklemeye calisir.
    with op.get_context().autocommit_block():
        for value in NEW_WEATHER:
            op.execute(f"ALTER TYPE weather ADD VALUE IF NOT EXISTS '{value}'")
    op.create_table(
        "ev_day_codes",
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("node_id", sa.String(length=90), nullable=False),
        sa.Column(
            "rule",
            sa.Enum("direct", "prorata_by_daily_qty", name="ev_allocation_rule"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id", "day", "node_id"),
    )
    op.create_table(
        "ev_day_notes",
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("unallocated_reason", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("site_id", "day"),
    )
    op.create_table(
        "ev_day_unlocks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("unlocked_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unlocked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ev_day_unlocks_site_id"), "ev_day_unlocks", ["site_id"], unique=False)
    op.create_table(
        "ev_report_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_report_approvals_site_id"), "ev_report_approvals", ["site_id"], unique=False
    )
    op.create_table(
        "ev_day_rows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "kind", sa.Enum("personnel", "subcontractor", name="ev_day_row_kind"), nullable=False
        ),
        sa.Column("personnel_id", sa.UUID(), nullable=True),
        sa.Column("subcontractor_id", sa.UUID(), nullable=True),
        sa.Column("source_hours", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.CheckConstraint(
            "(kind = 'personnel') = (personnel_id IS NOT NULL) AND "
            "(kind = 'subcontractor') = (subcontractor_id IS NOT NULL)",
            name="ck_ev_day_rows_kind_ref",
        ),
        sa.CheckConstraint("source_hours >= 0", name="ck_ev_day_rows_hours"),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subcontractor_id"], ["subcontractors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ev_day_rows_personnel_id"), "ev_day_rows", ["personnel_id"], unique=False
    )
    op.create_index(op.f("ix_ev_day_rows_site_id"), "ev_day_rows", ["site_id"], unique=False)
    op.create_index(
        op.f("ix_ev_day_rows_subcontractor_id"), "ev_day_rows", ["subcontractor_id"], unique=False
    )
    op.create_index(
        "uq_ev_day_rows_personnel",
        "ev_day_rows",
        ["site_id", "day", "personnel_id"],
        unique=True,
        postgresql_where=sa.text("personnel_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ev_day_rows_subcontractor",
        "ev_day_rows",
        ["site_id", "day", "subcontractor_id"],
        unique=True,
        postgresql_where=sa.text("subcontractor_id IS NOT NULL"),
    )
    op.create_table(
        "ev_day_cells",
        sa.Column("row_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.String(length=90), nullable=False),
        sa.Column("hours", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.CheckConstraint("hours > 0", name="ck_ev_day_cells_hours"),
        sa.ForeignKeyConstraint(["row_id"], ["ev_day_rows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("row_id", "node_id"),
    )
    op.add_column(
        "site_diary_entries",
        sa.Column("temp_min_c", sa.Numeric(precision=4, scale=1), nullable=True),
    )
    op.add_column(
        "site_diary_entries",
        sa.Column("temp_max_c", sa.Numeric(precision=4, scale=1), nullable=True),
    )
    op.add_column(
        "site_diary_entries", sa.Column("wind_ms", sa.Numeric(precision=4, scale=1), nullable=True)
    )
    # B2-2 (genislet): eski tek sicaklik iki yeni alana kopyalanir; `temperature_c` KALIR.
    op.execute(
        "UPDATE site_diary_entries SET temp_min_c = temperature_c, temp_max_c = temperature_c "
        "WHERE temperature_c IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_site_diary_entries_temp_max_range",
        "site_diary_entries",
        "temp_max_c IS NULL OR temp_max_c BETWEEN -60 AND 60",
    )
    op.create_check_constraint(
        "ck_site_diary_entries_temp_min_le_max",
        "site_diary_entries",
        "temp_min_c IS NULL OR temp_max_c IS NULL OR temp_min_c <= temp_max_c",
    )
    op.create_check_constraint(
        "ck_site_diary_entries_temp_min_range",
        "site_diary_entries",
        "temp_min_c IS NULL OR temp_min_c BETWEEN -60 AND 60",
    )
    op.create_check_constraint(
        "ck_site_diary_entries_wind_range",
        "site_diary_entries",
        "wind_ms IS NULL OR wind_ms BETWEEN 0 AND 80",
    )
    op.add_column("site_diary_lines", sa.Column("section_id", sa.UUID(), nullable=True))
    op.add_column("site_diary_lines", sa.Column("overrun_reason", sa.Text(), nullable=True))
    op.drop_index(
        op.f("uq_site_diary_lines_boq_item"),
        table_name="site_diary_lines",
        postgresql_where="(boq_item_id IS NOT NULL)",
    )
    op.create_index(
        op.f("ix_site_diary_lines_section_id"), "site_diary_lines", ["section_id"], unique=False
    )
    op.create_index(
        "uq_site_diary_lines_item_nosection",
        "site_diary_lines",
        ["entry_id", "boq_item_id"],
        unique=True,
        postgresql_where=sa.text("boq_item_id IS NOT NULL AND section_id IS NULL"),
    )
    op.create_index(
        "uq_site_diary_lines_item_section",
        "site_diary_lines",
        ["entry_id", "boq_item_id", "section_id"],
        unique=True,
        postgresql_where=sa.text("boq_item_id IS NOT NULL AND section_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "site_diary_lines_section_id_fkey",
        "site_diary_lines",
        "sections",
        ["section_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "site_diary_worker_counts", sa.Column("subcontractor_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "site_diary_worker_counts",
        sa.Column("hours", sa.Numeric(precision=4, scale=1), nullable=True),
    )
    op.drop_constraint(
        op.f("uq_site_diary_worker_counts_entry_trade_source"),
        "site_diary_worker_counts",
        type_="unique",
    )
    op.create_index(
        "uq_site_diary_worker_counts_entry_trade_source",
        "site_diary_worker_counts",
        ["entry_id", "trade", "source"],
        unique=True,
        postgresql_where=sa.text("subcontractor_id IS NULL"),
    )
    op.create_index(
        op.f("ix_site_diary_worker_counts_subcontractor_id"),
        "site_diary_worker_counts",
        ["subcontractor_id"],
        unique=False,
    )
    op.create_index(
        "uq_site_diary_worker_counts_entry_subcontractor",
        "site_diary_worker_counts",
        ["entry_id", "subcontractor_id"],
        unique=True,
        postgresql_where=sa.text("subcontractor_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "site_diary_worker_counts_subcontractor_id_fkey",
        "site_diary_worker_counts",
        "subcontractors",
        ["subcontractor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_site_diary_worker_counts_hours_range",
        "site_diary_worker_counts",
        "hours IS NULL OR (hours > 0 AND hours <= 24)",
    )
    op.create_check_constraint(
        "ck_site_diary_worker_counts_subcontractor_source",
        "site_diary_worker_counts",
        "subcontractor_id IS NULL OR source = 'subcontractor'",
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 Veri kaybettirecek durumda DURUR (sessiz silme YOK): bolumlu gunluk satiri ya da
    firma satiri varsa eski tekillik geri kurulamaz. Yeni hava degerleri eski en yakin
    degere indirilir (PG enum degeri SILINEMEZ; tip degerleri tasir, kullanilmaz).
    """
    bind = op.get_bind()
    sectioned = bind.execute(
        sa.text("SELECT count(*) FROM site_diary_lines WHERE section_id IS NOT NULL")
    ).scalar()
    firm_rows = bind.execute(
        sa.text("SELECT count(*) FROM site_diary_worker_counts WHERE subcontractor_id IS NOT NULL")
    ).scalar()
    if sectioned or firm_rows:
        raise RuntimeError(
            f"PLN-B2 downgrade durdu: {sectioned} bolumlu gunluk satiri, {firm_rows} firma satiri "
            "var — eski tekillik geri kurulamaz. Once veriyi elle birlestir."
        )
    for new, old in WEATHER_DOWNGRADE.items():
        op.execute(f"UPDATE site_diary_entries SET weather = '{old}' WHERE weather = '{new}'")
    op.drop_constraint(
        "ck_site_diary_worker_counts_subcontractor_source",
        "site_diary_worker_counts",
        type_="check",
    )
    op.drop_constraint(
        "ck_site_diary_worker_counts_hours_range", "site_diary_worker_counts", type_="check"
    )
    op.drop_constraint(
        "site_diary_worker_counts_subcontractor_id_fkey",
        "site_diary_worker_counts",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_site_diary_worker_counts_entry_subcontractor",
        table_name="site_diary_worker_counts",
        postgresql_where=sa.text("subcontractor_id IS NOT NULL"),
    )
    op.drop_index(
        op.f("ix_site_diary_worker_counts_subcontractor_id"), table_name="site_diary_worker_counts"
    )
    op.drop_index(
        "uq_site_diary_worker_counts_entry_trade_source",
        table_name="site_diary_worker_counts",
        postgresql_where=sa.text("subcontractor_id IS NULL"),
    )
    op.create_unique_constraint(
        op.f("uq_site_diary_worker_counts_entry_trade_source"),
        "site_diary_worker_counts",
        ["entry_id", "trade", "source"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("site_diary_worker_counts", "hours")
    op.drop_column("site_diary_worker_counts", "subcontractor_id")
    op.drop_constraint("site_diary_lines_section_id_fkey", "site_diary_lines", type_="foreignkey")
    op.drop_index(
        "uq_site_diary_lines_item_section",
        table_name="site_diary_lines",
        postgresql_where=sa.text("boq_item_id IS NOT NULL AND section_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_site_diary_lines_item_nosection",
        table_name="site_diary_lines",
        postgresql_where=sa.text("boq_item_id IS NOT NULL AND section_id IS NULL"),
    )
    op.drop_index(op.f("ix_site_diary_lines_section_id"), table_name="site_diary_lines")
    op.create_index(
        op.f("uq_site_diary_lines_boq_item"),
        "site_diary_lines",
        ["entry_id", "boq_item_id"],
        unique=True,
        postgresql_where="(boq_item_id IS NOT NULL)",
    )
    op.drop_column("site_diary_lines", "overrun_reason")
    op.drop_column("site_diary_lines", "section_id")
    op.drop_constraint("ck_site_diary_entries_wind_range", "site_diary_entries", type_="check")
    op.drop_constraint("ck_site_diary_entries_temp_min_range", "site_diary_entries", type_="check")
    op.drop_constraint("ck_site_diary_entries_temp_min_le_max", "site_diary_entries", type_="check")
    op.drop_constraint("ck_site_diary_entries_temp_max_range", "site_diary_entries", type_="check")
    op.drop_column("site_diary_entries", "wind_ms")
    op.drop_column("site_diary_entries", "temp_max_c")
    op.drop_column("site_diary_entries", "temp_min_c")
    op.drop_table("ev_day_cells")
    op.drop_index(
        "uq_ev_day_rows_subcontractor",
        table_name="ev_day_rows",
        postgresql_where=sa.text("subcontractor_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_ev_day_rows_personnel",
        table_name="ev_day_rows",
        postgresql_where=sa.text("personnel_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_ev_day_rows_subcontractor_id"), table_name="ev_day_rows")
    op.drop_index(op.f("ix_ev_day_rows_site_id"), table_name="ev_day_rows")
    op.drop_index(op.f("ix_ev_day_rows_personnel_id"), table_name="ev_day_rows")
    op.drop_table("ev_day_rows")
    op.drop_index(op.f("ix_ev_report_approvals_site_id"), table_name="ev_report_approvals")
    op.drop_table("ev_report_approvals")
    op.drop_index(op.f("ix_ev_day_unlocks_site_id"), table_name="ev_day_unlocks")
    op.drop_table("ev_day_unlocks")
    op.drop_table("ev_day_notes")
    op.drop_table("ev_day_codes")
    bind = op.get_bind()
    for enum_name in ("ev_day_row_kind", "ev_allocation_rule"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
