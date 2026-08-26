"""Fatura DURUM GEÇİŞLERİ (FAT-1 T4) — spec §7 md. 8, 9, 10, 11.

`service.py`den AYRI bir dosyadır ve bu bilinçlidir: `service.py` zaten altı
ucun iş kurallarını taşır (494 satır) ve dört geçiş ucu onu 800 satır tavanına
(spec §9) doğru iterdi. SA'nın 973 satırlık `service.py` borcu TEKRARLANMAZ.
Ayrım aynı zamanda anlamlıdır: bu dosya faturanın İÇERİĞİNE hiç dokunmaz,
yalnızca `status` damgalar.

## 🔴 EŞİK = KİLİT (spec §8, WORKFLOW §4 kanonu · İK-2 dersi)

Sıra DEĞİŞMEZDİR ve kilit HER ŞEYDEN ÖNCE gelir:

    1. kilit   — `visible_invoice(..., for_update=True)` (fatura satırı)
    2. kapsam  — görünmeyen fatura 404 (kilitli satır üzerinde koşar)
    3. matris  — `transitions.next_status` → 409 (yön dışı ya da matris dışı)
    4. K6      — `validation.gate_blockers` → 422 (kalemsiz `send`/`approve`)
    5. damga   — `status` yazılır

Kilit 3. adımdan SONRA alınsaydı iki eşzamanlı `send` de `draft` okur, ikisi de
matrisi geçer ve fatura İKİ KEZ gönderilmiş olurdu — `UPDATE`in örtük satır
kilidi yazma ANINDA alınır, yani kararın çok geç bir noktasında. TOCTOU
penceresini kapatan tek şey OKUMADAKİ açık `FOR UPDATE`tir ve `populate_existing`
onun ayrılmaz parçasıdır (kimlik haritasındaki bayat nesne `session.get`i
sorgusuz döndürür, kilit HİÇ ALINMAZ).

Bekleyen istek uyandığında kararı YENİDEN verir: taze satırda durum artık `sent`
olduğu için matris `(sent, send)` çiftini tanımaz ve **409** döner.

Kilit sırası uçtan uca SABİT: fatura → kalemler (`service.py` ile aynı).

## 🔴 K7 — geçiş HİÇBİR ŞEYİ CANLI OKUMAZ

Bu dosyada `amounts.compute` ÇAĞRISI YOKTUR ve olmamalıdır. Faturanın parasını
üreten çarpanların tamamı yazma anında donmuştur (spec §5 K7); geçiş anında
yeniden hesaplansalardı hakediş tutarı ya da cari ünvanı sonradan değişen bir
kaynak, GÖNDERİLMİŞ bir faturayı sessizce oynatırdı (MK-2 dersi). Kaynak
kayıtlara (hakediş · ekipman kira faturası · sipariş · cari kart) bu dosyadan
HİÇBİR sorgu gitmez.

## Yeni `AuditAction` üyesi AÇILMADI (TB3/T3 kanonu)

`action` gerçek bir Postgres enum tipidir ve yeni üye migration ister. Dört
geçiş mevcut üyelere oturur: `approve` zaten tanımlıdır ve gelen faturanın
onayına birebir uyar; ötekiler `update`tir. Ayrım `messages.*` METNİNDEDİR ve
denetim tablosunda numara ile birlikte okunur.
"""

import uuid
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvoicingValidationError
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.invoicing import (
    posting,
    repository,
    service,
    source_posting,
    transitions,
    validation,
)
from app.modules.invoicing.models import Invoice
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.users.models import User

__all__ = ["TransitionOutcome", "perform_transition"]


class TransitionOutcome(NamedTuple):
    """Geçişin çıktısı — router yalnız bunu denetime yazar.

    `audit_action` de burada durur: hangi işlemin hangi `AuditAction`a düştüğü
    bir GEÇİŞ bilgisidir; router'ların içine dağıtılsaydı dört uç dört farklı
    karar verebilirdi.
    """

    invoice: Invoice
    audit_action: AuditAction
    detail: str


#: İşlem → denetim eylemi. **Yeni enum üyesi AÇILMAZ** (modül docstring'i);
#: `dispute` bir REDDETMEDİR ama `reject` diye bir üye yoktur ve açmak gerçek
#: bir Postgres enum tipine migration demektir — ayrım metne bırakılır.
_AUDIT_ACTIONS: dict[InvoiceAction, AuditAction] = {
    InvoiceAction.send: AuditAction.update,
    InvoiceAction.mark_collected: AuditAction.update,
    InvoiceAction.approve: AuditAction.approve,
    InvoiceAction.dispute: AuditAction.update,
}

#: İşlem → denetim metni üreticisi. Metinler `messages.py`de TEK kopyadır.
_AUDIT_MESSAGES = {
    InvoiceAction.send: messages.invoice_sent,
    InvoiceAction.mark_collected: messages.invoice_collected,
    InvoiceAction.approve: messages.invoice_approved,
    InvoiceAction.dispute: messages.invoice_disputed,
}


async def perform_transition(
    session: AsyncSession, actor: User, invoice_id: uuid.UUID, action: InvoiceAction
) -> TransitionOutcome:
    """Dört geçiş ucunun TEK gövdesi — sıra modül docstring'indedir.

    Dört uç için dört fonksiyon yazılsaydı kilidi ya da K6 kapısını birinde
    unutmak mümkün olurdu; işlemler arasındaki tek fark `action` PARAMETRESİDİR
    ve geçerliliği `transitions.py`nin matrisinden okunur — burada hiçbir
    `if status == …` yoktur.
    """
    invoice = await service.visible_invoice(session, actor, invoice_id, for_update=True)
    yeni_durum = transitions.next_status(invoice.direction, invoice.status, action)

    engeller = validation.gate_blockers(action, await repository.load_lines(session, invoice.id))
    if engeller:
        raise InvoicingValidationError(" · ".join(engeller))

    invoice.status = yeni_durum

    # 🔴 MU-3B — 5.5. FİŞLEME. Damgadan SONRA ve AYNI transaction'da: fiş
    #     yazılamazsa (kapalı dönem 409 · eksik eşleme 422) geçiş de GERİ ALINIR,
    #     yani "gönderilmiş ama fişsiz" bir fatura DOĞMAZ. Kapıların hangisi
    #     olduğu `posting/service.py`dedir ve burada TEKRARLANMAZ.
    #
    #     K7 KORUNUR: `posting.lines_for` faturanın DONMUŞ kolonlarını okur,
    #     `amounts.compute` bu dosyadan hâlâ ÇAĞRILMAZ.
    if action in posting.POSTING_ACTIONS:
        await posting.post_invoice(session, actor, invoice)
        # 🔴 MU-3D İŞ 2 — TAKAS: faturanın fişi yazıldıysa kaynak hakedişin
        #    fişi STORNO edilir. AYNI transaction, faturanın fişinden HEMEN
        #    SONRA: sıra tersine çevrilseydi gider bir an için defterden
        #    tamamen düşerdi ve araya giren bir hata onu ORADA bırakırdı.
        #
        #    🔴 Tetikleyici burada, `create_invoice`te DEĞİL — gerekçe
        #    `source_posting` modül docstring'inde ÖLÇÜLEREK yazılıdır:
        #    fatura `draft`/`pending` doğar ve fişi ANCAK BU GEÇİŞTE yazılır;
        #    oluşturmada storno atılsaydı, gönderilmeyen (ya da silinen) bir
        #    taslak yüzünden gider mizandan KALICI olarak kaybolurdu.
        await source_posting.reverse_source_entry(session, actor, invoice)

    await session.flush()
    # `updated_at` sunucu damgasıdır; UPDATE'ten sonra ORM'deki değer bayattır
    # ve yanıt şeması onu okuduğunda async bağlamda `MissingGreenlet` = 500
    # olurdu (P11 dersi, `service._refresh_stamps` ile aynı gerekçe).
    await session.refresh(invoice)
    return TransitionOutcome(
        invoice=invoice,
        audit_action=_AUDIT_ACTIONS[action],
        detail=_AUDIT_MESSAGES[action](invoice.invoice_no),
    )
