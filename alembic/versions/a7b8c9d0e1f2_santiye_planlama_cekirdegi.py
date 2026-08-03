"""santiye planlama cekirdegi

Dort yeni tablo (`site_plan_rows` / `site_plan_cells` / `site_plan_goals` /
`site_plan_sprints`) ve UC yeni enum (`plan_resource_kind` / `plan_cell_tag` /
`plan_goal_status`) — planlama spec §2, Task T1.

IZIN MIGRATION'I YOKTUR (spec §6 S1 onayi): planlama `site_diary` iznini
kullanir, yeni izin modulu ACILMAZ — matris DEGISMEZ.

Kapsam disi (spec §5, kasitli): malzeme/stok tablosu YOK · ekipman FK'si YOK
(`label` serbest metin) · plan-gerceklesen kiyas kolonu YOK · taslak/onay durum
akisi YOK (mockup'ta tek "Kaydet") · gorunum kipi icin period-tipi kolonu YOK.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a7b8c9d0e1f2
Revises: c6d7e8f9a0b1
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

plan_resource_kind_enum = sa.Enum("crew", "equipment", name="plan_resource_kind")
# Mockup'un renk kodu YORUMLANMADAN tasinir (spec §2).
plan_cell_tag_enum = sa.Enum(
    "blue", "green", "yellow", "purple", "gray", "red", name="plan_cell_tag"
)
plan_goal_status_enum = sa.Enum(
    "completed", "in_progress", "waiting", "service_pending", name="plan_goal_status"
)

NEW_ENUMS = (plan_resource_kind_enum, plan_cell_tag_enum, plan_goal_status_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipleri.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. site_plan_rows — izgaranin satirlari (kaynak).
    op.create_table(
        "site_plan_rows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind", postgresql.ENUM(name="plan_resource_kind", create_type=False), nullable=False
        ),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("planned_worker_count", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id",
            "kind",
            "section_id",
            "label",
            name="uq_site_plan_rows_site_kind_section_label",
        ),
    )
    op.create_index("ix_site_plan_rows_site_id", "site_plan_rows", ["site_id"])
    op.create_index("ix_site_plan_rows_project_id", "site_plan_rows", ["project_id"])
    op.create_index("ix_site_plan_rows_section_id", "site_plan_rows", ["section_id"])

    # 3. site_plan_cells — satir x gun. Hucre yoklugu = plan yok.
    op.create_table(
        "site_plan_cells",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("row_id", sa.UUID(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("tag", postgresql.ENUM(name="plan_cell_tag", create_type=False), nullable=True),
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
        sa.ForeignKeyConstraint(["row_id"], ["site_plan_rows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_id", "plan_date", name="uq_site_plan_cells_row_date"),
    )
    op.create_index("ix_site_plan_cells_row_id", "site_plan_cells", ["row_id"])

    # 4. site_plan_goals — haftalik hedefler.
    op.create_table(
        "site_plan_goals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status", postgresql.ENUM(name="plan_goal_status", create_type=False), nullable=False
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_plan_goals_site_id", "site_plan_goals", ["site_id"])
    op.create_index("ix_site_plan_goals_project_id", "site_plan_goals", ["project_id"])
    op.create_index("ix_site_plan_goals_week_start", "site_plan_goals", ["week_start"])

    # 5. site_plan_sprints — yalniz ad + aktiflik; tarih alani YOK.
    op.create_table(
        "site_plan_sprints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
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
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_plan_sprints_site_id", "site_plan_sprints", ["site_id"])
    # Kismi benzersiz indeks: santiye basina AYNI ANDA tek aktif sprint.
    op.create_index(
        "uq_site_plan_sprints_active_site",
        "site_plan_sprints",
        ["site_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("uq_site_plan_sprints_active_site", table_name="site_plan_sprints")
    op.drop_index("ix_site_plan_sprints_site_id", table_name="site_plan_sprints")
    op.drop_table("site_plan_sprints")

    op.drop_index("ix_site_plan_goals_week_start", table_name="site_plan_goals")
    op.drop_index("ix_site_plan_goals_project_id", table_name="site_plan_goals")
    op.drop_index("ix_site_plan_goals_site_id", table_name="site_plan_goals")
    op.drop_table("site_plan_goals")

    op.drop_index("ix_site_plan_cells_row_id", table_name="site_plan_cells")
    op.drop_table("site_plan_cells")

    op.drop_index("ix_site_plan_rows_section_id", table_name="site_plan_rows")
    op.drop_index("ix_site_plan_rows_project_id", table_name="site_plan_rows")
    op.drop_index("ix_site_plan_rows_site_id", table_name="site_plan_rows")
    op.drop_table("site_plan_rows")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
