"""sakilit purchase_orders.request_id UNIQUE (kilit altinda sayim + kosullu ekleme)

SA-KILIT T4 — bir talep EN COK BIR siparise donusur ve bu artik **DB'de**
zorlanir. Uygulama kilidi (`service.visible_request_locked`, `router.py`
`select_and_order_endpoint`) asil savunmadir; bu kisit onun YEDEGIDIR.

--------------------------------------------------------------------------
🔴 URUN SORUSU ONCE OLCULDU: TALEP BOLUNEBILIYOR MU? -> HAYIR
--------------------------------------------------------------------------
UNIQUE, mesru bir akisi kirsaydi YANLIS olurdu. Kirmadigi tahmin edilmedi,
koddan olculdu (gerekcenin tamami `models.PurchaseOrder` docstring'indedir):

* `request_id`i NULL-DISI yazan TEK yer `service.orders.select_and_order`;
* `PurchaseOrderCreate`te `request_id` YOKTUR (govdede gelse yok sayilir),
  `PurchaseOrderUpdate`te de YOKTUR -> bag sonradan kurulamaz/degistirilemez;
* `REQUEST_TRANSITIONS`ta `ordered` hicbir ciftte KAYNAK degildir -> ayni
  talep ikinci kez `select-and-order` edilemez;
* sipariste IPTAL durumu YOKTUR (`approved/in_transit/delivered`) ve
  `DELETE /purchase-orders/{id}` de yoktur (405, bekci testli) -> "iptal edip
  yeniden siparis" akisi YOKTUR.

Kismi kisit (`WHERE ...`) GEREKMEDI: bugun ayirt edilecek bir "iptal" ya da
"bolunmus" hali YOK. Postgres UNIQUE zaten coklu NULL'a IZIN VERIR, dolayisiyla
TALEPSIZ (SIP 35) siparisler sinirsiz kalir — olculdu ve bekcilendi.

--------------------------------------------------------------------------
🔴 EMIRDEN SAPMA — `NOT VALID` BU KISIT TURUNDE **MUMKUN DEGIL** (olculdu)
--------------------------------------------------------------------------
Gorev emri TB6 desenini isaret ediyordu: "kisiti `NOT VALID` kipiyle indir,
ihlal 0 ise AYNI migration'da `VALIDATE` et". Bu desen UNIQUE'e UYGULANAMAZ;
PostgreSQL 16.15 uzerinde dogrudan olculdu:

    ALTER TABLE t ADD CONSTRAINT ... UNIQUE (request_id) NOT VALID;
    -> ERROR:  UNIQUE constraints cannot be marked NOT VALID

    ALTER TABLE t ADD CONSTRAINT ... EXCLUDE USING btree (...) NOT VALID;
    -> ERROR:  EXCLUDE constraints cannot be marked NOT VALID

`NOT VALID` YALNIZCA `CHECK` ve `FOREIGN KEY` icindir. `CREATE UNIQUE INDEX
CONCURRENTLY` de cikis degil: "cannot run inside a transaction block" (olculdu)
ve alembic migration'i islem icinde kosar.

Yani UNIQUE, TB6'nin kacindigi seyi yapmak ZORUNDADIR: mevcut satirlari TARAR
ve ihlal varsa `ALTER TABLE` **PATLAR**.

--------------------------------------------------------------------------
🔴 O HALDE TB6'NIN ASIL KANONU KORUNUR: **`raise` YOK, KESINTI YOK**
--------------------------------------------------------------------------
`Dockerfile` acilista `alembic upgrade head && uvicorn ...` kosar. `&&` kisa
devre yapar: migration'in COKMESI = uvicorn HIC BASLAMAZ = **TAM KESINTI**.
TB6 bu yuzden `raise`i kaldirmisti; burada tehlike daha da buyuktur cunku
patlamayi biz secmesek de `ADD CONSTRAINT`in kendisi patlatabilir.

Cozum: **once say, sonra kosullu ekle** — ve arada yaris olmasin diye sayim
`ALTER TABLE`in alacagi kilidin ALTINDA kosar:

1. `LOCK TABLE purchase_orders IN ACCESS EXCLUSIVE MODE` — `ADD CONSTRAINT`in
   zaten alacagi kilit, yalnizca BIRAZ ONCE alinir. Ek maliyet YOK.
2. Sayim bu kilidin altinda kosar -> arada yeni bir cift satir commit
   EDILEMEZ. TB6'nin "sayim ADD CONSTRAINT'ten SONRA" gerekcesinin bu kisit
   turundeki karsiligi budur: orada kilidi kisit aliyordu, burada ELLE aliriz
   cunku kisiti eklemeden ONCE karar vermek zorundayiz.
3. Sayim 0 ise `ADD CONSTRAINT` **matematiksel olarak patlayamaz** (tarayacagi
   kume kilit altinda sabittir ve bostur) -> kisit TAM dogrulanmis girer.
4. Sayim > 0 ise kisit EKLENMEZ, WARNING dusulur, migration **BASARIYLA**
   biter ve uygulama ACILIR. `raise` YOKTUR.

--------------------------------------------------------------------------
🔴 CANLI VERI OLCULEMIYOR -> OLCUM MIGRATION'IN ICINE YAZILDI
--------------------------------------------------------------------------
Canli veritabanina erisim YETKI DISIDIR (kalici kural). Olculemeyen bir olguya
karar baglanamayacagi icin olcum KOSAN YERE tasindi: sayim burada kosar ve
sonucu Railway deploy gunlugune duser (`alembic.ini` kok logger'i WARNING/
stderr, `alembic` logger'i INFO -> iki satir da gorunur). Desen TB6'nindir.

🔴 LOG SATIRINA YALNIZ SAYI YAZILIR: talep/siparis kimligi, tutar ve tedarikci
ASLA yazilmaz — deploy gunlugu ticari veri sizdirmaz.

Ihlal cikarsa yapilacak is de log satirindadir: cift siparisler ayiklanip
`ALTER TABLE purchase_orders ADD CONSTRAINT uq_purchase_orders_request_id
UNIQUE (request_id);` ELLE kosulmalidir — bu migration bir daha KOSMAZ.

--------------------------------------------------------------------------
`ix_purchase_orders_request_id` NEDEN DURUYOR
--------------------------------------------------------------------------
UNIQUE kendi indeksini yaratir ve kolon uzerindeki duz indeks teknik olarak
gereksizlesir. Yine de DUSURULMEDI: bu dilim bir PARA KUSURU onarimidir,
indeks temizligi ayri bir karardir ve kisit eklenemezse (ihlal > 0) duz indeksi
dusurmus olmak performansi sebepsiz bozardi.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d9e0f1a2b3c4
Revises: a2b3c4d5e6f7
Create Date: 2026-08-23

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

#: TB6 ile AYNI logger: `alembic.ini` kok logger'i WARNING/stderr, `alembic`
#: logger'i INFO -> hem INFO hem WARNING Railway deploy gunlugunde gorunur.
logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "purchase_orders"
CONSTRAINT = "uq_purchase_orders_request_id"

#: Kisitin reddedecegi kume ile BIREBIR ayni kumeyi sayar: NULL'lar `GROUP BY`
#: disinda kalmaz ama `count(*) > 1` yalnizca NULL-DISI tekrarlar icin anlamli
#: olsun diye `request_id IS NOT NULL` suzgeci vardir — Postgres UNIQUE coklu
#: NULL'a izin verdigi icin NULL tekrarlari IHLAL DEGILDIR (olculdu).
#: Bu esitlik, "sayim 0 => ADD CONSTRAINT patlayamaz" garantisinin TEK
#: dayanagidir; degistirilirse garanti duser.
COUNT_SQL = sa.text(
    "SELECT count(*) FROM ("
    "  SELECT request_id FROM purchase_orders"
    "   WHERE request_id IS NOT NULL"
    "   GROUP BY request_id HAVING count(*) > 1"
    ") AS cift"
)

#: Deploy gunlugunde GOZLE aranan greplenebilir imzalar.
ADD_LOG_PREFIX = "SA-KILIT UNIQUE: EKLENIYOR"
SKIP_LOG_PREFIX = "SA-KILIT UNIQUE: EKLENMEDI"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 1. `ADD CONSTRAINT`in zaten alacagi kilit, BIRAZ ONCE alinir: sayim ile
    #    ekleme arasina baska bir islem cift satir SOKAMAZ (yarissiz karar).
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))

    # 2. Olcum kilidin ALTINDA kosar.
    cift = bind.execute(COUNT_SQL).scalar_one()

    # 3. Ihlal varsa: kisit EKLENMEZ, migration BASARIYLA biter (uygulama
    #    ACILIR — `Dockerfile`daki `&&` yuzunden `raise` TAM KESINTI olurdu),
    #    atlama SESSIZ OLMAZ.
    if cift:
        logger.warning(
            "%s: `%s` tablosunda %d adet talep BIRDEN COK siparise baglanmis "
            "(request_id NOT NULL, GROUP BY request_id HAVING count(*) > 1). "
            "`%s` kisiti bu yuzden EKLENMEDI: UNIQUE `NOT VALID` kipini "
            "DESTEKLEMEZ (olculdu), dolayisiyla eklenseydi `ALTER TABLE` mevcut "
            "satirlari tarayip PATLAR ve `alembic upgrade head && uvicorn` "
            "zinciri kirilarak uygulama HIC ACILMAZDI. Migration BASARIYLA "
            "bitti. 🔴 UYGULAMA KATMANI KORUNUYOR: `select-and-order` ucu artik "
            "`visible_request_locked` ile aciliyor, yeni cift siparis "
            "URETILEMEZ; bu %d kayit GECMISTEN kalmadir. Ayiklandiktan SONRA "
            "elle `ALTER TABLE %s ADD CONSTRAINT %s UNIQUE (request_id);` "
            "kosulmalidir — bu migration bu veritabaninda BIR DAHA KOSMAZ. "
            "Kayitlarin kimligi/tutari/tedarikcisi BILEREK yazilmadi: deploy "
            "gunlugu ticari veri sizdirmaz.",
            SKIP_LOG_PREFIX,
            TABLE,
            cift,
            CONSTRAINT,
            cift,
            TABLE,
            CONSTRAINT,
        )
        return

    # 4. Sayim 0: tarayacagi kume ACCESS EXCLUSIVE kilidi altinda sabit ve bos
    #    oldugundan `ADD CONSTRAINT` patlayamaz -> kisit TAM dogrulanmis girer.
    logger.info(
        "%s: `%s` tablosunda birden cok siparise baglanmis talep sayisi %d. "
        "`%s` UNIQUE kisiti ekleniyor. Sayim `ACCESS EXCLUSIVE` kilidi altinda "
        "kosuldu, araya cift satir giremez. NOT: Postgres UNIQUE coklu NULL'a "
        "izin verir -> TALEPSIZ (dogrudan) siparisler kisittan ETKILENMEZ.",
        ADD_LOG_PREFIX,
        TABLE,
        cift,
        CONSTRAINT,
    )
    op.create_unique_constraint(CONSTRAINT, TABLE, ["request_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
