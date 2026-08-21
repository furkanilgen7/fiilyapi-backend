"""fisno yevmiye fis numarasi

FIS-NO — sunucu uretimli yevmiye fis numarasi `YEV-{yil}-{sira:04d}`
(`YEV-2026-0214`). Kullanici karari 2026-08-21. Mockup dayanagi:
`projedesign/Form - Yevmiye Kaydi.dc.html` (**Fis No** alani `disabled`,
"Otomatik" / "Kayitta uretilir") ve
`projedesign/Muhasebe - Donem Kapanisi.dc.html` (TASLAK fisler `YEV-2026-0214`
/ `0216` / `0218` — numara taslakta ZATEN vardir ve sira BOSLUKLU ilerler).

BIR yeni tablo + BIR eklenen kolon:
  1. `journal_entry_counters(year PK, next_no)` — YIL bazli, SIRKET GENELINDE
     TEK sayac. Fislerden BAGIMSIZ yasar: silme sayaci GERI SARMAZ (karar 2).
  2. `journal_entries.entry_no` — NOT NULL + UNIQUE.

🔴 SIRA SARTTIR: kolon ONCE nullable eklenir -> BACKFILL -> SONRA NOT NULL +
UNIQUE. Dogrudan NOT NULL eklenseydi, icinde fis olan bir veritabaninda
(CANLI) `column "entry_no" contains null values` ile patlardi.

🔴 BACKFILL DETERMINISTIKTIR: yil icinde `ORDER BY entry_date, id`. Ikinci
anahtar SARTTIR — `entry_date` TEKRAR EDER (ayni gune birden fazla fis kesmek
olagandir) ve tek anahtarli bir `row_number()` penceresinde esit siralarin
duzeni TANIMSIZDIR: ayni migration iki veritabaninda FARKLI numaralar
uretebilirdi. `id` (UUID) tekildir ve sirayi tam olarak belirler.

🔴 SAYAC TABLOSU HER YIL ICIN TOHUMLANIR (`count(*) + 1`). Tohumlanmazsa ilk
yeni fis `next_no = 1` ile dogar, `YEV-2026-0001` zaten backfill'de
dagitilmistir ve uc `uq_journal_entries_entry_no` ihlaliyle patlar — bu YALNIZ
VERI OLAN bir veritabaninda gorulur, bos test veritabaninda ASLA.

🔴 `lpad` TUZAGI: `lpad('10000', 4, '0')` -> `'1000'`. Postgres'in `lpad`i
metni genislige BUDAR ve bu, "9999'dan sonra numara budanmaz, bes haneye uzar"
kararinin sessiz ihlalidir (ustelik `10000` -> `1000` bir CAKISMA uretirdi).
Bu yuzden genislik `greatest(4, length(...))` ile hesaplanir — Python'daki
`f"{sira:04d}"` davranisinin BIREBIR karsiligi.

Downgrade kolonu VE tabloyu dusurur. Biri kalirsa ikinci `upgrade` "already
exists" ile patlar ve bu YALNIZ CANLIDA gorulur: `Dockerfile` acilista
`alembic upgrade head && uvicorn …` kosar, patlarsa `&&` kisa devre yapar ve
uvicorn HIC BASLAMAZ (tam kesinti).

Yeni Postgres enum tipi YOKTUR — `ALTER TYPE` geri alinamazligi bu dilimde
gundem disidir.

Izin modulu ACILMAZ: `accounting` seed'de ZATEN vardir; bu migration izin
satiri YAZMAZ.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "journal_entries"
COLUMN = "entry_no"
COUNTER_TABLE = "journal_entry_counters"
UNIQUE_CONSTRAINT = "uq_journal_entries_entry_no"

#: 🔴 `app.modules.accounting.numbering.format_entry_no`in SQL karsiligi.
#: Ikisi AYNI kurali soyler ve `test_fisno_migration` ikisini KARSILASTIRIR —
#: aksi hâlde backfill ile canli uretim sessizce AYRISIRDI.
#: `greatest(4, length(...))`: `lpad` metni BUDAR, bkz. modul docstring'i.
_BACKFILL = sa.text(
    """
    WITH numaralanmis AS (
        SELECT id,
               period_year,
               row_number() OVER (
                   PARTITION BY period_year
                   ORDER BY entry_date, id
               ) AS sira
        FROM journal_entries
    )
    UPDATE journal_entries AS je
    SET entry_no = 'YEV-'
                   || n.period_year::text
                   || '-'
                   || lpad(n.sira::text, greatest(4, length(n.sira::text)), '0')
    FROM numaralanmis AS n
    WHERE je.id = n.id
    """
)

#: Her yilin sayaci o yilin SON sirasindan devam eder. `count(*)` = backfill'in
#: `max(sira)`sidir (row_number bosluksuz uretir); `+ 1` "BIR SONRAKI"dir.
#: `journal_entries` bossa hicbir satir yazilmaz ve bu DOGRUDUR.
_SEED_COUNTERS = sa.text(
    """
    INSERT INTO journal_entry_counters (year, next_no)
    SELECT period_year, count(*) + 1
    FROM journal_entries
    GROUP BY period_year
    """
)


def upgrade() -> None:
    # 1. SAYAC TABLOSU — kolondan ONCE: tohumlama backfill'den sonra kosar ama
    #    tablonun kendisi o noktada ayakta olmalidir.
    op.create_table(
        COUNTER_TABLE,
        # `autoincrement=False`: yil bir dizi degeri DEGIL, veridir.
        sa.Column("year", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("next_no", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Elle bir `SET next_no = 0` sayaci GERI SARARDI (karar 2'nin tek fiili
        # ihlal yolu).
        sa.CheckConstraint("next_no >= 1", name="ck_journal_entry_counters_next_no_positive"),
    )

    # 2. KOLON — ONCE NULLABLE. Mevcut satirlarin numarasi HENUZ yoktur.
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=20), nullable=True))

    # 3. BACKFILL — deterministik (`entry_date, id`), bkz. modul docstring'i.
    op.execute(_BACKFILL)

    # 4. SAYAC TOHUMU — 3'ten SONRA olmak ZORUNDA: sayim backfill'in dagittigi
    #    son siraya dayanir.
    op.execute(_SEED_COUNTERS)

    # 5. ARTIK dolu: NOT NULL + UNIQUE. Sira TERSINE cevrilseydi veri olan her
    #    veritabaninda patlardi.
    op.alter_column(TABLE, COLUMN, existing_type=sa.String(length=20), nullable=False)
    op.create_unique_constraint(UNIQUE_CONSTRAINT, TABLE, [COLUMN])


def downgrade() -> None:
    # Sira TERSTIR. 🔴 KISIT + KOLON + TABLO: biri kalirsa ikinci upgrade
    # "already exists" ile patlar ve bu YALNIZ canlida gorulur.
    op.drop_constraint(UNIQUE_CONSTRAINT, TABLE, type_="unique")
    op.drop_column(TABLE, COLUMN)
    op.drop_table(COUNTER_TABLE)
