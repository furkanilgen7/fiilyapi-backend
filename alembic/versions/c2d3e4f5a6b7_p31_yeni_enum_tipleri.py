"""P3.1 — yedi yeni enum tipi (izole revizyon)

`block_roof_type`, `block_ground_usage`, `block_parking_type`, `block_status`,
`unit_facing`, `unit_parking_right`, `unit_sales_status` tipleri olusturulur.
KOLON EKLENMEZ — 21 kolonluk sema genislemesi ayri revizyondadir (spec §10.2/R3).

NEDEN R3'TEN AYRI: Postgres'te `ENUM` tipi tablo/kolonla birlikte SILINMEZ.
R2+R3 birlesik olsaydi `downgrade` kolonlari dusurup tipleri birakabilir ve
IKINCI `upgrade` "type already exists" ile PATLARDI. Ayri revizyon her tipin
`DROP TYPE`'ini kendi `downgrade`'ine yazmayi ZORUNLU kilar.

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-31 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Etiket sirasi spec §3.1 / §4.1-4.2 tablolarindan BIREBIR alinmistir.
ENUM_TYPES: dict[str, tuple[str, ...]] = {
    "block_roof_type": ("none", "duplex", "terrace"),
    "block_ground_usage": ("commercial", "apartment", "common"),
    "block_parking_type": ("closed", "open", "none"),
    "block_status": ("planning", "construction", "completed"),
    "unit_facing": ("south", "southwest", "east", "north", "west"),
    "unit_parking_right": ("none", "one_closed", "two"),
    "unit_sales_status": ("listed", "reserved", "sold", "closed"),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, labels in ENUM_TYPES.items():
        sa.Enum(*labels, name=name).create(bind, checkfirst=False)


def downgrade() -> None:
    """Yedi tipin HEPSI dusurulur — biri unutulursa ikinci upgrade patlar."""
    bind = op.get_bind()
    for name, labels in ENUM_TYPES.items():
        sa.Enum(*labels, name=name).drop(bind, checkfirst=True)
