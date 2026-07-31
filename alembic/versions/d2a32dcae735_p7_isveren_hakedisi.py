"""p7 isveren hakedisi

progress_payment_status enum'u + progress_payments + progress_payment_lines
tablolari (Task H1, spec §4/§12). Izin migration'i YOKTUR — modul ve 8
role_permissions satiri seed_data.py'de zaten var (spec §0/§2, GOREV-SIRASI §3).

Revision ID: d2a32dcae735
Revises: e9e8e6a52f96
Create Date: 2026-07-31 10:42:18.669752

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a32dcae735"
down_revision: str | Sequence[str] | None = "e9e8e6a52f96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

progress_payment_status_enum = sa.Enum(
    "draft", "pending_approval", "approved", "paid", name="progress_payment_status"
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Enum
    progress_payment_status_enum.create(bind, checkfirst=True)

    # 2. progress_payments
    op.create_table(
        "progress_payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=True),
        sa.Column("period_month", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="progress_payment_status", create_type=False),
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
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
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
            ["project_id"], ["project_contracts.project_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "sequence_no", name="uq_progress_payments_project_sequence"
        ),
        sa.CheckConstraint(
            "period_month IS NULL OR period_month BETWEEN 1 AND 12",
            name="ck_progress_payments_month_range",
        ),
        sa.CheckConstraint(
            "vat_pct BETWEEN 0 AND 100 "
            "AND advance_pct BETWEEN 0 AND 100 "
            "AND retainage_pct BETWEEN 0 AND 100",
            name="ck_progress_payments_pct_range",
        ),
        sa.CheckConstraint(
            "default_coefficient > 0", name="ck_progress_payments_coefficient_positive"
        ),
    )
    op.create_index("ix_progress_payments_project_id", "progress_payments", ["project_id"])

    # 3. progress_payment_lines + kismi benzersiz indeks
    op.create_table(
        "progress_payment_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("contract_item_id", sa.UUID(), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["payment_id"], ["progress_payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["contract_item_id"], ["employer_contract_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "coefficient > 0", name="ck_progress_payment_lines_coefficient_positive"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_progress_payment_lines_quantity_nonneg"),
    )
    op.create_index(
        "ix_progress_payment_lines_payment_id", "progress_payment_lines", ["payment_id"]
    )
    op.create_index(
        "ix_progress_payment_lines_contract_item_id",
        "progress_payment_lines",
        ["contract_item_id"],
    )
    op.create_index("ix_progress_payment_lines_site_id", "progress_payment_lines", ["site_id"])
    op.create_index(
        "uq_progress_payment_lines_item_site",
        "progress_payment_lines",
        ["payment_id", "contract_item_id", "site_id"],
        unique=True,
        postgresql_where=sa.text("contract_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_progress_payment_lines_item_site", table_name="progress_payment_lines")
    op.drop_index("ix_progress_payment_lines_site_id", table_name="progress_payment_lines")
    op.drop_index("ix_progress_payment_lines_contract_item_id", table_name="progress_payment_lines")
    op.drop_index("ix_progress_payment_lines_payment_id", table_name="progress_payment_lines")
    op.drop_table("progress_payment_lines")

    op.drop_index("ix_progress_payments_project_id", table_name="progress_payments")
    op.drop_table("progress_payments")

    bind = op.get_bind()
    progress_payment_status_enum.drop(bind, checkfirst=True)
