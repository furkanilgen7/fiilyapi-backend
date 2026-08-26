"""mu3b canli fis kismi tekilligi

MU-3B IS 1 — 🔴 **TEKILLIK "IPTAL EDILMEMIS FISLER ARASINDA"** (kullanici karari
2026-08-26).

MU-3A (`a2d6b11efdcf`) `uq_journal_entries_source`u `(source_type, source_id)`
uzerinde TAM tekillik olarak kurdu. Olculen sonucu su: bir belge fislenip
STORNOLANIRSA orijinal fis `reversed` durumda AYAKTA KALIR ve kaynak damgasini
HALA tasir → belge BIR DAHA HIC fislenemez. Mali iz netlenmistir
(`posted` + `reversed` = 0, `balance.POSTING_STATUSES`), yani belge FIILEN
FISSIZDIR; ama sistem onu fisli sayar. Bir kez stornolanan fatura muhasebede bir
daha hic gorunmez, mizan KALICI olarak eksik kalir ve bunu kullaniciya soyleyen
HICBIR mekanizma yoktur — **sessiz kayip**.

Bu migration TEK SEY yapar: kisiti KISMI bir unique INDEKSE donusturur.

    WHERE status <> 'reversed'

`reversed`in secimi KODDAN gelir, varsayim degil: `accounting/transitions.py`
matrisinde o durum TERMINALDIR (hicbir ciftte kaynak degildir) ve bir fisi mali
olarak SILEN tek durum odur. `draft` iptal DEGIL YARIM'dir (ustelik otomatik
fiste hic dogmaz, KARAR-3), `posted` CANLIdir. Sabit `models.LIVE_SOURCE_WHERE`
ile AYNI metindir; asagida DONMUS KOPYA olarak durur (K1 kanonu — uygulanmis
migration donmus olmalidir, uygulama kodu zamanla degisir).

## 🔴 `UniqueConstraint` DEGIL `CREATE UNIQUE INDEX`

PG'de bir UNIQUE KISITI kismi olamaz — `WHERE` kabul etmez. Kismilik yalniz
unique INDEKSTE mumkundur. Ad KORUNUR (`uq_journal_entries_source`): ihlal
metni, testler ve dokumanlar ayni adi gosterir ve `duplicate key value violates
unique constraint "uq_journal_entries_source"` cumlesi INDEKS icin de aynen
uretilir.

## 🔴 IHLAL SAYMA DANSI NEDEN YOK — ve bu OLCULMUSTUR

Depo kanonu, mevcut veri tasiyan bir tabloya kisit DARALTIRKEN "ACCESS EXCLUSIVE
altinda SAY → 0 ise EKLE → ihlalde WARNING dus, basariyla bit" der. 🔴 Buradaki
degisim bir DARALTMA DEGIL, bir GEVSETMEDIR: yeni indeksin kapsadigi satir
kumesi (`status <> 'reversed'`) eski kisitin kapsadigi kumenin ALT KUMESIDIR.
Eski kisiti saglayan her veri yeni indeksi de saglar; ihlal sayisi YAPISAL
OLARAK SIFIRDIR ve bir `SELECT count(*)`in soracagi soru yoktur.

`CREATE UNIQUE INDEX CONCURRENTLY` de kullanilamaz (transaction icinde kosmaz,
alembic ile catisir) ve GEREKMEZ: kisit dusurulurken tablo zaten ACCESS
EXCLUSIVE ile kilitlenir, indeks AYNI kilidin altinda dogar.

🔴 `NOT VALID` yalniz `CHECK`/`FK` icindir; ne UNIQUE kisiti ne de INDEKS onu
kabul eder.

## DOWNGRADE

Indeks dusurulur ve TAM tekillik geri kurulur. 🔴 Bu bir DARALTMADIR ve
patlayabilir: kismi tekillik altinda ayni belgeye birden fazla fis (bir olu +
bir canli) yazilmis olabilir ve `ADD CONSTRAINT` ham bir hata verir. Downgrade
bu yuzden ONCE SAYAR; ihlal varsa **RuntimeError ile DURUR ve semayi BOZMADAN
birakir** (yarim downgrade daha kotudur — `e5f6a7b8c9d0` K7 deseni).

⚠️ Bu dosyanin `upgrade`inde `raise` YOKTUR: `Dockerfile` acilista
`alembic upgrade head && uvicorn …` kosar ve burada patlayan bir satir `&&`yi
kisa devre yaptirip uvicorn'u HIC BASLATMAZ (tam kesinti). Downgrade elle
kosulur, acilis yolunda degildir — orada `raise` DOGRUDUR.

Elle yazilmistir (autogenerate DEGIL) — repo deseni.

Revision ID: b9c0d1e2f3a4
Revises: a2d6b11efdcf
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "a2d6b11efdcf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTRY_TABLE = "journal_entries"
INDEX_NAME = "uq_journal_entries_source"

#: 🔴 DONMUS KOPYA — `app.modules.accounting.models.LIVE_SOURCE_WHERE` ile
#: birebir ayni metin. Uygulama kodu IMPORT EDILMEZ (K1): uygulanmis bir
#: migration donmus olmalidir. Iki katmanin ayni oldugunu T-testi iddia eder.
LIVE_WHERE = "status <> 'reversed'"


def upgrade() -> None:
    # Kisit dusurulurken tablo ACCESS EXCLUSIVE ile kilitlenir; indeks AYNI
    # kilidin altinda dogar (ikinci bir kilit turu yok).
    op.drop_constraint(INDEX_NAME, ENTRY_TABLE, type_="unique")
    op.create_index(
        INDEX_NAME,
        ENTRY_TABLE,
        ["source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text(LIVE_WHERE),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 🔴 VERI KAPISI — TAM tekillige donmek bir DARALTMADIR. Kismi tekillik
    #    altinda yazilmis (olu + canli) ciftler `ADD CONSTRAINT`i ham bir hatayla
    #    patlatir ve migration YARIM kalirdi.
    cakisanlar = bind.execute(
        sa.text(
            "SELECT source_type::text, source_id, count(*) AS adet "
            "FROM journal_entries "
            "WHERE source_type IS NOT NULL "
            "GROUP BY source_type, source_id HAVING count(*) > 1"
        )
    ).all()
    if cakisanlar:
        raise RuntimeError(
            "downgrade DURDURULDU: kismi tekillik altinda ayni belgeye birden "
            "fazla fis yazilmis; TAM tekillik geri kurulamaz. Cakisan belgeler: "
            + ", ".join(f"{tur}/{belge} ({adet} fis)" for tur, belge, adet in cakisanlar)
        )

    op.drop_index(INDEX_NAME, table_name=ENTRY_TABLE)
    op.create_unique_constraint(INDEX_NAME, ENTRY_TABLE, ["source_type", "source_id"])
