"""mu3d kaynak fatura tekilligi

MU-3D IS 3 — bir KAYNAK BELGEYE (hakedis / kira hakedisi / siparis) en fazla
BIR ASIL FATURA baglanabilir.

## OLCULMUS ACIK

MU-3D oncesi `invoices` tablosundaki TEK tekillik `uq_invoices_no_direction`
(yon + fatura no) idi. `ck_invoices_single_source` YALNIZCA "bir faturada en
fazla BIR kaynak kolonu dolu olsun" der — "bir kaynaga en fazla BIR fatura
baglansin" DEMEZ. Servis katmaninda da bir sayim yoktur
(`service._assert_references` yalniz VARLIK ve PROJE KAPSAMI bakar), ustelik
kaynak FK'leri PATCH ile de yazilabilir. Sonuc: ayni `progress_payment_id`
sinirsiz sayida faturaya yazilabiliyordu.

Bedeli bir CIFT SAYIMDIR ve IKI yuzeyde birden gorunur:
  * `vat_return` ayni hakedisin KDV'sini IKI KEZ beyan eder (beyanname yalniz
    `invoices`tan turer ve kaynak FK'sini HIC gormez);
  * MU-3D'nin storno kurali ikinci faturada calisacak bir fis BULAMAZ (hakedis
    fisi zaten ilk faturada stornolanmistir) ve ikinci fatura gideri/hasilati
    IKINCI KEZ deftere yazar.

## 🔴 "IPTAL EDILMIS FATURA" BU URUNDE BIR DURUM DEGILDIR (OLCULDU)

`InvoiceStatus`in alti uyesinin hicbiri iptal anlamina gelmez; sinifin kendi
docstring'i "Iptal/iade gecisi ... YOKTUR" der ve `transitions.py`de
`collected`/`approved`/`disputed` TERMINALDIR. Silme YALNIZ `draft` icindir.
Bir faturayi geri alan tek belge AYRI bir faturadir: `document_type='refund'`
(Iade Faturasi). Suzgec bu yuzden DURUMA degil BELGE TIPINE bakar — bir
hakedise kesilmis faturanin iadesi MESRUDUR ve ayni kaynaga baglanabilmelidir.

Metin `app.modules.invoicing.models.BINDING_SOURCE_WHERE` ile BIREBIR AYNIDIR;
uygulama kodu IMPORT EDILMEZ (K1: uygulanmis bir migration DONMUS olmalidir).
Iki katmanin ayni oldugunu `tests/modules/invoicing/test_mu3d_kaynak_tekilligi.py`
iddia eder.

## 🔴 BU BIR DARALTMADIR → SAY, SONRA EKLE

Depo kanonu (`d9e0f1a2b3c4` SAKILIT emsali): mevcut veri tasiyan bir tabloya
tekillik eklerken

  1. `LOCK TABLE invoices IN ACCESS EXCLUSIVE MODE` — indeksin zaten alacagi
     kilit BIRAZ ONCE alinir, boylece sayim ile ekleme arasina baska bir islem
     cift satir SOKAMAZ (yarissiz karar);
  2. sayim kilidin ALTINDA kosar;
  3. ihlal varsa indeks EKLENMEZ, WARNING duser, migration BASARIYLA biter.

🔴 `raise` YOKTUR: `Dockerfile` `alembic upgrade head && uvicorn ...` kosar ve
burada patlayan bir satir `&&`yi kisa devre yaptirip uvicorn'u HIC BASLATMAZ
(tam kesinti). Downgrade elle kosulur, acilis yolunda degildir.

🔴 `CREATE UNIQUE INDEX CONCURRENTLY` KULLANILAMAZ: transaction icinde kosmaz,
alembic ise `transaction_per_migration=True` ile her migration'i bir islemde
kosar. `NOT VALID` de yoktur — o kip YALNIZCA `CHECK` ve `FOREIGN KEY` icindir.

🔴 DORT KOLON AYRI AYRI KARARA BAGLANIR: biri kirli diye otekiler de bekcisiz
kalsaydi, temiz uc kolonun acigi bir dorduncunun gecmis verisi yuzunden acik
kalirdi.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: d2e3f4a5b6c7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-26

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

TABLE = "invoices"

#: 🔴 DONMUS KOPYA — `models.BINDING_SOURCE_WHERE` ile birebir ayni metin.
WHERE_SQL = "document_type <> 'refund'"

#: 🔴 DONMUS KOPYA — `models.SOURCE_UNIQUE_INDEXES` ile birebir ayni sira/icerik.
SOURCE_INDEXES: tuple[tuple[str, str], ...] = (
    ("progress_payment_id", "uq_invoices_progress_payment"),
    ("subcontractor_progress_payment_id", "uq_invoices_subcontractor_progress_payment"),
    ("equipment_rental_invoice_id", "uq_invoices_equipment_rental_invoice"),
    ("purchase_order_id", "uq_invoices_purchase_order"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Indeksin zaten alacagi kilit BIRAZ ONCE alinir (yarissiz karar).
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))

    for kolon, indeks in SOURCE_INDEXES:
        # 2. Olcum kilidin ALTINDA kosar. `NULL`lar GROUP BY'da tek bir kumeye
        #    duser, bu yuzden `IS NOT NULL` SART: kaynaga baglanmamis yuzlerce
        #    fatura yoksa da "cift" sayilirdi.
        cift = bind.execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT {kolon} FROM {TABLE} "
                f"WHERE {kolon} IS NOT NULL AND {WHERE_SQL} "
                f"GROUP BY {kolon} HAVING count(*) > 1) AS c"
            )
        ).scalar_one()

        # 3. Ihlal varsa indeks EKLENMEZ, migration BASARIYLA biter, atlama
        #    SESSIZ OLMAZ.
        if cift:
            logger.warning(
                "MU-3D: `%s.%s` uzerinde %d adet kaynak BIRDEN COK asil faturaya "
                "baglanmis. `%s` tekillik indeksi bu yuzden EKLENMEDI: eklenseydi "
                "`CREATE UNIQUE INDEX` mevcut satirlari tarayip PATLAR ve "
                "`alembic upgrade head && uvicorn` zinciri kirilarak uygulama HIC "
                "ACILMAZDI. 🔴 BU KOLONDA CIFT SAYIM ACIGI ACIK KALMISTIR: ayni "
                "kaynaga ikinci bir fatura hala baglanabilir, `vat_return` o KDV'yi "
                "iki kez beyan eder ve MU-3D'nin hakedis stornosu ikinci faturada "
                "calisacak bir fis bulamaz. Cakisan kayitlar ayiklandiktan SONRA elle "
                "`CREATE UNIQUE INDEX %s ON %s (%s) WHERE %s;` kosulmalidir — bu "
                "migration bu veritabaninda BIR DAHA KOSMAZ. Kayitlarin kimligi/"
                "tutari/taraf adi BILEREK yazilmadi: deploy gunlugu ticari veri "
                "sizdirmaz.",
                TABLE,
                kolon,
                cift,
                indeks,
                indeks,
                TABLE,
                kolon,
                WHERE_SQL,
            )
            continue

        # 4. Sayim 0: tarayacagi kume ACCESS EXCLUSIVE kilidi altinda sabit ve
        #    temiz oldugundan `CREATE UNIQUE INDEX` patlayamaz.
        logger.info(
            "MU-3D: `%s.%s` temiz (cift baglanmis kaynak yok). `%s` tekillik "
            "indeksi ekleniyor. Sayim `ACCESS EXCLUSIVE` kilidi altinda kosuldu, "
            "araya cift satir giremez. NOT: PG'de NULL'lar ayriktir -> kaynaga "
            "BAGLANMAMIS faturalar indeksten ETKILENMEZ; iade faturalari "
            "(`%s`) da kapsam DISINDADIR.",
            TABLE,
            kolon,
            indeks,
            WHERE_SQL,
        )
        op.create_index(indeks, TABLE, [kolon], unique=True, postgresql_where=sa.text(WHERE_SQL))


def downgrade() -> None:
    # Genisleme yonu — veri kapisi GEREKMEZ. `IF EXISTS`: upgrade bir kolonu
    # kirli veri yuzunden ATLAMIS olabilir ve o indeks HIC DOGMAMISTIR;
    # ciplak `DROP INDEX` o veritabaninda downgrade'i patlatirdi.
    for _kolon, indeks in reversed(SOURCE_INDEXES):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {indeks}"))
