"""🔴 FAT-HAK — *"bu faturanın bağlı olduğu hakedişin BRÜTÜ kaç"* sorusunun TEK yeri.

## Neden AYRI bir modül

`source_posting.py`nin kardeşidir ve aynı sebeple ayrıdır: fatura ile kaynak
belge arasındaki her köprü, köprünün İKİ ucunu da bilen bir yerde durur.
`validation.py` bu sorguyu TAŞIYAMAZ (o modül bilinçli olarak ORM'e bağlı
DEĞİLDİR ve kuralın saf tarafını tutar), `service.py` de taşıyamaz (aynı
sorguyu `state_service` de sorar ve iki kopya bir gün ayrışırdı).

## 🔴 TABLO YALNIZ İKİ HAKEDİŞ AİLESİNİ TAŞIR — ve bu bir eksiklik DEĞİLDİR

`invoices` DÖRT kaynak FK'si taşır ama ikisi bu kuralın DIŞINDADIR:

* **`equipment_rental_invoice_id`** (MK-2 makine kira hakedişi) — tutarı N
  çarpandan oluşan bir snapshot'tır ve "brüt" diye tek bir kolonu yoktur;
* **`purchase_order_id`** (SA siparişi) — sipariş bir TAAHHÜTTÜR, faturası
  kısmi kesilebilir ve KARAR-7 gereği fiş bile atmaz.

Bu ikisine uydurma bir eşitlik dayatmak, bugün çalışan meşru faturaları
reddederdi. Anahtar kümesi `treasury.realized.SOURCE_DIRECTION` ile BİREBİR
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

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import Invoice
from app.modules.progress_payments.calculations import gross_total
from app.modules.progress_payments.models import ProgressPayment
from app.modules.subcontractor_progress_payments.models import SubcontractorProgressPayment

__all__ = ["SOURCE_GROSS_MODELS", "source_gross_for_invoice"]

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
