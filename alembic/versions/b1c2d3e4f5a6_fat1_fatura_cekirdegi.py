"""fat1 fatura cekirdegi

FAT-1 T1 — iki yeni tablo (`invoices` / `invoice_lines`) ve DORT yeni enum
(`invoice_direction` / `invoice_document_type` / `invoice_status` /
`invoice_payment_method`). Spec:
`docs/superpowers/specs/2026-08-14-fat1-fatura-cekirdegi-design.md` §2, §10.

IZIN MIGRATION'I YOKTUR (spec §6): `invoicing` ("Fatura Yonetimi",
ModuleGroup.MALI) izin modulu seed'de ZATEN VARDIR ve matris satiri da
mevcuttur — yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

BASKA HICBIR TABLOYA DOKUNULMAZ: bu dilim ADDITIVE kolon eklemez, kaynak
kayitlara (hakedis / kira faturasi / siparis) ters yonde bir bag KURMAZ —
fatura onlari GOSTERIR, onlar faturayi bilmez.

🔴 DORT ENUM DA DOWNGRADE'DE DUSER. Biri bile kalirsa ikinci `upgrade`
"type already exists" ile patlar (`d4e5f6a7b8c9` dersi) ve bu yalniz canlida
gorulurdu: `Dockerfile` acilista `alembic upgrade head` kosar, patlarsa uvicorn
hic baslamaz (tam kesinti).

TUREV OLAN KOLON ACILMAZ (spec §2/§3): "kalan gun" · "Vadeli" rozeti · KDV
farki · satir KDV tutari. Para kolonlari TUREV OLDUKLARI HALDE saklanir —
K7 snapshot kanonu (onayli faturanin tutari kaynak duzeltilince oynamaz).

Kapsam disi (spec §1, kasitli): GIB/e-Fatura alanlari · muhasebe/yevmiye ·
tahsilat kaydi ve banka hesabi · eslestirme motoru · para birimi/kur ·
iskonto sutunu.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

invoice_direction_enum = sa.Enum("outgoing", "incoming", name="invoice_direction")
invoice_document_type_enum = sa.Enum(
    "einvoice", "earchive", "refund", "withholding", name="invoice_document_type"
)
# IKI YONUN durumlari TEK tipte: `status` kolonu tektir. Yon disi gecisi
# (giden faturaya `approve`) DB degil `transitions.py` reddeder (409).
invoice_status_enum = sa.Enum(
    "draft", "sent", "collected", "pending", "approved", "disputed", name="invoice_status"
)
invoice_payment_method_enum = sa.Enum(
    "transfer", "cheque", "cash", "credit_card", name="invoice_payment_method"
)

NEW_ENUMS = (
    invoice_direction_enum,
    invoice_document_type_enum,
    invoice_status_enum,
    invoice_payment_method_enum,
)


def _dolu_sayisi(*kolonlar: str) -> str:
    """`en fazla biri dolu` CHECK'inin SQL metni — modeldeki ikizin aynisi."""
    return (
        "("
        + " + ".join(f"CASE WHEN {kolon} IS NULL THEN 0 ELSE 1 END" for kolon in kolonlar)
        + ") <= 1"
    )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Dort yeni enum tipi.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. invoices — fatura basligi.
    #    Numara YON ICINDE tekildir (§4/S5): giden'de sunucu, gelen'de satici
    #    uretir; global UNIQUE olsaydi saticinin serisi bizimkini bloklardi.
    #    Taraf snapshot'i ZORUNLU (`party_name` NOT NULL) + dort opsiyonel taraf
    #    FK'sinin en fazla BIRI dolu; kaynak FK'lari icin de ayni kural.
    #    `project_id` gorunurluk (IDOR) kolonudur: CASCADE, ve NULL = sirket
    #    geneli fatura (yalniz modul izniyle gorunur).
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM(name="invoice_direction", create_type=False),
            nullable=False,
        ),
        sa.Column("invoice_no", sa.String(length=30), nullable=False),
        sa.Column(
            "document_type",
            postgresql.ENUM(name="invoice_document_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="invoice_status", create_type=False),
            nullable=False,
        ),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "payment_method",
            postgresql.ENUM(name="invoice_payment_method", create_type=False),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        # Taraf snapshot'i (K7): cari karti degisse bile fatura DEGISMEZ.
        sa.Column("party_name", sa.String(length=200), nullable=False),
        sa.Column("party_tax_number", sa.String(length=11), nullable=True),
        sa.Column("party_tax_office", sa.String(length=100), nullable=True),
        sa.Column("party_address", sa.Text(), nullable=True),
        # Taraf izi.
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("supplier_id", sa.UUID(), nullable=True),
        sa.Column("subcontractor_id", sa.UUID(), nullable=True),
        # Kaynak izi.
        sa.Column("progress_payment_id", sa.UUID(), nullable=True),
        sa.Column("subcontractor_progress_payment_id", sa.UUID(), nullable=True),
        sa.Column("equipment_rental_invoice_id", sa.UUID(), nullable=True),
        sa.Column("purchase_order_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("site_id", sa.UUID(), nullable=True),
        # Para: hepsi NOT NULL — NULL bir toplam "bilinmiyor" ile "sifir"i ayni
        # yere dusururdu (NULL-ESIK kanonu).
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("advance_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "advance_amount",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("retention_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "retention_amount",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("tax_base", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("withholding_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "withholding_amount",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
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
        sa.CheckConstraint(
            _dolu_sayisi("employer_id", "customer_id", "supplier_id", "subcontractor_id"),
            name="ck_invoices_single_party",
        ),
        sa.CheckConstraint(
            _dolu_sayisi(
                "progress_payment_id",
                "subcontractor_progress_payment_id",
                "equipment_rental_invoice_id",
                "purchase_order_id",
            ),
            name="ck_invoices_single_source",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND advance_amount >= 0 AND retention_amount >= 0 AND "
            "vat_amount >= 0 AND withholding_amount >= 0 AND total >= 0",
            name="ck_invoices_amounts_non_negative",
        ),
        # NULL oran CHECK'i GECER: "kesinti isaretlenmemis" ile "oran %0" farkli
        # seylerdir (FK:223/229/235 checkbox'lari).
        sa.CheckConstraint(
            "(advance_rate IS NULL OR advance_rate BETWEEN 0 AND 100) AND "
            "(retention_rate IS NULL OR retention_rate BETWEEN 0 AND 100) AND "
            "(withholding_rate IS NULL OR withholding_rate BETWEEN 0 AND 100)",
            name="ck_invoices_rates_percentage",
        ),
        # Cari ve kaynak kayitlari RESTRICT: faturasi olan kayit silinemez.
        sa.ForeignKeyConstraint(["employer_id"], ["employers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subcontractor_id"], ["subcontractors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["progress_payment_id"], ["progress_payments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subcontractor_progress_payment_id"],
            ["subcontractor_progress_payments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_rental_invoice_id"],
            ["equipment_rental_invoices.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # Santiye yalnizca BILGI alanidir (FGI:106): kapansa bile fatura kalir.
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("direction", "invoice_no", name="uq_invoices_no_direction"),
    )
    # FK'ler otomatik indeks URETMEZ; liste suzgecleri bu sutunlardan gecer.
    op.create_index("ix_invoices_issue_date", "invoices", ["issue_date"])
    op.create_index("ix_invoices_project_id", "invoices", ["project_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])

    # 3. invoice_lines — CASCADE (yetim kalem birakilmaz).
    #    `vat_rate` SATIR BAZINDADIR (FGI:121): karma oranli fatura mumkundur.
    #    `line_total` sunucunun yazdigi donmus turevdir (K7); istemci gonderemez.
    #    `sort_order` sunucu varsayilani TASIMAZ: her yazma yolu govdedeki
    #    dizinin indeksini acikca doldurur (SA/T3 dersi).
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # SERBEST METIN (S3): FK:169 bir input'tur, kapali kume ICAT EDILMEZ.
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("detail_note", sa.String(length=200), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity_positive"),
        # Bedelsiz kalem MESRUDUR (0); negatif fiyat iskontonun yerine gecemez.
        sa.CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price_non_negative"),
        sa.CheckConstraint(
            "vat_rate BETWEEN 0 AND 100", name="ck_invoice_lines_vat_rate_percentage"
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")

    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_project_id", table_name="invoices")
    op.drop_index("ix_invoices_issue_date", table_name="invoices")
    op.drop_table("invoices")

    # 🔴 Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa
    # ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
