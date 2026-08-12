"""ik2 izin yonetimi

İK-2 T1 — izin yönetimi şeması (backend spec
`docs/superpowers/specs/2026-08-12-ik2-izin-yonetimi-design.md` §1, §5).

Üç tablo:
  1. `leave_types` — izin tipi kataloğu + SEED 3 sabit tip (Yıllık / Hastalık /
     Mazeret, spec §1). CRUD ucu AÇILMAZ (ayarlar dilimi) — İK-1'in
     `personnel_document_types` deseninin birebir kardeşi. Downgrade tabloyu
     tamamen düşürdüğü için seed de temizlenir.
  2. `leave_requests` — izin talebi. `days` SUNUCU hesabıdır (spec §5 K2: takvim
     günü, başlangıç-bitiş DAHİL) ama KOLONDUR (rapor/toplam sorguları tekrar
     hesaplamasın). `document_id` BC-2 pilotu (İK-1 emsali): rapor dosyası
     `documents` arşivine yazılır, bu kayıt yalnız künyeye bağlanır — SET NULL,
     arşiv kaydı silinse de talep KALIR.
  3. `leave_balances` — yıl bazlı bakiye. YALNIZ `carried_over` kolondur (İZ 137
     "Devreden", manuel girilir). **`annual_entitlement` KOLON DEĞİLDİR**
     (spec §5 K1: kıdemden türev, 4857 kademeleri servis katmanında tek kaynak
     sabit); `used`/`remaining`/`usage_pct` de türevdir.

Bir yeni enum tipi: `leave_status(pending, approved, rejected)`. Downgrade'de
AÇIKÇA `DROP TYPE` edilir — yoksa ikinci `upgrade` "type already exists" ile
patlar (d4e5f6a7b8c9 dersi), bu yalnız CANLIDA görülürdü.

Elle yazılmıştır (autogenerate DEĞİL) — repo deseni.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-12

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

leave_status_enum = sa.Enum("pending", "approved", "rejected", name="leave_status")

NEW_ENUMS = (leave_status_enum,)

# Spec §1: SEED 3 tip. `deducts_from_annual` YALNIZ Yıllık'ta true — İZ 87
# "Rapor" yıllık haktan düşmez; `requires_document` YALNIZ Hastalık'ta (İZ 88).
# Sabit UUID DEĞİLDİR: downgrade tabloyu düşürdüğü için ikinci upgrade'de
# çakışma riski yoktur (İK-1 emsali).
LEAVE_TYPE_SEED = (
    {
        "name": "Yıllık İzin",
        "deducts_from_annual": True,
        "is_paid": True,
        "requires_document": False,
        "color": "#2563eb",
        "sort_order": 1,
    },
    {
        "name": "Hastalık İzni",
        "deducts_from_annual": False,
        "is_paid": True,
        "requires_document": True,
        "color": "#f59e0b",
        "sort_order": 2,
    },
    {
        "name": "Mazeret İzni",
        "deducts_from_annual": False,
        "is_paid": True,
        "requires_document": False,
        "color": "#8b5cf6",
        "sort_order": 3,
    },
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 1. leave_types — katalog. CRUD ucu YOK, seed 3 sabit tip (spec §1).
    op.create_table(
        "leave_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "deducts_from_annual", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_paid", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "requires_document", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_leave_types_name"),
    )

    leave_types_table = sa.table(
        "leave_types",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("deducts_from_annual", sa.Boolean()),
        sa.column("is_paid", sa.Boolean()),
        sa.column("requires_document", sa.Boolean()),
        sa.column("color", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        leave_types_table,
        [{**row, "id": uuid.uuid4()} for row in LEAVE_TYPE_SEED],
    )

    # 2. leave_requests — izin talebi.
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("personnel_id", sa.UUID(), nullable=False),
        sa.Column("leave_type_id", sa.UUID(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="leave_status", create_type=False),
            server_default=sa.text("'pending'::leave_status"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(length=2000), nullable=True),
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
        sa.CheckConstraint("end_date >= start_date", name="ck_leave_requests_date_order"),
        sa.CheckConstraint("days > 0", name="ck_leave_requests_days_positive"),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["leave_type_id"], ["leave_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leave_requests_personnel_id", "leave_requests", ["personnel_id"])
    op.create_index("ix_leave_requests_leave_type_id", "leave_requests", ["leave_type_id"])
    op.create_index("ix_leave_requests_status", "leave_requests", ["status"])
    # Cakisma (spec §5 K3) ve "bugun izinli" KPI'i tarih araligi tarar.
    op.create_index(
        "ix_leave_requests_personnel_range",
        "leave_requests",
        ["personnel_id", "start_date", "end_date"],
    )

    # 3. leave_balances — yil bazli bakiye. YALNIZ `carried_over` kolon.
    op.create_table(
        "leave_balances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("personnel_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "carried_over",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
        sa.CheckConstraint("carried_over >= 0", name="ck_leave_balances_carried_over_positive"),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("personnel_id", "year", name="uq_leave_balances_personnel_year"),
    )
    op.create_index("ix_leave_balances_personnel_id", "leave_balances", ["personnel_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_leave_balances_personnel_id", table_name="leave_balances")
    op.drop_table("leave_balances")

    op.drop_index("ix_leave_requests_personnel_range", table_name="leave_requests")
    op.drop_index("ix_leave_requests_status", table_name="leave_requests")
    op.drop_index("ix_leave_requests_leave_type_id", table_name="leave_requests")
    op.drop_index("ix_leave_requests_personnel_id", table_name="leave_requests")
    op.drop_table("leave_requests")

    # Katalog tablosu tamamen duser → SEED de temizlenir.
    op.drop_table("leave_types")

    # Enum tipi tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (İK-1 / d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
