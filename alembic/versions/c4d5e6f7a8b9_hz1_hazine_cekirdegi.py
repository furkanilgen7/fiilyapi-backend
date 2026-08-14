"""hz1 hazine cekirdegi

HZ-1 T1 — iki yeni tablo (`bank_accounts` / `payments`) ve IKI yeni enum
(`bank_account_type` / `payment_method_kind`). Spec:
`docs/superpowers/specs/2026-08-14-hz1-hazine-cekirdegi-design.md` §2, §6.

IZIN MIGRATION'I YOKTUR (spec §4): `treasury` ("Hazine", ModuleGroup.MALI) izin
modulu seed'de ZATEN VARDIR ve matris satiri da mevcuttur
(`roles/seed_data.py:103`) — yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

BASKA HICBIR TABLOYA DOKUNULMAZ: bu dilim ADDITIVE kolon eklemez. Ozellikle
`invoices` uzerinde `paid_amount` ACILMAZ (K5): odenen = Σ payments, kalan =
`total − Σ payments`; faturanin durumu bundan TURETILEREK damgalanir. Bakiye de
SAKLANMAZ (K2), `opening_balance`ten ve odemelerden turetilir.

🔴 IKI ENUM DA DOWNGRADE'DE DUSER. Biri bile kalirsa ikinci `upgrade`
"type already exists" ile patlar (`d4e5f6a7b8c9` dersi) ve bu yalniz canlida
gorulurdu: `Dockerfile` acilista `alembic upgrade head` kosar, patlarsa uvicorn
hic baslamaz (tam kesinti).

IBAN tekilligi KISMI indekstir (`WHERE iban IS NOT NULL`): Kasa satirlarinin
NULL IBAN'i coklanabilir, dolu IBAN'lar tekildir (`customers.national_id`
emsali). Tam UNIQUE olsaydi ikinci kasa hesabi hic acilamazdi.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# K1: E9 YALNIZ `Vadesiz` ve `Kasa` ciziyor — baska tip ICAT EDILMEZ.
bank_account_type_enum = sa.Enum("checking", "cash", name="bank_account_type")
# FGI:225-228 birebir. `cheque`/`promissory_note` yalnizca ODEME SEKLI
# etiketidir; cek/senet VARLIGI HZ-2'nin isidir (`cheque_id` kolonu YOK).
payment_method_kind_enum = sa.Enum(
    "transfer", "cheque", "promissory_note", "cash", name="payment_method_kind"
)

NEW_ENUMS = (bank_account_type_enum, payment_method_kind_enum)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Iki yeni enum tipi.
    for enum_type in NEW_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # 2. bank_accounts — banka/kasa hesabi (E9:70-84).
    #    🔴 K3: proje/santiye FK'si YOKTUR — hesap SIRKET GENELIDIR, erisim
    #    `treasury` izin moduluyle denetlenir.
    #    🔴 K2: guncel bakiye KOLON DEGILDIR; saklanan tek para alani acilis
    #    bakiyesidir, gerisi `balance.py`de turetilir.
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bank_name", sa.String(length=100), nullable=False),
        sa.Column(
            "account_type",
            postgresql.ENUM(name="bank_account_type", create_type=False),
            nullable=False,
        ),
        # IBAN azami 34 karakter (ISO 13616); Kasa'da YOKTUR (E9:83).
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column(
            "opening_balance",
            sa.Numeric(precision=18, scale=2),
            server_default=sa.text("0"),
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
        # E9:83 Kasa kartinda IBAN yerine ad basilir — bos kalsaydi kart
        # tamamen isimsiz gorunurdu.
        sa.CheckConstraint(
            "account_type <> 'cash' OR display_name IS NOT NULL",
            name="ck_bank_accounts_cash_has_name",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # KISMI unique: NULL IBAN'lar coklanabilir (birden cok kasa), dolu IBAN'lar
    # tekildir — ayni hesap iki kart olarak acilirsa bakiye iki yere duserdi.
    op.create_index(
        "uq_bank_accounts_iban",
        "bank_accounts",
        ["iban"],
        unique=True,
        postgresql_where=sa.text("iban IS NOT NULL"),
    )

    # 3. payments — tahsilat VE odeme (FGI:220-247).
    #    🔴 K4: yon AYRI KOLON DEGILDIR, bagli faturanin `direction`'indan gelir.
    #    Uc FK de RESTRICT: odemesi olan fatura/hesap/kullanici silinemez,
    #    yoksa tahsilat gecmisi sessizce yok olur ve bakiye kayardi.
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("bank_account_id", sa.UUID(), nullable=False),
        sa.Column(
            "method",
            postgresql.ENUM(name="payment_method_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        # Sifir hicbir sey ifade etmez; negatif gizli bir IADE olurdu
        # (iade/avans kavrami hicbir mockup'ta modellenmemis). Asiri tahsilat
        # (K6) bir CHECK'le yakalanamaz — baska satirlarin toplamini goremez —
        # o denetim servistedir ve KILITLIDIR (K7).
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # FK'ler otomatik indeks URETMEZ: fatura odemeleri (uc 6 + K5 toplami),
    # bakiye turetimi (K2) ve nakit akisi ay penceresi (uc 10) bu sutunlardan
    # gecer.
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("ix_payments_bank_account_id", "payments", ["bank_account_id"])
    op.create_index("ix_payments_paid_on", "payments", ["paid_on"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # payments ONCE duser: bank_accounts'a RESTRICT ile baglidir.
    op.drop_index("ix_payments_paid_on", table_name="payments")
    op.drop_index("ix_payments_bank_account_id", table_name="payments")
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("uq_bank_accounts_iban", table_name="bank_accounts")
    op.drop_table("bank_accounts")

    # 🔴 Enum tipleri tablolarla birlikte SILINMEZ — acikca dusurulur, yoksa
    # ikinci `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    for enum_type in NEW_ENUMS:
        enum_type.drop(bind, checkfirst=False)
