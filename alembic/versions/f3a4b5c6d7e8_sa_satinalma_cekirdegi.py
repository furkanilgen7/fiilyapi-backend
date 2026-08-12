"""sa satinalma cekirdegi

Bes yeni tablo (`suppliers` / `purchase_requests` / `purchase_request_lines` /
`purchase_quotes` / `purchase_orders`), DORT yeni enum (`payment_terms` /
`purchase_priority` / `purchase_request_status` / `purchase_order_status`) ve
ST'ye TEK ADDITIVE kolon (`stock_entries.purchase_order_id`) — SA spec §2,
plan T1.

IZIN MIGRATION'I YOKTUR (spec §2): `procurement` ("Satinalma & Teklif",
ModuleGroup.STOK_SATINALMA) izin modulu seed'de ZATEN VARDIR ve matris satiri
da mevcuttur — yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

TUREV OLAN KOLON ACILMAZ (spec §2): talep/kalem tutari · "Mevcut Stok" ·
"EN IYI FIYAT"/"EN HIZLI" rozetleri · tedarikcinin yillik siparis toplami.
Kapsam disi (spec §5, kasitli): cok adimli onay MOTORU tablosu YOK · tedarikci
PUANI YOK · adres/e-posta/IBAN YOK · mal kabul tablosu ve kismi teslim alani
YOK · bildirim alani YOK.

`stock_entries.supplier_name` SERBEST METNI DEGISMEZ (kayitli karar): geriye
donuk tedarikci eslestirmesi bu dilimin isi degildir.

Tedarikci ORNEK VERISI seed EDILMEZ (TED mockup verisidir).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_terms_enum = sa.Enum("cash", "days_15", "days_30", "days_60", name="payment_terms")
purchase_priority_enum = sa.Enum("normal", "urgent", "critical", name="purchase_priority")
purchase_request_status_enum = sa.Enum(
    "draft",
    "pending_approval",
    "quote_wait",
    "ordered",
    "delivered",
    "rejected",
    name="purchase_request_status",
)
purchase_order_status_enum = sa.Enum(
    "approved", "in_transit", "delivered", name="purchase_order_status"
)

NEW_ENUMS = (
    payment_terms_enum,
    purchase_priority_enum,
    purchase_request_status_enum,
    purchase_order_status_enum,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipleri.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. suppliers — tedarikci katalogu. DELETE ucu YOKTUR (`is_active`).
    #    Puan/adres/IBAN kolonu ACILMAZ (spec §5).
    op.create_table(
        "suppliers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # SERBEST METIN: TED alt-etiketi acik ucludur, enum ICAT EDILMEZ.
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("tax_no", sa.String(length=10), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column(
            "payment_terms",
            postgresql.ENUM(name="payment_terms", create_type=False),
            nullable=False,
        ),
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
    )

    # 3. purchase_requests — talep basligi. Numara SUNUCU URETIR ve GLOBAL tekildir.
    #    Santiye/bolum DARALTMADIR: silinince talep KALIR (SET NULL).
    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_no", sa.String(length=20), nullable=False),
        sa.Column("request_date", sa.Date(), nullable=False),
        sa.Column(
            "priority",
            postgresql.ENUM(name="purchase_priority", create_type=False),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=True),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("needed_by", sa.Date(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="purchase_request_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("quote_deadline", sa.Date(), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_no", name="uq_purchase_requests_request_no"),
    )
    # FK'ler otomatik indeks URETMEZ; liste suzgecleri bu sutunlardan gecer.
    op.create_index("ix_purchase_requests_project_id", "purchase_requests", ["project_id"])
    op.create_index("ix_purchase_requests_site_id", "purchase_requests", ["site_id"])
    op.create_index("ix_purchase_requests_section_id", "purchase_requests", ["section_id"])
    op.create_index("ix_purchase_requests_status", "purchase_requests", ["status"])
    op.create_index("ix_purchase_requests_request_date", "purchase_requests", ["request_date"])

    # 4. purchase_request_lines — CASCADE (yetim kalem) + kart RESTRICT.
    #    Miktar CHECK'i: ST'nin negatif duzeltme istisnasi burada YOKTUR.
    #    Stok karti / serbest metin XOR'u DB'de zorlanmaz: taslak GEVSEKTIR.
    #    `sort_order` (T3 eklemesi): FST kalem tablosu SIRALIDIR ve kullanicinin
    #    girdigi sira korunmalidir. `id` bir UUID4'tur, yani ona gore siralamak
    #    kararli ama EKLEME SIRASINDAN BAGIMSIZ bir dizilis verirdi. Sunucu
    #    varsayilani YOKTUR: degeri govdedeki dizinin INDEKSI belirler ve her
    #    yazma yolu onu acikca doldurur — varsayilan 0 olsaydi eksik doldurulan
    #    bir yol tum satirlari ayni sirada birakip sessizce keyfi dizerdi.
    op.create_table(
        "purchase_request_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("stock_item_id", sa.UUID(), nullable=True),
        sa.Column("free_text_name", sa.String(length=200), nullable=True),
        sa.Column("free_text_unit", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("estimated_unit_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_request_lines_quantity_positive"),
        sa.ForeignKeyConstraint(["request_id"], ["purchase_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_item_id"], ["stock_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_request_lines_request_id", "purchase_request_lines", ["request_id"]
    )
    op.create_index(
        "ix_purchase_request_lines_stock_item_id", "purchase_request_lines", ["stock_item_id"]
    )

    # 5. purchase_quotes — teklifler. `delivery_time` SERBEST METIN (TEK 67);
    #    "EN IYI FIYAT"/"EN HIZLI" rozetleri TUREVDIR, kolonlari YOKTUR.
    op.create_table(
        "purchase_quotes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("delivery_time", sa.String(length=100), nullable=False),
        sa.Column("warranty_note", sa.String(length=200), nullable=True),
        sa.Column(
            "payment_terms",
            postgresql.ENUM(name="payment_terms", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "shipping_included", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("shipping_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("is_selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(["request_id"], ["purchase_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_quotes_request_id", "purchase_quotes", ["request_id"])
    op.create_index("ix_purchase_quotes_supplier_id", "purchase_quotes", ["supplier_id"])

    # 6. purchase_orders — `request_id` NULLABLE (talepsiz siparis MESRU, §7 S3);
    #    talebi olan siparis talebi KILITLER (RESTRICT).
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_no", sa.String(length=20), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("quote_id", sa.UUID(), nullable=True),
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("expected_delivery", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="purchase_order_status", create_type=False),
            server_default="approved",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["request_id"], ["purchase_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quote_id"], ["purchase_quotes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no", name="uq_purchase_orders_order_no"),
    )
    op.create_index("ix_purchase_orders_request_id", "purchase_orders", ["request_id"])
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"])
    op.create_index("ix_purchase_orders_project_id", "purchase_orders", ["project_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])

    # 7. ST bagi (ADDITIVE): SG 85 "Ilgili Siparis". SET NULL — siparis
    #    dusurulse bile stok hareketi KALIR. `supplier_name` DEGISMEZ.
    op.add_column("stock_entries", sa.Column("purchase_order_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_stock_entries_purchase_order_id",
        "stock_entries",
        "purchase_orders",
        ["purchase_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_stock_entries_purchase_order_id", "stock_entries", ["purchase_order_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # ST'ye eklenen kolon geri alinir; `stock_entries` TABLOSU DUSMEZ (ST'nindir).
    op.drop_index("ix_stock_entries_purchase_order_id", table_name="stock_entries")
    op.drop_constraint("fk_stock_entries_purchase_order_id", "stock_entries", type_="foreignkey")
    op.drop_column("stock_entries", "purchase_order_id")

    op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_project_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_supplier_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_request_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")

    op.drop_index("ix_purchase_quotes_supplier_id", table_name="purchase_quotes")
    op.drop_index("ix_purchase_quotes_request_id", table_name="purchase_quotes")
    op.drop_table("purchase_quotes")

    op.drop_index("ix_purchase_request_lines_stock_item_id", table_name="purchase_request_lines")
    op.drop_index("ix_purchase_request_lines_request_id", table_name="purchase_request_lines")
    op.drop_table("purchase_request_lines")

    op.drop_index("ix_purchase_requests_request_date", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_status", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_section_id", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_site_id", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_project_id", table_name="purchase_requests")
    op.drop_table("purchase_requests")

    op.drop_table("suppliers")

    # Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
