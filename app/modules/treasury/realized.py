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

## 🔴 BAĞLAYICI FATURANIN ÜÇ ŞARTI

Faturanın kaynağa BAĞLI OLMASI yetmez; "bağlayıcı" sayılması için:

    1. `document_type <> 'refund'`   (asıl belge, iade değil)
    2. `total > 0`                   🔴 kusur 1 — sıfır tutarda `0 < 0` False'tur
    3. yön kaynağın para akışına uygun  🔴 kusur 2 — `SOURCE_DIRECTION`

2 ve 3 bağımsız bir denetim turunda bulundu ve ikisi de CANLIDA AÇIKTI.
Gerekçeleri `assert_realized_covers` ve `SOURCE_DIRECTION`dadır.

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
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceDocumentType
from app.modules.treasury import balance
from app.modules.treasury.models import Payment, PaymentMethodKind

__all__ = [
    "BINDING_INVOICE_INVALID",
    "NEGOTIABLE_METHODS",
    "PAYMENT_NOT_REALIZED",
    "SOURCE_DIRECTION",
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

#: 🔴 409 — bağlayıcı fatura VAR ama BELGE OLARAK GEÇERSİZ: tutarı sıfır ya da
#: yönü kaynağın para akışına ters. Üçüncü bir metindir çünkü kullanıcının
#: yapacağı iş de üçüncüdür: "fatura kes" değil, "ödeme yaz" değil — **bu
#: faturayı düzelt/sil ve doğrusunu kes**.
BINDING_INVOICE_INVALID = (
    "Hakediş ödendi işaretlenemez: hakedişe bağlı fatura geçersiz — tutarı sıfır "
    "ya da yönü hakedişin para akışına ters. Faturayı düzeltip yeniden deneyin."
)

#: 🔴 KAYNAK KOLONU → faturanın olması gereken YÖNÜ. Tablo TEK KOPYADIR ve
#: uydurulmadı, YEVMİYE ROLLERİNDEN ölçüldü:
#:
#:   * işveren hakedişi  → `120 receivable` BORÇ / `600 revenue` ALACAK
#:     (`progress_payments.posting`) → para BİZE GELİR → faturayı BİZ keseriz
#:     → **giden** (`outgoing`);
#:   * taşeron hakedişi  → `740 expense` BORÇ / `320 payable` ALACAK
#:     (`subcontractor_progress_payments.posting`) → para BİZDEN ÇIKAR →
#:     faturayı taşeron keser → **gelen** (`incoming`).
#:
#: `treasury.payments_service._UYUMLU_YON` de aynı ikiliyi kullanır (giden ↔
#: alınan çek, gelen ↔ verilen çek); yani üç yer de AYNI yön anlayışındadır.
#:
#: 🔴 Neden GEREKLİ (denetim kusuru 2): yön denetlenmezse taşerona kesilen bir
#: GİDEN fatura (kesinti/ceza) hakedişe bağlanabilir; taşeron onu BİZE öderse
#: `realized` bir TAHSİLATLA dolar ve kapı geçer — yani bize GİREN para,
#: taşerona olan borcumuzu "ödenmiş" gösterir. Taşerona tek kuruş çıkmamıştır.
#:
#: Okuma `.get()` iledir: yeni bir kaynak kolonu eklenirse yön BİLİNMEZ olur ve
#: bilinmeyen REDDEDİLİR (fail-closed) — `KeyError` ham 500 verirdi.
SOURCE_DIRECTION: dict[str, InvoiceDirection] = {
    "progress_payment_id": InvoiceDirection.outgoing,
    "subcontractor_progress_payment_id": InvoiceDirection.incoming,
}

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
) -> tuple[uuid.UUID, Decimal, InvoiceDirection] | None:
    """Kaynağın BAĞLAYICI faturası: `(id, total, direction)` ya da `None`.

    `document_type <> 'refund'` süzgeci sayesinde sonuç EN FAZLA BİR SATIRDIR ve
    bu bir varsayım değil ŞEMA GARANTİSİDİR: `invoicing.models.
    SOURCE_UNIQUE_INDEXES` kaynak başına kısmi UNIQUE indeks kurar (`WHERE
    document_type <> 'refund'`). Süzgeç o sabitle AYNI enum üyesinden türer.

    🔴 **GEÇERLİLİK BURADA SÜZÜLMEZ, ÇAĞIRANDA DENETLENİR.** Tutar/yön şartları
    bu sorguya eklenseydi geçersiz bir fatura "hiç fatura yok" ile AYNI sonucu
    (`None`) verirdi ve kullanıcı, sistemde duran bozuk faturayı hiç görmeden
    "fatura kes" mesajı alırdı — üstelik kısmi UNIQUE indeks yüzünden ikinci bir
    asıl fatura KESEMEZDİ. Üç hâl üç ayrı 409'dur.
    """
    stmt = select(Invoice.id, Invoice.total, Invoice.direction).where(
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
    """`mark-paid` kapısı. ÜÇ ayrı engel, ÜÇ ayrı 409 metni.

    ## 🔴 BAĞLAYICI FATURA "VAR" DEMEK YETMEZ (denetim kusuru 1)

    İlk uygulama yalnız faturanın VARLIĞINA bakıyordu ve `realized < total`
    karşılaştırması **sıfır tutarlı faturada `0 < 0` → False** verdiği için kapı
    BOŞTA GEÇİYORDU. Senaryo canlıda çalışır durumdaydı:

        `POST /invoices` + `subcontractor_progress_payment_id=<hakediş>` ve
        `lines` HİÇ GÖNDERİLMEZ (şema `default_factory=list`, meşru) →
        `amounts.compute` `subtotal=0` → `total=0,00` → `realized=0` →
        `0 < 0` False → `mark-paid` **200**, sıfır ödemeyle "Ödendi".

    Aynı sonuç `unit_price=0` kalemle de üretilir (`_UNIT_PRICE = Field(ge=0)`).

    İki ağırlaştırıcı vardı: (a) kalemsiz fatura `approve` EDİLEMEZ
    (`validation.gate_blockers` → `LINES_REQUIRED`), yani kapı hiçbir zaman
    geçerli belge olamayacak bir kaydı "bağlayıcı fatura" sayıyordu; (b) kısmi
    UNIQUE indeks kaynak başına tek asıl faturaya izin verdiği için sahte fatura
    slotu KALICI olarak işgal ediyor, gerçek fatura o hakedişe bir daha hiç
    bağlanamıyordu — ve `paid` TERMİNAL.

    Bu yüzden `total > 0` ARTIK ŞARTTIR.

    ## 🔴 DURUM ŞARTI BİLEREK YOKTUR — ölçüldü ve gerekçelendirildi

    "Kalemsiz fatura onaylanamıyorsa `approved` isteyelim" doğal görünür ama
    YANLIŞTIR:

    * `approved` GİDEN faturada ULAŞILAMAZ bir durumdur — `OUTGOING_TRANSITIONS`
      yalnız `draft → sent → collected` taşır. Yani durum şartı zorunlu olarak
      YÖNE GÖRE DEĞİŞEN bir tablo olurdu ve `invoicing.transitions`ın durum
      bilgisini İKİNCİ KEZ yazardı; iki tablo bir gün ayrışırdı.
    * Kullanıcının kuralı PARANIN hareketiyle ilgilidir, evrak onayıyla değil:
      gelen fatura sisteme `pending` girer ve ödemesi o hâldeyken yapılabilir.
      `test_FATURA_pending_iken_de_odeme_SAYILIR` bunu zaten kilitler; durum
      şartı onu kırardı ve parayı ödemiş kullanıcı hakedişi kapatamazdı.
    * Ve gereksizdir: denetimin bulduğu tek durum-bağıntılı açık SIFIR TUTARLI
      faturaydı, onu `total > 0` daha doğrudan kapatır.

    ## Kapı İLERİ YÖNDEDİR

    `paid` DÖRT evrak ailesinde de TERMİNALDİR; ters geçiş AÇILMAZ. Ödeme
    sonradan silinirse/karşılıksız çıkarsa ne olacağı AYRI bir karardır.

    ## Kilit gerekmez (İK-2 "EŞİK = KİLİT" kanonunun SINIRI)

    O kanon eşiğin TÜKETİLDİĞİ hâller içindir; burada tüketilen bir şey yoktur:
    aynı hakedişte iki eşzamanlı `mark-paid` `visible_payment_locked`
    (`FOR UPDATE` + `populate_existing`) ile serileşir ve ikincisi 409 alır; iki
    FARKLI hakediş aynı parayı sayamaz çünkü `payments.invoice_id` NOT NULL,
    `ck_invoices_single_source` ve `SOURCE_UNIQUE_INDEXES` bunu ŞEMA düzeyinde
    imkânsız kılar.

    Karşılaştırma `<` iledir: TAM EŞİT tutar GEÇER.
    """
    binding = await binding_invoice_for_source(session, source_column, source_id)
    if binding is None:
        raise ConflictError(SOURCE_NOT_INVOICED)

    _, total, direction = binding
    beklenen_yon = SOURCE_DIRECTION.get(source_column.key)
    if total <= 0 or direction is not beklenen_yon:
        raise ConflictError(BINDING_INVOICE_INVALID)

    realized = await realized_total_for_source(session, source_column, source_id)
    if realized < total:
        raise ConflictError(PAYMENT_NOT_REALIZED)
