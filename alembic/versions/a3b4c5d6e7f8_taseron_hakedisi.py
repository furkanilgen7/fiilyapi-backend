"""taseron hakedisi

subcontractor_payment_status + quantity_source enum'lari,
subcontractor_progress_payments + subcontractor_progress_payment_lines tablolari ve
subcontractor_contracts.vat_pct kolonu (spec §2/§8 S1, Task T1).

Izin migration'i YOKTUR — modul `progress_payments`tir (isveren hakedisiyle ayni
ekran ailesi, spec §1), yeni modul ACILMAZ.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DIKKAT: `progress_payment_status` (isveren hakedisi, d2a32dcae735) ile AYRI bir
# tiptir — degerler ayni olsa da iki evrak ailesi birbirine kilitlenmez.
subcontractor_payment_status_enum = sa.Enum(
    "draft", "pending_approval", "approved", "paid", name="subcontractor_payment_status"
)
quantity_source_enum = sa.Enum("manual", "diary", name="quantity_source")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Enum'lar
    subcontractor_payment_status_enum.create(bind, checkfirst=True)
    quantity_source_enum.create(bind, checkfirst=True)

    # 2. subcontractor_contracts.vat_pct (spec §8 S1) — mevcut satirlar 20 alir.
    op.add_column(
        "subcontractor_contracts",
        sa.Column(
            "vat_pct",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("20"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_subcontract_vat_pct_range", "subcontractor_contracts", "vat_pct BETWEEN 0 AND 100"
    )

    # 3. subcontractor_progress_payments
    op.create_table(
        "subcontractor_progress_payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=True),
        sa.Column("period_month", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="subcontractor_payment_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("vat_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("advance_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("retainage_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "default_coefficient",
            sa.Numeric(precision=8, scale=3),
            server_default=sa.text("1.000"),
            nullable=False,
        ),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["contract_id"], ["subcontractor_contracts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # Sayac SOZLESME kapsamlidir (mockup #47/#48) — isverendeki proje kapsamli
        # UQ'nun karsiligi.
        sa.UniqueConstraint(
            "contract_id",
            "sequence_no",
            name="uq_subcontractor_progress_payments_contract_sequence",
        ),
        sa.CheckConstraint(
            "period_month IS NULL OR period_month BETWEEN 1 AND 12",
            name="ck_subcontractor_progress_payments_month_range",
        ),
        sa.CheckConstraint(
            "vat_pct BETWEEN 0 AND 100 "
            "AND advance_pct BETWEEN 0 AND 100 "
            "AND retainage_pct BETWEEN 0 AND 100",
            name="ck_subcontractor_progress_payments_pct_range",
        ),
        sa.CheckConstraint(
            "default_coefficient > 0",
            name="ck_subcontractor_progress_payments_coefficient_positive",
        ),
    )
    op.create_index(
        "ix_subcontractor_progress_payments_contract_id",
        "subcontractor_progress_payments",
        ["contract_id"],
    )
    op.create_index(
        "ix_subcontractor_progress_payments_project_id",
        "subcontractor_progress_payments",
        ["project_id"],
    )
    op.create_index(
        "ix_subcontractor_progress_payments_section_id",
        "subcontractor_progress_payments",
        ["section_id"],
    )

    # 4. subcontractor_progress_payment_lines + kismi benzersiz indeks
    op.create_table(
        "subcontractor_progress_payment_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("contract_item_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("contract_unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "coefficient",
            sa.Numeric(precision=8, scale=3),
            server_default=sa.text("1.000"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("group_name", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "quantity_source",
            postgresql.ENUM(name="quantity_source", create_type=False),
            server_default="manual",
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["payment_id"], ["subcontractor_progress_payments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contract_item_id"], ["subcontractor_contract_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "coefficient > 0", name="ck_subcontractor_pp_lines_coefficient_positive"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_subcontractor_pp_lines_quantity_nonneg"),
    )
    op.create_index(
        "ix_subcontractor_progress_payment_lines_payment_id",
        "subcontractor_progress_payment_lines",
        ["payment_id"],
    )
    op.create_index(
        "ix_subcontractor_progress_payment_lines_contract_item_id",
        "subcontractor_progress_payment_lines",
        ["contract_item_id"],
    )
    op.create_index(
        "uq_subcontractor_pp_lines_item",
        "subcontractor_progress_payment_lines",
        ["payment_id", "contract_item_id"],
        unique=True,
        postgresql_where=sa.text("contract_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_subcontractor_pp_lines_item", table_name="subcontractor_progress_payment_lines"
    )
    op.drop_index(
        "ix_subcontractor_progress_payment_lines_contract_item_id",
        table_name="subcontractor_progress_payment_lines",
    )
    op.drop_index(
        "ix_subcontractor_progress_payment_lines_payment_id",
        table_name="subcontractor_progress_payment_lines",
    )
    op.drop_table("subcontractor_progress_payment_lines")

    op.drop_index(
        "ix_subcontractor_progress_payments_section_id",
        table_name="subcontractor_progress_payments",
    )
    op.drop_index(
        "ix_subcontractor_progress_payments_project_id",
        table_name="subcontractor_progress_payments",
    )
    op.drop_index(
        "ix_subcontractor_progress_payments_contract_id",
        table_name="subcontractor_progress_payments",
    )
    op.drop_table("subcontractor_progress_payments")

    op.drop_constraint("ck_subcontract_vat_pct_range", "subcontractor_contracts", type_="check")
    op.drop_column("subcontractor_contracts", "vat_pct")

    bind = op.get_bind()
    quantity_source_enum.drop(bind, checkfirst=True)
    subcontractor_payment_status_enum.drop(bind, checkfirst=True)
