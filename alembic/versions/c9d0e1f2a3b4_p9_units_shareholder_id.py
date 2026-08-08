"""p9 hissedar-unite: units.shareholder_id

Tek kolon: `units.shareholder_id` — UUID FK → `land_share_shareholder.id`,
NULLABLE, `ondelete="SET NULL"` + `ix_units_shareholder_id` indeksi
(P9 spec §3, plan T1).

NEDEN `SET NULL` (spec §3): kaskat sirasi deterministik DEGILDIR — proje
silindiginde `land_share_shareholder` satirlari uniteler dusmeden once
dusebilir; `RESTRICT` proje silmeyi RASTGELE kirardi. SET NULL yalniz o
kaskadin DB emniyetidir. Atanmis hissedarin listeden cikarilmasina karsi ASIL
koruma uygulama katmanindadir (spec §4.1: 409) — DB'nin sessiz bosaltmasina
GUVENILMEZ.

Enum YOKTUR, izin modulu YOKTUR (`projects` modulu zaten allocation ucunu
tasiyor — spec §1). Veri gecisi YOKTUR: mevcut uniteler `NULL` dogar.

`ADD COLUMN ... DEFAULT` kullanilmaz — kolon nullable ve varsayilansizdir,
mevcut satirlara dokunulmaz (c3d4e5f6a7b8 dersi).

GERI ALMA NOTU: `downgrade` indeksi ve kolonu dusurur, dolayisiyla yapilmis
hissedar atamalari KAYBOLUR. Bu bilinclidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("units", sa.Column("shareholder_id", sa.UUID(), nullable=True))
    # Ad, Postgres'in kendi uretecegi adin AYNISIDIR (`units_project_id_fkey`
    # deseni): model tarafinda FK adsizdir, `alembic check` ad farkina takilmaz.
    op.create_foreign_key(
        "units_shareholder_id_fkey",
        "units",
        "land_share_shareholder",
        ["shareholder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_units_shareholder_id", "units", ["shareholder_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_units_shareholder_id", table_name="units")
    op.drop_constraint("units_shareholder_id_fkey", "units", type_="foreignkey")
    op.drop_column("units", "shareholder_id")
