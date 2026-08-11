"""st stok cekirdegi

Dort yeni tablo (`stock_items` / `warehouses` / `stock_entries` /
`stock_entry_lines`) ve UC yeni enum (`stock_category` / `stock_entry_type` /
`stock_quality`) — ST spec §2, plan T1.

IZIN MIGRATION'I YOKTUR (spec §7 S5): `inventory` ("Stok & Depo",
ModuleGroup.STOK_SATINALMA) izin modulu seed'de ZATEN VARDIR ve matris satiri da
mevcuttur — 21. modul ACILMAZ, `seed_data.py` DEGISMEZ.

BAKIYE KOLONU YOKTUR (spec §3): bakiye tamamen `SUM(stock_entry_lines.quantity)`
turevidir. Miktara ISARET KISITI da konmaz — `adjustment` satirlari negatif
olabilir (§7 S4).

Kapsam disi (spec §5, kasitli): siparis FK'si YOK · tedarikci tablosu YOK
(`supplier_name` serbest metin) · sarf/cikis tablosu YOK · belge alani YOK
(BC form-slot) · bolum-ihtiyac kolonu YOK. Bunlar SA ve BC dilimlerinindir.

Depo ORNEK VERISI seed EDILMEZ: D-1/D-2/D-3 mockup verisidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

stock_category_enum = sa.Enum(
    "structural", "steel", "electrical", "mechanical", "interior", name="stock_category"
)
stock_entry_type_enum = sa.Enum("purchase", "transfer", "adjustment", name="stock_entry_type")
stock_quality_enum = sa.Enum("ok", "defective", "rejected", name="stock_quality")

NEW_ENUMS = (stock_category_enum, stock_entry_type_enum, stock_quality_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipleri.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. stock_items — malzeme karti katalogu. `unit` SERBEST METIN (enum DEGIL).
    op.create_table(
        "stock_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "category", postgresql.ENUM(name="stock_category", create_type=False), nullable=False
        ),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("min_stock", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.UniqueConstraint("code", name="uq_stock_items_code"),
    )

    # 3. warehouses — `site_id` NULL = merkez depo (§7 S2). SEED YOK.
    op.create_table(
        "warehouses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=True),
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
        # SET NULL: santiye silinince depo ve hareket gecmisi KALIR, bag kopar.
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_warehouses_site_name"),
    )
    op.create_index("ix_warehouses_site_id", "warehouses", ["site_id"])

    # 4. stock_entries — hareket basligi. Depolar RESTRICT: hareketi olan depo
    #    silinemez, yoksa bakiye tarihi sessizce delinir.
    op.create_table(
        "stock_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "entry_type",
            postgresql.ENUM(name="stock_entry_type", create_type=False),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("warehouse_id", sa.UUID(), nullable=False),
        sa.Column("source_warehouse_id", sa.UUID(), nullable=True),
        sa.Column("supplier_name", sa.String(length=200), nullable=True),
        sa.Column("delivery_note_no", sa.String(length=50), nullable=True),
        sa.Column("received_by_user_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["received_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # FK'ler otomatik indeks URETMEZ; bakiye/liste sorgulari bu uc sutundan gecer.
    op.create_index("ix_stock_entries_warehouse_id", "stock_entries", ["warehouse_id"])
    op.create_index(
        "ix_stock_entries_source_warehouse_id", "stock_entries", ["source_warehouse_id"]
    )
    op.create_index("ix_stock_entries_entry_date", "stock_entries", ["entry_date"])

    # 5. stock_entry_lines — CASCADE (yetim satir bakiyeyi sisirir) +
    #    kart RESTRICT (hareketi olan kart silinemez; `is_active=false` kullanilir).
    #    Miktara CHECK KONMAZ: `adjustment` negatif olabilir (§7 S4).
    op.create_table(
        "stock_entry_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "quality",
            postgresql.ENUM(name="stock_quality", create_type=False),
            server_default="ok",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["stock_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["stock_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_entry_lines_entry_id", "stock_entry_lines", ["entry_id"])
    op.create_index("ix_stock_entry_lines_item_id", "stock_entry_lines", ["item_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_stock_entry_lines_item_id", table_name="stock_entry_lines")
    op.drop_index("ix_stock_entry_lines_entry_id", table_name="stock_entry_lines")
    op.drop_table("stock_entry_lines")

    op.drop_index("ix_stock_entries_entry_date", table_name="stock_entries")
    op.drop_index("ix_stock_entries_source_warehouse_id", table_name="stock_entries")
    op.drop_index("ix_stock_entries_warehouse_id", table_name="stock_entries")
    op.drop_table("stock_entries")

    op.drop_index("ix_warehouses_site_id", table_name="warehouses")
    op.drop_table("warehouses")

    op.drop_table("stock_items")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
