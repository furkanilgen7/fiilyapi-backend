"""fat1t3 invoices tax_base non negative CHECK (NOT VALID + kosullu VALIDATE)

Envanter kaydi #56 — `ck_invoices_amounts_non_negative` YEDI para kolonundan
yalniz ALTISINI sayiyordu, `tax_base` DISARIDA kalmisti. Fatura defterine giden
kolon tam da budur (`posting.py`: credit=tax_base, debit=tax_base) — yani
`models.py`deki "DB SON SAVUNMADIR" yorumu bu kolon icin bugune kadar YALANDI.

## Kapatilan delik

Uygulama katmaninda negatif `tax_base` yazan BILINEN bir yol yok: tek insa
noktasi `amounts.py:compute` ve o kirpilmis kesinti bacaklarindan besleniyor
(kayit #56'nin SOMUT yarisi 2026-09-17 `c0784c1` ile kapandi). Kalan risk
derinlemesine-savunma boslugu: migration/toplu veri duzeltmesi/ileride
eklenecek bir yazma yolu `tax_base`i negatife dusurebilirdi ve DB bunu bugune
kadar REDDETMIYORDU.

--------------------------------------------------------------------------
🔴 NEDEN `NOT VALID` + KOSULLU `VALIDATE` (TB6 deseni — `e9f0a1b2c3d4`)
--------------------------------------------------------------------------
`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar: migration
patlarsa `&&` kisa devre yapar ve uvicorn HIC BASLAMAZ (tam kesinti). Duz bir
`DROP + ADD CONSTRAINT` mevcut satirlari TARAR ve TEK BIR ihlal satiri
`ALTER TABLE`i `CheckViolationError` ile patlatir.

`ADD CONSTRAINT ... NOT VALID` bu riski sifirlar: mevcut satirlari TARAMAZ
(`ALTER TABLE` ihlal yuzunden ASLA patlamaz), yeni ve GUNCELLENEN her satiri
TAM enforce eder. Sayim `ADD CONSTRAINT`in ACCESS EXCLUSIVE kilidi ALTINDA
kosar (araya yeni ihlal satiri commit edilemez -> "sayim 0 => VALIDATE
guvenli" garantiye doner) ve sonucu deploy gunlugune duser (yalniz SATIR
SAYISI — tutar/kimlik/tarih SIZMAZ).

Ihlal 0 ise AYNI islemde `VALIDATE` calisir (duz `ADD CONSTRAINT` ile ayni
guvence, `convalidated = t`). Ihlal > 0 ise `VALIDATE` ATLANIR, migration
BASARIYLA biter (uygulama ACILIR), WARNING satiri kalan isi soyler; `raise`
YOKTUR.

--------------------------------------------------------------------------
Kapsama: YENI kisit ESKISININ ustunu ORTER
--------------------------------------------------------------------------
YENI kisit ESKI kisitin katı bir kisitlamasidir: ESKI'nin reddettigi her satir
(altı kolondan biri negatif) YENI tarafindan da reddedilir (aynı yüklemler
degismeden kaldi); YENI ayrica `tax_base < 0` satirlarini da reddeder. Yani
ESKI kisiti dusurmek hicbir sey kaybettirmez, YENI kesin olarak daha gucludur
(`test_KAPSAMA_ve_SAYIM_DENKLIGI...` ile gercek Postgres uzerinde olculur).

Kisit ADI DEGISMEDI (`ck_invoices_amounts_non_negative`) — yalniz METNI
genisledi, anlami degismedi ("hicbir para kolonu negatif olamaz").

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: ca36b2e59ee3
Revises: b2c3d4e5f8a1
Create Date: 2026-09-23

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

#: `alembic.ini` kok logger'i WARNING/stderr, `alembic` logger'i INFO'dur ->
#: hem INFO hem WARNING Railway deploy gunlugune duser (TB6 emsali).
logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "ca36b2e59ee3"
down_revision: str | Sequence[str] | None = "b2c3d4e5f8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "invoices"
NAME = "ck_invoices_amounts_non_negative"

#: 🔴 SQL BURAYA KOPYALANIR ve `app.modules.invoicing.models.
#: AMOUNTS_NON_NEGATIVE_CHECK`ten ITHAL EDILMEZ: migration gecmisi DONMUS
#: olmalidir (TB6 emsali). Ikisinin BUGUN esit oldugu
#: `test_migration_SQL_i_modelin_SQL_i_ile_AYNI` ile AYRICA iddia edilir.
OLD_SQL = (
    "subtotal >= 0 AND advance_amount >= 0 AND retention_amount >= 0 AND "
    "vat_amount >= 0 AND withholding_amount >= 0 AND total >= 0"
)
NEW_SQL = (
    "subtotal >= 0 AND advance_amount >= 0 AND retention_amount >= 0 AND "
    "tax_base >= 0 AND vat_amount >= 0 AND withholding_amount >= 0 AND total >= 0"
)

#: Ihlal sayimi — kisit `NOT VALID` EKLENDIKTEN SONRA kosar (ACCESS EXCLUSIVE
#: kilidi altinda). Sorgu YENI kisitin reddedecegi satir kumesiyle BIREBIR
#: aynisini sayar; bu esitlik `VALIDATE`in guvenli oldugunun TEK dayanagidir.
COUNT_SQL = sa.text(
    "SELECT count(*) FROM invoices WHERE NOT ("
    "subtotal >= 0 AND advance_amount >= 0 AND retention_amount >= 0 AND "
    "tax_base >= 0 AND vat_amount >= 0 AND withholding_amount >= 0 AND total >= 0)"
)

#: Deploy gunlugunde GOZLE aranan greplenebilir imzalar.
VALIDATE_LOG_PREFIX = "FAT1T3 TAX_BASE CHECK: DOGRULANIYOR"
SKIP_VALIDATE_LOG_PREFIX = "FAT1T3 TAX_BASE CHECK: DOGRULAMA ATLANDI"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1-2. Eski (dar) kisit duser, genisletilmis metin `NOT VALID` ile girer.
    #      `NOT VALID` mevcut satirlari TARAMAZ -> `ALTER TABLE` ihlal
    #      yuzunden PATLAYAMAZ.
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, sa.text(NEW_SQL), postgresql_not_valid=True)

    # 3. Sayim, `ADD CONSTRAINT`in ACCESS EXCLUSIVE kilidi ALTINDA kosar:
    #    arada yeni satir commit edilemez, sonuc yarissiz.
    ihlal = bind.execute(COUNT_SQL).scalar_one()

    # 4. Ihlal varsa: VALIDATE ATLANIR, migration BASARIYLA biter (uygulama
    #    acilir), atlama SESSIZ OLMAZ.
    if ihlal:
        logger.warning(
            "%s: `%s` tablosunda %d adet negatif tutarli (tax_base dahil) "
            "fatura satiri var. `%s` kisiti genisletilmis metinle `NOT VALID` "
            "olarak EKLENDI ve bundan sonraki her INSERT/UPDATE'i TAM enforce "
            "eder; migration BASARIYLA bitti, uygulama ACILIR. Ancak "
            "`VALIDATE` ATLANDI: kisit gecmis satirlar icin dogrulanmamis "
            "(`convalidated = f`) kalir. Bu %d satir duzeltildikten SONRA elle "
            "`ALTER TABLE %s VALIDATE CONSTRAINT %s;` kosulmalidir. 🔴 BU "
            "MIGRATION BU VERITABANINDA BIR DAHA KOSMAZ (alembic revizyonu "
            "bir kez kosar) -> dogrulama kendiliginden YAPILMAYACAKTIR. "
            "Satirlarin kimligi/tutari/tarihi BILEREK yazilmadi: deploy "
            "gunlugu mali veri sizdirmaz.",
            SKIP_VALIDATE_LOG_PREFIX,
            TABLE,
            ihlal,
            NAME,
            ihlal,
            TABLE,
            NAME,
        )
        return

    # 5. Ihlal 0: sayim kumesi CHECK'in red kumesiyle BIREBIR ayni oldugundan
    #    `VALIDATE` matematiksel olarak patlayamaz -> kisit TAM dogrulanmis
    #    biter, duz `ADD CONSTRAINT` ile ayni guvence saglanir.
    logger.info(
        "%s: `%s` tablosunda negatif tutarli (tax_base dahil) fatura satiri "
        "sayisi %d. `%s` kisiti genisletilmis metinle `NOT VALID` eklendi ve "
        "AYNI islemde `VALIDATE` ediliyor -> tam dogrulanmis "
        "(`convalidated = t`) bitecek. Sayim `ADD CONSTRAINT`in ACCESS "
        "EXCLUSIVE kilidi altinda kosuldu, araya yeni satir giremez.",
        VALIDATE_LOG_PREFIX,
        TABLE,
        ihlal,
        NAME,
    )
    op.execute(sa.text(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {NAME}"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, sa.text(OLD_SQL))
