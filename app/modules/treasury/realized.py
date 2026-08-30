"""PARA-GERCEK — bir hakedişin arkasında GERÇEKTEN ne kadar para hareket etti.

Kullanıcının kuralı birebir şudur:

    "Nakit olarak görmeden veya çekin vadesi gelip de tahsil edilmeden
     'ödendi' gözükmemesi gerekiyor."

## Kural NEDEN burada ikinci kez YAZILMADI

"Para gerçekten hareket etti mi" sorusunun cevabı bu depoda ZATEN VARDIR ve
`treasury/balance.py:cash_realized_condition()`tir (ODM-1 D2). Bu modül o
yüklemi İTHAL EDER, KOPYALAMAZ:

    bağsız ödeme (`financial_instrument_id IS NULL`)      → nakit
    bağlı ödeme, evrak `collected|paid`                   → nakit
    bağlı ödeme, evrak `portfolio|returned|cancelled`     → nakit DEĞİL

🔴 İkinci bir tanım yazılsaydı, AYNI ödeme satırı için banka bakiyesi kartı
"bu para henüz hesapta değil" derken hakediş ekranı "ödendi" derdi — ikisi de
tek bir sayı bastığı için kusur hiçbir ekranda GÖRÜNMEZDİ (P5'in "iki farklı
doğruluk tanımı" bulgusu).

🔴 **YÖN AYRICA DENETLENMEZ ve bu bir eksiklik DEĞİLDİR.** `collected` (alınan
çek tahsil edildi) ile `paid` (verilen çek ödendi) tek bir beyaz listede
durabilir; çünkü yönün doğruluğu ÖDEMENİN YAZILDIĞI AN zaten kapıya takılır:
`payments_service._UYUMLU_YON` giden faturaya YALNIZ `received`, gelen faturaya
YALNIZ `issued` evrak bağlanmasına izin verir (FIN-PAY K3, **422**). Yani
"işveren hakedişinde hangi durum para demek" sorusunun cevabı yapısal olarak
tekildir ve burada ikinci bir yön tablosu açmak, bir gün öbüründen sapacak
üçüncü bir doğruluk tanımı olurdu.

## Toplam NEYİN üzerinden alınır

Zincir `hakediş ← fatura ← ödeme`dir (`payments`ten hakedişe FK YOKTUR;
`invoices.progress_payment_id` / `invoices.subcontractor_progress_payment_id`
vardır). Toplama YALNIZ **bağlayıcı** faturanın ödemelerini sayar, yani
`document_type <> 'refund'` olanı:

* `invoicing.models.SOURCE_UNIQUE_INDEXES` bir kaynağa **en fazla BİR** asıl
  fatura bağlanmasını kısmi UNIQUE indeksle garanti eder — yani bu süzgeçle
  toplam DAİMA tek bir faturanın ödemelerinden oluşur, belirsizlik yoktur;
* iade faturası (`refund`) MEŞRUDUR ve aynı kaynağa bağlanabilir, ama parası
  TERS yöne akar. Sayılsaydı bir iade tahsilatı, taşerona ödenmemiş bir borcu
  "ödenmiş" gösterebilirdi.

Süzgeç `invoicing.models.BINDING_SOURCE_WHERE` ile AYNI enum üyesinden
(`InvoiceDocumentType.refund`) türer; üye yeniden adlandırılırsa ikisi de aynı
anda kırılır, biri sessizce eskimez.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.core.errors import ConflictError
from app.modules.invoicing.models import Invoice, InvoiceDocumentType
from app.modules.treasury import balance, repository
from app.modules.treasury.models import Payment

__all__ = [
    "PAYMENT_NOT_REALIZED",
    "assert_realized_covers",
    "realized_total_for_source",
]

#: 🔴 409 — evrağın GÖVDESİ kusurlu değildir (422 olurdu); engel kaydın ARKASINDAKİ
#: para durumudur. Metin kullanıcıya iki yolu da söyler: ya ödeme kaydı hiç yok/eksik,
#: ya da çek portföyde bekliyor ve tahsil edilmesi gerekiyor.
PAYMENT_NOT_REALIZED = (
    "Hakediş ödendi işaretlenemez: faturasına kaydedilmiş ve nakde geçmiş ödeme "
    "tutarı hakediş netini karşılamıyor. Çek/senetle ödemede evrağın tahsil "
    "edildiği (ya da ödendiği) işaretlenmelidir."
)


async def realized_total_for_source(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
) -> Decimal:
    """Hakedişin bağlayıcı faturasına yazılmış, NAKDE GEÇMİŞ ödemelerin toplamı.

    `source_column` `Invoice.progress_payment_id` ya da
    `Invoice.subcontractor_progress_payment_id`tir — kolon ÇAĞIRANDAN gelir,
    böylece bu modül iki hakediş ailesinden HİÇBİRİNİ import etmez (import yönü
    tek taraflı kalır: `treasury` → `invoicing.models`, ki o bir YAPRAKTIR).

    `outerjoin` ŞART (`balance.join_instrument`): ödemelerin ezici çoğunluğu
    evraksızdır; INNER olsaydı hepsi düşer ve gerçekleşen toplam sessizce
    (neredeyse) SIFIR olurdu — yani kapı her hakedişi reddederdi.

    `coalesce` da ŞART ve `repository.paid_sum()`tan gelir: hiç ödemesi olmayan
    hakedişte `SUM()` NULL döner, 0 değil; ikinci bir `sum(amount)` yazılsaydı
    biri `coalesce`ı unuturdu.
    """
    stmt = balance.join_instrument(
        select(repository.paid_sum())
        .select_from(Payment)
        .join(Invoice, Invoice.id == Payment.invoice_id)
    ).where(
        source_column == source_id,
        # Bkz. modül docstring'i: yalnız BAĞLAYICI fatura sayılır, iade değil.
        Invoice.document_type != InvoiceDocumentType.refund,
        balance.cash_realized_condition(),
    )
    return (await session.execute(stmt)).scalar_one()


async def assert_realized_covers(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
    net: Decimal,
) -> None:
    """`mark-paid` kapısı: gerçekleşen para hakediş NETİNİ karşılamıyorsa **409**.

    🔴 **KAPI İLERİ YÖNDEDİR.** Geçişi ENGELLER; `paid`den çıkan bir ters geçiş
    AÇMAZ. `paid` bu depodaki DÖRT evrak ailesinde de TERMİNALDİR ve gerekçesi
    yazılıdır ("banka çıkışı olmuş bir kaydı geri sarmak, kayıt ile para
    hareketi arasındaki bağı koparırdı"). Ödeme sonradan silinirse/karşılıksız
    çıkarsa ne olacağı AYRI bir karardır ve bu dilimde çözülmemiştir.

    🔴 **KİLİT GEREKMEZ ve gerekçesi ölçülmüştür (İK-2 "EŞİK = KİLİT" kanonunun
    SINIRI).** O kanon, eşiğin TÜKETİLDİĞİ hâller içindir: iki eşzamanlı onay
    aynı kotayı okuyup ikisi de geçerse kota bir kez tüketilmiş sayılır ama iki
    kayıt girer. Burada tüketilen bir şey YOKTUR:

    * aynı hakediş üzerinde iki eşzamanlı `mark-paid` ZATEN serileşir —
      `visible_payment_locked` satırı `FOR UPDATE` + `populate_existing` ile
      kilitler ve ikinci istek durumu kilit ALTINDA yeniden okur, tabloda
      `(paid, mark_paid)` çifti olmadığı için **409** alır;
    * iki FARKLI hakediş aynı parayı sayamaz: `payments.invoice_id` NOT NULL'dır
      (bir ödeme tek faturanındır), `ck_invoices_single_source` bir faturada en
      fazla BİR kaynak kolonunun dolmasına izin verir ve `SOURCE_UNIQUE_INDEXES`
      bir kaynağa en fazla BİR asıl fatura bağlar. Yani bir ödeme satırı
      YAPISAL olarak tek bir hakedişe atfedilir — çift sayım için kilit değil,
      şema gerekir ve o şema zaten yerindedir.

    Karşılaştırma `<` iledir, yani TAM EŞİT tutar GEÇER: fazla ödeme zaten
    `PAYMENT_EXCEEDS_TOTAL` ile fatura tarafında engellidir, eksik ödeme ise
    kullanıcının kuralının reddettiği hâldir.
    """
    realized = await realized_total_for_source(session, source_column, source_id)
    if realized < net:
        raise ConflictError(PAYMENT_NOT_REALIZED)
