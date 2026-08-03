"""puantaj cekirdegi

Iki yeni tablo (`personnel` / `timesheet_entries`) ve BIR yeni enum
(`timesheet_code`) — puantaj spec §2, Task T1.

PAYLASILAN ENUM: `personnel.source` YENI bir tip ACMAZ — santiye gunlugu
diliminde (`b5c6d7e8f9a0`) yaratilan `worker_source` tipini yeniden kullanir.
Bu yuzden `create_type=False` ile baglanir ve `downgrade` bu tipi DUSURMEZ:
`site_diary_worker_counts` halen kullanmaktadir.

Izin migration'i YOKTUR: `timesheet` ve `personnel` modulleri seed'de zaten var
(`app/modules/roles/seed_data.py` satir 78-79 ve matris satir 171-172) —
matris DEGISMEZ.

IK alani ACILMAZ (belge/izin/SGK/bordro/ucret kolonu yok, spec §1) · meslek
katalog tablosu YOK (spec §7 S5) · onay/durum kolonu YOK (spec §7 S3) ·
kisi/gun toplamlari TUREV, kolon yok (spec §2).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# E5'in dortlusu + SP'nin `G`'si tek sette (spec §2).
timesheet_code_enum = sa.Enum(
    "worked", "leave", "holiday", "overtime", "temporary_duty", name="timesheet_code"
)

NEW_ENUMS = (timesheet_code_enum,)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum (paylasilan `worker_source` BURADA YARATILMAZ).
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. personnel — puantajin minimum IK cekirdegi.
    op.create_table(
        "personnel",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("trade", sa.String(length=100), nullable=True),
        sa.Column(
            "source", postgresql.ENUM(name="worker_source", create_type=False), nullable=False
        ),
        sa.Column("subcontractor_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["subcontractor_id"], ["subcontractors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # Tek yon zorlanir; ters yon (kaynak taseron ama bag bos) MESRUDUR.
        sa.CheckConstraint(
            "source = 'subcontractor' OR subcontractor_id IS NULL",
            name="ck_personnel_subcontractor_only_for_subcontractor_source",
        ),
    )
    op.create_index("ix_personnel_subcontractor_id", "personnel", ["subcontractor_id"])
    op.create_index("ix_personnel_user_id", "personnel", ["user_id"])

    # 3. timesheet_entries — UQ (personnel_id, work_date): kisi bir gunde TEK yerde.
    op.create_table(
        "timesheet_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("personnel_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column(
            "code", postgresql.ENUM(name="timesheet_code", create_type=False), nullable=False
        ),
        sa.Column("overtime_hours", sa.Numeric(precision=4, scale=1), nullable=True),
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
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "personnel_id", "work_date", name="uq_timesheet_entries_personnel_date"
        ),
        sa.CheckConstraint(
            "overtime_hours IS NULL OR (overtime_hours > 0 AND overtime_hours <= 24)",
            name="ck_timesheet_entries_overtime_hours_range",
        ),
    )
    op.create_index("ix_timesheet_entries_personnel_id", "timesheet_entries", ["personnel_id"])
    op.create_index("ix_timesheet_entries_site_id", "timesheet_entries", ["site_id"])
    op.create_index("ix_timesheet_entries_project_id", "timesheet_entries", ["project_id"])
    op.create_index("ix_timesheet_entries_section_id", "timesheet_entries", ["section_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_timesheet_entries_section_id", table_name="timesheet_entries")
    op.drop_index("ix_timesheet_entries_project_id", table_name="timesheet_entries")
    op.drop_index("ix_timesheet_entries_site_id", table_name="timesheet_entries")
    op.drop_index("ix_timesheet_entries_personnel_id", table_name="timesheet_entries")
    op.drop_table("timesheet_entries")

    op.drop_index("ix_personnel_user_id", table_name="personnel")
    op.drop_index("ix_personnel_subcontractor_id", table_name="personnel")
    op.drop_table("personnel")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    # `worker_source` DUSURULMEZ: site_diary_worker_counts halen kullaniyor.
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
