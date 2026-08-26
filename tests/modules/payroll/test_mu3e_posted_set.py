"""🔴 MU-3E — FİŞLENEN OLAY KÜMESİ BEKÇİSİ (sahte-yeşilin 8. hâli).

## Ölçtüğü kusur

`post_document` İDEMPOTANDIR: aynı belgeye ikinci kez çağrıldığında sessizce
mevcut fişi döndürür. Bu yüzden *"kaç fiş yazıldı"* diye soran bir test,
fişlenen eylem KÜMESİNE sahte bir üye eklendiğinde **KIRMIZIYA DÖNMEZ** — yeni
üye ya idempotanlık dalına düşer (hiç yazmaz) ya da başka bir belgeye yazar ve
sayı yine "1" kalır.

Çare: **evreni BAĞIMSIZ BİR KAYNAKTAN türet, her olayı TEK TEK koştur, KÜMEYİ
karşılaştır.** Buradaki bağımsız kaynak `payroll.transitions`ın iki
frozenset'idir (`PERIOD_TRANSITIONS` + `LINE_TRANSITIONS`) — geçiş tablosuna
yeni bir çift eklenip burada denenmezse evren iddiası kırmızıya döner.

## Neden İKİ tablo birden

Bordronun İKİ durum makinesi vardır ve fiş yalnız DÖNEM makinesinden doğar.
Yalnız dönem tablosu denenseydi, bir gün SATIR onayından fiş atan bir kod
(48 kişilik bir dönemde 48 fiş!) bu bekçiden geçerdi.

## Beklenen küme TEK ÜYELİDİR

    {"period.pending_approval->approved"}

🔴 Bu kümeye eklenen HER ÜYE bir ÇİFT SAYIMDIR: dönemin tahakkuku bir kez
doğar. `period.approved->paid` (ödeme damgası) buraya girerse aynı bordro hem
tahakkukta hem ödemede gider yazar; `line.*` üyelerinden biri girerse aynı
dönem satır sayısı kadar fişlenir.
"""

import uuid

from sqlalchemy import select

from app.core.errors import ConflictError, PayrollValidationError
from app.modules.accounting.models import JournalEntry
from app.modules.payroll import service, transitions
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
)
from app.modules.payroll.schemas import PayrollLineUpdate


def _donem_olaylari() -> tuple[str, ...]:
    return tuple(
        sorted(
            f"period.{kaynak.value}->{hedef.value}"
            for kaynak, hedef in transitions.PERIOD_TRANSITIONS
        )
    )


def _satir_olaylari() -> tuple[str, ...]:
    return tuple(
        sorted(
            f"line.{kaynak.value}->{hedef.value}" for kaynak, hedef in transitions.LINE_TRANSITIONS
        )
    )


async def _kaynak_damgalari(session) -> set[tuple[object, uuid.UUID]]:
    """Deftere düşmüş TÜM kaynak damgaları.

    🔴 Ürün deposundan (`posting.repository`) GEÇİLMEZ: test, ölçtüğü şeyin
    tanımını ölçtüğü koddan alsaydı o süzgeç bozulduğunda yeşil kalırdı.
    """
    rows = (
        await session.execute(
            select(JournalEntry.source_type, JournalEntry.source_id).where(
                JournalEntry.source_type.is_not(None)
            )
        )
    ).all()
    return {(tur, kimlik) for tur, kimlik in rows}


async def _yeni_donem(db_session, ay: int, durum: PayrollPeriodStatus) -> PayrollPeriod:
    period = PayrollPeriod(year=2026, month=ay, status=durum)
    db_session.add(period)
    await db_session.flush()
    return period


async def _hesaplanmis_donem(db_session, kaydeden, donem, dort_tip) -> None:
    await service.compute_period(db_session, donem.id)


async def _pending_satir(db_session, donem) -> PayrollLine:
    return (
        (
            await db_session.execute(
                select(PayrollLine).where(
                    PayrollLine.payroll_period_id == donem.id,
                    PayrollLine.status == PayrollLineStatus.pending,
                )
            )
        )
        .scalars()
        .first()
    )


async def test_FISLENEN_OLAY_KUMESI_bagimsiz_evrenden_TURETILIR(
    db_session, donem, dort_tip, kaydeden
) -> None:
    """🔴 Evren geçiş TABLOLARINDAN gelir; fişleyen küme TEK ÜYELİ olmalıdır."""
    fisleyen: set[str] = set()
    denenen: list[str] = []

    # --- DÖNEM makinesi -----------------------------------------------------
    await service.compute_period(db_session, donem.id)
    satir = await _pending_satir(db_session, donem)
    assert satir is not None, "kurulum hesaplanabilir satır üretmedi — evren boş koşardı"

    # `draft → pending_approval`: `compute` dönemi zaten oraya taşıdı (T6), bu
    # yüzden çift AYRI bir dönemle denenir.
    bos = await _yeni_donem(db_session, ay=1, durum=PayrollPeriodStatus.draft)
    for olay, cagri in (
        (
            "period.draft->pending_approval",
            lambda: service.approve_period(db_session, kaydeden, bos.id),
        ),
        (
            "period.pending_approval->approved",
            lambda: service.approve_period(db_session, kaydeden, donem.id),
        ),
        ("period.approved->paid", lambda: service.pay_period(db_session, donem.id)),
    ):
        denenen.append(olay)
        once = await _kaynak_damgalari(db_session)
        try:
            await cagri()
        except (ConflictError, PayrollValidationError):
            # Bir geçiş bu kurulumda uygulanamıyorsa da EVRENDE DENENMİŞ sayılır:
            # ölçülen şey "fiş yazdı mı", "başarılı oldu mu" DEĞİL.
            pass
        if await _kaynak_damgalari(db_session) - once:
            fisleyen.add(olay)

    assert sorted(denenen) == sorted(_donem_olaylari()), (
        "evren eksik denendi — `PERIOD_TRANSITIONS` ile denenen olaylar AYRIŞTI: "
        f"denenen={sorted(denenen)} tablo={sorted(_donem_olaylari())}"
    )
    assert fisleyen == {"period.pending_approval->approved"}, (
        "FİŞLENEN OLAY KÜMESİ DEĞİŞTİ. Bu kümeye eklenen her üye bir ÇİFT "
        f"SAYIMDIR: dönemin tahakkuku BİR KEZ doğar. fişleyen={sorted(fisleyen)}"
    )


async def test_SATIR_GECISLERININ_HICBIRI_fis_YAZMAZ(db_session, donem, dort_tip, kaydeden) -> None:
    """🔴 Satır makinesi fiş DOĞURMAZ — 48 kişilik dönem 48 fiş üretmemelidir.

    Evren `LINE_TRANSITIONS`tan türetilir ve DÖRDÜ DE sürülür. `uncomputed →
    pending` çifti K3 override'ının çıkışıdır (`update_line`); `approved →
    paid`in TEK yolu `pay_period`tir (ayrı bir satır ucu YOKTUR).

    🔴 **Dönemin `approved`a taşınması ÖLÇÜM PENCERESİNİN DIŞINDADIR.** O adım
    bir DÖNEM olayıdır ve fiş YAZAR; ölçümün içinde kalsaydı bu test kendi
    kurulumunun yazdığı fişi `line.approved->paid`e YAZAR ve sahte bir kırmızı
    üretirdi (ilk koşuda tam olarak bu oldu).
    """
    await service.compute_period(db_session, donem.id)
    fisleyen: set[str] = set()
    denenen: list[str] = []

    async def olc(olay: str, cagri) -> None:
        denenen.append(olay)
        once = await _kaynak_damgalari(db_session)
        try:
            await cagri()
        except (ConflictError, PayrollValidationError):
            # Geçiş bu kurulumda uygulanamasa da EVRENDE DENENMİŞ sayılır:
            # ölçülen şey "fiş yazdı mı", "başarılı oldu mu" DEĞİL.
            pass
        if await _kaynak_damgalari(db_session) - once:
            fisleyen.add(olay)

    uncomputed = (
        (
            await db_session.execute(
                select(PayrollLine).where(
                    PayrollLine.payroll_period_id == donem.id,
                    PayrollLine.status == PayrollLineStatus.uncomputed,
                )
            )
        )
        .scalars()
        .first()
    )
    assert uncomputed is not None, "kurulumda `uncomputed` satır YOK — evren eksik koşar"
    pending = await _pending_satir(db_session, donem)
    assert pending is not None

    await olc(
        "line.uncomputed->pending",
        lambda: service.update_line(
            db_session, kaydeden.id, uncomputed.id, PayrollLineUpdate(gross_amount="5000.00")
        ),
    )
    await olc("line.pending->approved", lambda: service.approve_line(db_session, pending.id))
    await olc("line.approved->pending", lambda: service.reject_line(db_session, pending.id))

    # --- ÖLÇÜM DIŞI KURULUM: dönemi `approved`a taşı (DÖNEM olayı, fiş yazar).
    while donem.status is not PayrollPeriodStatus.approved:
        await service.approve_period(db_session, kaydeden, donem.id)

    await olc("line.approved->paid", lambda: service.pay_period(db_session, donem.id))

    assert sorted(denenen) == sorted(_satir_olaylari()), (
        "evren eksik denendi — `LINE_TRANSITIONS` ile denenen olaylar AYRIŞTI: "
        f"denenen={sorted(denenen)} tablo={sorted(_satir_olaylari())}"
    )
    assert fisleyen == set(), (
        f"SATIR geçişinden fiş doğdu: {sorted(fisleyen)} — bir dönem satır sayısı "
        "kadar fişlenir ve tahakkuk N KEZ yazılır"
    )


async def test_HER_ONAYLI_DONEMIN_canli_fisi_VARDIR(db_session, donem, dort_tip, kaydeden) -> None:
    """Ters yön: fişlenmiş dönem kümesi == `approved`/`paid` dönem kümesi.

    Bağımsız kaynak `payroll_periods` TABLOSUNUN KENDİSİDİR. Yukarıdaki bekçi
    "fazladan fiş" hâlini, bu "EKSİK fiş" hâlini yakalar.
    """
    from app.modules.accounting.models import JournalSourceType

    await service.compute_period(db_session, donem.id)
    await service.approve_period(db_session, kaydeden, donem.id)
    # İkinci bir dönem BİLEREK `draft` bırakılır: kümeler kendiliğinden eşit
    # olsaydı iddia hiçbir şey ölçmezdi.
    await _yeni_donem(db_session, ay=2, durum=PayrollPeriodStatus.draft)

    fislenmis_olmali = set(
        (
            await db_session.execute(
                select(PayrollPeriod.id).where(
                    PayrollPeriod.status.in_(
                        [PayrollPeriodStatus.approved, PayrollPeriodStatus.paid]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    fislenen = set(
        (
            await db_session.execute(
                select(JournalEntry.source_id).where(
                    JournalEntry.source_type == JournalSourceType.payroll_period
                )
            )
        )
        .scalars()
        .all()
    )

    assert fislenmis_olmali, "kurulumda onaylı dönem YOK — bekçi hiçbir şeyi ölçmüyor"
    assert fislenen == fislenmis_olmali, (
        f"FİŞSİZ onaylı dönem: {sorted(fislenmis_olmali - fislenen)} · "
        f"onaysız dönemin fişi: {sorted(fislenen - fislenmis_olmali)}"
    )
