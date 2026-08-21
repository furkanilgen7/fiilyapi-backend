"""tb6 dengesiz reversed fis check (NOT VALID + kosullu VALIDATE)

TB6 — `journal_entries` denge CHECK'i `POSTING_STATUSES`in TAMAMINI kapsar ve
**kesinti riski olmadan** eklenir.

## Kapatilan delik

`ck_journal_entries_posted_balanced` yalnizca `status <> 'posted'` diyordu. Ama
`balance.POSTING_STATUSES` = `posted` **+ `reversed`**tir ve deftere (mizan,
bilanco, gelir tablosu, nakit akisi) **ikisi de girer**. Yani **dengesiz bir
`reversed` fis DB'ye yasal olarak girebiliyordu** ve girdiginde mali tablolarin
`is_balanced` gostergesi sessizce `False` doner, denge kalici olarak kayardi.

Yapisal olarak ihlal BEKLENMEZ ve gerekcesi olculmustur:

* `reversed`a giden TEK yol `state_service.perform_transition`dir ve matris
  yalnizca `posted -> reversed` gecisini tanir (`transitions.py`);
* `posted` olabilmenin sarti ESKI CHECK'ti (denge) ve gecis toplamlara
  DOKUNMAZ;
* baslik toplamlari yalnizca `service.apply_totals`tan yazilir, o da yalnizca
  `draft` fise (`assert_lines_editable`).

Yani uygulama uzerinden dengesiz bir `reversed` satir URETILEMEZ; delik ancak
dogrudan SQL ile kullanilabilirdi. Sayim yine de kosar: "yapisal olarak
imkansiz" bir OLCUM degildir.

--------------------------------------------------------------------------
🔴 NEDEN `NOT VALID` — VE NEDEN ARTIK HIC DURULMUYOR
--------------------------------------------------------------------------
Bu migration'in ILK hâli kisiti eklemeden ONCE ihlal sayiyor, sayim sifir
degilse `RuntimeError` firlatiyordu. `Dockerfile` acilista
`alembic upgrade head && uvicorn ...` kosar: `&&` kisa devre yapar ve **TEK BIR
ihlal satiri uvicorn'u HIC BASLATMAZ = TAM KESINTI.** Duz bir
`ADD CONSTRAINT` de ayni sonucu verirdi (tarama sirasinda `CheckViolationError`
ile patlar). Yani "guvende olmak icin durmak" fiilen kacinilmak istenen riskin
TA KENDISIYDI; dilim de bu yuzden aylarca kimsenin kosamadigi bir CANLI SQL
sayimini bekledi.

`ADD CONSTRAINT ... NOT VALID` bu dugumu ceker:

* **mevcut satirlari TARAMAZ** -> ihlal ne olursa olsun `ALTER TABLE` patlamaz,
  kesinti riski SIFIRDIR;
* **yeni ve GUNCELLENEN her satiri TAM enforce eder.** Olculdu: NOT VALID iken
  dengesiz `reversed` INSERT -> `23514` RED; dengesiz `posted` INSERT -> RED;
  temiz satiri ihlale ceviren UPDATE -> RED; kirli satira dokunan UPDATE ->
  RED. Dengeli INSERT ve dengesiz `draft` INSERT -> GECER.

Yani kisitin ILERIYE donuk gucu `NOT VALID` ile hic azalmaz; azalan tek sey
GECMIS satirlar hakkindaki `convalidated` isaretidir.

--------------------------------------------------------------------------
🔴 NEDEN SAYIM LOG'A YAZILIYOR
--------------------------------------------------------------------------
Canli veritabani OLCULEMIYORDU (yetki disi) ve olculemeyen bir olguya
"uygulamayi acmama" riski baglanamaz. Olcemedigimiz veriyi olcmenin yolu
OLCUMU CALISAN BIR YERE TASIMAKTIR: sayim migration'in ICINDEN kosar ve sonucu
deploy gunlugune duser. `alembic.ini` kok logger'i WARNING/stderr'dir ve
`alembic` logger'i INFO'dur -> iki satir da Railway deploy gunlugunde gorunur.

🔴 **LOG SATIRINA YALNIZ SATIR SAYISI YAZILIR.** Fis kimligi, tutar, tarih
ASLA yazilmaz: deploy gunlugu mali veri sizdirmaz.

--------------------------------------------------------------------------
🔴 NEDEN IHLAL 0 IKEN VALIDATE EDILIYOR (hicbir guvence feda edilmiyor)
--------------------------------------------------------------------------
`COUNT_SQL`, CHECK'in reddedecegi satir kumesiyle BIREBIR ayni kumeyi sayar
(NULL'lar dâhil olculdu, uyumsuzluk 0). O hâlde **sayim 0 ise `VALIDATE`
MATEMATIKSEL OLARAK patlayamaz.** Temiz bir veritabaninda kisit tam
dogrulanmis (`convalidated = t`) biter — yani duz `ADD CONSTRAINT` ile AYNI
guvence, ama kirli veri ihtimalinde kesinti YOK.

Sayim > 0 ise `VALIDATE` ATLANIR ve migration **BASARIYLA** biter: kisit yine
de ileriye donuk enforce eder, uygulama ACILIR, WARNING satiri operatore kalan
isi soyler. `raise` YOKTUR.

--------------------------------------------------------------------------
🔴 NEDEN SAYIM `ADD CONSTRAINT`TEN SONRA
--------------------------------------------------------------------------
Alembic READ COMMITTED kosar. Sayim ONCE kosarsa, sayim ile `ALTER TABLE`in
kilidi arasindaki pencerede baska bir islem ihlal satiri commit edebilir:
sayim "0" der, `VALIDATE` patlar, migration coker -> **tam kesinti**, yani
kacindigimiz seyin ta kendisi. `ADD CONSTRAINT` ACCESS EXCLUSIVE kilidi alir ve
islem sonuna kadar tutar; sayim O KILIDIN ALTINDA kosarsa araya yeni satir
giremez ve "sayim 0 => VALIDATE guvenli" bir GARANTIYE doner.

`ADD ... NOT VALID` ile `VALIDATE`in ayni islemde calistigi olculdu:
`convalidated` `f` -> `t` olur ve commit sonrasi `t` kalir.

--------------------------------------------------------------------------
Kapsama: YENI kisit ESKISININ ustunu ORTER
--------------------------------------------------------------------------
27 kombinasyon uzerinde (NULL'lar dâhil) `NEW => OLD` olculdu; kapsama ihlali
**0**. Yani eski CHECK'i dusurmek hicbir sey kaybettirmez: yeni kisit 4, eski
kisit 2 satir reddeder — kesin olarak daha gucludur.

--------------------------------------------------------------------------
Kisit ADI da degisti
--------------------------------------------------------------------------
`ck_journal_entries_posted_balanced` -> `ck_journal_entries_posting_balanced`:
eski ad artik YALAN soyluyordu (kisit `posted`i degil, DEFTERE GIRENLERI
bagliyor).

Downgrade SIMETRIKTIR: yeni kisit duser, eski kisit AYNEN eski hâliyle (yani
`NOT VALID` OLMADAN, taranarak) geri gelir. Tarama guvenlidir cunku eski kisit
yeninin GEVSEK bir alt kumesidir: dengesiz bir `reversed` satir eski kisiti
zaten gecer (`status <> 'posted'` dogrudur), dengesiz bir `posted` satir ise
eski kisit DOGRULANMIS oldugu icin hic var olamaz.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-19

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

#: `alembic.ini` kok logger'i WARNING/stderr, `alembic` logger'i INFO'dur ->
#: hem INFO hem WARNING Railway deploy gunlugune duser. `alembic.runtime`
#: altinda durur ki migration ciktisiyla ayni akista okunsun.
logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "journal_entries"
OLD_NAME = "ck_journal_entries_posted_balanced"
NEW_NAME = "ck_journal_entries_posting_balanced"

#: 🔴 SQL BURAYA KOPYALANIR ve `models.POSTING_BALANCED_CHECK`ten ITHAL EDILMEZ:
#: migration gecmisi DONMUS olmalidir. Modelden okunsaydi, kume ileride
#: degistiginde bu migration GERIYE DONUK baska bir sey basar ve zincir
#: yeniden kosuldugunda farkli bir semaya varirdi. Ikisinin BUGUN esit oldugunu
#: `test_tb6_reversed_balanced_check` ayrica iddia eder.
OLD_SQL = "status <> 'posted' OR total_debit = total_credit"
NEW_SQL = "status NOT IN ('posted', 'reversed') OR total_debit = total_credit"

#: Ihlal sayimi — kisit `NOT VALID` EKLENDIKTEN SONRA kosar (modul docstring'i:
#: "NEDEN SAYIM ADD CONSTRAINT'TEN SONRA"). Sorgu, CHECK'in reddedecegi satir
#: kumesiyle BIREBIR ayni kumeyi sayar; bu esitlik `VALIDATE`in guvenli
#: oldugunun tek dayanagidir, degistirilirse guvence duser.
COUNT_SQL = sa.text(
    "SELECT count(*) FROM journal_entries "
    "WHERE status IN ('posted', 'reversed') AND total_debit <> total_credit"
)

#: Deploy gunlugunde GOZLE aranan greplenebilir imzalar.
VALIDATE_LOG_PREFIX = "TB6 DENGE CHECK: DOGRULANIYOR"
SKIP_VALIDATE_LOG_PREFIX = "TB6 DENGE CHECK: DOGRULAMA ATLANDI"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1-2. Eski (dar) kisit duser, yenisi `NOT VALID` ile girer. `NOT VALID`
    #      mevcut satirlari TARAMAZ -> `ALTER TABLE` ihlal yuzunden PATLAYAMAZ.
    op.drop_constraint(OLD_NAME, TABLE, type_="check")
    op.create_check_constraint(NEW_NAME, TABLE, sa.text(NEW_SQL), postgresql_not_valid=True)

    # 3. Sayim, `ADD CONSTRAINT`in ACCESS EXCLUSIVE kilidi ALTINDA kosar:
    #    arada yeni satir commit edilemez, sonuc yarissiz.
    ihlal = bind.execute(COUNT_SQL).scalar_one()

    # 4. Ihlal varsa: VALIDATE ATLANIR, migration BASARIYLA biter (uygulama
    #    acilir), atlama SESSIZ OLMAZ.
    if ihlal:
        logger.warning(
            "%s: `%s` tablosunda %d adet DENGESIZ deftere-giren fis var "
            "(status IN ('posted','reversed') AND total_debit <> total_credit). "
            "`%s` kisiti `NOT VALID` olarak EKLENDI ve bundan sonraki her "
            "INSERT/UPDATE'i TAM enforce eder; migration BASARIYLA bitti, "
            "uygulama ACILIR. Ancak `VALIDATE` ATLANDI: kisit gecmis satirlar "
            "icin dogrulanmamis (`convalidated = f`) kalir. Bu %d satir "
            "duzeltildikten SONRA elle `ALTER TABLE %s VALIDATE CONSTRAINT %s;` "
            "kosulmalidir. 🔴 BU MIGRATION BU VERITABANINDA BIR DAHA KOSMAZ "
            "(alembic revizyonu bir kez kosar) -> dogrulama kendiliginden "
            "YAPILMAYACAKTIR. Satirlarin kimligi/tutari/tarihi BILEREK "
            "yazilmadi: deploy gunlugu mali veri sizdirmaz.",
            SKIP_VALIDATE_LOG_PREFIX,
            TABLE,
            ihlal,
            NEW_NAME,
            ihlal,
            TABLE,
            NEW_NAME,
        )
        return

    # 5. Ihlal 0: sayim kumesi CHECK'in red kumesiyle BIREBIR ayni oldugundan
    #    `VALIDATE` matematiksel olarak patlayamaz -> kisit TAM dogrulanmis
    #    biter, duz `ADD CONSTRAINT` ile ayni guvence saglanir.
    logger.info(
        "%s: `%s` tablosunda dengesiz deftere-giren fis sayisi %d "
        "(status IN ('posted','reversed') AND total_debit <> total_credit). "
        "`%s` kisiti `NOT VALID` eklendi ve AYNI islemde `VALIDATE` ediliyor -> "
        "tam dogrulanmis (`convalidated = t`) bitecek. Sayim `ADD CONSTRAINT`in "
        "ACCESS EXCLUSIVE kilidi altinda kosuldu, araya yeni satir giremez.",
        VALIDATE_LOG_PREFIX,
        TABLE,
        ihlal,
        NEW_NAME,
    )
    op.execute(sa.text(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {NEW_NAME}"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(NEW_NAME, TABLE, type_="check")
    op.create_check_constraint(OLD_NAME, TABLE, sa.text(OLD_SQL))
