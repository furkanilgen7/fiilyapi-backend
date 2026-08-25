"""suptckn tedarikci tax_no 10 -> 11 hane (sahis sirketi TCKN'si)

SUP-TCKN — kullanici karari 2026-08-25: **sahis tedarikcisi kaydedilebilmeli.**

--------------------------------------------------------------------------
NICIN BU MIGRATION VAR — OLCULMUS ASIMETRI
--------------------------------------------------------------------------
`suppliers.tax_no` `varchar(10)`di. Gerekcesi kolonun kendi yorumundaydi:
"TR vergi kimlik numarasi 10 hanedir". Dogru ama EKSIK — SAHIS SIRKETI vergi
kimligi olarak 11 haneli TCKN kullanir. Sonuc: 11 hane gonderen istemci
`max_length=10` yuzunden **422** aliyordu ve sahis tedarikcisi sisteme HIC
girilemiyordu.

Depo genelinde olculdu (`grep -E "(tax_no|tax_number|national_id)\s*:\s*Mapped"`):
kimlik tasiyan YEDI kolonun ALTISI zaten >= 11 idi
(`customers.national_id` 11 · `customers.tax_number` 11 ·
`employers.tax_number` 11 · `subcontractors.tax_number` 11 ·
`invoices.party_tax_number` 11 · `company.tax_number` 50);
`suppliers.tax_no` 10 ile **TEK ISTISNAYDI**.

--------------------------------------------------------------------------
NICIN TEK KOLON GENISLETILDI, IKINCI BIR KIMLIK ALANI ACILMADI
--------------------------------------------------------------------------
`customers` iki AYRI kolon tasir (`national_id` + `tax_number`) ama bunu
YAPABILMESININ sebebi `customer_type` ENUM AYIRT EDICISI ve
`guards.validate_customer_identity`in "tam biri dolu" korkulugudur: tip
`person` ise TCKN ZORUNLU, VKN YASAK; `company` ise tersi.

Tedarikcide o ayirt edici YOKTUR ve `tax_no` ZORUNLU BILE DEGILDIR
(SA spec §2/T1 karari, mockup **TED** 48). Musteri desenini birebir tasimak
`supplier_type` enum'u ICAT ETMEYI ve kimligi ZORUNLU KILMAYI gerektirirdi —
ikisi de kayitli urun kararlarinin TERSIDIR.

Ayirt edicisi OLMAYAN durumun depoda ZATEN bir emsali var:
`invoices.party_tax_number` `varchar(11)` ve kolonun kendi yorumu
"TCKN 11 / VKN 10 — `customers.national_id`/`tax_number` emsali" diyor. Yani
musteri emsali, tip ayirt edicisi bulunmayan bir baglama daha once de **TEK
11'lik kolon** olarak indirilmis. SUP-TCKN ayni cevabi verir.

--------------------------------------------------------------------------
BICIM KURALI EKLENMEDI (BILEREK)
--------------------------------------------------------------------------
"Yalniz rakam / tam 10 ya da 11 hane" turunde bir regex KONMADI. Iki dayanak:
(a) `customers/guards.py` acikca yaziyor — "Bicim dogrulamasi BILINCLI OLARAK
yok ... gerekirse TUM VKN alanlariyla BIRLIKTE ve ayri bir kararla eklenir";
(b) `SupplierCreate`in kendi gerekcesi — "dis ulke tedarikcisi ya da sahis
firmasi kaliba oturmayabilir". Depoda regex tasiyan TEK alan
`EmployerCreate.tax_number` (`^\d{10,11}$`) ve o bir azinliktir. Yeni bir
sertlik BU dilimde ICAT EDILMEZ; ayrica MEVCUT satirlari da reddederdi.

--------------------------------------------------------------------------
KILIT / YENIDEN YAZMA
--------------------------------------------------------------------------
`varchar(n)` GENISLETMEK PostgreSQL'de tabloyu YENIDEN YAZMAZ (PG >= 9.2,
`ALTER TABLE ... ALTER COLUMN ... TYPE varchar(daha_buyuk)` yalnizca katalog
guncellemesidir). Kilit yine de `ACCESS EXCLUSIVE`dir ama SURESI sabittir ve
tablo boyutundan bagimsizdir — `suppliers` zaten kucuk bir katalog tablosudur.

`NOT VALID` BURADA GUNDEM DISI: o kip yalnizca `CHECK`/`FK` icindir, bir
`ALTER COLUMN TYPE` kabul etmez.

--------------------------------------------------------------------------
🔴 DOWNGRADE DARALTMA YAPMAZ, BAGIRIR
--------------------------------------------------------------------------
`varchar(11)` -> `varchar(10)` daraltmasi 11 haneli bir TCKN tasiyan satir
varsa `StringDataRightTruncation` ile PATLAR. `USING left(tax_no, 10)`
yazilsaydi patlamaz ama TCKN'leri SESSIZCE BUDARDI — geri alinamaz VERI
KAYBI. Bu yuzden downgrade ONCE sayar: ihlal varsa daraltmayi ATLAR, WARNING
duser ve BASARIYLA biter. Kolon 11'de kalir (veri korunur), sema tam olarak
geri sarmaz ve bu BILINCLI bir tercihtir: bir korkuluk korudugu seyden buyuk
hasar uretemez. Bos veritabaninda (CI `alembic-cycle`) sayim 0'dir ve
daraltma normal kosar.

--------------------------------------------------------------------------
CANLI OLCUM — DEPLOY GUNLUGUNDEN OKUNUR
--------------------------------------------------------------------------
Canli DB'ye elle sorgu KOSULMAZ (WORKFLOW §4). Sorunun canlida ne kadar
isirdigi migration'in KENDISINDE olculur ve Railway deploy gunlugune duser:
kac tedarikci var, kaci `tax_no` dolu, kaci TAM 10 hane. Greplenebilir imza:
`SUP-TCKN OLCUM`. Ticari veri (ad/VKN) BILEREK yazilmaz, yalniz SAYILAR.

Yeni Postgres enum tipi YOKTUR — `DROP TYPE` gundem disidir.
Yeni izin modulu ACILMAZ: `procurement` seed'de ZATEN vardir.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: a5b6c7d8e9f0
Revises: d9e0f1a2b3c4
Create Date: 2026-08-25

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

#: `d9e0f1a2b3c4`/TB6 ile AYNI logger: `alembic.ini` kok logger'i
#: WARNING/stderr, `alembic` logger'i INFO -> iki satir da Railway deploy
#: gunlugunde gorunur.
logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: str | Sequence[str] | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "suppliers"
COLUMN = "tax_no"
ESKI_UZUNLUK = 10
YENI_UZUNLUK = 11

#: Canli olcum: uc sayi tek turda. `length()` NULL'da NULL doner, bu yuzden
#: `count(*) FILTER` kullanildi — `sum(case...)` bos tabloda NULL verirdi.
OLCUM_SQL = sa.text(
    "SELECT count(*) AS toplam,"
    f" count({COLUMN}) AS dolu,"
    f" count(*) FILTER (WHERE length({COLUMN}) = {ESKI_UZUNLUK}) AS tam_on"
    f" FROM {TABLE}"
)

#: Downgrade'in daraltma oncesi sayimi — daraltmanin patlatacagi kumeyle BIREBIR.
TASAN_SQL = sa.text(f"SELECT count(*) FROM {TABLE} WHERE length({COLUMN}) > {ESKI_UZUNLUK}")

#: Deploy gunlugunde GOZLE aranan greplenebilir imzalar.
OLCUM_LOG_PREFIX = "SUP-TCKN OLCUM"
DOWN_SKIP_LOG_PREFIX = "SUP-TCKN DOWNGRADE: DARALTILMADI"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    toplam, dolu, tam_on = bind.execute(OLCUM_SQL).one()
    logger.info(
        "%s: `%s` tablosunda %d tedarikci var, %d tanesinin `%s` alani dolu, "
        "%d tanesi TAM %d hane. Kolon `varchar(%d)` -> `varchar(%d)` "
        "genisletiliyor: sahis sirketi vergi kimligi olarak 11 haneli TCKN "
        "kullanir ve onceki sinir onu 422 ile reddediyordu. Genisletme tabloyu "
        "YENIDEN YAZMAZ (PG >= 9.2) ve MEVCUT hicbir satiri etkilemez — 10 "
        "haneli VKN'ler aynen gecerlidir. Ticari veri BILEREK yazilmadi.",
        OLCUM_LOG_PREFIX,
        TABLE,
        toplam,
        dolu,
        COLUMN,
        tam_on,
        ESKI_UZUNLUK,
        ESKI_UZUNLUK,
        YENI_UZUNLUK,
    )

    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.String(length=ESKI_UZUNLUK),
        type_=sa.String(length=YENI_UZUNLUK),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 VERI KAYBI KAPISI: 11 haneli TCKN tasiyan satir varsa daraltma ATLANIR.
    """
    bind = op.get_bind()

    # Daraltmanin alacagi kilit BIRAZ ONCE alinir: sayim ile `ALTER` arasina
    # baska bir islem 11 haneli satir SOKAMAZ (yarissiz karar).
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))

    tasan = bind.execute(TASAN_SQL).scalar_one()

    if tasan:
        logger.warning(
            "%s: `%s.%s` alaninda %d satir %d haneden UZUN (sahis "
            "tedarikcisinin TCKN'si). `varchar(%d)` daraltmasi bu satirlarda "
            "`StringDataRightTruncation` ile PATLAR; `USING left(%s, %d)` ise "
            "TCKN'leri SESSIZCE BUDAR (geri alinamaz VERI KAYBI). Ikisi de "
            "yapilmadi: kolon `varchar(%d)` olarak BIRAKILDI ve migration "
            "BASARIYLA bitti. Sema tam geri sarmadi — bilincli tercih. "
            "Gercekten daraltilacaksa once o %d satirin `%s` degeri elle "
            "ayiklanmali, SONRA "
            "`ALTER TABLE %s ALTER COLUMN %s TYPE varchar(%d);` kosulmalidir. "
            "Ticari veri BILEREK yazilmadi.",
            DOWN_SKIP_LOG_PREFIX,
            TABLE,
            COLUMN,
            tasan,
            ESKI_UZUNLUK,
            ESKI_UZUNLUK,
            COLUMN,
            ESKI_UZUNLUK,
            YENI_UZUNLUK,
            tasan,
            COLUMN,
            TABLE,
            COLUMN,
            ESKI_UZUNLUK,
        )
        return

    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.String(length=YENI_UZUNLUK),
        type_=sa.String(length=ESKI_UZUNLUK),
        existing_nullable=True,
    )
