"""fin1 cek senet portfoyu

FIN-1 — cek & senet portfoyu (gorev emri K1-K4). Mockup:
`projedesign/Ekran 10 - Finans Cek Odeme.dc.html`.

BIR yeni tablo + BIR eklenen kolon:
  1. `financial_instruments` — cek VE senet TEK tabloda (K1). Alan kumesi %95
     ortaktir; ayirmak iki kopya dogrulayici, iki kopya KPI ve iki kopya durum
     makinesi demekti.
  2. `payments.financial_instrument_id` — ISTEGE BAGLI bag (K4). **NULLABLE ve
     SET NULL**: `method='cheque'` iken doluluk ZORUNLU KILINMAZ, cunku bugunku
     kayitlarin hepsi bostur ve bu migration onlari dolduramaz — zorunluluk
     MEVCUT VERIYI gecersizlestirirdi.

UC yeni Postgres enum tipi gelir. 🔴 Downgrade UCUNU DE dusurur; biri kalirsa
ikinci `upgrade` "type already exists" ile patlar ve bu YALNIZ canlida gorulur
(`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar — patlarsa
`&&` kisa devre yapar ve uvicorn HIC BASLAMAZ, tam kesinti).
Ayni sey EKLENEN KOLON icin de gecerlidir: dusurulmezse ikinci upgrade
"column already exists" verir.

Izin modulu ACILMAZ: `treasury` seed'de ZATEN vardir (`roles/seed_data.py:103`),
bu migration izin satiri YAZMAZ (K9).

`accounting/` tablolari HIC DOKUNULMAZ (K5): cekin tahsilinde yevmiye fisi atmak
ayri bir dilimin isidir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d8e9f0a1b2c3
Revises: b4c5d6e7f8a9
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 🔴 `create_type=False` + acik `.create()`: `alembic/env.py`de
#: `transaction_per_migration=True` oldugu icin tip ile tabloyu AYNI islemde
#: yaratmak sorun degildir, ama tipin YARATIMI ve DUSURULMESI acikca yazilirsa
#: downgrade'de unutulamaz (repo deseni).
INSTRUMENT_KIND = postgresql.ENUM(
    "cheque", "promissory_note", name="financial_instrument_kind", create_type=False
)
INSTRUMENT_DIRECTION = postgresql.ENUM(
    "received", "issued", name="financial_instrument_direction", create_type=False
)
INSTRUMENT_STATUS = postgresql.ENUM(
    "portfolio",
    "collected",
    "paid",
    "returned",
    "cancelled",
    name="financial_instrument_status",
    create_type=False,
)

_ENUMS = (INSTRUMENT_KIND, INSTRUMENT_DIRECTION, INSTRUMENT_STATUS)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "financial_instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_kind", INSTRUMENT_KIND, nullable=False),
        sa.Column("direction", INSTRUMENT_DIRECTION, nullable=False),
        # K3: TEKIL DEGIL — farkli bankalarin cek numaralari cakisabilir.
        sa.Column("serial_no", sa.String(length=50), nullable=False),
        sa.Column("drawer_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        # Senette banka OLMAYABILIR.
        sa.Column("bank_name", sa.String(length=100), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "status",
            INSTRUMENT_STATUS,
            nullable=False,
            server_default=sa.text("'portfolio'"),
        ),
        # 🔴 SET NULL: proje/hesap bir BILGI BAGIDIR. CASCADE olsaydi bir projenin
        # silinmesi PORTFOYDEN para eksiltirdi.
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_financial_instruments_amount_positive"),
        sa.CheckConstraint(
            "due_date >= issue_date", name="ck_financial_instruments_due_after_issue"
        ),
    )
    op.create_index(
        "ix_financial_instruments_direction_status",
        "financial_instruments",
        ["direction", "status"],
    )
    op.create_index("ix_financial_instruments_due_date", "financial_instruments", ["due_date"])
    op.create_index(
        "ix_financial_instruments_instrument_kind", "financial_instruments", ["instrument_kind"]
    )
    op.create_index("ix_financial_instruments_project_id", "financial_instruments", ["project_id"])

    # K4 — ISTEGE BAGLI bag. Mevcut satirlar NULL kalir ve bu DOGRUDUR: hangi
    # odemenin hangi ceke ait oldugu bilgisi bugun HICBIR YERDE yoktur, uydurulamaz.
    op.add_column(
        "payments",
        sa.Column(
            "financial_instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_instruments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_payments_financial_instrument_id", "payments", ["financial_instrument_id"])


def downgrade() -> None:
    # Sira TERSTIR: once `payments`in bagi (FK hedefi ayakta olmali), sonra tablo,
    # en son tipler.
    op.drop_index("ix_payments_financial_instrument_id", table_name="payments")
    op.drop_column("payments", "financial_instrument_id")

    op.drop_index("ix_financial_instruments_project_id", table_name="financial_instruments")
    op.drop_index("ix_financial_instruments_instrument_kind", table_name="financial_instruments")
    op.drop_index("ix_financial_instruments_due_date", table_name="financial_instruments")
    op.drop_index("ix_financial_instruments_direction_status", table_name="financial_instruments")
    op.drop_table("financial_instruments")

    # 🔴 UCU DE DUSER — biri kalirsa ikinci upgrade "type already exists" ile
    # patlar ve uygulama canlida HIC ACILMAZ.
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.drop(bind, checkfirst=False)
