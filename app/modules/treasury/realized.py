"""PARA-GERCEK — bir hakedişin arkasında GERÇEKTEN ne kadar para hareket etti.

Kullanıcının kuralı birebir şudur:

    "Nakit olarak görmeden veya çekin vadesi gelip de tahsil edilmeden
     'ödendi' gözükmemesi gerekiyor."

## 🔴 EŞİK FATURANIN `total`İDİR — hakediş NETİ DEĞİL (denetim bulgusu 1)

İlk uygulama eşiği `calculations.net_amount`tan (hakediş neti) okuyordu ve bu
KULLANICIYI KİLİTLİYORDU. Sebep ölçüldü: iki formül YAPISAL olarak ayrışır,
çünkü KDV'nin MATRAHI farklıdır.

    hakediş neti : KDV **brüt** üzerinden  → net = brüt + KDV − avans − teminat
    fatura total : KDV **tax_base** üzerinden (avans/teminat DÜŞÜLDÜKTEN SONRA)
                   → total = tax_base + KDV − tevkifat

Deponun kendi fixture'ıyla (avans %10 · teminat %5 · KDV %20, brüt 233.500):

    hakediş neti = 245.175,00        fatura total = 238.170,00      fark 7.005,00

Ödeme YALNIZ faturaya yazılabilir ve `payments_service` toplamı
`invoice.total` ile KURUŞ BAZINDA sınırlar (`PAYMENT_EXCEEDS_TOTAL`, tolerans
YOK). Yani hakediş netine eşit bir eşik, kesinti taşıyan HİÇBİR hakediş için
ULAŞILABİLİR DEĞİLDİR — kapı, ürünü kilitleyen bir duvara dönüşürdü.

🔴 **Eşik neden `total`, seçim neye dayanıyor:**

1. **ULAŞILABİLİRLİK.** Ödemenin tavanı `total`dir; ondan büyük bir eşik
   yapısal olarak geçilemez.
2. **TEK UZAY.** `Σ payments` bir FATURA uzayı büyüklüğüdür. Onu hakediş uzayı
   büyüklüğüyle (net) karşılaştırmak, deponun yasakladığı *"iki farklı doğruluk
   tanımı"*nın ta kendisidir: iki formülün KDV matrahı gerçekten farklıdır ve
   biri ötekinden türetilemez.
3. **EMSAL.** Bu depo "borç kapandı"yı ZATEN `Σ payments >= invoice.total`
   olarak tanımlar: `payments_service._rederive_status` `collected` damgasını
   TAM O EŞİKTE basar ve `upcoming.py` "kalan"ı `Invoice.total − Σ` ile kurar.
4. **ANLATILABİLİRLİK.** Kural kullanıcıya tek cümleyle söylenir: *hakediş,
   faturası tamamen tahsil edildiğinde ödenmiş sayılır.*

⚠️ **AÇIK ÜRÜN BOŞLUĞU (bu dilimde KAPATILMADI, ölçüldü):** faturanın tutarının
kaynak hakedişle uyuştuğunu doğrulayan HİÇBİR kural yoktur
(`command grep -rn "progress_payment" app/modules/invoicing/validation.py`
→ **EXIT=1**). Yani 1.000.000'lık bir hakedişe 1 ₺'lik fatura kesilip
ödenebilir. Bu, kapıdan ÖNCE de var olan bir boşluktur ve kapatılması iki
formülün hangisinin "doğru tutar" olduğuna dair bir ÜRÜN KARARI gerektirir.

## Nakdin tanımı — bir DAR, bir GENİŞ

`treasury/balance.py::cash_realized_condition()` (ODM-1 D2) BANKA BAKİYESİNİN
tanımıdır ve bağsız bir `method='cheque'` ödemesini NAKİT sayar. Bu kapı için
o tanım YETERSİZDİR (denetim bulgusu 5) — ayrıntı `gate_realized_condition`da.
"""

import uuid
from decimal import Decimal

from sqlalchemy import and_, case, func, literal, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.core.errors import ConflictError
from app.modules.invoicing.models import Invoice, InvoiceDocumentType
from app.modules.treasury import balance
from app.modules.treasury.models import Payment, PaymentMethodKind

__all__ = [
    "NEGOTIABLE_METHODS",
    "PAYMENT_NOT_REALIZED",
    "SOURCE_NOT_INVOICED",
    "assert_realized_covers",
    "binding_invoice_for_source",
    "gate_realized_condition",
    "realized_total_for_source",
]

#: 🔴 409 — kaynağın BAĞLAYICI faturası yok. `PAYMENT_NOT_REALIZED`tan AYRI bir
#: metindir çünkü kullanıcının yapacağı iş de ayrıdır: burada "önce fatura kes",
#: ötekinde "ödemeyi tamamla / çeki tahsil et". Tek metin olsaydı faturası hiç
#: olmayan kullanıcı ödeme aramaya çıkardı.
SOURCE_NOT_INVOICED = "Hakediş ödendi işaretlenemez: önce hakedişe bağlı fatura kesilmelidir."

#: 🔴 409 — evrağın GÖVDESİ kusurlu değildir (422 olurdu); engel kaydın
#: ARKASINDAKİ para durumudur.
PAYMENT_NOT_REALIZED = (
    "Hakediş ödendi işaretlenemez: faturasına kaydedilmiş ve nakde geçmiş ödeme "
    "tutarı fatura tutarını karşılamıyor. Çek/senetle ödemede evrak kaydı "
    "seçilmeli ve tahsil edildiği (ya da ödendiği) işaretlenmelidir."
)

#: Kıymetli evrakla yapılan ödeme ETİKETLERİ. Bunlar `FinancialInstrumentKind`
#: ile aynı ikilidir ama AYRI bir tiptir (`PaymentMethodKind` ayrıca
#: `transfer`/`cash` taşır) — küme burada üyeden ÜRETİLMEZ, çünkü iki enum'un
#: birleştirilmemesi bilinçli bir karardır (FIN-1 K1).
NEGOTIABLE_METHODS = (PaymentMethodKind.cheque, PaymentMethodKind.promissory_note)


def gate_realized_condition():
    """🔴 `mark-paid` KAPISININ nakit tanımı — bakiyeninkinden DAR (bulgu 5).

    Bakiye tanımı (`balance.cash_realized_condition`, ODM-1 D1) bağsız bir
    ödemeyi **etiketine bakmadan** nakit sayar; yani `method='cheque'` yazıp
    `financial_instrument_id` GÖNDERMEYEN bir ödeme (form bunu zorunlu tutmuyor)
    o tanıma göre nakittir. Bakiye için bu DOĞRUDUR ve değiştirilmedi — üç
    ölçülmüş gerekçesi vardır ve değiştirmek CANLI BAKİYELERİ oynatırdı.

    Ama bu kapı BAŞKA BİR SORU soruyor. Kullanıcının kuralı birebir şunu diyor:
    *"...**veya çekin vadesi gelip de tahsil edilmeden** 'ödendi' gözükmemesi
    gerekiyor."* Bağsız bir çek ödemesinde tahsil olayı GÖZLENEMEZ: ortada
    izlenecek bir evrak yoktur. Bakiye tanımıyla yetinilseydi kullanıcı çeki
    yazdığı AN hakediş `paid` olurdu — kuralın birebir yasakladığı hâl.

    Bu yüzden kapı, bakiye yüklemini İTHAL EDER (drift olmasın) ve ÜSTÜNE tek
    bir daraltma koyar — **fail-closed**:

        bağlı ödeme, evrak `collected|paid`            → SAYILIR
        bağsız ödeme, `transfer|cash`                  → SAYILIR (para indi)
        bağsız ödeme, `cheque|promissory_note`         → SAYILMAZ  🔴
        bağlı ödeme, evrak `portfolio|returned|cancel` → SAYILMAZ

    Kullanıcının çıkış yolu KAPALI DEĞİLDİR ve iki tanedir: ya ödemeyi bir
    çek/senet kaydına bağlayıp tahsil edildiğinde işaretler, ya da para gerçekten
    nakit/havale ile geldiyse `method`u ona göre yazar.
    """
    return and_(
        balance.cash_realized_condition(),
        not_(
            and_(
                Payment.financial_instrument_id.is_(None),
                Payment.method.in_(NEGOTIABLE_METHODS),
            )
        ),
    )


async def binding_invoice_for_source(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
) -> tuple[uuid.UUID, Decimal] | None:
    """Kaynağın BAĞLAYICI faturası: `(id, total)` ya da `None`.

    `document_type <> 'refund'` süzgeci sayesinde sonuç EN FAZLA BİR SATIRDIR ve
    bu bir varsayım değil ŞEMA GARANTİSİDİR: `invoicing.models.
    SOURCE_UNIQUE_INDEXES` kaynak başına kısmi UNIQUE indeks kurar (`WHERE
    document_type <> 'refund'`). Süzgeç o sabitle AYNI enum üyesinden türer, yani
    üye yeniden adlandırılırsa ikisi de aynı anda kırılır.
    """
    stmt = select(Invoice.id, Invoice.total).where(
        source_column == source_id,
        Invoice.document_type != InvoiceDocumentType.refund,
    )
    return (await session.execute(stmt)).one_or_none()


async def realized_total_for_source(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
) -> Decimal:
    """Kaynağa bağlı faturalara yatmış NET nakit: asıl fatura − İADE faturaları.

    🔴 **İADE ÇIKARILIR, ATLANMAZ (denetim bulgusu 6).** İlk uygulama iade
    faturasının ödemesini tamamen görmezden geliyordu; senaryo şuydu: 1.000.000
    tahsil edildi, sonra 400.000 iade edildi ve o para GERİ DÖNDÜ — kasada net
    600.000 varken kapı 1.000.000 görüyor ve geçiyordu. Aynı PR'ın ODM-2 mantığı
    (para gerçekten el değiştirdi mi) bunun tam tersini söyler.

    İşaret `document_type`tan gelir: iade faturasının parası TERS yöne akar, bu
    yüzden `-amount` ile toplanır. Tek sorgu, tek `GROUP BY`sız toplam.

    `outerjoin` ŞART (`balance.join_instrument`): ödemelerin ezici çoğunluğu
    evraksızdır; INNER olsaydı hepsi düşer ve toplam sessizce (neredeyse) SIFIR
    olurdu — kapı her hakedişi reddederdi.

    `coalesce` da ŞART: hiç ödemesi olmayan kaynakta `SUM()` NULL döner, 0 değil.
    """
    isaretli = case(
        (Invoice.document_type == InvoiceDocumentType.refund, -Payment.amount),
        else_=Payment.amount,
    )
    stmt = balance.join_instrument(
        select(func.coalesce(func.sum(isaretli), literal(balance.ZERO)))
        .select_from(Payment)
        .join(Invoice, Invoice.id == Payment.invoice_id)
    ).where(
        source_column == source_id,
        gate_realized_condition(),
    )
    return (await session.execute(stmt)).scalar_one()


async def assert_realized_covers(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
) -> None:
    """`mark-paid` kapısı. İKİ ayrı engel, İKİ ayrı 409 metni.

    🔴 **KAPI İLERİ YÖNDEDİR.** Geçişi ENGELLER; `paid`den çıkan bir ters geçiş
    AÇMAZ. `paid` bu depodaki DÖRT evrak ailesinde de TERMİNALDİR ve gerekçesi
    yazılıdır ("banka çıkışı olmuş bir kaydı geri sarmak, kayıt ile para
    hareketi arasındaki bağı koparırdı"). Ödeme sonradan silinirse/karşılıksız
    çıkarsa ne olacağı AYRI bir karardır ve bu dilimde çözülmemiştir.

    🔴 **KİLİT GEREKMEZ ve gerekçesi ölçülmüştür (İK-2 "EŞİK = KİLİT" kanonunun
    SINIRI).** O kanon eşiğin TÜKETİLDİĞİ hâller içindir. Burada tüketilen bir
    şey YOKTUR:

    * aynı hakediş üzerinde iki eşzamanlı `mark-paid` ZATEN serileşir —
      `visible_payment_locked` satırı `FOR UPDATE` + `populate_existing` ile
      kilitler ve ikinci istek durumu kilit ALTINDA yeniden okuyup **409** alır;
    * iki FARKLI hakediş aynı parayı sayamaz: `payments.invoice_id` NOT NULL,
      `ck_invoices_single_source` bir faturada en fazla BİR kaynak kolonuna izin
      verir ve `SOURCE_UNIQUE_INDEXES` bir kaynağa en fazla BİR asıl fatura
      bağlar. Çift sayım için kilit değil ŞEMA gerekir ve o şema yerindedir.

    Karşılaştırma `<` iledir: TAM EŞİT tutar GEÇER (fazlası zaten
    `PAYMENT_EXCEEDS_TOTAL` ile fatura tarafında engellidir).
    """
    binding = await binding_invoice_for_source(session, source_column, source_id)
    if binding is None:
        raise ConflictError(SOURCE_NOT_INVOICED)
    _, total = binding
    realized = await realized_total_for_source(session, source_column, source_id)
    if realized < total:
        raise ConflictError(PAYMENT_NOT_REALIZED)
