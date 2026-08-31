"""AI-CHAT-2 / K2 — `ai_conversations` + `ai_messages`.

🔴 **KULLANICI KARARI A3 (2026-08-30): SORU + ÖZET SAKLANIR, ARAÇ SONUÇ
GÖVDELERİ HİÇ SAKLANMAZ.** Bu migration o kararın şema hâlidir; araç sonucunun
gövdesini (bordro satırı, TCKN, personel/müşteri verisi) taşıyabilecek **hiçbir
kolon** açılmaz. `ai_messages` yalnız araç **adlarını** ve zarf **hâllerini**
tutar.

🔴 `user_id` `ON DELETE CASCADE` — `ai_tool_calls`ın `SET NULL`undan bilinçli
SAPMA. Orada iz atfedilebilirlik için yaşar ve gövdesizdir; burada içerik
kullanıcının kendi sorularıdır ve sahipsiz kalmamalıdır.

Revision ID: a7c2e9d4b6f1
Revises: e5f7a9c1b3d4
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c2e9d4b6f1"
down_revision: str | None = "e5f7a9c1b3d4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_ai_conversations_user_updated",
        "ai_conversations",
        ["user_id", sa.text("updated_at DESC")],
    )

    ai_message_role = postgresql.ENUM(
        "kullanici", "asistan", name="ai_message_role", create_type=False
    )
    ai_message_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", ai_message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # 🔴 ADLAR — argümanlar DEĞİL.
        sa.Column("tool_names", postgresql.ARRAY(sa.Text()), nullable=False),
        # 🔴 ZARF HÂLLERİ — `veri` alanı DEĞİL.
        sa.Column("tool_states", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("finish_reason", sa.String(length=20), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_ai_messages_conversation", "ai_messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_messages_conversation", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_conversations_user_updated", table_name="ai_conversations")
    op.drop_table("ai_conversations")
    postgresql.ENUM(name="ai_message_role").drop(op.get_bind(), checkfirst=True)
