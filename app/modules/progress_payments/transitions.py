"""Hakediş durum makinesi — task H6 (spec §7, §9.4).

## Tek tablo, tek kapı

Geçerli geçişler AŞAĞIDAKİ TEK sözlüktedir (`TRANSITIONS`); uçlar kendi
`if status == …` kontrollerini YAZMAZ. Tabloda olmayan her çift 409
`INVALID_STATUS_TRANSITION`'dır — "tanımlı olanı say, gerisini reddet" yaklaşımı
sayesinde yeni bir durum eklendiğinde varsayılan davranış REDDETMEKTİR (izin
vermek değil).

## Kilit

Her geçiş `SELECT … FOR UPDATE` ALTINDA koşar (spec §7 eşzamanlılık notu):
önce sözleşme satırı, sonra hakediş satırı kilitlenir. Sıra `service.create` ile
AYNIDIR (sözleşme → hakediş) — ters sırada kilitleyen ikinci bir yol açılırsa
karşılıklı kilitlenme (deadlock) doğar.

Kilit ALTINDA durum YENİDEN okunur (`populate_existing`): iki eşzamanlı `approve`
denemesinde ikincisi, birincinin commit'ini gördükten sonra `approved` durumunu
okur ve 409 alır — `approved_at`/`approved_by` çifte damgalanamaz.

## Kotanın nihai bekçisi: ONAY anı (H5 denetimi O2)

`approve` kotayı (§6.5/2) kilit altında YENİDEN doğrular. Gerekçe: kota kontrolü
yalnız satır-yazma anında koşarsa, aynı sözleşmede bir şekilde iki açık hakediş
bulunduğunda (D8'in DB karşılığı yoktur — yalnız uygulama kontrolü vardır) ikisi
de kotayı AYRI AYRI geçer, ikisi onaylanınca toplam kota SESSİZCE aşılır. Kotayı
tüketen şey satırın yazılması değil hakedişin ONAYLANMASIDIR (kümülatif küme
`approved|paid`), bu yüzden son söz buradadır.

Toplama `lines.prior_completed_totals` ÜZERİNDEN yapılır — ikinci bir toplama
yolu AÇILMAZ (P5'in "iki farklı doğruluk tanımı" bulgusu: aşım kontrolü ile
ekranda gösterilen "önceki" farklı kümelerden gelirse kullanıcı hangisine
güveneceğini bilemez).

**Bilinen sınır:** "önceki" kümesi §6.6'nın tanımıyla `sequence_no` küçüklüğüne
dayanır. İki açık hakediş TERS sırada (büyük sıra numaralı önce) onaylanırsa
küçük numaralı olan büyüğü "önceki" saymaz. Bu, tanımı çatallamamak için bilinçli
bırakılmıştır; D8 zaten iki açık hakedişi engeller ve bu kontrol o kuralın
İKİNCİ savunma hattıdır.
"""

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, SiteValidationError
from app.modules.progress_payments import guards, lines, repository, service
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus
from app.modules.projects.models import ProjectContract
from app.modules.users.models import User

_ZERO = Decimal("0")


class PaymentAction(str, enum.Enum):
    """Geçiş işlemleri — değerler UÇ YOLLARIYLA birebir aynıdır (`…/mark-paid`),
    böylece router ile tablo arasında ikinci bir eşleme sözlüğü gerekmez."""

    submit = "submit"
    approve = "approve"
    reject = "reject"
    mark_paid = "mark-paid"
    unapprove = "unapprove"


#: Spec §7 tablosu — TEK KOPYA. Burada olmayan çift 409'dur.
TRANSITIONS: dict[tuple[ProgressPaymentStatus, PaymentAction], ProgressPaymentStatus] = {
    (ProgressPaymentStatus.draft, PaymentAction.submit): ProgressPaymentStatus.pending_approval,
    (
        ProgressPaymentStatus.pending_approval,
        PaymentAction.approve,
    ): ProgressPaymentStatus.approved,
    (ProgressPaymentStatus.pending_approval, PaymentAction.reject): ProgressPaymentStatus.draft,
    (ProgressPaymentStatus.approved, PaymentAction.mark_paid): ProgressPaymentStatus.paid,
    # §7: "approved → pending_approval (geri çek)" — taslağa DÖNMEZ. Taslağa
    # dönüş iki adımdır (unapprove + reject) ve her adım ayrı denetim kaydıdır.
    # `paid` bu tablonun hiçbir çiftinde KAYNAK değildir (K7: ödenmiş hakedişin
    # geri dönüşü yoktur).
    (
        ProgressPaymentStatus.approved,
        PaymentAction.unapprove,
    ): ProgressPaymentStatus.pending_approval,
}


async def _revalidate_quota(session: AsyncSession, payment: ProgressPayment) -> None:
    """§6.5/1-2'yi ONAY anında yeniden doğrular (modül docstring'indeki gerekçe).

    Satır yazma yolundaki (`lines._resolve`) "yalnız artışta koşar" inceltmesi
    BURADA GEÇERSİZDİR: orada amaç kotası sonradan düşürülen bir taslağın
    düzeltilebilir kalmasıdır (kilitlenmeyi önler); burada ise kayıt kümülatif
    kümeye GİRİYOR — aşmış bir hakedişin onaylanması aşımı kalıcılaştırır.
    """
    item_ids = [line.contract_item_id for line in payment.lines if line.contract_item_id]
    if not item_ids:
        return
    site_ids = [line.site_id for line in payment.lines if line.contract_item_id]
    quotas = await repository.get_distributed_quotas(session, item_ids, site_ids)
    prior_totals = await lines.prior_completed_totals(
        session, payment.project_id, payment.sequence_no
    )

    for line in payment.lines:
        if line.contract_item_id is None:
            # Kalemi silinmiş satırın kotası da yoktur; onayı bu yüzden
            # engellemek evrakı kilitlerdi (snapshot'la ayakta kalır, spec §4.2).
            continue
        key = (line.contract_item_id, line.site_id)
        quota = quotas.get(key)
        if quota is None:
            raise SiteValidationError(guards.ITEM_NOT_DISTRIBUTED)
        previous_quantity = prior_totals.get(key, (_ZERO, _ZERO))[0]
        if previous_quantity + line.quantity > quota:
            raise SiteValidationError(guards.QUANTITY_EXCEEDS_QUOTA)


def _stamp(payment: ProgressPayment, action: PaymentAction, actor: User) -> None:
    """§7 tablosunun damga kolonu. `reject` damga BIRAKMAZ (gerekçe denetim
    günlüğüne gider, H10 — ayrı kolon AÇILMAZ, K12)."""
    now = datetime.now(UTC)
    if action is PaymentAction.submit:
        payment.submitted_at = now
    elif action is PaymentAction.approve:
        payment.approved_at = now
        payment.approved_by = actor.id
    elif action is PaymentAction.mark_paid:
        payment.paid_at = now
    elif action is PaymentAction.unapprove:
        # Onay GERİ ÇEKİLDİ: damgalar da silinir. Bırakılsaydı onay bekleyen bir
        # kayıt "onaylayan" bilgisi taşır, denetimde yanlış kişiyi işaret ederdi.
        payment.approved_at = None
        payment.approved_by = None


async def _apply_action_rules(
    session: AsyncSession,
    payment: ProgressPayment,
    contract: ProjectContract | None,
    action: PaymentAction,
) -> None:
    """İşleme özgü korkuluklar — HEPSİ kilit altında koşar."""
    if action is PaymentAction.submit:
        if contract is None:
            raise SiteValidationError(guards.NO_EMPLOYER_CONTRACT)
        # §7 zorunluluk kuralları TEK kopya `guards.validate_submit`'tedir —
        # burada yeniden yazılmaz (metinler de oradan gelir).
        guards.validate_submit(payment, contract)
    elif action is PaymentAction.approve:
        await _revalidate_quota(session, payment)


async def perform(
    session: AsyncSession, actor: User, payment_id: uuid.UUID, action: PaymentAction
) -> ProgressPayment:
    """Tek geçiş yolu (spec §7). Sıra: kapsam → kilit → tablo → korkuluk → damga.

    Kapsam süzgeci (404) korkuluklardan ÖNCE koşar: görünmeyen bir hakedişin
    durumu hakkında 409/422 ile bilgi sızdırılmaz (spec §9.0).
    """
    payment, _, contract = await service.visible_payment_locked(session, actor, payment_id)

    new_status = TRANSITIONS.get((payment.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    await _apply_action_rules(session, payment, contract, action)

    payment.status = new_status
    _stamp(payment, action, actor)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendiği için expire olur; açık
    # refresh olmadan yanıt inşası `MissingGreenlet` verir.
    await session.refresh(payment)
    return payment
