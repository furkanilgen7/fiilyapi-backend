"""puan-saat-3: bordro SAATE uyarlandi (adam-gun turev + FM carpani)

Iki semasal degisiklik ve BIR para karari tasir:

1. `payroll_lines.days` **`Integer` -> `Numeric(6,1)`**. Adam-gun artik bir
   SAYIM degil bir TUREVDIR (`toplam saat / 9`, mockup E5 349-350
   "588 saat · 65,3 adam/gun"). Eski kolon yarim gunu temsil EDEMIYORDU ve
   PUAN-SAAT-2'nin haftalik ekrani 4 saatlik gun girmeye izin verdigi an
   yevmiyeli personelde FAZLA ODEME uretecekti.
2. `payroll_overtime_rates` tablosu — FM carpani (mockup E5 358
   "x saatlik ucret x 1,5"). K1 kanonu: **oranlar VERIDIR, koda gomulmez.**

--------------------------------------------------------------------------
🔴 GECMIS BORDRO DEGISMEZ — tip GENISLEMESI, veri donusumu DEGIL
--------------------------------------------------------------------------
`integer -> numeric(6,1)` bir GENISLEMEDIR: `22` -> `22.0` AYNI sayidir, tek
bir satirin degeri oynamaz. Kolonu daraltan ya da yeniden hesaplayan hicbir
UPDATE yoktur. Onaylanmis/odenmis (`approved`/`paid`) ve elle duzeltilmis
(`is_overridden`) satirlar zaten `compute` tarafindan EZILMEZ (S5/S6), yani
gecmis donemlerin brutu de gunu de yerinde kalir
(`personnel_source` SNAPSHOT kanonuyla ayni aile).

⚠️ **HESAPLANMAMIS/TASLAK donemler yeniden hesaplandiginda DEGISIR** ve bu
dilimin AMACI budur: yevmiyelinin bruti artik gun sayisindan degil saatten
turer. Olcum asagida deploy gunlugune dusurulur.

--------------------------------------------------------------------------
🔴 NEDEN OLCUM MIGRATION'IN ICINDE
--------------------------------------------------------------------------
Canli veritabanina erisimimiz YOK (PUAN-SAAT-1 kanonu, `d3f8a1c60b27`).
Olcemedigimiz bir semasal degisikligi "sonra bakariz"a birakamayiz: olcumu
KOSAN YERE tasiyoruz. ONCESI/SONRASI toplamlari deploy gunlugune duser.
🔴 Satirlarin KIMLIGI yazilmaz — yalnizca toplamlar.

--------------------------------------------------------------------------
🔴 `raise` YOK
--------------------------------------------------------------------------
`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar: `&&` kisa
devre yapar ve tek bir istisnada uvicorn HIC BASLAMAZ = TAM KESINTI (TB6
kanonu). Bu migration'in hicbir adimi ihlal uretemez (genisleme + bos tabloya
CHECK) ama olcum adimlari yine de yalnizca LOG duser.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: ca19424d7118
Revises: d3f8a1c60b27
Create Date: 2026-08-28

"""

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "ca19424d7118"
down_revision: str | Sequence[str] | None = "d3f8a1c60b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Is K. m.41 — fazla calisma her bir saat icin %50 zamli (mockup E5 358/359).
#: Tohum SADECE bir baslangictir: sayi VERIDIR, degistigi gun kod degismez.
OVERTIME_MULTIPLIER = Decimal("1.500")

#: `payroll_rates` / `payroll_minimum_wages` tohumlariyla AYNI yil.
TARGET_YEAR = 2026

BEFORE_LOG = "PUAN-SAAT-3 ONCESI"
AFTER_LOG = "PUAN-SAAT-3 SONRASI"

_DAYS_SQL = sa.text(
    """
    SELECT
        count(*)                                            AS satir,
        count(*) FILTER (WHERE days IS NOT NULL)            AS gunlu,
        coalesce(sum(days), 0)                              AS gun_toplami,
        count(*) FILTER (
            WHERE status::text IN ('approved', 'paid') OR is_overridden
        )                                                   AS donmus
    FROM payroll_lines
    """
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    before = bind.execute(_DAYS_SQL).mappings().one()
    logger.warning(
        "%s: payroll_lines satiri=%s · gunu dolu=%s · gun toplami=%s · "
        "DONMUS satir (approved/paid/overridden, yeniden hesaplanmaz)=%s",
        BEFORE_LOG,
        before["satir"],
        before["gunlu"],
        before["gun_toplami"],
        before["donmus"],
    )

    # 1. Adam-gun ONDALIKLI olur. GENISLEME: `USING` bir donusum DEGIL, tip
    #    yukseltmesidir — 22 ve 22.0 ayni sayidir.
    op.alter_column(
        "payroll_lines",
        "days",
        existing_type=sa.Integer(),
        type_=sa.Numeric(6, 1),
        existing_nullable=True,
        postgresql_using="days::numeric(6,1)",
    )

    # 2. FM carpani tablosu. `payroll_minimum_wages`in birebir kardesi: yil
    #    anahtarli, tek satir, ucu YOK — mevzuat sayisi VERIDIR (K1).
    op.create_table(
        "payroll_overtime_rates",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("multiplier", sa.Numeric(4, 3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("multiplier >= 1", name="ck_payroll_overtime_rates_multiplier_min"),
        sa.UniqueConstraint("year", name="uq_payroll_overtime_rates_year"),
    )
    bind.execute(
        sa.text(
            "INSERT INTO payroll_overtime_rates (id, year, multiplier, is_active) "
            "VALUES (:id, :year, :multiplier, true) ON CONFLICT (year) DO NOTHING"
        ),
        {"id": uuid.uuid4(), "year": TARGET_YEAR, "multiplier": OVERTIME_MULTIPLIER},
    )

    after = bind.execute(_DAYS_SQL).mappings().one()
    logger.warning(
        "%s: payroll_lines satiri=%s · gunu dolu=%s · gun toplami=%s "
        "(ONCESI ile BIREBIR AYNI OLMALI: satir=%s gunlu=%s toplam=%s) · "
        "FM carpani tohumu %s -> %s",
        AFTER_LOG,
        after["satir"],
        after["gunlu"],
        after["gun_toplami"],
        before["satir"],
        before["gunlu"],
        before["gun_toplami"],
        TARGET_YEAR,
        OVERTIME_MULTIPLIER,
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 `numeric(6,1) -> integer` DARALTMADIR ve ondalikli gunleri yuvarlar;
    geri donusun kayipsiz olmadigi BURADA yazilidir. `ROUND` acikca yazilir —
    PostgreSQL'in ortuk donusumune birakilsaydi kayip gorunmez olurdu.
    """
    op.drop_table("payroll_overtime_rates")
    op.alter_column(
        "payroll_lines",
        "days",
        existing_type=sa.Numeric(6, 1),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(days)::integer",
    )
