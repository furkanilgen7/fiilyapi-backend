"""İK-3 T4 — onay + odeme yolu (satir ve donem).

Bolumun tamami PARA CIKISININ KAPISIDIR; iki invariant (K2 cift odeme ve
EŞİK = KİLİT) asagidaki bolum notunda gerekcelidir.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.audit import messages
from app.modules.payroll import guards, posting, schemas, transitions
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
)
from app.modules.payroll.service.core import (
    LOCKED_LINE_STATUSES,
    LOCKED_PERIOD_STATUSES,
    _full_name,
    _line_response,
    _lock_period,
    _locked_line,
    _locked_period_lines,
    has_payable_line,
    rates_by_source,
)
from app.modules.users.models import User

# --- T4: onay + ödeme yolu -------------------------------------------------
#
# 🔴 BU BÖLÜM PARA ÇIKIŞININ KAPISIDIR. İki invariant burada yaşar:
#
# ## K2 — çift ödeme YAPISAL OLARAK imkânsız
#
# Taşeron satırı (`excluded`) hiçbir yoldan `approved` olamaz: satır onayı 409
# verir, toplu onay onu ATLAR ve sayar, `pay` ne durumunu değiştirir ne de
# tutarını toplama katar. Üç yolun üçü de ayrı ayrı kapalıdır çünkü biri açık
# kalsaydı taşeron işçisinin aynı emeği hem hakedişten (TH) hem bordrodan
# ödenirdi. Kapının kendisi `transitions.py`dedir: `excluded` hiçbir çiftin
# KAYNAĞI değildir — buradaki denetimler yalnız AÇIKLAYICI mesaj içindir.
#
# ## EŞİK = KİLİT (WORKFLOW §4, İK-2 dersi)
#
# Bordroda "eşik" bir kota değil bir DURUM KAPISIDIR: her adım YALNIZ BİR KEZ
# atılabilir. Kilit olmadan iki eşzamanlı istek AYNI durumu okur ve İKİSİ DE
# geçer — dönem iki kez "ödendi" damgası alır. Beş şart da tutulur:
# (a) serileştirme DÖNEM satırındadır, (b) işlem satırı ayrıca `with_for_update`
# + `populate_existing`, (c) kilit DURUM DENETİMİNDEN ÖNCE alınır (TOCTOU),
# (d) sıra tüm uçlarda SABİT dönem → satır, (e) regresyon iki gerçek bağlantıyla
# `tests/modules/payroll/test_payroll_approval_concurrency.py`tedir.


def _assert_line_decidable(period: PayrollPeriod, line: PayrollLine) -> None:
    """Onay/red yolunun İKİ ortak kapısı — ikisi de 409 (durum engeli, yetki değil).

    1. **Dönem** `approved`/`paid`: onaylanmış dönemin toplamları raporlanmıştır;
       içindeki bir satırın onayını sonradan oynatmak o raporu sessizce
       yalanlardı. PATCH ile AYNI kapı (`LOCKED_PERIOD_STATUSES`).
       Spec S8'in "geri geçiş yalnız dönem `paid` DEĞİLKEN" cümlesinden DAHA
       DARDIR ve bu bilinçlidir: para yönünde fail-closed davranılır, düzeltme
       dönem onaylanmadan ÖNCE yapılır.
    2. **K2 — `excluded` satır:** taşeron bordrodan ödenmez; onayı da reddi de
       anlamsızdır. Bu kapı geçiş tablosunun söylediğini TEKRAR ETMEZ, yalnız
       kullanıcıya niçin olduğunu söyler.
    """
    if period.status in LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED_FOR_DECISION)
    if line.status is PayrollLineStatus.excluded:
        raise ConflictError(guards.LINE_EXCLUDED)


async def approve_line(
    session: AsyncSession, line_id: uuid.UUID
) -> tuple[schemas.PayrollLineResponse, str]:
    """`POST /payroll/lines/{id}/approve` — BY satır durumu "Beklemede" → "Onaylandı".

    S4 kapısı AÇIKÇA burada durur (`uncomputed`): geçiş tablosu onu zaten
    reddederdi ama genel bir "bu duruma geçirilemez" cümlesi kullanıcıya
    yapması gerekeni söylemez — eksik olan şey ÜCRET TANIMIDIR.

    Aktör satıra YAZILMAZ: satırda onaylayan kolonu yoktur (T1). Onaylayanın izi
    dönemdedir (`approved_by_id`) ve her kararın izi denetim günlüğündedir.
    """
    period, line = await _locked_line(session, line_id)
    _assert_line_decidable(period, line)
    if line.status is PayrollLineStatus.uncomputed:
        raise ConflictError(guards.LINE_UNCOMPUTED)

    transitions.assert_line_transition(line.status, PayrollLineStatus.approved)
    line.status = PayrollLineStatus.approved

    await session.flush()
    full_name = await _full_name(session, line.personnel_id)
    return _line_response(line, full_name), messages.payroll_line_approved(
        full_name, period.year, period.month
    )


async def reject_line(
    session: AsyncSession, line_id: uuid.UUID
) -> tuple[schemas.PayrollLineResponse, str]:
    """`POST /payroll/lines/{id}/reject` — ONAYIN GERİ ALINMASI (`approved → pending`).

    Ayrı bir `rejected` durumu YOKTUR ve icat edilmez: satır durumu kümesi T1'de
    kapanmıştır ve "reddedilmiş bordro satırı" diye bir şey yoktur — kişi ya
    ödenir ya da satırı düzeltilir. Red, satırı yeniden DÜZENLENEBİLİR kılar
    (S5'in düzeltme yolu).

    🔴 Kaynak durum AÇIKÇA `approved` olmalıdır. Yalnız geçiş tablosuna
    güvenilseydi `uncomputed → pending` çifti (K3 override'ının çıkışı) bu uçtan
    da kullanılabilir, brütü `null` bir satır "onay bekliyor" hâline gelir ve S4
    fail-closed kapısı ARKADAN DOLANILIRDI.
    """
    period, line = await _locked_line(session, line_id)
    _assert_line_decidable(period, line)
    if line.status is not PayrollLineStatus.approved:
        raise ConflictError(guards.LINE_NOT_APPROVED)

    transitions.assert_line_transition(line.status, PayrollLineStatus.pending)
    line.status = PayrollLineStatus.pending

    await session.flush()
    full_name = await _full_name(session, line.personnel_id)
    return _line_response(line, full_name), messages.payroll_line_rejected(
        full_name, period.year, period.month
    )


async def approve_period(
    session: AsyncSession, actor: User, period_id: uuid.UUID
) -> tuple[schemas.PayrollPeriodApproveResult, str]:
    """`POST /payroll/periods/{id}/approve` — BY 303 "Tümünü Onayla" + BY 56.

    Dönemi **TEK ADIM** ilerletir (`draft → pending_approval → approved`) ve aynı
    işlemde `pending` satırları onaylar. Tek çağrıda `draft → approved`
    yapılsaydı S8'in "atlama yok" kuralı DIŞARIDAN gözlemlenemez hâle gelir ve
    BY 61'in "onay bekliyor" hâli hiç yaşanmazdı. Hedef `transitions.py`den
    TÜRETİLİR; burada ikinci bir zincir tanımı yoktur.

    Ödeme damgası bu uçtan BASILMAZ: `approved → paid` de tabloda vardır ama
    para çıkışının kendi ucu (`/pay`) vardır — "onayla"ya basan kullanıcı ödeme
    yapmış olmamalıdır.

    🔴 Atlananlar SEBEBE GÖRE sayılır (WORKFLOW §3): `excluded` (K2) ve
    `uncomputed` (S4) ayrı ayrı raporlanır — kullanıcının yapacağı iş farklıdır.

    🔴 **MU-3E — TAHAKKUK FİŞİ TAM OLARAK BURADA DOĞAR** (`hedef is approved`
    iken). Gerekçe `payroll/posting.py`nin modül docstring'inde ÖLÇÜLEREK
    yazılıdır ve burada TEKRARLANMAZ; özeti: bu, kilidin düştüğü ve tutarların
    DONDUĞU tek geçiştir.

    ⚠️ **Kanca GEÇİŞE DEĞİL HEDEF DURUMA bağlıdır.** Bu uç TEK ADIM ilerletir
    (S8), yani aynı fonksiyon `draft → pending_approval` için de koşar ve o
    çağrıda fiş YAZILMAZ. `action is approve` gibi bir koşul yazılsaydı ilk
    tıkta da fiş kesilir, bordro onaylanmadan mizana girerdi.

    🔴 Fiş satırlar `approved` yapıldıktan SONRA yazılır: `posting.
    postable_lines` `PAYABLE_LINE_STATUSES` kümesine bakar ve sıra tersine
    çevrilseydi henüz `pending` olan satırlar da fişe girerdi — bugün aynı
    sonucu verir (`pending` de o kümededir) ama kümenin daralması hâlinde
    sessizce ayrışırdı.

    🔴 `actor` bir `User`dır, `actor_id` DEĞİL: `post_document` fişin
    `created_by_id`sini yazar. Kimliği alıp burada kullanıcıyı yeniden okumak
    ikinci bir sorgu ve ikinci bir "bulunamadı" dalı açardı.

    Fiş yazılamazsa (kapalı dönem **409** · eksik eşleme ya da eksik bileşen
    **422**) ONAY DA GERİ ALINIR — AYNI transaction'dadır. "Onaylı ama fişsiz"
    bir bordro DOĞMAZ.

    🔴 **KRIT-BORDRO — ÖDENECEK SATIRI OLMAYAN DÖNEM BU UÇTAN DA GEÇEMEZ (409).**

    Bu kapı yeni bir icat DEĞİL, `compute_flow._promote_period_after_compute`te
    ZATEN tarif edilmiş ve orada bekçilenmiş invariantın İKİNCİ KAPIYA
    uygulanmasıdır; yüklem `core.has_payable_line`de TEK KOPYADIR. Oradaki
    bekçi `compute`un KENDİLİĞİNDEN yaptığı terfiyi kapatıyordu, ama AYNI
    `draft → pending_approval` çiftini kullanıcı BU UÇTAN elle sürebiliyordu —
    bekçi yanlış kapıda duruyordu.

    Ölçülen zarar (boş dönem, iki istek): `approve` 200 → `pending_approval`,
    `approve` 200 → `approved`. Ardından `compute` **409**, satır `PATCH`
    **409**, dönem `DELETE` **405** (uç yok), aynı ayı yeniden açmak **409**
    (UQ `year, month`). Yani o ayın bordrosu elle SQL dışında kurtarılamaz
    hâle geliyordu — "geri dönüşü olmayan bir boş onay"ın birebir kendisi.

    🔴 Denetim İKİ ADIMDA DA koşar, yalnız `draft → pending_approval`de değil.
    `pending_approval → approved` adımında ulaşılamaz DEĞİLDİR ve bu ÖLÇÜLDÜ:
    puantajı girilmiş bir dönem `pending_approval`a terfi ettikten SONRA
    personelin ücret tanımı kaldırılıp `compute` yeniden koşarsa satır
    `uncomputed`a düşer, dönem `pending_approval` KALIR (terfi yalnız `draft`a
    bakar) ve ikinci tık dönemi yine boş boş `approved` yapardı. O dönemin
    doğru çıkışı onay değil YENİDEN HESAPTIR ve `pending_approval` kilitli
    olmadığı için o yol AÇIKTIR — kapı kullanıcıyı tıkamaz, kurtarılabilir
    tarafta tutar.

    🔴 Denetim satır döngüsünden ÖNCE ve `period.status` yazımından ÖNCEDİR:
    sonraya konsaydı satırlar onaylanmış, dönem ilerletilmiş olurdu ve 409
    yalnız yanıtı değiştirir, YAZIYI geri almazdı (`ConflictError` transaction'ı
    düşürse bile kapı "hiç girmeme" değil "girip çıkma" olurdu).
    """
    period = await _lock_period(session, period_id)
    hedef = transitions.next_period_step(period.status)
    if hedef is None or hedef is PayrollPeriodStatus.paid:
        raise ConflictError(guards.PERIOD_NOT_APPROVABLE)
    transitions.assert_period_transition(period.status, hedef)

    onaylanan = atlanan_uncomputed = atlanan_excluded = atlanan_onayli = 0
    # Satır listesi DEĞİŞKENE ALINIR: MU-3E fişi AYNI kümeyi tutarlar. Yeniden
    # okunsaydı fiş, onaylanan satırlardan BAŞKA bir küme üzerinde tanımlanabilirdi.
    satirlar = await _locked_period_lines(session, period.id)
    if not has_payable_line(satirlar):
        raise ConflictError(guards.PERIOD_EMPTY_NOT_APPROVABLE)
    for line in satirlar:
        if line.status is PayrollLineStatus.uncomputed:
            atlanan_uncomputed += 1
            continue
        if line.status is PayrollLineStatus.excluded:
            atlanan_excluded += 1
            continue
        if line.status in LOCKED_LINE_STATUSES:
            atlanan_onayli += 1
            continue
        transitions.assert_line_transition(line.status, PayrollLineStatus.approved)
        line.status = PayrollLineStatus.approved
        onaylanan += 1

    period.status = hedef
    if hedef is PayrollPeriodStatus.approved:
        period.approved_by_id = actor.id
        period.approved_at = datetime.now(UTC)
        await posting.post_payroll_period(
            session,
            actor,
            period,
            satirlar,
            await rates_by_source(session, period.year),
        )

    await session.flush()
    return (
        schemas.PayrollPeriodApproveResult(
            period_status=period.status,
            approved=onaylanan,
            skipped_uncomputed=atlanan_uncomputed,
            skipped_excluded=atlanan_excluded,
            skipped_already_approved=atlanan_onayli,
        ),
        messages.payroll_period_approved(period.year, period.month, period.status.value),
    )


async def pay_period(
    session: AsyncSession, period_id: uuid.UUID
) -> tuple[schemas.PayrollPeriodPayResult, str]:
    """`POST /payroll/periods/{id}/pay` — ödendi damgası (spec §5).

    Dönem `approved` DEĞİLSE **409**: `draft → paid` para çıkışının onay
    zincirini atlardı (S8). Kapı geçiş tablosudur, burada ikinci bir `if` yoktur.

    Yalnız `approved` satırlar ödenir:

    * **K2** — taşeron satırı `excluded` KALIR ve `paid_net_total`a GİRMEZ;
    * **S4** — `uncomputed` satırın ödenecek tutarı yoktur;
    * onayı geri alınmış (`pending`) satır ödenmez — onaysız para çıkmaz.

    Üçü de SAYIYLA raporlanır. Onaylı görünüp neti `null` olan bir satır
    (T1 invariantına göre imkânsız) TÜM ödemeyi durdurur: bilinmeyen tutar 0
    sayılıp geçilseydi eksik ödeme ancak banka ekstresinden anlaşılırdı
    (NULL-EŞİK kanonu, fail-closed).

    Dış sistem entegrasyonu YOKTUR (spec §1): bu uç bir DAMGADIR, EFT talimatı
    (BY 319) göndermez.
    """
    period = await _lock_period(session, period_id)
    transitions.assert_period_transition(period.status, PayrollPeriodStatus.paid)

    odenen = atlanan_uncomputed = atlanan_excluded = atlanan_onaysiz = 0
    toplam = Decimal("0.00")
    for line in await _locked_period_lines(session, period.id):
        if line.status is PayrollLineStatus.uncomputed:
            atlanan_uncomputed += 1
            continue
        if line.status is PayrollLineStatus.excluded:
            atlanan_excluded += 1
            continue
        if line.status is not PayrollLineStatus.approved:
            atlanan_onaysiz += 1
            continue
        if line.net_amount is None:
            raise ConflictError(guards.PAID_WITHOUT_NET)
        transitions.assert_line_transition(line.status, PayrollLineStatus.paid)
        line.status = PayrollLineStatus.paid
        toplam += line.net_amount
        odenen += 1

    period.status = PayrollPeriodStatus.paid
    period.paid_at = datetime.now(UTC)

    await session.flush()
    return (
        schemas.PayrollPeriodPayResult(
            period_status=period.status,
            paid_at=period.paid_at,
            paid=odenen,
            paid_net_total=toplam,
            skipped_unapproved=atlanan_onaysiz,
            skipped_uncomputed=atlanan_uncomputed,
            skipped_excluded=atlanan_excluded,
        ),
        messages.payroll_period_paid(period.year, period.month, odenen, toplam),
    )
