"""Taşeron hakedişi durum makinesi (T4; spec §5).

## Tablo PAYLAŞILIR, kopyalanmaz

Geçiş tablosunun ŞEKLİ `progress_payments/transitions.py:_TRANSITION_SHAPE`te
TEK kopyadır; burada yalnız kendi enum tipimize BAĞLANIR
(`build_transition_table`). `PaymentAction` de oradan İTHAL EDİLİR — uç yolları
(`…/mark-paid`) iki ailede birebir aynıdır, ikinci bir eşleme sözlüğü doğmaz.

Yön TEK taraflıdır (`subcontractor_progress_payments` → `progress_payments`),
`calculations`/`guards` paylaşımıyla aynı yön; ters import ASLA açılmaz.

## İşverenden İKİ FARK (spec §5)

1. **`reject` damga BIRAKIR.** İşverende gerekçe yalnız denetim günlüğüne giden
   opsiyonel bir metindir; burada `rejected_at` + `rejection_reason` KOLONLARINA
   yazılır ve gerekçe ZORUNLUDUR. Kaynağı L177 "Revize Gerekli" rozetidir:
   rozet beşinci bir durum DEĞİL, `draft AND rejected_at IS NOT NULL` türevidir
   (`schemas`/`read` tarafında `is_revision_required`).
2. **`submit` damgayı TEMİZLER.** Yeniden onaya gönderilen hakediş artık
   "revize bekleyen" değildir; `rejected_at`/`rejection_reason` NULL'lanır.
   İşverendeki "reject `submitted_at`'i temizlemez" asimetrisi burada da
   korunur (gönderim GERÇEKTEN olmuştur, damga yeniden `submit`te üzerine yazılır).

## Kotanın nihai bekçisi: ONAY anı (spec §4)

`approve` kotayı KİLİT ALTINDA yeniden doğrular ve bunu **sırasız TAM küme**
üzerinden yapar (`lines.completed_quantities_for(exclude_payment_id=…)`). Satır
yazma yolundaki "yalnız artışta koşar" inceltmesi BURADA GEÇERSİZDİR: orada amaç
kotası sonradan düşürülen bir taslağın düzeltilebilir kalmasıdır; burada ise
kayıt kümülatif kümeye (`approved|paid`) GİRİYOR — aşmış bir hakedişin onayı
aşımı KALICILAŞTIRIR. Kendisi kümeden dışlanır, yoksa `unapprove` + yeniden
`approve` kendi miktarını iki kez sayardı.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.contracts.models import SubcontractorContract
from app.modules.progress_payments.transitions import PaymentAction, build_transition_table
from app.modules.projects.models import Project
from app.modules.subcontractor_progress_payments import guards, lines, repository, service
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)
from app.modules.users.models import User

_ZERO = Decimal("0")

__all__ = ["TRANSITIONS", "PaymentAction", "TransitionResult", "perform"]

#: Spec §5 tablosu — ŞEKLİ işveren modülünden gelir, TİPİ buradan.
TRANSITIONS: dict[tuple[SubcontractorPaymentStatus, PaymentAction], SubcontractorPaymentStatus] = (
    build_transition_table(SubcontractorPaymentStatus)
)


class TransitionResult(NamedTuple):
    """`perform()` dönüşü — denetim günlüğü sözleşme/proje adlarını da ister.

    `previous_approver_name`/`previous_approved_at` YALNIZ `unapprove`de doludur
    (işveren H10 dersinin birebiri): `_stamp` damgaları NULL'lamadan ÖNCE
    okunur — router döndüğünde değerler zaten silinmiştir, yeniden sorgulayamaz.
    """

    payment: SubcontractorProgressPayment
    contract: SubcontractorContract
    project: Project
    previous_approver_name: str | None = None
    previous_approved_at: datetime | None = None


async def _revalidate_quota(
    session: AsyncSession, contract: SubcontractorContract, payment: SubcontractorProgressPayment
) -> None:
    """Spec §4 tavanını ONAY anında yeniden doğrular (modül docstring'indeki gerekçe).

    Kural `lines.check_quota` ile TEK kopyadır, toplama `lines.
    completed_quantities_for` ile TEK kopyadır — ikinci bir doğruluk tanımı
    açılmaz. Bağı kopmuş satır (`contract_item_id IS NULL`) atlanır: kalemi
    silinmiş satırın kotası da yoktur, onayı engellemek evrağı kilitlerdi
    (kümülatiften de düşer — `completed_quantities` ile aynı ONAYLI SAPMA).
    """
    item_ids = [line.contract_item_id for line in payment.lines if line.contract_item_id]
    if not item_ids:
        return
    completed = await lines.completed_quantities_for(
        session, contract.id, exclude_payment_id=payment.id
    )
    items = await repository.get_contract_items_by_ids(session, item_ids)
    for line in payment.lines:
        item = items.get(line.contract_item_id) if line.contract_item_id else None
        if item is None:
            continue
        lines.check_quota(item, completed.get(item.id, _ZERO), line.quantity)


def _stamp(
    payment: SubcontractorProgressPayment,
    action: PaymentAction,
    actor: User,
    reason: str | None,
) -> None:
    """Spec §5 tablosunun damga kolonu."""
    now = datetime.now(UTC)
    if action is PaymentAction.submit:
        payment.submitted_at = now
        # "Revize Gerekli" rozeti SÖNER: kayıt yeniden onay sürecindedir.
        payment.rejected_at = None
        payment.rejection_reason = None
    elif action is PaymentAction.approve:
        payment.approved_at = now
        payment.approved_by = actor.id
    elif action is PaymentAction.reject:
        payment.rejected_at = now
        payment.rejection_reason = reason
    elif action is PaymentAction.mark_paid:
        payment.paid_at = now
    elif action is PaymentAction.unapprove:
        # Onay GERİ ÇEKİLDİ: damgalar da silinir — bırakılsaydı onay bekleyen
        # bir kayıt "onaylayan" bilgisi taşır, denetimde yanlış kişiyi gösterirdi.
        payment.approved_at = None
        payment.approved_by = None


async def _apply_action_rules(
    session: AsyncSession,
    contract: SubcontractorContract,
    payment: SubcontractorProgressPayment,
    action: PaymentAction,
    reason: str | None,
) -> str | None:
    """İşleme özgü korkuluklar — HEPSİ kilit altında koşar; kırpılmış gerekçeyi döner."""
    if action is PaymentAction.submit:
        guards.validate_submit(payment)
    elif action is PaymentAction.approve:
        await _revalidate_quota(session, contract, payment)
    elif action is PaymentAction.reject:
        return guards.validate_reject(reason)
    return None


async def _resolve_username(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user.full_name if user is not None else None


async def perform(
    session: AsyncSession,
    actor: User,
    payment_id: uuid.UUID,
    action: PaymentAction,
    *,
    reason: str | None = None,
) -> TransitionResult:
    """Tek geçiş yolu. Sıra: kapsam → kilit → tablo → korkuluk → damga.

    Kapsam süzgeci (404) korkuluklardan ÖNCE koşar: görünmeyen bir hakedişin
    durumu hakkında 409/422 ile bilgi sızdırılmaz (spec §9.0). Kilit sırası
    `service.create`/`save_lines` ile AYNIDIR (önce sözleşme, sonra hakediş) —
    ters sırada kilitleyen bir yol karşılıklı kilitlenme doğurur.

    ZORUNLULUK: `unapprove` için eski `approved_by`/`approved_at` `_stamp` onları
    NULL'lamadan ÖNCE okunur; sıra tersine çevrilirse denetim mesajı sessizce
    "Bilinmiyor" ile gider (hata FIRLAMAZ — bu yüzden testle korunur).
    """
    context = await service.visible_payment_locked(session, actor, payment_id)
    payment, contract, project = context

    new_status = TRANSITIONS.get((payment.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    trimmed_reason = await _apply_action_rules(session, contract, payment, action, reason)

    previous_approver_name: str | None = None
    previous_approved_at: datetime | None = None
    if action is PaymentAction.unapprove:
        previous_approved_at = payment.approved_at
        previous_approver_name = await _resolve_username(session, payment.approved_by)

    payment.status = new_status
    _stamp(payment, action, actor, trimmed_reason)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendiği için expire olur; açık
    # refresh olmadan yanıt inşası `MissingGreenlet` verir.
    await session.refresh(payment)
    return TransitionResult(
        payment, contract, project, previous_approver_name, previous_approved_at
    )
