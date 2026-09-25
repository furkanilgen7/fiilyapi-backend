"""DET-1.B — gunluk kaydinin GONDERENI (`site_diary_entries.submitted_by_user_id`)

Salt EKLEME: tek NULL kolon + FK (users, ON DELETE SET NULL). Varsayilan YOK, geri doldurma
YOK — DET-1.B oncesi gonderimler NULL kalir (denetim satirinda varlik kimligi yoktur; metinden
turetmek yeniden adlandirmada yanlis kisiyi dondururdu). Canli acilis guvenligi: NULL +
varsayilansiz ADD COLUMN tabloyu YENIDEN YAZMAZ (yalniz katalog degisikligi); FK eklemesi
mevcut satirlari tarar ama hepsi NULL oldugundan dogrulama anlik.

Revision ID: c7d1e2f3a4b5
Revises: 5b2637be627a
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "5b2637be627a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "site_diary_entries"
COLUMN = "submitted_by_user_id"
FK = "fk_site_diary_entries_submitted_by_user_id_users"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(COLUMN, postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(FK, TABLE, "users", [COLUMN], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(FK, TABLE, type_="foreignkey")
    op.drop_column(TABLE, COLUMN)
