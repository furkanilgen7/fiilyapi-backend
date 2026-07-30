"""p3 proje tip detay units

unit_kind/unit_owner_side enum'lari + blocks/units tablolari.

Izin matrisine DOKUNULMAZ (spec §8, kullanici karari 2026-07-30): yeni izin
modulu acilmaz, `projects` modulunun seviyeleri kullanilir — modul sayisi 17'de
kalir. Bu yuzden bu migration `modules` / `role_permissions` tablolarina
hicbir sey yazmaz.

Veri gecisi yok, mevcut hicbir tabloya ALTER yapilmaz (spec §10.4): `blocks` ve
`units` yepyeni tablolardir, `sites` ve `projects` dokunulmadan kalir.

Revision ID: a4c7f1d2e8b3
Revises: e3a8b4a5b93b
Create Date: 2026-07-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c7f1d2e8b3"
down_revision: str | Sequence[str] | None = "e3a8b4a5b93b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

unit_kind_enum = sa.Enum("apartment", "shop", name="unit_kind")
unit_owner_side_enum = sa.Enum("contractor", "landowner", name="unit_owner_side")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    unit_kind_enum.create(bind, checkfirst=True)
    unit_owner_side_enum.create(bind, checkfirst=True)

    # `blocks` ONCE gelmek zorundadir: `units`'in bilesik FK'si
    # uq_blocks_project_id_id'e baglidir (spec §10.2).
    op.create_table(
        "blocks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_blocks_project_name"),
        sa.UniqueConstraint("project_id", "id", name="uq_blocks_project_id_id"),
    )
    op.create_index("ix_blocks_project_id", "blocks", ["project_id"])
    op.create_index("ix_blocks_site_id", "blocks", ["site_id"])

    op.create_table(
        "units",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("block_id", sa.UUID(), nullable=False),
        sa.Column("unit_no", sa.String(length=30), nullable=False),
        sa.Column(
            "unit_kind",
            postgresql.ENUM(name="unit_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("layout", sa.String(length=20), nullable=True),
        sa.Column("gross_area_m2", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("net_area_m2", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("list_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("appraisal_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "owner_side",
            postgresql.ENUM(name="unit_owner_side", create_type=False),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # Unitesi olan blok DB duzeyinde silinemez (spec §4.2/§7.9).
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"], ondelete="RESTRICT"),
        # Bilesik FK: unit.project_id != block.project_id imkansiz (spec §4.3).
        sa.ForeignKeyConstraint(
            ["project_id", "block_id"],
            ["blocks.project_id", "blocks.id"],
            name="fk_units_block_project",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("block_id", "unit_no", name="uq_units_block_no"),
        sa.CheckConstraint(
            "gross_area_m2 IS NULL OR gross_area_m2 >= 0", name="ck_units_gross_area"
        ),
        sa.CheckConstraint("net_area_m2 IS NULL OR net_area_m2 >= 0", name="ck_units_net_area"),
        sa.CheckConstraint("list_price IS NULL OR list_price >= 0", name="ck_units_list_price"),
        sa.CheckConstraint(
            "appraisal_value IS NULL OR appraisal_value >= 0", name="ck_units_appraisal_value"
        ),
        sa.CheckConstraint(
            "gross_area_m2 IS NULL OR net_area_m2 IS NULL OR net_area_m2 <= gross_area_m2",
            name="ck_units_net_le_gross",
        ),
    )
    op.create_index("ix_units_project_id", "units", ["project_id"])
    op.create_index("ix_units_block_id", "units", ["block_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_units_block_id", table_name="units")
    op.drop_index("ix_units_project_id", table_name="units")
    op.drop_table("units")
    op.drop_index("ix_blocks_site_id", table_name="blocks")
    op.drop_index("ix_blocks_project_id", table_name="blocks")
    op.drop_table("blocks")

    # KRITIK: Postgres ENUM tipi tabloyla birlikte SILINMEZ. Bu iki satir
    # unutulursa ikinci `upgrade` "type already exists" ile patlar (spec §10.3).
    unit_owner_side_enum.drop(op.get_bind(), checkfirst=True)
    unit_kind_enum.drop(op.get_bind(), checkfirst=True)
