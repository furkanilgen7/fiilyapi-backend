"""🔴 MU-3D İŞ 2 — FATURA FİŞLENİNCE KAYNAK HAKEDİŞİN FİŞİ STORNO EDİLİR.

## Kullanıcı kararı (2026-08-26, SEÇENEK B)

> Hakediş onaylandığında KDV'siz fiş yazar (gider/hasılat + cari). O hakedişten
> fatura oluşturulduğunda hakediş fişi STORNO edilir ve fatura kendi fişini yazar.

Böylece **faturalanmayan** hakedişin gideri de deftere girer (mizan taşeron
maliyetini TAM gösterir), ama faturalanan hakediş İKİ KEZ yazılmaz.

## 🔴 TETİKLEYİCİNİN YERİ — kararın metninden SAPILDI, GEREKÇESİ ÖLÇÜLDÜ

Kararın metni *"fatura OLUŞTURULDUĞUNDA"* der. Tetikleyici `create_invoice`e
konulsaydı **gideri deftere sokmak isteyen kararın kendisi delinirdi**. Ölçüm:

* `create_invoice` faturayı `transitions.INITIAL_STATUS` ile açar: giden →
  **`draft`**, gelen → **`pending`**. İkisi de fişlenmemiş durumlardır.
* Faturanın KENDİ fişi `send`/`approve` geçişinde doğar
  (`invoicing.posting.POSTING_ACTIONS`) — oluşturmada DEĞİL.

Yani oluşturmada storno atılsaydı, fatura gönderilene kadar (ya da HİÇ
gönderilmezse SONSUZA KADAR) **ne hakediş ne fatura** defterde olurdu: gider
mizandan TAMAMEN kaybolurdu. Dahası `draft` fatura SİLİNEBİLİR
(`DELETABLE_STATUS`, yalnız sysadmin) ve silinen taslak stornoyu geri
getirmezdi — kalıcı bir kayıp.

👉 Storno bu yüzden **faturanın kendi fişinin yazıldığı ANDA** koşar:
`state_service.perform_transition`ın fişleme adımında, AYNI transaction'da.
Takas ATOMİKTİR ve gider defterden bir an bile düşmez.

## Fatura SİLİNİR/İPTAL EDİLİRSE hakediş fişi ne olur — ÖLÇÜLDÜ

🔴 **Bu üründe fatura İPTAL EDİLEMEZ.** `InvoiceStatus`ın altı üyesinin hiçbiri
iptal anlamına gelmez; `collected`/`approved`/`disputed` TERMİNALDİR ve
`transitions.py` bunu açıkça yazar. Silme YALNIZ `draft` içindir.

Sonuç, ek bir koda GEREK KALMADAN doğrudur:

| Olay | Faturanın fişi | Hakediş fişi | Doğru mu |
|---|---|---|---|
| `draft` fatura silindi | hiç doğmadı | **CANLI kaldı** | ✅ gider defterde |
| `sent`/`approved` fatura | yazıldı | stornolandı | ✅ tek kez sayıldı |
| `sent` fatura silinmek istendi | — | — | 409 (silinemez) |

Yani "fatura silinirse hakediş fişi geri gelir mi?" sorusunun cevabı: **silinen
fatura hiç fişlenmemiş bir taslaktır ve hakediş fişine hiç dokunmamıştır.** Bir
"storno'yu geri al" yolu AÇILMAZ — açılsaydı, olmayan bir olayı (iptal) taklit
eden bir kod olurdu.

Kesilmiş bir faturanın düzeltilmesi bu üründe İADE FATURASIDIR
(`InvoiceDocumentType.refund`) ve o ayrı bir belgedir; kendi fişini kendisi
yazar. `ck_invoices_single_source`in tekillik indeksi de iadeyi kapsam dışında
bırakır (`models.BINDING_SOURCE_WHERE`).

## 🔴 `disputed` STORNO YAZMAZ

`dispute` `POSTING_ACTIONS`ta DEĞİLDİR: itiraz edilen fatura hiç fişlenmez ve
`vat_return` de onu saymaz. Dolayısıyla hakediş fişi de DOKUNULMADAN kalır —
istenen budur: itiraz edilmiş bir faturanın arkasındaki gider hâlâ gerçektir.
"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.modules.accounting.models import JournalEntry, JournalSourceType
from app.modules.equipment import rental_posting
from app.modules.invoicing.models import Invoice
from app.modules.posting.repository import CANCELLED_STATUS
from app.modules.progress_payments import posting as progress_posting
from app.modules.subcontractor_progress_payments import posting as subcontractor_posting
from app.modules.users.models import User

__all__ = ["SOURCE_REVERSERS", "reverse_source_entry", "source_replaced_by_invoice"]

#: 🔴 `invoices` kaynak FK'si → o ailenin STORNO fonksiyonu.
#:
#: Anahtarlar `models.SOURCE_UNIQUE_INDEXES`in kolonlarıyla ÖRTÜŞÜR ama
#: `purchase_order_id` BURADA YOKTUR ve olmamalıdır: **KARAR-7** gereği
#: satınalma fiş ATMAZ (`JournalSourceType`ta üyesi bile yoktur), dolayısıyla
#: stornolanacak bir fişi de yoktur. Bir giriş yazılsaydı hiçbir zaman fiş
#: bulamayan ölü bir dal olurdu ve okuyucuya siparişin fişlendiğini ima ederdi.
#:
#: 🔴 Bu sözlüğün TAM olduğunu bir bekçi testi `JournalSourceType` üzerinden
#: iddia eder: yeni bir hakediş ailesi fişlenmeye başlayıp buraya eklenmezse,
#: o ailenin faturası çift sayardı ve hiçbir sayı bunu ele vermezdi.
SOURCE_REVERSERS: dict[str, Callable[[AsyncSession, User, uuid.UUID], Awaitable[bool]]] = {
    "progress_payment_id": progress_posting.reverse_progress_payment,
    "subcontractor_progress_payment_id": subcontractor_posting.reverse_subcontractor_payment,
    "equipment_rental_invoice_id": rental_posting.reverse_rental_invoice,
}


async def reverse_source_entry(session: AsyncSession, actor: User, invoice: Invoice) -> bool:
    """Faturanın KAYNAK belgesinin CANLI fişini storno eder. `True` = storno YAZILDI.

    🔴 COMMIT ETMEZ: çağıranın (`state_service.perform_transition`) kendi
    transaction'ında koşar. Faturanın fişi ile kaynağın stornosu AYNI
    transaction'da olmalıdır, aksi hâlde gider bir an için İKİ KEZ (ya da hiç)
    sayılırdı.

    `False` üç meşru hâli birden taşır:
      · fatura hiçbir kaynağa BAĞLI DEĞİL (çoğunluk);
      · kaynak `purchase_order`dır (KARAR-7: fiş atmaz, stornolanacak fiş yok);
      · kaynak MU-3D ÖNCESİ onaylanmıştır ya da tabanı sıfırdır — fişi hiç
        doğmamıştır.

    🔴 `ck_invoices_single_source` en fazla BİR kolonun dolu olmasını garanti
    eder, ama bu döngü yine de İLK dolu kolonda DURMAZ: garanti DB'dedir ve
    burada yeniden varsayılmaz. İki kolon birden dolu olsaydı (kısıt bir gün
    düşürülürse) ikisi de stornolanır, biri sessizce ATLANMAZDI.
    """
    yazildi = False
    for alan, storno in SOURCE_REVERSERS.items():
        kaynak_id = getattr(invoice, alan)
        if kaynak_id is None:
            continue
        yazildi = await storno(session, actor, kaynak_id) or yazildi
    return yazildi


async def source_replaced_by_invoice(
    session: AsyncSession,
    source_column: InstrumentedAttribute[uuid.UUID | None],
    source_id: uuid.UUID,
) -> bool:
    """🔴 KRIT-HAKEDIS K3 — TAKASIN İKİNCİ YARISI: *"bu kaynağın yerini fatura ALDI mı?"*

    `reverse_source_entry` takası BİR YÖNDE kurar (fatura fişlenince kaynağın
    fişi storno edilir) ve MU-3D bunu ölçtü. Ölçülmeyen yön ŞUYDU:

        approve       → hakediş fişi CANLI
        fatura `send` → takas: hakediş fişi `reversed`, faturanın fişi CANLI
        unapprove     → `reverse_*` CANLI fiş BULAMAZ, sessizce `False` döner
        approve       → `post_document`in idempotanlık dalı da CANLI fiş
                        aramaktadır ve bulamaz ⇒ **YENİ** bir hakediş fişi yazar

    Sonuç: faturanın fişi ile yeni hakediş fişi AYNI hasılatı/gideri İKİ KEZ
    taşır. 🔴 **Mizan DENKTİR** (her fiş kendi içinde dengelidir), yani denklik
    kontrolü bu kusuru GÖRMEZ — ölçülmesi gereken şey hesabın NETİDİR.

    Kapı bu yüzden fişleme kancasının İÇİNDEDİR ve fail-closed'dur: kaynağın
    yerini alan CANLI bir fatura fişi varsa kaynak YENİDEN FİŞLENMEZ. Kaydın
    mali izi yok olmaz — faturanın fişi zaten defterdedir ve `unapprove`
    hakedişin kümülatif kümeden çıkmasını sağlamıştır.

    🔴 **KÜME `reverse_source_entry`inkiyle AYNIDIR ve olmak ZORUNDADIR:**
    `document_type` süzgeci YOKTUR çünkü storno tarafında da yoktur. Buraya bir
    süzgeç eklenseydi, storno eden ama "yerini aldı" sayılmayan bir fatura
    sınıfı doğar ve tam o sınıfta çift kayıt geri gelirdi — hiçbir kolon farkı
    da bunu ele vermezdi.

    "CANLI" tanımı `posting.repository.CANCELLED_STATUS`tan TEK KOPYA okunur
    (`entry_for_source`in süzgeciyle aynı enum üyesi).
    """
    stmt = (
        select(Invoice.id)
        .join(
            JournalEntry,
            (JournalEntry.source_type == JournalSourceType.invoice)
            & (JournalEntry.source_id == Invoice.id),
        )
        .where(source_column == source_id, JournalEntry.status != CANCELLED_STATUS)
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None
