"""mk3 kapasite snapshot

MK-3 T1 — `equipment_rental_invoice_lines.capacity_hours` (backend spec
`docs/superpowers/specs/2026-08-14-mk3-kapasite-snapshot-design.md` K1/K2/K4).

MK-2'nin kapatmadığı TEK delik: `rate_period = monthly` faturada saatlik bedelin
PAYDASI `equipment.monthly_capacity_hours`tan CANLI okunuyordu. Ekipman kartındaki
bu değer düzeltilirse ONAYLANMIŞ (hatta ödenmiş) bir faturanın tutarı geriye dönük
oynardı. Kolon o paydayı satıra DONDURUR.

🔴 Snapshot'lanan şey GİRDİdir, TÜREV değil (K1): çözülmüş saatlik bedel
(`hourly_rate`) KOLONLAŞTIRILMAZ — "para tek formülden türer" kanonu (MK-2 K4)
ayakta kalır; formül yalnız girdisini artık satırdan alır.

NULLABLE'dır (K2, fail-closed): kapasite yoksa saatlik bedel hesaplanamaz ve
`our_amount` `null` durur. Uydurma 0 ya da enjekte edilmiş varsayılan 200
BASILMAZ — varsayılan ekipman tablosunun işidir, faturanın değil.

🔴 K4 — MEVCUT SATIRLAR DOLDURULUR: `NULL` bırakmak, bugüne kadar doğru
hesaplanan onaylanmış bir faturayı deploy anında `null` tutara düşürürdü.
Bilgi kayıp değildir, ekipman kartında durmaktadır → `UPDATE … FROM equipment`.

Yeni enum YOKTUR → `DROP TYPE` işi de yoktur. İzin modülü AÇILMAZ (`equipment`
MK-1'de açıldı).

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a0b1c2d3e4f5"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINE_TABLE = "equipment_rental_invoice_lines"
CAPACITY_CHECK = "ck_equipment_rental_invoice_lines_capacity_hours_non_negative"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(LINE_TABLE, sa.Column("capacity_hours", sa.Integer(), nullable=True))
    # `rate_amount` deseniyle aynı: negatif payda hiçbir okumada anlamlı değildir,
    # NULL ("bilinmiyor") serbesttir.
    op.create_check_constraint(
        CAPACITY_CHECK, LINE_TABLE, "capacity_hours IS NULL OR capacity_hours >= 0"
    )

    # 🔴 K4 — mevcut satırlar ekipmandan doldurulur. Ekipmanı silinmiş satır
    # (RESTRICT yüzünden imkânsız) NULL kalır ve K2 gereği `null` tutara düşer.
    op.execute(
        sa.text(
            f"UPDATE {LINE_TABLE} SET capacity_hours = equipment.monthly_capacity_hours "
            f"FROM equipment WHERE equipment.id = {LINE_TABLE}.equipment_id"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CAPACITY_CHECK, LINE_TABLE, type_="check")
    op.drop_column(LINE_TABLE, "capacity_hours")
