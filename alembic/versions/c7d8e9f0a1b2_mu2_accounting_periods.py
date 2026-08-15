"""mu2 accounting periods

MU-2 T2 — TEK yeni tablo (`accounting_periods`) ve TEK yeni enum
(`accounting_period_status`). MU-1 bu tabloyu BILEREK acmamisti
(`accounting/models.py` "ACILMAYANLAR" listesi): `journal_entries.period_year`/
`period_month` cifti ve `ix_journal_entries_period` indeksi tam olarak BU tablo
icin hazirlanmisti.

IZIN MIGRATION'I YOKTUR: `accounting` ("Muhasebe") izin modulu seed'de ZATEN
VARDIR (`roles/seed_data.py`) — yeni modul ACILMAZ, `seed_data.py` DEGISMEZ.

BASKA HICBIR TABLOYA DOKUNULMAZ: bu dilim ADDITIVE kolon eklemez. Kapali doneme
yazma YASAGI ve donem kilidi SERVIS katmanindadir (T3); burada yalniz KAYIT ve
tutarlilik kisitlari kurulur.

🔴 ENUM DOWNGRADE'DE DUSER. Kalirsa ikinci `upgrade` "type already exists" ile
patlar (`d4e5f6a7b8c9` dersi) ve bu YALNIZ CANLIDA gorulurdu: `Dockerfile`
acilista `alembic upgrade head` kosar, patlarsa uvicorn hic baslamaz (tam
kesinti).

🔴 `ck_accounting_periods_closed_stamp` bu dilimin ASIL bekcisidir. Damga IKI
PARCADIR (`closed_at` + `closed_by_id`) ve N-CARPANLI SNAPSHOT kanonu (MK-2)
geregi N'in HEPSI birlikte yazilir:
  * `closed` + eksik damga → "kapali ama kim/ne zaman kapatti belli degil";
    denetim gunlugu (B5) o donemi kimin kilitledigini SORAMAZ hale gelir,
  * `open` + artik damga  → yeniden acilmis donem hala eski kapatma damgasini
    tasir ve mali iz YALAN SOYLER.

🔴 UNIQUE ZATEN bir B-tree indeks URETIR — ayrica bir `ix_accounting_periods_
year_month` ACILMAZ (ayni iki sutun uzerinde ikinci bir indeks her yazmayi iki
kez maliyetlendirir, hicbir okumayi hizlandirmaz).

Ay/yil bantlari `journal_entries`te YOKTU cunku orada donem `entry_date`ten
TURETILIR ve `ck_journal_entries_period_matches_date` ile kilitlidir. Burada
tarih dayanagi olmadigi icin bant ACIKCA yazilir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: c7d8e9f0a1b2
Revises: d5e6f7a8b9c0
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Donem YA aciktir YA kapalidir. Ucuncu uye ICAT EDILMEZ: `CLOSED_STAMP` CHECK'i
# IKILI bir mantiktir, ucuncu degerde damganin ne olmasi gerektigi TANIMSIZ
# kalirdi.
accounting_period_status_enum = sa.Enum("open", "closed", name="accounting_period_status")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Yeni enum tipi.
    accounting_period_status_enum.create(bind, checkfirst=True)

    # 2. accounting_periods — donem kaydi + kapanis damgasi.
    #    🔴 Proje/santiye FK'si YOKTUR: MU-1'in uc tablosuyla AYNI gerekce —
    #    proje bazli donem acilsaydi ayni ay bir projede kapali bir projede
    #    acik olur ve "donem kapali" ifadesi ANLAMINI KAYBEDERDI.
    #    🔴 Turev alan (toplam/mizan) YOKTUR: yevmiyeden TURETILIR (K3 kardesi).
    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="accounting_period_status", create_type=False),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        # 🔴 IKISI DE nullable OLMAK ZORUNDA: `open` donemde ikisi de NULL'dir
        # (asagidaki CHECK bunu zorlar). NOT NULL olsalardi acik donem HIC
        # yazilamazdi.
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.UUID(), nullable=True),
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
        # `month = 0`/`13` var olmayan bir donem uretir, mizan hicbir takvimde
        # bulamaz; `year = 26`/`20026` sessizce kalici olurdu.
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_accounting_periods_month_range"),
        sa.CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_accounting_periods_year_range"),
        # 🔴 BU DILIMIN ASIL BEKCISI (bkz. modul docstring'i): damga BUTUNDUR.
        sa.CheckConstraint(
            "(status = 'closed' AND closed_at IS NOT NULL AND closed_by_id IS NOT NULL) OR "
            "(status = 'open' AND closed_at IS NULL AND closed_by_id IS NULL)",
            name="ck_accounting_periods_closed_stamp",
        ),
        # Ayni ay iki kez acilabilseydi biri `open` biri `closed` iki satir
        # dogar ve "2026/07 kapali mi?" sorusunun IKI cevabi olurdu.
        sa.UniqueConstraint("year", "month", name="uq_accounting_periods_year_month"),
        # RESTRICT: donemi kapatan kullanici silinemez. SET NULL olsaydi kapali
        # donem damgasiz kalir ve yukaridaki CHECK DB'nin KENDISI tarafindan
        # ihlal edilirdi.
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 🔴 `op.create_index(...)` YOK: UNIQUE zaten B-tree indeks uretir ve sorgu
    # yolu (`WHERE year = ? AND month = ?`) onun ta kendisini kullanir.


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_table("accounting_periods")

    # 🔴 Enum tipi tabloyla birlikte SILINMEZ — acikca dusurulur, yoksa ikinci
    # `upgrade` "type already exists" ile patlar (d4e5f6a7b8c9 dersi).
    accounting_period_status_enum.drop(bind, checkfirst=False)
