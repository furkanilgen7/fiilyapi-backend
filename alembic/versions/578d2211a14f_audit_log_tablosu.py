"""audit_log tablosu

Denetim gunlugu (B5): degistirilemez kayit tablosu + `audit_action` enum tipi +
3 indeks. Additive migration — mevcut tablolara dokunmaz, canli oturumlari etkilemez.

`actor_user_id` FK'si ON DELETE SET NULL'dir: kullanici silindiginde denetim satiri
KORUNUR, aktor "Sistem"e duser. CASCADE denetim izini yok ederdi.

Revision ID: 578d2211a14f
Revises: 2cffc2fcfcf0
Create Date: 2026-07-25 21:19:05.137131

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "578d2211a14f"
down_revision: str | Sequence[str] | None = "2cffc2fcfcf0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Uygulanmis migration donmus olmalidir: app.modules.audit.models kasitli olarak
# import EDILMEZ, enum degerleri burada birebir kopyalanir.
AUDIT_ACTION_VALUES = ("login", "create", "update", "delete", "approve", "backup")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(*AUDIT_ACTION_VALUES, name="audit_action"),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_occurred_at", "audit_log", [sa.text("occurred_at DESC")])
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_occurred_at", table_name="audit_log")
    op.drop_table("audit_log")
    # Tabloyla birlikte otomatik dusmez: PG enum tipi acikca kaldirilir.
    sa.Enum(name="audit_action").drop(op.get_bind(), checkfirst=True)
