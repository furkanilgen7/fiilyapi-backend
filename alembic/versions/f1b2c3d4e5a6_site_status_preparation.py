"""santiye formu — `site_status` enum genislemesi (izole revizyon)

`site_status` enum'una `preparation` degeri eklenir (mockup satir 71 "Hazirlik").
`ALTER TYPE ... ADD VALUE` ayni islem icinde kullanilamadigi ve GERI ALINAMADIGI
icin tip TAKAS edilir (spec §3.1). `completed` KALIR (§3.1). Yeni sira:
preparation · active · on_hold · completed. Mevcut satirlarin hicbiri degismez;
sunucu varsayilani `active` kalir (mockup 71'de `Aktif` secili).

Bu revizyonda BASKA HICBIR SEY yoktur — 22 kolonluk sema genislemesi ayri
revizyondadir (`d1a2b3c4e5f6` dersi: enum takasi izole edilir).

Revision ID: f1b2c3d4e5a6
Revises: a4c7f1d2e8b3
Create Date: 2026-07-30 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5a6"
down_revision: str | Sequence[str] | None = "a4c7f1d2e8b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """`preparation` iceren yeni tipe takas et (spec §3.1'deki alti satirlik SQL)."""
    op.execute(
        "CREATE TYPE site_status_new AS ENUM ('preparation', 'active', 'on_hold', 'completed')"
    )
    op.execute("ALTER TABLE sites ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE sites ALTER COLUMN status TYPE site_status_new "
        "USING status::text::site_status_new"
    )
    op.execute("DROP TYPE site_status")
    op.execute("ALTER TYPE site_status_new RENAME TO site_status")
    op.execute("ALTER TABLE sites ALTER COLUMN status SET DEFAULT 'active'")


def downgrade() -> None:
    """Ters takas. ONCE `preparation` satirlarini `active`'e dusur, SONRA tip degistir —
    sira ters olursa `USING` cevrimi gecersiz deger yuzunden patlar (spec §3.1)."""
    op.execute("UPDATE sites SET status = 'active' WHERE status = 'preparation'")
    op.execute("CREATE TYPE site_status_old AS ENUM ('active', 'on_hold', 'completed')")
    op.execute("ALTER TABLE sites ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE sites ALTER COLUMN status TYPE site_status_old "
        "USING status::text::site_status_old"
    )
    op.execute("DROP TYPE site_status")
    op.execute("ALTER TYPE site_status_old RENAME TO site_status")
    op.execute("ALTER TABLE sites ALTER COLUMN status SET DEFAULT 'active'")
