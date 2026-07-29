"""p1.1a project_status enum genislemesi (izole revizyon)

`project_status` enum'una `planning` degeri eklenir. `ALTER TYPE ... ADD VALUE`
ayni islem icinde kullanilamadigi (ve geri alinamadigi) icin tip TAKAS edilir
(spec §2.1). `completed` KALIR (§7.2). Yeni sira: planning · active · on_hold ·
completed. Mevcut satirlarin hicbiri degismez; sunucu varsayilani `active` kalir.

Revision ID: d1a2b3c4e5f6
Revises: c41a7e2b9d05
Create Date: 2026-07-29 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a2b3c4e5f6"
down_revision: str | Sequence[str] | None = "c41a7e2b9d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """`planning` iceren yeni tipe takas et (spec §2.1'deki yedi satirlik SQL)."""
    op.execute(
        "CREATE TYPE project_status_new AS ENUM ('planning', 'active', 'on_hold', 'completed')"
    )
    op.execute("ALTER TABLE projects ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE projects ALTER COLUMN status TYPE project_status_new "
        "USING status::text::project_status_new"
    )
    op.execute("DROP TYPE project_status")
    op.execute("ALTER TYPE project_status_new RENAME TO project_status")
    op.execute("ALTER TABLE projects ALTER COLUMN status SET DEFAULT 'active'")


def downgrade() -> None:
    """Ters takas. ONCE `planning` satirlarini `active`'e dusur, sonra tip degistir —
    sira ters olursa `USING` cevrimi gecersiz deger yuzunden patlar."""
    op.execute("UPDATE projects SET status = 'active' WHERE status = 'planning'")
    op.execute("CREATE TYPE project_status_old AS ENUM ('active', 'on_hold', 'completed')")
    op.execute("ALTER TABLE projects ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE projects ALTER COLUMN status TYPE project_status_old "
        "USING status::text::project_status_old"
    )
    op.execute("DROP TYPE project_status")
    op.execute("ALTER TYPE project_status_old RENAME TO project_status")
    op.execute("ALTER TABLE projects ALTER COLUMN status SET DEFAULT 'active'")
