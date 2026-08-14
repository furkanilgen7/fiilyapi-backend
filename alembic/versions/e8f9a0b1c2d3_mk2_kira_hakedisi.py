"""mk2 kira hakedisi

Iki yeni tablo (`equipment_rental_invoices` / `equipment_rental_invoice_lines`)
ve IKI yeni enum (`rental_invoice_status` / `rental_line_kind`)
— MK-2 spec §2.1, §2.2, §5.

🔴 UCUNCU bir tip (`equipment_rate_period`) KULLANILIR ama YARATILMAZ ve
DUSURULMEZ: o MK-1'in (d7e8f9a0b1c2) malidir ve DB tipi TEKTIR (`worker_source`
dersi). `postgresql.ENUM(..., create_type=False)` deseni mevcut tipi yeniden
olusturmadan baglar.

Izin modulu ACILMAZ: `equipment` MK-1'de acildi (21. modul), MK-2 ayni anahtari
kullanir — `payroll`/IK-3 emsali. Bu yuzden bu migration izin satiri YAZMAZ.

`our_amount` / `vat_amount` / `payable_total` / `hours_variance` KOLON DEGILDIR
(K4/K1/K6): hepsi turevdir — P10 "tek formul" kanonu. Toplamlar satirlardan
turer (MK-1 K15).

Belge tablolari (spec §2.3) BU MIGRATION'DA YOKTUR — T4'un isidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --------------------------------------------------------------------------- #
# Enum'lar (spec §5) — YALNIZ IKISI YENI.
# --------------------------------------------------------------------------- #

rental_invoice_status_enum = sa.Enum(
    "draft",
    "pending_verification",
    "approved",
    "paid",
    name="rental_invoice_status",
)
rental_line_kind_enum = sa.Enum("rented", "owned", "breakdown", name="rental_line_kind")

NEW_ENUMS = (rental_invoice_status_enum, rental_line_kind_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Iki yeni enum tipi. `equipment_rate_period` BURADA YARATILMAZ.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. equipment_rental_invoices — M5 basligi. `supplier_id` RESTRICT'tir
    #    (`equipment.supplier_id`in SET NULL'inin bilincli istisnasi): fatura bir
    #    PARA izidir, tedarikci silinerek odemenin muhatabi yok edilemez.
    op.create_table(
        "equipment_rental_invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        # K8: bir fatura TEK tedarikciye aittir (eslesme denetimi SERVISTE, 422).
        sa.Column("supplier_id", sa.UUID(), nullable=False),
        # M5:59 — taslakta henuz bilinmeyebilir.
        sa.Column("invoice_no", sa.String(length=100), nullable=True),
        # 🔴 K1: firmanin kestigi tutar, KDV HARIC matrahtir.
        sa.Column("invoice_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        # M5:72 — donemsiz fatura hicbir aya dusmezdi.
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        # M5:73 "Tum Projeler" = NULL (K9: NULL olan fatura HERKESE gorunur).
        sa.Column("site_id", sa.UUID(), nullable=True),
        # 🔴 M5:74 — MK-1'in tipi YENIDEN KULLANILIR, yeniden olusturulmaz.
        sa.Column(
            "rate_period",
            postgresql.ENUM(name="equipment_rate_period", create_type=False),
            nullable=False,
        ),
        # K1: oran VERIDIR, koda gomulu sabit DEGIL — gecmis fatura KENDI
        # oraniyla okunabilir kalir (IK-3 `payroll_rates` dersi).
        sa.Column(
            "vat_rate",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("20.00"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="rental_invoice_status", create_type=False),
            server_default=sa.text("'draft'::rental_invoice_status"),
            nullable=False,
        ),
        # SET NULL: onaylayan kullanici silinse de onay ZAMANI ayakta kalir.
        sa.Column("approved_by_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
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
            "period_month >= 1 AND period_month <= 12",
            name="ck_equipment_rental_invoices_month_range",
        ),
        sa.CheckConstraint(
            "invoice_amount IS NULL OR invoice_amount >= 0",
            name="ck_equipment_rental_invoices_amount_non_negative",
        ),
        sa.CheckConstraint(
            "vat_rate >= 0 AND vat_rate <= 100",
            name="ck_equipment_rental_invoices_vat_rate_range",
        ),
        # 🔴 Ayni faturayi iki kez odemeyi YAPISAL olarak engeller. `invoice_no`
        # NULL iken Postgres'in varsayilan NULLS DISTINCT semantigi altinda
        # taslaklar serbesttir (`personnel.tc_no` emsali).
        sa.UniqueConstraint(
            "supplier_id",
            "invoice_no",
            name="uq_equipment_rental_invoices_supplier_invoice_no",
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_equipment_rental_invoices_supplier_id", "equipment_rental_invoices", ["supplier_id"]
    )
    op.create_index(
        "ix_equipment_rental_invoices_site_id", "equipment_rental_invoices", ["site_id"]
    )
    op.create_index("ix_equipment_rental_invoices_status", "equipment_rental_invoices", ["status"])
    # Liste ucu donem bazli suzer (M5:72); iki kolon TEK indekste birlikte.
    op.create_index(
        "ix_equipment_rental_invoices_period",
        "equipment_rental_invoices",
        ["period_year", "period_month"],
    )

    # 3. equipment_rental_invoice_lines — M5 tablosu. `our_amount` KOLONU YOKTUR
    #    (K4): `worked_hours × saatlik bedel` MK-1'in `cost.py`sinden turer.
    op.create_table(
        "equipment_rental_invoice_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("equipment_id", sa.UUID(), nullable=False),
        # K3: odenecek toplama KATILIM buradan okunur (`owned`/`breakdown`
        # hicbir toplamin kaynagi degildir — cift odeme yapisal olarak imkansiz).
        sa.Column(
            "line_kind",
            postgresql.ENUM(name="rental_line_kind", create_type=False),
            nullable=False,
        ),
        # 🔴 Satirin SANTIYESI de bir SNAPSHOT'tir (K2 ilkesi + MK-1 K9): M5:89
        # tabloda satir basina "Santiye" sutunu var, M5:177-193 proje dagilimi
        # tam olarak satirin santiyesi + ekipmani + saati + tutari. Canli
        # `equipment.site_id`den turetilseydi makine tasininca ONAYLANMIS bir
        # faturanin proje maliyeti geriye donuk kayardi. NULL = "Atanmamis".
        sa.Column("site_id", sa.UUID(), nullable=True),
        # 🔴 K2: SNAPSHOT — calisma kaydindan KOPYALANIR, canli okunmaz.
        sa.Column("worked_hours", sa.Numeric(precision=8, scale=2), nullable=False),
        # M5:92 — varsayilani 0: "arizasiz" ile "bilinmiyor" ayni sey degildir.
        sa.Column(
            "breakdown_hours",
            sa.Numeric(precision=8, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        # M5:93 — DUZENLENEBILIR; bossa ekipmanin kendi bedeli, o da yoksa
        # maliyet `null` durur (MK-1 K16 fail-closed), 0 DEGIL.
        sa.Column("rate_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        # M5:95 — firmanin IDDIA ETTIGI saat; fark (K6) ancak iki bagimsiz sayi
        # varsa hesaplanabilir, bu yuzden AYRI kolondur.
        sa.Column("invoiced_hours", sa.Numeric(precision=8, scale=2), nullable=True),
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
            "worked_hours >= 0",
            name="ck_equipment_rental_invoice_lines_worked_hours_non_negative",
        ),
        sa.CheckConstraint(
            "breakdown_hours >= 0",
            name="ck_equipment_rental_invoice_lines_breakdown_hours_non_negative",
        ),
        sa.CheckConstraint(
            "rate_amount IS NULL OR rate_amount >= 0",
            name="ck_equipment_rental_invoice_lines_rate_amount_non_negative",
        ),
        sa.CheckConstraint(
            "invoiced_hours IS NULL OR invoiced_hours >= 0",
            name="ck_equipment_rental_invoice_lines_invoiced_hours_non_negative",
        ),
        # M5 ayni makineyi `rented` ve `breakdown` olarak IKI AYRI satir ciziyor;
        # UQ `line_kind`i icermeseydi ariza satiri sessizce reddedilirdi.
        sa.UniqueConstraint(
            "invoice_id",
            "equipment_id",
            "line_kind",
            name="uq_equipment_rental_invoice_lines_equipment_kind",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["equipment_rental_invoices.id"], ondelete="CASCADE"
        ),
        # RESTRICT: satiri olan ekipman silinemez (para izi).
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="RESTRICT"),
        # SET NULL: santiye kaydi kalksa satirin parasi ve saati AYAKTA kalir,
        # yalniz dagilimdaki kova "Atanmamis"a duser.
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_equipment_rental_invoice_lines_invoice_id",
        "equipment_rental_invoice_lines",
        ["invoice_id"],
    )
    op.create_index(
        "ix_equipment_rental_invoice_lines_equipment_id",
        "equipment_rental_invoice_lines",
        ["equipment_id"],
    )
    # Proje bazli dagilim (M5:177-193) satirin santiyesinden suzer.
    op.create_index(
        "ix_equipment_rental_invoice_lines_site_id",
        "equipment_rental_invoice_lines",
        ["site_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index(
        "ix_equipment_rental_invoice_lines_site_id", table_name="equipment_rental_invoice_lines"
    )
    op.drop_index(
        "ix_equipment_rental_invoice_lines_equipment_id",
        table_name="equipment_rental_invoice_lines",
    )
    op.drop_index(
        "ix_equipment_rental_invoice_lines_invoice_id", table_name="equipment_rental_invoice_lines"
    )
    op.drop_table("equipment_rental_invoice_lines")

    op.drop_index("ix_equipment_rental_invoices_period", table_name="equipment_rental_invoices")
    op.drop_index("ix_equipment_rental_invoices_status", table_name="equipment_rental_invoices")
    op.drop_index("ix_equipment_rental_invoices_site_id", table_name="equipment_rental_invoices")
    op.drop_index(
        "ix_equipment_rental_invoices_supplier_id", table_name="equipment_rental_invoices"
    )
    op.drop_table("equipment_rental_invoices")

    # Enum tipleri tablolarla birlikte SILINMEZ — IKISI DE acikca dusurulur,
    # yoksa ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    #
    # 🔴 `equipment_rate_period` BURADA YOKTUR ve OLMAMALIDIR: o MK-1'in malidir
    # ve `equipment.rate_period` kolonu ona baglidir — dusurulseydi MK-1'e
    # downgrade bile edilemezdi.
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
