"""Satınalmanın İKİ durum makinesi ve ₺500K onay eşiği (SA spec §3, §7 S1/S2).

## Tek tablo, tek kapı

Geçerli geçişler AŞAĞIDAKİ İKİ veri yapısındadır (`REQUEST_TRANSITIONS` ·
`ORDER_TRANSITIONS`); uçlar ve servis kendi `if status == …` kontrollerini
YAZMAZ. Tabloda olmayan her çift 409'dur — "tanımlı olanı say, gerisini
reddet" yaklaşımıyla yeni bir durum eklendiğinde varsayılan davranış
REDDETMEKTİR. Desen `progress_payments/transitions.py`ten alınmıştır.

`build_transition_table` oradan İTHAL EDİLMEDİ ve bu bilinçlidir: o fonksiyon
`_TRANSITION_SHAPE`i (hakediş dörtlüsü) `PaymentAction`a bağlar; satınalmanın
işlem kümesi (`select-and-order`) ve hedefleri (`approve → quote_wait`,
`reject → rejected`) FARKLIDIR. Ortaklaştırılsaydı iki iş akışının şekli tek
sabitte birbirine düğümlenir ve birinin değişimi ötekini sessizce bozardı.
Ortak olan ŞEY DESENDİR, veri değil.

## Neyin tabloda OLMADIĞI da bir karardır

* Talep `delivered`e ELLE geçmez: o damgayı stok girişi atar (§7 S4, T4'ün ST
  zinciri). Bir uç açılsaydı hiç mal girmemiş bir talep teslim görünürdü.
* Sipariş `in_transit → delivered` de AYNI sebeple tabloda yoktur.
* `ordered`/`delivered`/`rejected` talep tarafında TERMİNALDİR: hiçbir çiftte
  KAYNAK değillerdir. Reddedilen talep diriltilmez — ihtiyaç sürüyorsa YENİ
  talep açılır, çünkü ret gerekçesi o kaydın kalıcı bir niteliğidir.

## ₺500K eşiği bir YETKİ kuralıdır, zorunluluk değil

`validation.submit_blockers` "talep eksik mi" sorusunu yanıtlar; eşik ise
"bunu KİM onaylayabilir" sorusunu. Bu yüzden ikisi ayrı modüldedir ve eşik
`submit`te DEĞİL `approve`ta koşar.

**Eşik ONAY ANINDA, GÜNCEL kalemlerden YENİDEN hesaplanır.** `purchase_requests`
üzerinde donmuş bir tutar kolonu yoktur (T1 kararı) ve olmamalıdır: olsaydı
kalem değişiminde bayatlar, düşük tutarla onaya gönderilip sonra şişirilen bir
talep düşük yetkiyle onaylanabilirdi. PATCH ucunun `pending_approval`da 409
vermesi bu saldırının bir yolunu zaten kapatır — ama eşik ona DAYANMAZ; iki
katman birbirinin yedeğidir ve savunma derinliği testle kilitlidir.
"""

import enum
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.errors import ApprovalNotAllowedError, ConflictError, ProcurementValidationError
from app.modules.procurement import guards, repository, validation
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequest,
    PurchaseRequestStatus,
)
from app.modules.users.models import User

__all__ = [
    "APPROVAL_THRESHOLD_LEVEL",
    "APPROVAL_THRESHOLD_TRY",
    "ORDER_TRANSITIONS",
    "REQUEST_TRANSITIONS",
    "RequestAction",
    "apply_request_transition",
    "assert_order_transition",
    "order_total_from_quote",
]


class RequestAction(str, enum.Enum):
    """Talep geçişleri — değerler UÇ YOLLARIYLA birebir aynıdır
    (`…/select-and-order`), böylece router ile tablo arasında ikinci bir
    eşleme sözlüğü gerekmez (`PaymentAction` deseni)."""

    submit = "submit"
    approve = "approve"
    reject = "reject"
    select_and_order = "select-and-order"


#: Spec §3 talep tablosu — TEK KOPYA. Burada olmayan çift 409'dur.
REQUEST_TRANSITIONS: dict[tuple[PurchaseRequestStatus, RequestAction], PurchaseRequestStatus] = {
    (PurchaseRequestStatus.draft, RequestAction.submit): PurchaseRequestStatus.pending_approval,
    # §3: `approve` ARA bir "onaylandı" durumu üretmez — onaydan sonraki iş
    # teklif toplamaktır ve SAT rozetlerinde de "Teklif Bekleniyor" vardır.
    (PurchaseRequestStatus.pending_approval, RequestAction.approve): (
        PurchaseRequestStatus.quote_wait
    ),
    (PurchaseRequestStatus.pending_approval, RequestAction.reject): PurchaseRequestStatus.rejected,
    (PurchaseRequestStatus.quote_wait, RequestAction.select_and_order): (
        PurchaseRequestStatus.ordered
    ),
}

#: Spec §3 sipariş tablosu — geçiş HEDEF DURUMLA adlandırılır çünkü PATCH
#: gövdesi `status` taşır (ayrı bir aksiyon yolu yoktur, SIP'te düğme de
#: durumun kendisini yazar). `(in_transit, delivered)` KASITLI olarak yoktur.
ORDER_TRANSITIONS: frozenset[tuple[PurchaseOrderStatus, PurchaseOrderStatus]] = frozenset(
    {(PurchaseOrderStatus.approved, PurchaseOrderStatus.in_transit)}
)

#: FST 166 "₺500K+ → Patron". Sihirli sayı KODA GÖMÜLMEZ; eşik ve onu geçen
#: seviye tek kaynaktır ve testle kilitlidir.
APPROVAL_THRESHOLD_TRY = Decimal("500000")

#: "Üst seviye rol" = `procurement` modülünde `full`. YENİ bir rol ya da izin
#: İCAT EDİLMEDİ: seed matrisinde (`roles/seed_data.py`) `procurement` satırı
#: sysadmin=`admin` · patron=`full` · satınalma=`full` · PM=`approve` ·
#: şef/saha=`request`tir. FST'nin "Patron"u tam olarak `full`e denk düşer ve
#: normal onaycı PM (`approve`) eşiğin altında kalır. Ladder zaten bu ayrımı
#: taşıdığı için ikinci bir mekanizma (bayrak kolonu, özel rol anahtarı)
#: gereksizdi — ve eklenseydi izin matrisi ile onay kuralı iki ayrı yerden
#: yönetilir, biri ötekinden saparadı.
APPROVAL_THRESHOLD_LEVEL = AccessLevel.full


def _next_status(request: PurchaseRequest, action: RequestAction) -> PurchaseRequestStatus:
    new_status = REQUEST_TRANSITIONS.get((request.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_REQUEST_TRANSITION)
    return new_status


async def _assert_submittable(session: AsyncSession, request: PurchaseRequest) -> None:
    """Sıkı doğrulama — TEK kaynağı `validation.submit_blockers`tır (T2).

    Engeller TEK 422'de birleşir: kullanıcıya eksikleri birer birer
    keşfettirmek FST gibi uzun bir formda kabul edilemez. Ayraç " · "dır ve
    sıra `submit_blockers`ın sırasıdır (başlık alanları önce, kalemler sonra).
    """
    lines = await repository.load_request_lines(session, request.id)
    blockers = validation.submit_blockers(request, lines)
    if blockers:
        raise ProcurementValidationError(" · ".join(blockers))


async def _assert_approver_level(
    session: AsyncSession, actor: User, request: PurchaseRequest
) -> None:
    """₺500K eşiği (modül docstring'indeki gerekçe).

    Tutar `repository.request_estimated_total` ile O AN hesaplanır — kayıtta
    donmuş bir toplam OKUNMAZ. Fiyatsız kalem toplama girmez (T2 kararı), yani
    fiyatı henüz bilinmeyen talep eşiğin altında kalır ve onaycısını bulur.
    """
    total = await repository.request_estimated_total(session, request.id)
    if total < APPROVAL_THRESHOLD_TRY:
        return
    level = await repository.actor_level(session, actor)
    if not satisfies(level, APPROVAL_THRESHOLD_LEVEL):
        raise ApprovalNotAllowedError(guards.APPROVAL_THRESHOLD_EXCEEDED)


def _stamp(
    request: PurchaseRequest, action: RequestAction, actor: User, reason: str | None
) -> None:
    """Geçişin damga kolonları.

    `submit` ve `select-and-order` damga BIRAKMAZ: ikisinin de "kim, ne zaman"
    bilgisi denetim günlüğündedir ve `purchase_requests`ta karşılık kolon
    açılmadı (T1). `reject` gerekçesi ise KOLONDUR (`rejection_reason`) çünkü
    SAT ekranı onu kaydın üstünde gösterir — denetim günlüğü ekranda okunmaz.
    """
    now = datetime.now(UTC)
    if action is RequestAction.approve:
        request.approved_at = now
        request.approved_by_user_id = actor.id
    elif action is RequestAction.reject:
        request.rejected_at = now
        request.rejection_reason = reason


async def apply_request_transition(
    session: AsyncSession,
    actor: User,
    request: PurchaseRequest,
    action: RequestAction,
    *,
    reason: str | None = None,
) -> None:
    """Talebin TEK geçiş yolu. Sıra: tablo → işleme özgü korkuluk → damga.

    Kapsam süzgeci (404) BURADA DEĞİL çağıranda koşar (`service.visible_request`)
    ve tablo kontrolünden ÖNCEDİR: görünmeyen bir talebin durumu hakkında 409
    ile bilgi sızdırılmaz.

    Korkuluklar tablodan SONRA koşar: yanlış durumdaki bir talep için önce
    "eksik alan" ya da "yetkin yetmiyor" demek, asıl engeli (kayıt o aşamada
    değil) gizlerdi.
    """
    new_status = _next_status(request, action)

    if action is RequestAction.submit:
        await _assert_submittable(session, request)
    elif action is RequestAction.approve:
        await _assert_approver_level(session, actor, request)

    request.status = new_status
    _stamp(request, action, actor, reason)
    await session.flush()


def assert_order_transition(order: PurchaseOrder, target: PurchaseOrderStatus) -> None:
    """Siparişin durum kapısı. Tabloda olmayan her çift 409.

    Hedefin MEVCUT durumla aynı olması da geçiştir ve reddedilir: "değişmedi"
    sessizce başarı sayılsaydı ekran, geçersiz bir düğmeyi çalışıyor sanırdı.
    """
    if (order.status, target) not in ORDER_TRANSITIONS:
        raise ConflictError(guards.INVALID_ORDER_TRANSITION)


def order_total_from_quote(
    unit_price: Decimal,
    quantity_total: Decimal,
    shipping_included: bool,
    shipping_cost: Decimal | None,
) -> Decimal:
    """Sipariş tutarı = teklif × talebin toplam miktarı + (varsa) nakliye.

    Formül TEK KOPYADIR: "en iyi fiyat" rozeti de (`service.quote_total_cost`)
    buradan geçer. İki kopya olsaydı ekranda en ucuz görünen teklif ile
    sipariş edilen tutar farklı tabanlardan gelir ve sessizce ayrışırdı.
    """
    kalem = unit_price * quantity_total
    if shipping_included or shipping_cost is None:
        return kalem
    return kalem + shipping_cost
