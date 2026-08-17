"""ik3gv dilimli kumulatif gelir vergisi motoru

IK3-GV — GVK m.103 ARTAN ORANLI tarifesi + KK-7 asgari ucret istisnasi.

--------------------------------------------------------------------------
NICIN BU MIGRATION VAR
--------------------------------------------------------------------------
Bordroda gelir vergisi DUZ %10 hesaplaniyordu. Bu oran `c5d6e7f8a9b0:102`de
mockup etiketinden (SGK 72 "Gelir Vergisi Stopaji (%10)") alinmisti,
MEVZUATTAN DEGIL. Turkiye'de ucret geliri vergisi GVK m.103 uyarinca artan
oranlidir ve KUMULATIF matraha gore isler; %10 hicbir dilime karsilik gelmez.

Kusur "orani degistir" kadar kucuk DEGILDIR ve olculdu: `compute.py` dort isci
oranini TEK yuzdede toplayip (%25,759) tek carpim yapiyordu ve gelir vergisi
hesabin hicbir yerinde ayri bir `Decimal` olarak var olmuyordu. Dilimli vergi
brutun sabit bir yuzdesi olmadigi icin o yaklasim yapisal olarak kullanilamaz;
hesap zinciri AYRISTIRILDI ve bu migration onun VERI tarafini kurar.

--------------------------------------------------------------------------
NE YAPAR
--------------------------------------------------------------------------
1. `payroll_income_kind` enum'u + `payroll_tax_brackets` tablosu (K2) ve 2026
   UCRET tarifesinin 5 dilimi (KK-6).
2. `payroll_minimum_wages` tablosu + 2026 brut asgari ucreti (33.030,00).
3. `payroll_lines`a UC vergi snapshot kolonu (K1) — nullable, sunucu
   varsayilansiz (S4 fail-closed).
4. `personnel`e devir matrahi kolonlari (K7) — ACILIR, DOLDURULMAZ.
5. `payroll_rates.income_tax_pct` NULLABLE olur (K3) ve 2026 tohumunun bastigi
   `10` degeri `company`/`subcontractor` icin `NULL`a cekilir = "dilimli motor".

--------------------------------------------------------------------------
🔴 ENUM/ISLEM TUZAGI — `transaction_per_migration=True`'ya DOKUNULMADI
--------------------------------------------------------------------------
PG < 17'de MEVCUT bir enum tipine `ALTER TYPE ... ADD VALUE` ile eklenen deger
AYNI islemde KULLANILAMAZ. Bu migration o yola HIC girmez: `payroll_income_kind`
YENI bir tiptir ve AYNI islemde yaratildigi icin degerleri hemen kullanilabilir
(PostgreSQL bunu acikca istisna tutar; `c5d6e7f8a9b0`in
`'uncomputed'::payroll_line_status` sunucu varsayilani ayni desendir).
🔴 Yerel PG 18 bu kusur sinifini ZATEN goremez (kisit PG 17'de kaldirildi) —
yalniz CI'in PG 16'si gorur, bu yuzden yerel yesil hicbir sey kanitlamaz.

--------------------------------------------------------------------------
🔴 `= 10` KOSULU ZORUNLUDUR — KULLANICININ KENDI DEGERI EZILMEZ
--------------------------------------------------------------------------
`UPDATE ... SET income_tax_pct = NULL WHERE year = 2026` kosulsuz yazilsaydi,
kullanicinin `PUT /payroll/rates/2026/{source}` ile ELLE girdigi bir oran da
sessizce silinir ve o tip dilimli motora ITILIRDI. Duzeltilmesi gereken yalniz
TOHUMUN bastigi `10`dur (IK3-RATE-FIX'in `= 1` kosulunun aynisi).

`freelance` (%20, GVK m.94 serbest meslek stopaji) ve `intern` (0) DUZ ORAN
rejiminde KALIR ve bu migration onlara DOKUNMAZ: `intern`in 0'i bir VERIDIR
("kesinti yok" karari), `NULL` ile ayni sey degildir.

--------------------------------------------------------------------------
🔴 KILITLI DONEM KAPISI — DURDURMAZ, ATLAR ve BAGIRIR
--------------------------------------------------------------------------
IK3-RATE-FIX'te baglanan yonetim karari BURADA DA gecerlidir ve gerekcesi
aynidir: migration'in durmasi `alembic upgrade head`i patlatir ve uygulama HIC
ACILMAZ (`Dockerfile:22` `alembic upgrade head && uvicorn …`). Bir korkuluk,
korudugu seyden buyuk hasar uretemez.

Kapinin korudugu olgu `service.upsert_rate`inkiyle aynidir: oran satira
KOPYALANMAZ (K1) ve `sgk.py`/`summary.py` isveren tarafini donemin yilina ait
CANLI setten turetir; oran degisince ONAYLANMIS donemin raporlanmis toplamlari
geriye donuk degisirdi. KK-8 ("gecmis donemler donmus kalir") ile tutarli olan
davranis ATLAMAKTIR.

🔴 SESSIZ ATLAMA YASAK: atlama ERROR duzeyinde, tek satirda, greplenebilir bir
imzayla (`IK3-GV ATLANDI`) kayit birakir.
🔴 ATLAMA KALICIDIR: alembic bir revizyonu BIR KEZ kosar.
🔴 SEMA ADIMLARI KAPIDAN ETKILENMEZ — yalnizca VERI duzeltmesi atlanir. Sema
atlansaydi `Base.metadata` ile DB kalici olarak ayrisir ve uygulama patlardi.

--------------------------------------------------------------------------
🔴 DOWNGRADE VERIYI GERI YAZMAK ZORUNDADIR (RATE-FIX'ten FARKLI)
--------------------------------------------------------------------------
IK3-RATE-FIX'in downgrade'i kasitli NO-OP'tu cunku sema degismiyordu. Burada
`income_tax_pct` yeniden `NOT NULL` olur; `NULL` satirlar oldugu surece bu
ALTER PATLAR. Bu yuzden downgrade `NULL` degerleri tohumun `10`una GERI YAZAR —
bir tercih degil, semanin ZORUNLU KILDIGI adimdir. Yalniz `NULL` olanlara
dokunur; kullanicinin girdigi hicbir sayi degismez.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b3c4d5e6f7a8
Revises: f6a7b8c9d0e1
Create Date: 2026-08-17

"""

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

#: Atlama satirinin GREPLENEBILIR imzasi — deploy gunlugunde gozle aranir.
SKIP_LOG_PREFIX = "IK3-GV ATLANDI"

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

income_kind_enum = sa.Enum("wage", "non_wage", name="payroll_income_kind")

#: Tohumlanan yil. `c5d6e7f8a9b0:123` `RATE_SEED_YEAR` ile AYNI olmalidir:
#: dilimli motorun devraldigi tam olarak o yilin oran setidir.
TARGET_YEAR = 2026

#: Tohumlanan TEK gelir turu (K5). Ucret disi tarife MODELLENIR ama BASILMAZ.
WAGE_INCOME_KIND = "wage"

# --------------------------------------------------------------------------- #
# KK-6 — 2026 UCRET geliri tarifesi (kullanici karari, 2026-08-17)
# --------------------------------------------------------------------------- #
# Kaynak: GV Genel Tebligi 332, RG 31.12.2025 sayi 33124 (5. mukerrer).
#
#   #  ust esik      oran   kumulatif formul
#   1    190.000     %15    m x 0,15
#   2    400.000     %20    28.500    + (m -   190.000) x 0,20
#   3  1.500.000     %27    70.500    + (m -   400.000) x 0,27
#   4  5.300.000     %35    367.500   + (m - 1.500.000) x 0,35
#   5  ustu          %40    1.697.500 + (m - 5.300.000) x 0,40
#
# 🔴 UCRET tablosudur (bordro = ucret geliri). Ucret DISI tablo 3. dilimden
#    itibaren AYRISIR (1.000.000 / 232.500 / 1.737.500) ve BASILMAZ.
# 🔴 Tarife YDO'dan (%25,49) TURETILMEZ — olculdu: 158.000 -> 190.000 = +%20,25,
#    mekanik bir yeniden degerleme degil. Yayimlanmis degerler SABITLENIR.
TAX_BRACKETS_2026_WAGE: tuple[tuple[int, str | None, str], ...] = (
    (1, "190000.00", "15.000"),
    (2, "400000.00", "20.000"),
    (3, "1500000.00", "27.000"),
    (4, "5300000.00", "35.000"),
    (5, None, "40.000"),
)

#: 2026 brut asgari ucret (Komisyon Karari 2025/1, RG 26.12.2025).
#: Net (28.075,50) BURAYA YAZILMAZ — turetilir (brut - %14 SGK - %1 issizlik).
MINIMUM_WAGE_GROSS_2026 = "33030.00"

#: Tohumun bastigi DUZ oran (`c5d6e7f8a9b0:102`). `UPDATE`in `WHERE`i budur.
SEEDED_INCOME_TAX_PCT = Decimal("10")

#: Dilimli motora gecen personel tipleri (K3). `freelance`/`intern` DOKUNULMAZ.
BRACKET_REGIME_SOURCES = ("company", "subcontractor")

#: Oran yazisini engelleyen donem durumlari — `service.LOCKED_PERIOD_STATUSES`
#: ile ayni kume. Migration uygulama kodunu IMPORT ETMEZ (uygulanmis bir
#: migration DONMUS olmalidir — `a477fdf00fdf` kanonu), deger KOPYALANMISTIR.
LOCKED_PERIOD_STATUSES = ("approved", "paid")


def _seed_tax_brackets(bind) -> None:
    """2026 ucret tarifesini basar. `ON CONFLICT DO NOTHING` — idempotent."""
    for ordinal, upper_bound, rate_pct in TAX_BRACKETS_2026_WAGE:
        bind.execute(
            sa.text(
                "INSERT INTO payroll_tax_brackets "
                "(id, year, income_kind, ordinal, upper_bound, rate_pct, is_active) "
                "VALUES (:id, :year, CAST(:kind AS payroll_income_kind), :ordinal, "
                ":upper_bound, :rate_pct, true) "
                "ON CONFLICT (year, income_kind, ordinal) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "year": TARGET_YEAR,
                "kind": WAGE_INCOME_KIND,
                "ordinal": ordinal,
                "upper_bound": Decimal(upper_bound) if upper_bound is not None else None,
                "rate_pct": Decimal(rate_pct),
            },
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # --- 1. Tarife tablosu (K2) -------------------------------------------
    # 🔴 Tip AYNI islemde yaratilir; PG bunu enum/islem kisitindan acikca
    #    istisna tutar (modul docstring'i). `CREATE TYPE`i `create_table`
    #    kendisi emit eder — ayrica `.create()` cagrilsaydi ikinci CREATE
    #    "type already exists" ile PATLARDI (olculdu).
    op.create_table(
        "payroll_tax_brackets",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "income_kind",
            income_kind_enum,
            nullable=False,
            server_default=sa.text("'wage'::payroll_income_kind"),
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # `upper_bound IS NULL` = SON dilim ("ustu").
        sa.Column("upper_bound", sa.Numeric(14, 2), nullable=True),
        sa.Column("rate_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_payroll_tax_brackets_ordinal_positive"),
        sa.CheckConstraint(
            "rate_pct >= 0 AND rate_pct <= 100", name="ck_payroll_tax_brackets_rate_range"
        ),
        sa.CheckConstraint(
            "upper_bound IS NULL OR upper_bound > 0",
            name="ck_payroll_tax_brackets_upper_bound_positive",
        ),
        sa.UniqueConstraint(
            "year", "income_kind", "ordinal", name="uq_payroll_tax_brackets_year_kind_ordinal"
        ),
    )
    op.create_index("ix_payroll_tax_brackets_year", "payroll_tax_brackets", ["year"])

    # --- 2. Asgari ucret tablosu (KK-7) -----------------------------------
    op.create_table(
        "payroll_minimum_wages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("gross_amount > 0", name="ck_payroll_minimum_wages_gross_positive"),
        sa.UniqueConstraint("year", name="uq_payroll_minimum_wages_year"),
    )

    # --- 3. Vergi snapshot kolonlari (K1) ----------------------------------
    # 🔴 Ucu de nullable ve SUNUCU VARSAYILANSIZ (S4): var olan satirlarda
    #    `NULL` kalir. 0 basilsaydi "vergisi 0" ile "IK3-GV oncesi hesaplandi"
    #    ayirt edilemez olurdu; `sgk.py` bu ayrimi `unknown_tax_count` ile
    #    gorunur kilar.
    for kolon in ("tax_base_amount", "cumulative_tax_base", "income_tax_amount"):
        op.add_column("payroll_lines", sa.Column(kolon, sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        "ck_payroll_lines_tax_base_positive",
        "payroll_lines",
        "tax_base_amount IS NULL OR tax_base_amount >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_lines_cumulative_tax_base_positive",
        "payroll_lines",
        "cumulative_tax_base IS NULL OR cumulative_tax_base >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_lines_income_tax_positive",
        "payroll_lines",
        "income_tax_amount IS NULL OR income_tax_amount >= 0",
    )

    # --- 4. Devir matrahi (K7) — ACILIR, DOLDURULMAZ -----------------------
    op.add_column(
        "personnel",
        sa.Column(
            "opening_tax_base", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")
        ),
    )
    # Yil niteleyicisi ZORUNLUDUR: devir BIR YILA aittir. Olmasaydi 2026'da
    # girilen bir devir 2027'de de uygulanir ve "31 Aralik -> 1 Ocak sifirlanir"
    # kuralini sessizce bozardi.
    op.add_column("personnel", sa.Column("opening_tax_base_year", sa.Integer(), nullable=True))

    # --- 5. Tarife tohumu --------------------------------------------------
    _seed_tax_brackets(bind)
    bind.execute(
        sa.text(
            "INSERT INTO payroll_minimum_wages (id, year, gross_amount, is_active) "
            "VALUES (:id, :year, :gross, true) ON CONFLICT (year) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "year": TARGET_YEAR,
            "gross": Decimal(MINIMUM_WAGE_GROSS_2026),
        },
    )

    # --- 6. `income_tax_pct` NULLABLE (K3) --------------------------------
    # SEMA adimi kapidan ETKILENMEZ: atlansaydi `Base.metadata` ile DB kalici
    # olarak ayrisir ve `PayrollRateResponse` NULL doner gibi tanimlandigi hâlde
    # kolon NOT NULL kalirdi.
    op.alter_column(
        "payroll_rates", "income_tax_pct", existing_type=sa.Numeric(6, 3), nullable=True
    )

    # --- 7. VERI duzeltmesi: dilimli rejime gecis (K3) ---------------------
    hedef_satirlar = (
        bind.execute(
            sa.text(
                "SELECT personnel_source::text FROM payroll_rates "
                "WHERE year = :year AND personnel_source::text = ANY(:sources) "
                "AND income_tax_pct = :seeded ORDER BY personnel_source"
            ),
            {
                "year": TARGET_YEAR,
                "sources": list(BRACKET_REGIME_SOURCES),
                "seeded": SEEDED_INCOME_TAX_PCT,
            },
        )
        .scalars()
        .all()
    )
    if not hedef_satirlar:
        # Degisecek satir YOK -> kapi HIC calismaz (korunacak bir degisiklik de
        # yoktur). IK3-RATE-FIX'in "KAPININ SIRASI ONEMLIDIR" kurali.
        return

    kilitli = bind.execute(
        sa.text(
            "SELECT month, status::text FROM payroll_periods "
            "WHERE year = :year AND status = ANY(:statuses) ORDER BY month"
        ),
        {"year": TARGET_YEAR, "statuses": list(LOCKED_PERIOD_STATUSES)},
    ).all()
    if kilitli:
        donemler = ", ".join(f"{TARGET_YEAR}-{month:02d} ({status})" for month, status in kilitli)
        logger.error(
            "%s: %s yilinda onaylanmis/odenmis %d bordro donemi var (%s) -> "
            "`income_tax_pct` %s -> NULL (dilimli gelir vergisi motoruna gecis, K3) "
            "duzeltmesi bu yil icin ATLANDI. Etkilenecek %d oran satiri (%s) "
            "DOKUNULMADAN birakildi ve DUZ %%%s oraninda KALDI. Gerekce: oran satira "
            "kopyalanmaz, degistirilseydi bu donemlerin raporlanmis kesintileri ve "
            "SGK bildiriminin TAMAMI geriye donuk degisirdi (KK-8: gecmis donemler "
            "donmus kalir). SEMA adimlari ve tarife tohumu UYGULANDI; atlanan yalniz "
            "bu VERI duzeltmesidir. "
            "🔴 BU DUZELTME BU VERITABANINDA BIR DAHA CALISMAYACAK (alembic revizyonu "
            "bir kez kosar): yil kilitten ciksa bile kendiliginden uygulanmaz. "
            "Duzeltme isteniyorsa acikca kararlastirilip elle yapilmalidir.",
            SKIP_LOG_PREFIX,
            TARGET_YEAR,
            len(kilitli),
            donemler,
            SEEDED_INCOME_TAX_PCT,
            len(hedef_satirlar),
            ", ".join(hedef_satirlar),
            SEEDED_INCOME_TAX_PCT,
        )
        # 🔴 ATLA — DURMA. Migration basariyla devam eder, uygulama ACILIR.
        return

    op.execute(
        sa.text(
            "UPDATE payroll_rates SET income_tax_pct = NULL, updated_at = now() "
            "WHERE year = :year AND personnel_source::text = ANY(:sources) "
            "AND income_tax_pct = :seeded"
        ).bindparams(
            year=TARGET_YEAR,
            sources=list(BRACKET_REGIME_SOURCES),
            seeded=SEEDED_INCOME_TAX_PCT,
        )
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 VERI GERI YAZMA ZORUNLUDUR (modul docstring'i): `income_tax_pct` yeniden
    `NOT NULL` olacagi icin `NULL` satirlar once doldurulmalidir. Yalniz `NULL`
    olanlara dokunulur — kullanicinin girdigi hicbir sayi degismez.
    """
    op.execute(
        sa.text(
            "UPDATE payroll_rates SET income_tax_pct = :seeded, updated_at = now() "
            "WHERE income_tax_pct IS NULL"
        ).bindparams(seeded=SEEDED_INCOME_TAX_PCT)
    )
    op.alter_column(
        "payroll_rates", "income_tax_pct", existing_type=sa.Numeric(6, 3), nullable=False
    )

    op.drop_column("personnel", "opening_tax_base_year")
    op.drop_column("personnel", "opening_tax_base")

    for kisit in (
        "ck_payroll_lines_income_tax_positive",
        "ck_payroll_lines_cumulative_tax_base_positive",
        "ck_payroll_lines_tax_base_positive",
    ):
        op.drop_constraint(kisit, "payroll_lines", type_="check")
    for kolon in ("income_tax_amount", "cumulative_tax_base", "tax_base_amount"):
        op.drop_column("payroll_lines", kolon)

    op.drop_table("payroll_minimum_wages")
    op.drop_index("ix_payroll_tax_brackets_year", table_name="payroll_tax_brackets")
    op.drop_table("payroll_tax_brackets")
    # 🔴 ACIKCA DROP: yoksa ikinci `upgrade` "type already exists" ile patlar
    #    (`d4e5f6a7b8c9` dersi) ve bu YALNIZ CANLIDA gorulurdu.
    income_kind_enum.drop(op.get_bind(), checkfirst=True)
