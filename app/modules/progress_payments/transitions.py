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

Toplama `lines.completed_totals` ÜZERİNDEN yapılır — ikinci bir toplama yolu
AÇILMAZ (P5'in "iki farklı doğruluk tanımı" bulgusu: aşım kontrolü ile ekranda
gösterilen "önceki" farklı kümelerden gelirse kullanıcı hangisine güveneceğini
bilemez).

## Kota kümesi SIRASIZDIR (H6 denetimi K1 — kapatılan KRİTİK açık)

Kota tavanı `completed_totals`'ın **tam küme** modundan okur: kendisi HARİÇ tüm
`approved|paid` kayıtlar, `sequence_no` GÖZETMEKSİZİN. Eskiden §6.6'nın sıra
tabanlı "önceki" tanımı kullanılıyordu ve tavan ONAY SIRASI değiştirilerek meşru
uçlarla aşılabiliyordu: seq1'i (600) onayla → seq2'yi (400) onaya gönder → seq1'i
geri çek + reddet → seq1'i 1.000'e yükselt (yazma kontrolü `seq < 1` baktığı için
seq2'yi GÖRMEZ) → seq2'yi, sonra seq1'i onayla ⇒ 1.400 > 1.000, hiçbir uç hata
vermez. Kota kronolojik değil TOPLAM bir kısıttır; sıraya bağlanması kavramsal
hataydı. §6.6'nın gösterim kolonları sıra tabanlı KALIR (spec §6.5/§6.6 ayrımı).
"""

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, SiteValidationError
from app.modules.progress_payments import guards, lines, repository, service
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus
from app.modules.projects.models import Project, ProjectContract
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


class TransitionResult(NamedTuple):
    """`perform()` dönüşü — denetim günlüğü (H10) için `project` de taşınır.

    `previous_approver_name`/`previous_approved_at` YALNIZ `unapprove`de
    doludur (H6'dan devredilen ZORUNLU not, plan H10, spec §11): `_stamp`
    damgaları NULL'lamadan ÖNCE `perform()` içinde okunur — router bu ikisini
    yeniden sorgulayamaz, çünkü döndüğünde damgalar zaten silinmiştir.
    """

    payment: ProgressPayment
    project: Project
    previous_approver_name: str | None = None
    previous_approved_at: datetime | None = None


#: Spec §7 tablosunun ŞEKLİ — TEK KOPYA, durum ADLARIYLA (enum tipinden bağımsız).
#:
#: Taşeron hakedişi (`subcontractor_progress_payments`) AYNI dört durumlu makineyi
#: kullanır ama kendi enum TİPİNİ taşır (`SubcontractorPaymentStatus`; iki evrak
#: ailesinin durum kümesi ileride ayrışabilsin diye bilinçli ayrı tip). Tablo
#: enum'a sabitlenseydi taşeron tarafı onu KOPYALAMAK zorunda kalırdı ve iki kopya
#: zamanla ayrışırdı; adlarla tutulup `build_transition_table` ile TİPLENDİRİLİR.
_TRANSITION_SHAPE: tuple[tuple[str, "PaymentAction", str], ...] = (
    ("draft", PaymentAction.submit, "pending_approval"),
    ("pending_approval", PaymentAction.approve, "approved"),
    ("pending_approval", PaymentAction.reject, "draft"),
    ("approved", PaymentAction.mark_paid, "paid"),
    # §7: "approved → pending_approval (geri çek)" — taslağa DÖNMEZ. Taslağa
    # dönüş iki adımdır (unapprove + reject) ve her adım ayrı denetim kaydıdır.
    # `paid` bu tablonun hiçbir çiftinde KAYNAK değildir (K7: ödenmiş hakedişin
    # geri dönüşü yoktur).
    ("approved", PaymentAction.unapprove, "pending_approval"),
)


def build_transition_table[StatusT: enum.Enum](
    status_enum: type[StatusT],
) -> dict[tuple[StatusT, PaymentAction], StatusT]:
    """`_TRANSITION_SHAPE`i verilen durum enum'una bağlar.

    Enum'da eksik bir üye varsa `KeyError` İTHALAT ANINDA patlar — sessizce
    yarım bir tabloyla çalışmaktansa (ve o durumun her geçişini 409 yapmaktansa)
    açılışta durmak tercih edilir.
    """
    return {
        (status_enum[source], action): status_enum[target]
        for source, action, target in _TRANSITION_SHAPE
    }


#: İşveren hakedişinin tiplenmiş tablosu. Burada olmayan çift 409'dur.
TRANSITIONS: dict[tuple[ProgressPaymentStatus, PaymentAction], ProgressPaymentStatus] = (
    build_transition_table(ProgressPaymentStatus)
)


async def _revalidate_quota(session: AsyncSession, payment: ProgressPayment) -> None:
    """§6.5/1-2'yi ONAY anında yeniden doğrular (modül docstring'indeki gerekçe).

    Satır yazma yolundaki (`lines._resolve`) "yalnız artışta koşar" inceltmesi
    BURADA GEÇERSİZDİR: orada amaç kotası sonradan düşürülen bir taslağın
    düzeltilebilir kalmasıdır (kilitlenmeyi önler); burada ise kayıt kümülatif
    kümeye GİRİYOR — aşmış bir hakedişin onaylanması aşımı kalıcılaştırır.

    Küme SIRASIZDIR (`exclude_payment_id`, modül docstring'indeki K1) ve kaydın
    KENDİSİ dışlanır: `unapprove` ile geri çekilip yeniden onaylanan bir hakediş
    kendi miktarını iki kez saymamalıdır.
    """
    item_ids = [line.contract_item_id for line in payment.lines if line.contract_item_id]
    if not item_ids:
        return
    site_ids = [line.site_id for line in payment.lines if line.contract_item_id]
    quotas = await repository.get_distributed_quotas(session, item_ids, site_ids)
    completed = await lines.completed_totals(
        session, payment.project_id, exclude_payment_id=payment.id
    )

    for line in payment.lines:
        if line.contract_item_id is None:
            # Kalemi silinmiş satırın kotası da yoktur; onayı bu yüzden
            # engellemek evrakı kilitlerdi (snapshot'la ayakta kalır, spec §4.2).
            # Bu satır kümülatif muhasebeden de düşer — ONAYLI SAPMA, spec §6.5
            # notu (H6 denetimi D3); `lines.completed_totals` aynı gerekçeyle atlar.
            continue
        key = (line.contract_item_id, line.site_id)
        quota = quotas.get(key)
        if quota is None:
            raise SiteValidationError(guards.ITEM_NOT_DISTRIBUTED)
        completed_quantity = completed.get(key, (_ZERO, _ZERO))[0]
        if completed_quantity + line.quantity > quota:
            raise SiteValidationError(guards.QUANTITY_EXCEEDS_QUOTA)


def _stamp(payment: ProgressPayment, action: PaymentAction, actor: User) -> None:
    """§7 tablosunun damga kolonu. `reject` damga BIRAKMAZ (gerekçe denetim
    günlüğüne gider, H10 — ayrı kolon AÇILMAZ, K12).

    `reject`, `unapprove`'un aksine `submitted_at`'i TEMİZLEMEZ — asimetri
    BİLİNÇLİDİR (H6 denetimi D1): `unapprove` bir onayı GERİ ALIR ve geride
    "onaylayan" bilgisi bırakırsa denetimde yanlış kişiyi işaret eder; `reject`
    ise gönderimin GERÇEKTEN olduğunu inkâr etmez, damga yeniden `submit`'te
    zaten üzerine yazılır. Davranış değiştirilmeyecektir."""
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


async def _resolve_username(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    """Denetim günlüğü (H10): `unapprove` öncesi `approved_by` FK'sini ada çevirir.

    `session.get` kimlik haritasından (identity map) okur — aynı transaction
    içinde ekstra bir round-trip garanti değildir ama gerekli olduğunda tek
    satır SELECT'tir, N+1 riski taşımaz (tek çağrı, tek kullanıcı).
    """
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    return user.full_name if user is not None else None


async def perform(
    session: AsyncSession, actor: User, payment_id: uuid.UUID, action: PaymentAction
) -> TransitionResult:
    """Tek geçiş yolu (spec §7). Sıra: kapsam → kilit → tablo → korkuluk → damga.

    Kapsam süzgeci (404) korkuluklardan ÖNCE koşar: görünmeyen bir hakedişin
    durumu hakkında 409/422 ile bilgi sızdırılmaz (spec §9.0).

    H6'dan devredilen ZORUNLULUK (plan H10, spec §11): `unapprove` için eski
    `approved_by`/`approved_at` `_stamp` onları NULL'lamadan ÖNCE okunur —
    sıra tersine çevrilirse (`_stamp` çağrısından SONRA okuma) değerler zaten
    `None`dır ve denetim mesajı sessizce "Bilinmiyor" ile gider (hata FIRLAMAZ,
    bu yüzden mutasyon testiyle ayrıca doğrulanır).
    """
    payment, project, contract = await service.visible_payment_locked(session, actor, payment_id)

    new_status = TRANSITIONS.get((payment.status, action))
    if new_status is None:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    await _apply_action_rules(session, payment, contract, action)

    previous_approver_name: str | None = None
    previous_approved_at: datetime | None = None
    if action is PaymentAction.unapprove:
        previous_approved_at = payment.approved_at
        previous_approver_name = await _resolve_username(session, payment.approved_by)

    payment.status = new_status
    _stamp(payment, action, actor)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendiği için expire olur; açık
    # refresh olmadan yanıt inşası `MissingGreenlet` verir.
    await session.refresh(payment)
    return TransitionResult(payment, project, previous_approver_name, previous_approved_at)
