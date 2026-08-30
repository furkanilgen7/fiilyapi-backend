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

## 🔴 PARA-GERCEK — `paid` DAMGASI ARTIK BEDAVA DEĞİL

Kullanıcının kuralı: *"Nakit olarak görmeden veya çekin vadesi gelip de tahsil
edilmeden 'ödendi' gözükmemesi gerekiyor."*

`mark_paid` eskiden tabloda YALNIZCA bir çiftti ve `_stamp` sadece `paid_at`
yazıyordu: arkasında para hareketi olup olmadığına HİÇ BAKILMIYORDU. Artık
`_assert_para_gercek` bir ÖN KOŞULDUR ve gerçekleşen ödeme hakediş NETİNİ
karşılamıyorsa geçiş **409**dur.

🔴 **KAPI İLERİ YÖNDEDİR; tablo DEĞİŞMEDİ.** `paid` bu tablonun hiçbir çiftinde
hâlâ KAYNAK DEĞİLDİR (K7). Ters bir geçiş (`paid → approved`) açmak, kaydın
geri sarılması ile para hareketi arasındaki bağı koparırdı — aynı kural
`subcontractor_progress_payments`, `payroll` ve `treasury/instruments`ta da
YAZILIDIR. Ödeme sonradan silinir ya da çek karşılıksız çıkarsa ne olacağı AYRI
bir karardır ve bu dilimde ÇÖZÜLMEMİŞTİR.

Kapı İKİ ailede de vardır (taşeron ikizi aynı adı taşır): işverende para bize
GELİR, taşeronda bizden ÇIKAR ama kural aynıdır ve tek ailede uygulansaydı iki
kopya zamanla ayrışırdı. `payroll`ün `paid`i BAŞKA bir olgudur (bordro dönemi)
ve bu dilimde DOKUNULMAMIŞTIR.
"""

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, SiteValidationError
from app.core.timezone import to_display
from app.modules.approvals import service as approvals_service
from app.modules.approvals.models import ApprovalDocumentType
from app.modules.invoicing.models import Invoice
from app.modules.progress_payments import (
    calculations,
    guards,
    lines,
    posting,
    repository,
    service,
)
from app.modules.progress_payments.models import ProgressPayment, ProgressPaymentStatus
from app.modules.projects.models import Project, ProjectContract
from app.modules.treasury import realized
from app.modules.users.models import User

_ZERO = Decimal("0")

#: Bu evrak ailesinin onay zincirindeki kimligi (mockup `Onay Kutusu.dc.html:210-240`).
_DOCUMENT_TYPE = ApprovalDocumentType.progress_payment


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
    #: OK-1A T3 — zincirin bu istekte verdigi karar (`None` => zincirsiz ESKI
    #: kayit). Router denetim metnini bununla BIRLESTIRIR ve `is_complete`
    #: evragin durumunun degisip degismedigini de anlatir.
    chain_step: approvals_service.ChainDecision | None = None
    #: `/unapprove`te geri sarilan adim (`None` => zincirsiz ya da imza yok).
    chain_rewind: approvals_service.ChainRewind | None = None


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


async def _fisle(
    session: AsyncSession,
    actor: User,
    payment: ProgressPayment,
    project: Project,
    contract: ProjectContract,
    action: PaymentAction,
    new_status: ProgressPaymentStatus,
) -> None:
    """🔴 MU-3D — hakedişin yevmiye fişi. Damgadan SONRA, AYNI transaction'da.

    ## 🔴 KANCA GEÇİŞE DEĞİL BELGEYE BAĞLIDIR

    Ölçüt `action is approve` DEĞİL, `new_status is approved`tir.

    🔴 **DÜRÜST KAYIT (mutasyonla ölçüldü):** bu iki koşul BUGÜN EŞDEĞERDİR —
    geçiş matrisinde `approve` eyleminin TEK hedefi `approved`tır, dolayısıyla
    ölçütü `action is approve` yapan bir mutant hiçbir testi kırmaz. Zincir
    tamamlanmadığında fişin yazılmasını önleyen şey BU SATIR DEĞİL, `perform`un
    yukarısındaki ERKEN DÖNÜŞTÜR (`not chain_step.is_complete`) — `_fisle` o
    hâlde hiç çağrılmaz.

    Denetim yine de `new_status` üzerindedir çünkü matrise `approved`a varan
    ikinci bir eylem eklendiğinde (ya da erken dönüş yeniden yazıldığında)
    YAPISAL olarak doğru kalan ölçüt odur; eylem adına bakan bir koşul o gün
    sessizce yanılırdı.

    🔴 Asıl bekçi bir TESTTİR ve gerçekten ısırır:
    `tests/progress_payments/test_ok1a_chain_binding.py::
    test_MU3D_ARA_adim_FIS_YAZMAZ_fis_SON_adimda_dogar` — erken dönüş
    kaldırıldığında KIRMIZIYA döner (M2 mutantı ölçtü).

    ## Sıra: damga → fiş

    Fiş yazılamazsa (kapalı dönem **409** · eksik eşleme **422**) geçiş de GERİ
    ALINIR, yani "onaylı ama fişsiz" bir hakediş DOĞMAZ. `perform` commit
    etmez; hata çağıranın transaction'ını devirir.

    ## KARAR-5 — `unapprove` STORNO yazar

    Onay geri çekildiğinde kayıt kümülatif kümeden ÇIKAR; fişi ayakta bırakmak,
    onaylı olmayan bir hakedişin hasılatını mizanda tutmak olurdu. Yeniden onay
    SERBESTTİR (tekillik CANLI fişlerle sınırlıdır, MU-3B).
    """
    if action is PaymentAction.unapprove:
        await posting.reverse_progress_payment(session, actor, payment.id)
        return
    if new_status is not ProgressPaymentStatus.approved:
        return
    # 🔴 Zincir `sequence_no` ARTAN sırada olmalıdır (avans tavanı sıralıdır) —
    #    repository öyle döner. `before_sequence_no` kaydın KENDİSİNİ dışlar.
    prior = await repository.list_completed_payments(
        session, payment.project_id, before_sequence_no=payment.sequence_no
    )
    advance_recovered = calculations.cumulative_state(prior, contract.amount).advance_recovered
    await posting.post_progress_payment(
        session,
        actor,
        payment,
        base=posting.posting_base_for(payment, contract.amount, advance_recovered),
        # 🔴 ONAY GÜNÜ — hakedişin dönemi (`period_year`/`period_month`) DEĞİL.
        #    Döneme yazılsaydı geçmiş bir aya kesilen hakediş KAPALI bir döneme
        #    fiş atmayı dener ve KARAR-6'yı delerdi. `_stamp` bu satırdan hemen
        #    ÖNCE koştuğu için damga DAİMA doludur.
        entry_date=to_display(payment.approved_at).date(),
        # 🔴 `to_display` ŞART, çıplak `.date()` DEĞİL (TB5 yerel takvim
        #    bekçisi bunu yakaladı): `approved_at` bir `timestamptz`tir ve
        #    ham `.date()` UTC gününü verir. TR UTC+3 olduğu için gece
        #    00:00-03:00 arasında onaylanan bir hakedişin fişi BİR GÜN
        #    GERİYE düşer — ay sınırında ise ÖNCEKİ AYIN mizanına, hatta
        #    KAPALI bir döneme. Gün sınırı tek kaynaktan okunur.
        employer_name=project.employer_name,
    )


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


async def _assert_para_gercek(session: AsyncSession, payment: ProgressPayment) -> None:
    """🔴 PARA-GERCEK — `mark-paid`in ÖN KOŞULU: para GERÇEKTEN geldi mi?

    Kullanıcının kuralı: *"Nakit olarak görmeden veya çekin vadesi gelip de
    tahsil edilmeden 'ödendi' gözükmemesi gerekiyor."* Bu kapı öncesinde
    `mark_paid` hiçbir şeye BAKMIYORDU — `_stamp` yalnız `paid_at`i yazıyordu ve
    arkasında tek kuruş hareket olmadan hakediş "ödendi" görünebiliyordu.

    Eşik hakediş neti DEĞİL, bağlayıcı FATURANIN `total`idir; gerekçesi (iki
    formülün KDV matrahı farklıdır ve net eşik ULAŞILAMAZDIR) `treasury.realized`
    modülünün docstring'inde TEK KOPYA olarak durur. Sözleşme bu yolda
    OKUNMAZ — eşik artık sözleşme bedeline hiç bağlı değildir.
    """
    await realized.assert_realized_covers(session, Invoice.progress_payment_id, payment.id)


async def _apply_action_rules(
    session: AsyncSession,
    payment: ProgressPayment,
    contract: ProjectContract | None,
    action: PaymentAction,
    reason: str | None,
) -> str | None:
    """İşleme özgü korkuluklar — HEPSİ kilit altında koşar; kırpılmış gerekçeyi döner.

    🔴 OK-1A K2 (KIRICI, kullanıcı kararı 2026-08-21): `reject` gerekçesi artık
    ZORUNLUDUR. Doğrulama zincirin İÇİNDE değil BURADA koşar ve bu bilinçlidir:
    zincirsiz ESKİ kayıtların reddi de gerekçesiz geçmemelidir — kural evrağın
    kendi kapısındadır, zincirin varlığına DAYANMAZ. Kırpma/tavan tanımı yine
    TEK kopyadır (`approvals.service.clean_reject_reason`), taşeron ailesinin
    `guards.validate_reject`i ile aynı deseni izler.
    """
    if action is PaymentAction.submit:
        if contract is None:
            raise SiteValidationError(guards.NO_EMPLOYER_CONTRACT)
        # §7 zorunluluk kuralları TEK kopya `guards.validate_submit`'tedir —
        # burada yeniden yazılmaz (metinler de oradan gelir).
        guards.validate_submit(payment, contract)
    elif action is PaymentAction.approve:
        await _revalidate_quota(session, payment)
    elif action is PaymentAction.mark_paid:
        await _assert_para_gercek(session, payment)
    elif action is PaymentAction.reject:
        return approvals_service.clean_reject_reason(reason)
    return None


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


async def _chain_decision(
    session: AsyncSession,
    actor: User,
    payment: ProgressPayment,
    action: PaymentAction,
    reason: str | None,
) -> tuple[approvals_service.ChainDecision | None, approvals_service.ChainRewind | None]:
    """OK-1A T3 — evrağın onay ZİNCİRİYLE bağı. TEK yer.

    🔴 KİLİT SIRASI: evrak satırı ZATEN kilitlidir (`visible_payment_locked`,
    sözleşme → hakediş) ve zincir satırı ANCAK ondan sonra kilitlenir. Sıra TÜM
    uçlarda ve ÜÇ evrak ailesinde AYNIDIR (deadlock).

    Geçiş tablosu ve zorunluluk korkulukları BURADAN ÖNCE koştu: yanlış
    durumdaki bir evrak için önce "bu adım sana kapalı" demek, asıl engeli
    (kayıt o aşamada değil) gizlerdi.
    """
    if action is PaymentAction.submit:
        await approvals_service.create_chain(
            session,
            document_type=_DOCUMENT_TYPE,
            document_id=payment.id,
            amount=chain_amount(payment),
            created_by_user_id=payment.created_by,
        )
        return None, None
    if action is PaymentAction.approve:
        return (
            await approvals_service.approve_next_step(
                session,
                actor=actor,
                document_type=_DOCUMENT_TYPE,
                document_id=payment.id,
                require_chain=False,
            ),
            None,
        )
    if action is PaymentAction.reject:
        return (
            await approvals_service.reject_chain(
                session,
                actor=actor,
                document_type=_DOCUMENT_TYPE,
                document_id=payment.id,
                reason=reason,
                require_chain=False,
            ),
            None,
        )
    if action is PaymentAction.unapprove:
        return None, await approvals_service.rewind_last_step(
            session, document_type=_DOCUMENT_TYPE, document_id=payment.id
        )
    return None, None


def chain_amount(payment: ProgressPayment) -> Decimal | None:
    """Zincirin eşikle karşılaştıracağı tutar — **BRÜT** (sözleşme R5).

    Kaynak `calculations.gross_total`tır, yani `service.build_detail`in ekranda
    gösterdiği "Brüt" ile AYNI tek toplama kopyası. `amounts.build_block(...).
    gross` de ilk satırında bunu çağırır — o yol seçilseydi sözleşme bedeli ve
    kümülatif avans için İKİ SORGU daha koşardı ve dönen SAYI aynı olurdu.

    🔴 NULL-EŞİK / FAIL-CLOSED (SA kanonu): satır YOKSA tutar BELİRLENEMEZ ve
    `None` döner — motor bunu eşiğin ÜSTÜ sayar, Patron adımı EKLENİR. Sıfır
    döndürülseydi "eksik veri" ile "sıfır tutar" ayırt edilemezdi. (`submit`
    zaten satırsız hakedişi 422 ile durdurur; bu İKİNCİ katmandır ve ona
    DAYANMAZ.)
    """
    if not payment.lines:
        return None
    return calculations.gross_total(payment.lines)


async def perform(
    session: AsyncSession,
    actor: User,
    payment_id: uuid.UUID,
    action: PaymentAction,
    *,
    reason: str | None = None,
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

    trimmed_reason = await _apply_action_rules(session, payment, contract, action, reason)

    chain_step, chain_rewind = await _chain_decision(
        session, actor, payment, action, trimmed_reason
    )
    if action is PaymentAction.approve and chain_step is not None and not chain_step.is_complete:
        # 🔴 ARA ADIM: evrak `pending_approval`da KALIR. Durum makinesi
        # DEĞİŞMEDİ — yalnız `approved`a giden yol artık zincirin SON adımından
        # geçiyor (OK-1A T3).
        await session.flush()
        await session.refresh(payment)
        return TransitionResult(payment, project, chain_step=chain_step)

    previous_approver_name: str | None = None
    previous_approved_at: datetime | None = None
    if action is PaymentAction.unapprove:
        previous_approved_at = payment.approved_at
        previous_approver_name = await _resolve_username(session, payment.approved_by)

    payment.status = new_status
    _stamp(payment, action, actor)
    await _fisle(session, actor, payment, project, contract, action, new_status)
    await session.flush()
    # `updated_at` server `onupdate` ile yenilendiği için expire olur; açık
    # refresh olmadan yanıt inşası `MissingGreenlet` verir.
    await session.refresh(payment)
    return TransitionResult(
        payment,
        project,
        previous_approver_name,
        previous_approved_at,
        chain_step=chain_step,
        chain_rewind=chain_rewind,
    )
