"""projects seed

Revision ID: 795d6498e4da
Revises: f0cdab9d36ff
Create Date: 2026-07-17 20:31:48.997043

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "795d6498e4da"
down_revision: str | Sequence[str] | None = "f0cdab9d36ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Bu migration app.modules.projects.models'i kasitli olarak import ETMEZ:
# uygulanmis bir migration donmus olmalidir, uygulama kodu zamanla degisir.


def upgrade() -> None:
    """Upgrade schema."""
    projects = sa.table(
        "projects",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("status", sa.Enum(name="project_status")),
        sa.column("budget", sa.Numeric()),
        sa.column("progress_pct", sa.Numeric()),
    )
    op.bulk_insert(
        projects,
        [
            {
                "id": uuid.uuid4(),
                "code": "GK-A",
                "name": "Güneşkent A-Blok",
                "status": "active",
                "budget": 1500000.00,
                "progress_pct": 42.50,
            },
            {
                "id": uuid.uuid4(),
                "code": "MERKEZ-1",
                "name": "Merkez Ofis",
                "status": "on_hold",
                "budget": 800000.00,
                "progress_pct": 15.00,
            },
            {
                "id": uuid.uuid4(),
                "code": "SAHIL-2",
                "name": "Sahil Sitesi",
                "status": "completed",
                "budget": 3200000.00,
                "progress_pct": 100.00,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM projects WHERE code IN ('GK-A', 'MERKEZ-1', 'SAHIL-2')")
