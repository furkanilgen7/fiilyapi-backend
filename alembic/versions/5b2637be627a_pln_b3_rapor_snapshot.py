"""PLN-B3 — raporlar: onayli gunluk rapor SNAPSHOT'i (surumlu)

PLANLAMA-SPEC §3.13 B3-1/B3-5, K23: rapor onayi (`ev_report_approvals`, B2) bu tabloya o
anki rapor yukunu (JSONB) yazar; onayli rapor DEGISMEZ. Yeniden onay (kilit acma sonrasi)
YENI surum yazar — tarihce saklanir, ekran en sonu gosterir. Rapor no = gun no (`day_no`).
Tekillik (santiye, gun, surum); onay silinirse snapshot da gider (CASCADE).

`alembic revision --autogenerate` ile uretildi, elle duzeltildi: ilgisiz
`financial_instruments` NOT NULL suruklenmesi ALINMADI (B1/B2'de de boyleydi). Salt
EKLEME: mevcut tablo/kolon degismez.

Revision ID: 5b2637be627a
Revises: b877270195d8
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5b2637be627a"
down_revision: str | Sequence[str] | None = "b877270195d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ev_report_snapshots"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("day_no", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.CheckConstraint("version >= 1", name="ck_ev_report_snapshots_version"),
        sa.ForeignKeyConstraint(["approval_id"], ["ev_report_approvals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "report_date", "version", name="uq_ev_report_snapshots_ver"),
    )
    op.create_index("ix_ev_report_snapshots_approval_id", TABLE, ["approval_id"])
    op.create_index("ix_ev_report_snapshots_site_id", TABLE, ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_ev_report_snapshots_site_id", table_name=TABLE)
    op.drop_index("ix_ev_report_snapshots_approval_id", table_name=TABLE)
    op.drop_table(TABLE)
