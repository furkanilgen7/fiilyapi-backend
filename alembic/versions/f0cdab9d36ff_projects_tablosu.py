"""projects tablosu

Revision ID: f0cdab9d36ff
Revises: a477fdf00fdf
Create Date: 2026-07-17 20:21:25.965235

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0cdab9d36ff"
down_revision: str | Sequence[str] | None = "a477fdf00fdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "on_hold", "completed", name="project_status"),
            nullable=False,
        ),
        sa.Column("budget", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("progress_pct", sa.Numeric(precision=5, scale=2), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_code"), "projects", ["code"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_projects_code"), table_name="projects")
    op.drop_table("projects")
    # Bos-kolonlu drop_table enum'u otomatik dusurmez — acikca dusur (DuplicateObject korumasi).
    sa.Enum(name="project_status").drop(op.get_bind(), checkfirst=True)
