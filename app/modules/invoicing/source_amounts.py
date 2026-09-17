"""🔴 FAT-HAK — *"bu faturanın bağlı olduğu hakedişin BRÜTÜ kaç"* sorusunun TEK yeri.

## Neden AYRI bir modül

`source_posting.py`nin kardeşidir ve aynı sebeple ayrıdır: fatura ile kaynak
belge arasındaki her köprü, köprünün İKİ ucunu da bilen bir yerde durur.
`validation.py` bu sorguyu TAŞIYAMAZ (o modül bilinçli olarak ORM'e bağlı
DEĞİLDİR ve kuralın saf tarafını tutar), `service.py` de taşıyamaz (aynı
sorguyu `state_service` de sorar ve iki kopya bir gün ayrışırdı).

## 🔴 BRÜT TABLOSU YALNIZ İKİ HAKEDİŞ AİLESİNİ TAŞIR

`invoices` DÖRT kaynak FK'si taşır ama ikisi **brüt** kuralının DIŞINDADIR:

* **`equipment_rental_invoice_id`** (MK-2 makine kira hakedişi) — hakedişin
  kendi tutarı `invoice_amount`tır ve FAT-HAK'ın brüt eşitliği bu ailede
  kullanıcı kararının (2026-09-03) kapsamına GİRMEZ;
* **`purchase_order_id`** (SA siparişi) — sipariş bir TAAHHÜTTÜR, faturası
  kısmi kesilebilir ve KARAR-7 gereği fiş bile atmaz.

⚠️ Bu daraltma **DEFTERİ korumaz, yalnız belgenin brütünü serbest bırakır** ve
eskiden korumasız kalan şey defterin ta kendisiydi: fişi storno edilen kira
hakedişinin yerine BAŞKA bir tutar geçebiliyordu. Defter tarafının kapısı
`SOURCE_ENTRY_TYPES`tır ve kapsamı BURADAN DEĞİL `source_posting.
SOURCE_REVERSERS`tan okunur — gerekçesi o sabitin başındadır.

Brüt kapısına kira eklemek `SOURCE_DIRECTION`ı da (aşağıdaki eşitlik bekçisi)
değiştirmek demektir ve bu bir ÜRÜN KARARIDIR; bu onarım ona dokunmadı.
Anahtar kümesi `treasury.realized.SOURCE_DIRECTION` ile BİREBİR
AYNIDIR ve bu tesadüf değildir: *"tutarı hakedişe kilitlenen kaynak"* ile
*"yönü hakedişin para akışına kilitlenen kaynak"* aynı iki kolondur. Bir
bekçi testi iki kümenin eşitliğini iddia eder — üçüncü bir hakediş ailesi
eklendiğinde biri güncellenip öteki unutulursa açık YALNIZ o ailede kalırdı.

## Brüt ÜRÜNÜN tek toplama kopyasından okunur

`progress_payments.calculations.gross_total` — SQL'de yeniden yazılmaz.
Yazılsaydı ikinci bir doğruluk tanımı doğardı: satır tutarı ÇİFT yuvarlanır
(`quantize2(quantize2(bf × katsayı) × miktar)`) ve bunu `SUM()` içinde
tekrarlayan her ifade er ya da geç kuruş ayrışırdı.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing.models import Invoice
from app.modules.posting import repository as posting_repository
from app.modules.progress_payments.calculations import gross_total
from app.modules.progress_payments.models import ProgressPayment
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment

__all__ = [
    "SOURCE_ENTRY_TYPES",
    "SOURCE_GROSS_MODELS",
    "source_gross_for_invoice",
    "source_posting_base_for_invoice",
]

#: Kaynak FK kolonu → hakediş modeli. Değerler `lines` ilişkisini `lazy="selectin"`
#: ile taşır (iki modelde de ölçüldü), yani `gross_total(payment.lines)` async
#: bağlamda `MissingGreenlet` üretmez.
SOURCE_GROSS_MODELS: dict[str, type] = {
    "progress_payment_id": ProgressPayment,
    "subcontractor_progress_payment_id": SubcontractorProgressPayment,
}


async def source_gross_for_invoice(session: AsyncSession, invoice: Invoice):
    """Faturanın bağlı olduğu hakedişin brütü; hakediş kaynağı yoksa `None`.

    🔴 `None` İKİ farklı meşru hâli birden taşır ve çağıran ikisini de AYNI
    şekilde ele alır (kural koşmaz): fatura hiçbir kaynağa bağlı değildir
    (çoğunluk), ya da kaynağı bu tablonun DIŞINDADIR (kira hakedişi · sipariş).

    🔴 Kaynak kaydı BULUNAMAZSA da `None` döner. Bu ulaşılamaz görünür
    (`ondelete=RESTRICT` faturası olan kaynağı silinemez kılar) ama savunma
    ucuzdur ve alternatifi `AttributeError` → ham 500'dür.
    """
    for alan, model in SOURCE_GROSS_MODELS.items():
        kaynak_id: uuid.UUID | None = getattr(invoice, alan)
        if kaynak_id is None:
            continue
        payment = await session.get(model, kaynak_id)
        if payment is None:
            return None
        return gross_total(payment.lines)
    return None


#: 🔴 MU-3D TAKAS — kaynak FK kolonu → o ailenin FİŞ kaynak türü.
#:
#: 🔴 **KÜME `SOURCE_GROSS_MODELS`inki DEĞİL, `source_posting.SOURCE_REVERSERS`ınkidir**
#: ve bir bekçi testi (`tests/modules/invoicing/test_fat_hak.py`) iki kümenin
#: eşitliğini iddia eder.
#: Gerekçe ÖLÇÜLDÜ: bu tablo *"faturanın brütü kaynağınkine uyuyor mu"* sorusunu
#: DEĞİL, *"takas sırasında storno edilecek tutar kaç"* sorusunu cevaplar. Yani
#: kapsamı FİŞİ STORNO EDİLEN ailelerdir — fişi storno edilip tabanı
#: kilitlenmeyen bir aile kalırsa, o ailede defter sessizce KAYAR.
#:
#: Kira hakedişi (`equipment_rental_invoice_id`) tam da böyle KALMIŞTI:
#: `SOURCE_REVERSERS` onun fişini de storno ediyor ama tutarını hiçbir kapı
#: ölçmüyordu, dolayısıyla `equipment_rental_invoice_id` taşıyan bir fatura
#: kaynağın `invoice_amount`ıyla İLGİSİ OLMAYAN bir tutarla kesilebiliyordu
#: (740 kira gideri 100.000'den 5.000'e düşüyor, MİZAN DENK kalıyordu).
#:
#: `purchase_order_id` BURADA YOKTUR ve olmamalıdır — KARAR-7 gereği sipariş
#: fiş ATMAZ, `SOURCE_REVERSERS`ta da yoktur (gerekçe `source_posting`ta).
#: FAT-HAK'ın brüt kapısı (`SOURCE_GROSS_MODELS`) ise AYRI bir kuraldır ve
#: kapsamı `treasury.realized.SOURCE_DIRECTION`a kilitlidir; kira orada
#: bilinçli olarak dışarıdadır ve bu tablo onu İKAME ETMEZ.
SOURCE_ENTRY_TYPES: dict[str, JournalSourceType] = {
    "progress_payment_id": JournalSourceType.progress_payment,
    "subcontractor_progress_payment_id": JournalSourceType.subcontractor_progress_payment,
    "equipment_rental_invoice_id": JournalSourceType.equipment_rental_invoice,
}


async def source_posting_base_for_invoice(
    session: AsyncSession, invoice: Invoice
) -> Decimal | None:
    """🔴 *"Takas sırasında STORNO EDİLECEK tutar kaç"* — kaynağın CANLI fişinin tabanı.

    `source_gross_for_invoice`in kardeşi ve İKİNCİ yarısı. FAT-HAK kapısı
    faturanın BRÜTÜNÜ (`subtotal`) hakedişin brütüne kilitler; bu fonksiyon
    faturanın DEFTERE GİDEN bacağını (`tax_base`) hakedişin DEFTERE GİTMİŞ
    bacağına kilitleyen kapının girdisini verir. İkisi ayrı olgulardır: brüt
    eşit olduğu hâlde tabanlar `avans + teminat` kadar ayrışabilir ve mizan
    DENK KALDIĞI için hiçbir kolon farkı bunu ele vermez.

    ## 🔴 Taban HESAPLANMAZ, FİŞTEN OKUNUR

    `posting.posting_base_for(payment, contract_amount, advance_recovered)`
    yeniden çağrılabilirdi ama YANLIŞ OLURDU: avans mahsubu KÜMÜLATİF TAVANLIDIR
    (`calculations.advance_deduction`) ve tavan, hakedişin onaylandığı ANDAKİ
    zincire bağlıdır. Sonradan yeniden hesaplanan bir taban, storno edilecek
    tutardan sessizce ayrışabilirdi. Fişin `total_debit`i ise o anın DONMUŞ
    kopyasıdır ve storno TAM OLARAK onu geri alır — üç ailenin de fişi iki
    bacaklıdır (`debit=base` / `credit=base`), yani `total_debit == base`.

    `None` = *"kilitlenecek bir fiş YOK"* ve üç meşru hâli birden taşır: fatura
    fişi storno edilen ailelerden birine bağlı değil (kaynaksız · sipariş),
    kaynak henüz onaylanmamış, ya da kaynak MU-3D ÖNCESİ onaylanmıştır. Üçünde
    de `reverse_source_entry` zaten `False` döner — yani kaydıracak bir takas
    yoktur.
    """
    for alan, source_type in SOURCE_ENTRY_TYPES.items():
        kaynak_id: uuid.UUID | None = getattr(invoice, alan)
        if kaynak_id is None:
            continue
        entry = await posting_repository.entry_for_source(session, source_type, kaynak_id)
        return None if entry is None else entry.total_debit
    return None
