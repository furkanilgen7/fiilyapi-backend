"""puan-saat: puantaj gun kodundan ADAM-SAATE

Puantaj hucresi artik **saat VEYA kod** tasir (mockup `Ekran 5 - Puantaj.dc.html`,
`5f3a944`). `worked`/`overtime` kodlari SAATE cevrilir, `overtime_hours` kolonu
duser (FM artik TUREVDIR, `app/modules/timesheet/hours.py`).

--------------------------------------------------------------------------
🔴 GOC KARARI — VERI SILINMEZ, `hours = 9 + COALESCE(overtime_hours, 0)`
--------------------------------------------------------------------------
Kullanici karari (2026-08-28): canlidaki puantaj SILINMEZ, varsayilan 9 saat
yazilir. Iki secenek olculdu:

  (a) `hours = 9`                       -> adam-gun TAM korunur, ama odenmis
                                           fazla mesai gecmisi (canlida ~30
                                           saat) SESSIZCE YOK OLUR;
  (b) `hours = 9 + overtime_hours`      -> FM gecmisi korunur, ekranin TUREV
                                           adam-gunu (saat/9) bir miktar kayar.

**(b) SECILDI.** Gerekcesi:
* para gecmisini silmek, bir TUREV sayinin kaymasindan pahalidir — silinen saat
  hicbir yerden geri gelmez, turev ise her istekte yeniden hesaplanir;
* mockup'in KENDI modeli de FM saatini adam/gun turevine katiyor (E5 347-350:
  `588 saat` icinde `27` saat FM var ve `588 / 9 = 65,3` yaziyor);
* 🔴 **BORDRO ETKILENMEZ** ve bu tesadufi degil, tasarimdir: `payroll` adam-gunu
  SAAT'ten degil "saati olan gun SAYISINDAN" okur
  (`payroll/service/compute_flow._man_day_counts`, `matrix.worked_day_clause`).
  Goc her `worked`/`overtime` hucresine saat yazdigi ve hicbirini silmedigi icin
  o sayi BIREBIR korunur -> **hesaplanmamis donemlerin brutu degismez.**
  (a) ile (b) arasindaki fark bordroya HIC yansimaz; yalnizca puantaj ekraninin
  serit rakami degisir.

--------------------------------------------------------------------------
🔴 NEDEN OLCUM MIGRATION'IN ICINDE
--------------------------------------------------------------------------
Canli veritabanina erisimimiz YOK. Olcemedigimiz bir goce "sonra bakariz"
denemez: olcumu KOSAN YERE tasiyoruz. ONCESI ve SONRASI sayimlari deploy
gunlugune duser (`alembic.ini` kok logger'i WARNING/stderr, `alembic` logger'i
INFO). 🔴 Satirlarin KIMLIGI yazilmaz — yalnizca toplamlar.

--------------------------------------------------------------------------
🔴 NEDEN `NOT VALID` + KOSULLU `VALIDATE`, NEDEN `raise` YOK
--------------------------------------------------------------------------
`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar: `&&` kisa
devre yapar ve TEK bir ihlalde uvicorn HIC BASLAMAZ = TAM KESINTI. Bu yuzden
(TB6 kanonu): kisit `NOT VALID` ile eklenir (mevcut satirlari TARAMAZ), ihlal
`ADD CONSTRAINT`in ACCESS EXCLUSIVE kilidi ALTINDA sayilir, 0 ise `VALIDATE`
edilir, degilse WARNING dusulur ve migration **BASARIYLA** biter.

--------------------------------------------------------------------------
PG enum etiketleri SILINMEZ
--------------------------------------------------------------------------
PostgreSQL bir enum tipinden etiket dusuremez. `timesheet_code` tipi `worked` ve
`overtime` etiketlerini TASIMAYA DEVAM EDER; geri sizmalarini
`ck_timesheet_entries_code_allowed` engeller (DB duzeyinde).

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d3f8a1c60b27
Revises: a6b7c8d9e0f1
Create Date: 2026-08-28

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "d3f8a1c60b27"
down_revision: str | Sequence[str] | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "timesheet_entries"

OLD_OVERTIME_CHECK = "ck_timesheet_entries_overtime_hours_range"

#: Yeni kisitlar — SQL BURAYA KOPYALANIR, modelden ithal EDILMEZ: migration
#: gecmisi DONMUS olmalidir (TB6 kanonu).
NEW_CHECKS: tuple[tuple[str, str], ...] = (
    ("ck_timesheet_entries_hours_range", "hours IS NULL OR (hours > 0 AND hours <= 24)"),
    ("ck_timesheet_entries_hours_xor_code", "(hours IS NULL) <> (code IS NULL)"),
    (
        "ck_timesheet_entries_code_allowed",
        "code IS NULL OR code IN ('leave', 'holiday', 'temporary_duty')",
    ),
)

#: Her kisitin REDDEDECEGI satir kumesiyle BIREBIR ayni kume (VALIDATE
#: guvenligi buna dayanir).
VIOLATION_SQL: dict[str, str] = {
    "ck_timesheet_entries_hours_range": (
        "SELECT count(*) FROM timesheet_entries "
        "WHERE hours IS NOT NULL AND NOT (hours > 0 AND hours <= 24)"
    ),
    "ck_timesheet_entries_hours_xor_code": (
        "SELECT count(*) FROM timesheet_entries "
        "WHERE NOT ((hours IS NULL) <> (code IS NULL))"
    ),
    "ck_timesheet_entries_code_allowed": (
        "SELECT count(*) FROM timesheet_entries "
        "WHERE code IS NOT NULL AND code::text NOT IN ('leave', 'holiday', 'temporary_duty')"
    ),
}

#: E5 71 "Normal gün 9 saat" — gocun varsayilani.
NORMAL_DAY_HOURS = 9

#: Deploy gunlugunde GOZLE aranan greplenebilir imzalar.
BEFORE_LOG = "PUAN-SAAT GOC ONCESI"
AFTER_LOG = "PUAN-SAAT GOC SONRASI"
SKIP_VALIDATE_LOG = "PUAN-SAAT CHECK: DOGRULAMA ATLANDI"
VALIDATE_LOG = "PUAN-SAAT CHECK: DOGRULANDI"

_BEFORE_SQL = sa.text(
    """
    SELECT
        count(*)                                                        AS hucre,
        count(*) FILTER (WHERE code::text IN ('worked', 'overtime'))    AS adam_gun,
        count(*) FILTER (WHERE code::text = 'overtime')                 AS fm_hucre,
        coalesce(sum(overtime_hours), 0)                                AS fm_saat,
        count(*) FILTER (
            WHERE code::text NOT IN ('worked', 'overtime')
        )                                                               AS kodlu
    FROM timesheet_entries
    """
)

_AFTER_SQL = sa.text(
    """
    SELECT
        count(*)                                    AS hucre,
        count(*) FILTER (WHERE hours IS NOT NULL)   AS saatli,
        count(*) FILTER (WHERE code IS NOT NULL)    AS kodlu,
        coalesce(sum(hours), 0)                     AS toplam_saat
    FROM timesheet_entries
    """
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. Saat kolonu + `code`un gevsetilmesi. Ikisi de goc UPDATE'inden ONCE
    #    olmali: kod NOT NULL kalirsa saate cevrilen hucrede NULL'a dusurulemez.
    op.add_column(TABLE, sa.Column("hours", sa.Numeric(4, 1), nullable=True))
    op.alter_column(TABLE, "code", existing_type=sa.Enum(name="timesheet_code"), nullable=True)

    # 2. ONCESI olcumu (goc UPDATE'inden once, ayni islemde).
    before = bind.execute(_BEFORE_SQL).mappings().one()
    logger.warning(
        "%s: hucre=%s · adam-gun (worked+overtime)=%s · FM hucresi=%s · FM saati=%s · "
        "kodlu (izin/tatil/gorev)=%s",
        BEFORE_LOG,
        before["hucre"],
        before["adam_gun"],
        before["fm_hucre"],
        before["fm_saat"],
        before["kodlu"],
    )

    # 3. GOC — karar (b): FM saati KORUNUR, hicbir satir SILINMEZ.
    op.execute(
        sa.text(
            "UPDATE timesheet_entries "
            "SET hours = :normal + coalesce(overtime_hours, 0), code = NULL "
            "WHERE code::text IN ('worked', 'overtime')"
        ).bindparams(normal=NORMAL_DAY_HOURS)
    )

    # 4. Eski FM kolonu ve kisiti duser — FM artik TUREVDIR.
    op.drop_constraint(OLD_OVERTIME_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "overtime_hours")

    # 5. SONRASI olcumu.
    after = bind.execute(_AFTER_SQL).mappings().one()
    toplam_saat = after["toplam_saat"]
    logger.warning(
        "%s: hucre=%s · saatli=%s · kodlu=%s · toplam saat=%s · turetilen adam-gun "
        "(saat/9)=%s · 🔴 bordronun adam-gunu (saatli hucre SAYISI)=%s "
        "(ONCESI adam-gun ile ESIT OLMALI: %s)",
        AFTER_LOG,
        after["hucre"],
        after["saatli"],
        after["kodlu"],
        toplam_saat,
        round(float(toplam_saat) / NORMAL_DAY_HOURS, 1),
        after["saatli"],
        before["adam_gun"],
    )

    # 6. Yeni kisitlar: `NOT VALID` -> kilit altinda say -> 0 ise VALIDATE.
    for name, sql in NEW_CHECKS:
        op.create_check_constraint(name, TABLE, sa.text(sql), postgresql_not_valid=True)
        ihlal = bind.execute(sa.text(VIOLATION_SQL[name])).scalar_one()
        if ihlal:
            logger.warning(
                "%s: `%s` kisiti `NOT VALID` olarak EKLENDI ve bundan sonraki her "
                "INSERT/UPDATE'i TAM enforce eder, ama %d mevcut satir onu ihlal "
                "ediyor -> `VALIDATE` ATLANDI (`convalidated = f`). Migration "
                "BASARIYLA bitti, uygulama ACILIR. Satirlar duzeltildikten SONRA "
                "elle `ALTER TABLE %s VALIDATE CONSTRAINT %s;` kosulmalidir. "
                "🔴 BU MIGRATION BIR DAHA KOSMAZ -> dogrulama kendiliginden "
                "YAPILMAYACAKTIR.",
                SKIP_VALIDATE_LOG,
                name,
                ihlal,
                TABLE,
                name,
            )
            continue
        op.execute(sa.text(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {name}"))
        logger.info("%s: `%s` (ihlal 0).", VALIDATE_LOG, name)


def downgrade() -> None:
    """Downgrade schema.

    SIMETRIK ama KAYIPLIDIR ve oyle olmak zorundadir: saat -> kod donusumu
    geri cevrilirken 9 saati asan kisim `overtime_hours`a, 9 ve altindaki gun
    `worked`a doner. 9'un ALTINDAKI saat (yarim gun) eski semada TEMSIL
    EDILEMEZ -> `worked` olur ve fark kaybolur. Bu kaybi sessizce yapmamak icin
    downgrade de olcum yazar.
    """
    bind = op.get_bind()

    for name, _ in NEW_CHECKS:
        op.drop_constraint(name, TABLE, type_="check")

    op.add_column(TABLE, sa.Column("overtime_hours", sa.Numeric(4, 1), nullable=True))

    kayip = bind.execute(
        sa.text("SELECT count(*) FROM timesheet_entries WHERE hours IS NOT NULL AND hours < :n")
        .bindparams(n=NORMAL_DAY_HOURS)
    ).scalar_one()
    logger.warning(
        "PUAN-SAAT DOWNGRADE: %d hucrede 9 saatin ALTINDA calisma var; eski sema "
        "yarim gunu temsil edemedigi icin bu hucreler `worked` (tam gun) olur ve "
        "eksik saat KAYBOLUR.",
        kayip,
    )

    op.execute(
        sa.text(
            "UPDATE timesheet_entries SET "
            "overtime_hours = CASE WHEN hours > :n THEN hours - :n ELSE NULL END, "
            "code = CASE WHEN hours > :n THEN 'overtime'::timesheet_code "
            "            ELSE 'worked'::timesheet_code END "
            "WHERE hours IS NOT NULL"
        ).bindparams(n=NORMAL_DAY_HOURS)
    )

    op.drop_column(TABLE, "hours")
    op.alter_column(TABLE, "code", existing_type=sa.Enum(name="timesheet_code"), nullable=False)
    op.create_check_constraint(
        OLD_OVERTIME_CHECK,
        TABLE,
        sa.text("overtime_hours IS NULL OR (overtime_hours > 0 AND overtime_hours <= 24)"),
    )
