"""p4 is kalemleri boq

boq_groups + boq_items tablolari (Alt-Proje 2 · P4, spec §3, §6). Tamamen
additive; modul/izin satiri ACILMAZ (spec §4) — `modules`/`role_permissions`
DOKUNULMAZ, seed parity testleri degismeden yesil kalir.

Revision ID: 7abe87671979
Revises: e2b3c4d5f6a7
Create Date: 2026-07-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7abe87671979"
down_revision: str | Sequence[str] | None = "e2b3c4d5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "boq_groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_boq_groups_site_id", "boq_groups", ["site_id"])

    op.create_table(
        "boq_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["boq_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "code", name="uq_boq_items_site_code"),
        sa.CheckConstraint("quantity > 0", name="ck_boq_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_boq_items_unit_price_nonneg"),
    )
    op.create_index("ix_boq_items_site_id", "boq_items", ["site_id"])
    op.create_index("ix_boq_items_group_id", "boq_items", ["group_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_boq_items_group_id", table_name="boq_items")
    op.drop_index("ix_boq_items_site_id", table_name="boq_items")
    op.drop_table("boq_items")

    op.drop_index("ix_boq_groups_site_id", table_name="boq_groups")
    op.drop_table("boq_groups")
