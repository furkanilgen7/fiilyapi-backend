"""b4 company settings tablolari

Revision ID: 6c98d5b8b142
Revises: 1c788f666c43
Create Date: 2026-07-19 12:04:50.312379

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c98d5b8b142"
down_revision: str | Sequence[str] | None = "1c788f666c43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "company",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("only_row", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("tax_number", sa.String(length=50), nullable=True),
        sa.Column("tax_office", sa.String(length=100), nullable=True),
        sa.Column("trade_registry_no", sa.String(length=100), nullable=True),
        sa.Column("kep_address", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("logo_data", sa.LargeBinary(), nullable=True),
        sa.Column("logo_content_type", sa.String(length=100), nullable=True),
        sa.Column("logo_filename", sa.String(length=255), nullable=True),
        sa.Column("brand_color", sa.String(length=20), server_default="#2563eb", nullable=False),
        sa.Column("gib_integration_code", sa.String(length=100), nullable=True),
        sa.Column("earsiv_portal", sa.String(length=255), nullable=True),
        sa.Column(
            "default_vat_rate",
            sa.Numeric(precision=5, scale=2),
            server_default="20.00",
            nullable=False,
        ),
        sa.Column("auto_einvoice", sa.Boolean(), server_default="false", nullable=False),
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
        sa.CheckConstraint("only_row IS TRUE", name="company_single_row"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("only_row"),
    )
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "locale", sa.Enum("tr", "en", name="ui_locale"), server_default="tr", nullable=False
        ),
        sa.Column(
            "currency",
            sa.Enum("TRY", "USD", "EUR", name="ui_currency"),
            server_default="TRY",
            nullable=False,
        ),
        sa.Column("date_format", sa.String(length=20), server_default="DD.MM.YYYY", nullable=False),
        sa.Column(
            "density",
            sa.Enum("comfortable", "normal", "compact", name="ui_density"),
            server_default="normal",
            nullable=False,
        ),
        sa.Column(
            "theme",
            sa.Enum("light", "dark", "system", name="ui_theme"),
            server_default="light",
            nullable=False,
        ),
        sa.Column("accent_color", sa.String(length=20), server_default="#2563eb", nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "notification_prefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event_key", sa.String(length=100), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("sms", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),
    )
    op.create_index(
        op.f("ix_notification_prefs_user_id"), "notification_prefs", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_notification_prefs_user_id"), table_name="notification_prefs")
    op.drop_table("notification_prefs")
    op.drop_table("user_preferences")
    op.drop_table("company")
    # Bos-kolonlu drop_table enum'u otomatik dusurmez — acikca dusur (DuplicateObject korumasi).
    sa.Enum(name="ui_locale").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_currency").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_density").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_theme").drop(op.get_bind(), checkfirst=True)
