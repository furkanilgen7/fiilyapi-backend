"""Bordro servisi — İK-3 T2 (`compute` akışı) + T3 (dönem/satır uçları).

Hesabın kendisi `compute.py`dedir (saf, DB'siz), toplama `summary.py`de, geçiş
tablosu `transitions.py`de. Bu dosya AKIŞTIR: kimin satırı açılır, gün nereden
okunur, hangi satır KORUNUR, kapı ne zaman kapalıdır. `DomainError` türevleri
`app/core/exception_handlers.py`te HTTP'ye çevrilir — router `try/except`
YAZMAZ.

## Neden gün sayısını burada saymıyoruz da `MAN_DAY_CODES`i import ediyoruz?

Adam-güne hangi kodun sayıldığı PUANTAJIN kanonudur (`timesheet/matrix.py`) ve
mockup'tan gelir (E5 203/210: FM'li gün çalışılmış sayılır · ŞP 245: geçici
görev sayılmaz). Burada yeniden tanımlansaydı bordronun günü ile puantaj
ekranının adam-günü zamanla ayrışır ve kullanıcı iki ekranda iki sayı görürdü.

## EŞİK = KİLİT (WORKFLOW §4, İK-2 dersi)

Serileştirme **dönem satırındadır** ve kilit DURUM DENETİMİNDEN ÖNCE alınır:
iki eşzamanlı `compute` (ya da `compute` + dönem onayı) sırayla koşar. Kilit
denetimden sonra alınsaydı iki istek de "dönem taslak" görüp aynı satırları
iki kez yazmaya çalışır, UQ ihlaliyle biri 500'e düşerdi.

## Bilinçli sınır

Personel bordro kapsamından çıkarsa (pasifleşme/taslağa dönme) MEVCUT satırı
SİLİNMEZ: silinmiş bir satır, o ay gerçekten hesaplanmış bir tutarın izini yok
ederdi. Satır olduğu gibi durur; kapsam dışına çıkan kişiye YENİ satır açılmaz.
"""

import calendar
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    DuplicateError,
    NotFoundError,
    PayrollValidationError,
)
from app.modules.audit import messages
from app.modules.payroll import compute, guards, schemas, summary, transitions
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRate,
)
from app.modules.payroll.schemas import PayrollComputeResult
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource
from app.modules.timesheet.matrix import MAN_DAY_CODES
from app.modules.timesheet.models import TimesheetEntry

#: `compute` kapısını KAPATAN dönem durumları (spec §5).
#: Ödenmiş/onaylanmış bir ayın tutarlarını yeniden hesaplamak, banka çıkışıyla
#: kayıt arasındaki bağı koparırdı.
LOCKED_PERIOD_STATUSES = frozenset({PayrollPeriodStatus.approved, PayrollPeriodStatus.paid})

#: Yeniden hesabın DOKUNMADIĞI satır durumları (S5). `is_overridden` ayrı bir
#: koruma sebebidir (S6) ve ayrı sayılır — ikisinin anlamı farklıdır.
LOCKED_LINE_STATUSES = frozenset({PayrollLineStatus.approved, PayrollLineStatus.paid})

#: İzin anahtarı — TEK KOPYA `guards.PERMISSION_MODULE`dedir (SA emsali); router
#: `service.PERMISSION_MODULE` yazmaya devam eder.
PERMISSION_MODULE = guards.PERMISSION_MODULE


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Ayın ilk ve son günü — TEK tanım.

    `calendar.monthrange` kullanılır: 28/29/30/31 ayrımını elle yazmak, şubatı
    ve artık yılı yanlış hesaplayan klasik bir hata kaynağıdır.
    """
    _, son_gun = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, son_gun)


async def _lock_period(session: AsyncSession, period_id: uuid.UUID) -> PayrollPeriod:
    """Dönemi `FOR UPDATE` ile okur — serileştirme noktası.

    Bulunamayan dönem 404'tür (görünmeyen ile var olmayan AYIRT EDİLEMEZ).
    """
    period = (
        await session.execute(
            select(PayrollPeriod).where(PayrollPeriod.id == period_id).with_for_update()
        )
    ).scalar_one_or_none()
    if period is None:
        raise NotFoundError(guards.PERIOD_MISSING)
    return period


async def rates_by_source(session: AsyncSession, year: int) -> dict[WorkerSource, PayrollRate]:
    """`(dönemin yılı, tip)` oran seti — **yıl DÖNEMİN yılıdır, bugünün değil** (S2).

    Yalnız `is_active` satırlar okunur; pasifleştirilmiş eski set geçmişi
    okunabilir tutmak için SİLİNMEZ ama yeni hesaba GİRMEZ.

    Eksik tip sözlükte HİÇ BULUNMAZ ve `compute_line` onu `rate=None` olarak
    görüp fail-closed davranır (ŞEF KARARI 2) — burada uydurma bir sıfır set
    üretilmez.
    """
    rows = (
        (
            await session.execute(
                select(PayrollRate).where(PayrollRate.year == year, PayrollRate.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return {row.personnel_source: row for row in rows}


async def _payroll_personnel(session: AsyncSession) -> list[Personnel]:
    """Bordroya giren personel — 🔴 ŞEF KARARI 5.

    Yalnız `is_active` ve `is_draft` OLMAYAN kayıtlar (İK-1 yayın kuralı
    emsali): taslak kartın ücreti henüz doğrulanmamıştır, pasif kişi işten
    ayrılmıştır. İkisine de satır açmak ödeme listesine gerçek olmayan kişi
    eklerdi.
    """
    return list(
        (
            await session.execute(
                select(Personnel)
                .where(Personnel.is_active.is_(True), Personnel.is_draft.is_(False))
                .order_by(Personnel.full_name)
            )
        )
        .scalars()
        .all()
    )


async def _man_day_counts(session: AsyncSession, year: int, month: int) -> dict[uuid.UUID, int]:
    """Kişi başına adam-gün — `MAN_DAY_CODES` kanonu (S7).

    Kaydı olmayan kişi sözlükte BULUNMAZ ve çağıran 0 sayar: bu uydurma bir
    değer değil, sayımın gerçek sonucudur (kişi o ay hiç çalışmamıştır). Ücret
    verisi eksik olsaydı S4 yolu devreye girerdi — iki durum karıştırılmaz.
    """
    ilk, son = month_bounds(year, month)
    rows = await session.execute(
        select(TimesheetEntry.personnel_id, func.count())
        .where(
            TimesheetEntry.work_date >= ilk,
            TimesheetEntry.work_date <= son,
            TimesheetEntry.code.in_(MAN_DAY_CODES),
        )
        .group_by(TimesheetEntry.personnel_id)
    )
    return {personnel_id: sayi for personnel_id, sayi in rows.all()}


async def _existing_lines(
    session: AsyncSession, period_id: uuid.UUID
) -> dict[uuid.UUID, PayrollLine]:
    """Dönemin mevcut satırları, personel kimliğiyle anahtarlı.

    UQ `(dönem, personel)` sayesinde anahtar tekildir; ikinci koşu bu sözlük
    üzerinden UPDATE'e döner, INSERT denemez.
    """
    rows = (
        (
            await session.execute(
                select(PayrollLine).where(PayrollLine.payroll_period_id == period_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.personnel_id: row for row in rows}


def _apply(line: PayrollLine, source: WorkerSource, hesap: compute.ComputedLine) -> None:
    """Hesap sonucunu satıra yazar — TÜM alanlar birlikte.

    Alanların bir kısmını yazıp bir kısmını bırakmak yarım dolu satır üretirdi
    (net dolu ama bölüşüm boş) ve T3'teki S3 kapısını sessizce atlatırdı.
    """
    line.personnel_source = source
    line.days = hesap.days
    line.gross_amount = hesap.gross_amount
    line.deduction_amount = hesap.deduction_amount
    line.net_amount = hesap.net_amount
    line.bank_amount = hesap.bank_amount
    line.cash_amount = hesap.cash_amount
    line.status = hesap.status
    line.excluded_reason = hesap.excluded_reason


async def compute_period(session: AsyncSession, period_id: uuid.UUID) -> PayrollComputeResult:
    """Dönemin satırlarını puantaj + ücret + oranlardan ÜRETİR/GÜNCELLER.

    Korunanlar (ikisi de AYRI sayılır, sessiz atlama yok):

    * `is_overridden` satır — kullanıcının düzeltmesi (K3/S6) ezilmez;
    * `approved`/`paid` satır — ödeme izi (S5) bozulmaz.

    Dönem `approved`/`paid` ise hiç başlanmaz: **409**.
    """
    period = await _lock_period(session, period_id)
    if period.status in LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED)

    rates = await rates_by_source(session, period.year)
    man_days = await _man_day_counts(session, period.year, period.month)
    existing = await _existing_lines(session, period.id)

    created = updated = skipped_overridden = skipped_approved = 0
    for person in await _payroll_personnel(session):
        line = existing.get(person.id)
        if line is not None and line.is_overridden:
            skipped_overridden += 1
            continue
        if line is not None and line.status in LOCKED_LINE_STATUSES:
            skipped_approved += 1
            continue

        hesap = compute.compute_line(
            personnel_source=person.source,
            wage_type=person.wage_type,
            wage_amount=person.wage_amount,
            payment_method=person.payment_method,
            man_days=man_days.get(person.id, 0),
            rate=rates.get(person.source),
        )
        if line is None:
            line = PayrollLine(payroll_period_id=period.id, personnel_id=person.id)
            session.add(line)
            created += 1
        else:
            updated += 1
        _apply(line, person.source, hesap)

    await session.flush()
    return PayrollComputeResult(
        created=created,
        updated=updated,
        skipped_overridden=skipped_overridden,
        skipped_approved=skipped_approved,
    )


# --- T3: dönem + satır uçlarının servisi -----------------------------------
#
# ## Kilit SIRASI tüm uçlarda SABİT: dönem → satır
#
# `compute_period` serileştirmesini dönem satırında yapar (yukarıdaki modül
# notu); `update_line` de ÖNCE dönemi, SONRA satırı kilitler. Sıra ters olsaydı
# bir `compute` ile bir `PATCH` birbirini karşılıklı bekleyip deadlock'a düşerdi
# (WORKFLOW §4 EŞİK=KİLİT). Tam eşzamanlılık regresyonu (iki gerçek bağlantı)
# T4'ün işidir; buradaki kural o testin ön koşuludur.
#
# ## `visible_projects` süzgeci YOKTUR
#
# Bordro şirket geneli bir İK varlığıdır (`personnel`/`timesheet` deseni):
# kapsam denetimi `payroll` İZNİDİR, proje erişimi değil. Bir bordro dönemi tek
# bir projeye ait değildir — süzgeç konsaydı aynı ayın toplamı iki kullanıcıda
# iki farklı sayı gösterirdi.

#: BY bölümlerinin EKRAN SIRASI: 124 → 172 → 240 → 268. `general` bordro tipi
#: değildir (spec §4) ama satırı varsa GİZLENMEZ — sona düşer, çünkü görünmeyen
#: bir satır sessizce kaybolmuş demektir.
SECTION_ORDER = (
    WorkerSource.company,
    WorkerSource.subcontractor,
    WorkerSource.freelance,
    WorkerSource.intern,
    WorkerSource.general,
)


async def create_period(
    session: AsyncSession, data: schemas.PayrollPeriodCreate
) -> tuple[PayrollPeriod, str]:
    """Ay açar. Var olan ay → **409** (UQ `(year, month)`).

    Çakışma UQ'ya DÜŞMEDEN önce açık bir SELECT ile yakalanır (`DuplicateError`
    deseni): IntegrityError'ın "Veri bütünlüğü hatası" metni kullanıcıya hangi
    ayın zaten açık olduğunu söylemezdi. UQ ikinci katman olarak KALIR (yarış).
    """
    mevcut = (
        await session.execute(
            select(PayrollPeriod.id).where(
                PayrollPeriod.year == data.year, PayrollPeriod.month == data.month
            )
        )
    ).scalar_one_or_none()
    if mevcut is not None:
        raise DuplicateError(guards.PERIOD_DUPLICATE)

    period = PayrollPeriod(year=data.year, month=data.month, payment_due_date=data.payment_due_date)
    session.add(period)
    await session.flush()
    return period, messages.payroll_period_created(period.year, period.month)


async def get_period(session: AsyncSession, period_id: uuid.UUID) -> PayrollPeriod:
    """Dönemi KİLİTSİZ okur — görünmeyen ile var olmayan AYIRT EDİLEMEZ (404).

    Yazma yollarında kullanılmaz: onlar `_lock_period`ten geçer (EŞİK=KİLİT).
    """
    period = (
        await session.execute(select(PayrollPeriod).where(PayrollPeriod.id == period_id))
    ).scalar_one_or_none()
    if period is None:
        raise NotFoundError(guards.PERIOD_MISSING)
    return period


async def _lines_with_names(
    session: AsyncSession, period_ids: list[uuid.UUID]
) -> list[tuple[PayrollLine, str]]:
    """Satırlar + personel ADI, TEK sorguda (BY 137).

    Ad satır başına ayrı sorgulansaydı 48 kişilik bir dönem 48 sorgu açardı;
    liste ucunda ise sayfa başına 50 dönem × satır sayısı kadar.
    """
    if not period_ids:
        return []
    rows = await session.execute(
        select(PayrollLine, Personnel.full_name)
        .join(Personnel, Personnel.id == PayrollLine.personnel_id)
        .where(PayrollLine.payroll_period_id.in_(period_ids))
        .order_by(Personnel.full_name)
    )
    return [(line, ad) for line, ad in rows.all()]


def _line_response(line: PayrollLine, full_name: str) -> schemas.PayrollLineResponse:
    return schemas.PayrollLineResponse(
        id=line.id,
        personnel_id=line.personnel_id,
        personnel_name=full_name,
        personnel_source=line.personnel_source,
        days=line.days,
        gross_amount=line.gross_amount,
        deduction_amount=line.deduction_amount,
        net_amount=line.net_amount,
        bank_amount=line.bank_amount,
        cash_amount=line.cash_amount,
        status=line.status,
        excluded_reason=line.excluded_reason,
        is_overridden=line.is_overridden,
        overridden_at=line.overridden_at,
        previous_gross_amount=line.previous_gross_amount,
    )


async def get_period_detail(
    session: AsyncSession, period_id: uuid.UUID
) -> schemas.PayrollPeriodDetailResponse:
    """BY ekranının tamamı: künye + dört kart + tip bazında gruplanmış satırlar."""
    period = await get_period(session, period_id)
    lines = await _lines_with_names(session, [period.id])
    ozet = summary.build_period_summary(
        [line for line, _ in lines], await rates_by_source(session, period.year)
    )

    sections = []
    for source in SECTION_ORDER:
        bolum = [_line_response(line, ad) for line, ad in lines if line.personnel_source is source]
        if bolum:
            sections.append(
                schemas.PayrollSectionResponse(
                    personnel_source=source, line_count=len(bolum), lines=bolum
                )
            )

    return schemas.PayrollPeriodDetailResponse(
        id=period.id,
        year=period.year,
        month=period.month,
        status=period.status,
        payment_due_date=period.payment_due_date,
        approved_at=period.approved_at,
        paid_at=period.paid_at,
        sgk_submitted_at=period.sgk_submitted_at,
        summary=schemas.PayrollSummaryResponse.model_validate(ozet),
        sections=sections,
    )


async def list_periods(
    session: AsyncSession, *, limit: int, offset: int
) -> schemas.PayrollPeriodListResponse:
    """BG listesi — en YENİ dönem başta (BG tbody: Temmuz · Haziran · Mayıs).

    Toplamlar SQL'de değil `summary.py`de hesaplanır ve bu bilinçlidir: BG'nin
    "Toplam Maliyet" sütunu ile BY'nin 4. kartı AYNI fonksiyondan geçmelidir
    (spec §7'nin üç kalemli formülü TEK KAYNAKTIR). SQL'de ikinci bir toplam
    yazılsaydı formül iki yerde yaşar, biri güncellenip öteki unutulurdu.
    Sayfa başına en çok 200 dönem okunur (TB3 tavanı) ve satırları TEK sorgu
    getirir — N+1 yoktur.
    """
    total = (await session.execute(select(func.count()).select_from(PayrollPeriod))).scalar_one()
    periods = list(
        (
            await session.execute(
                select(PayrollPeriod)
                .order_by(PayrollPeriod.year.desc(), PayrollPeriod.month.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    lines = await _lines_with_names(session, [p.id for p in periods])
    rates_by_year: dict[int, dict[WorkerSource, PayrollRate]] = {}
    for period in periods:
        if period.year not in rates_by_year:
            rates_by_year[period.year] = await rates_by_source(session, period.year)

    items = []
    for period in periods:
        ozet = summary.build_period_summary(
            [line for line, _ in lines if line.payroll_period_id == period.id],
            rates_by_year[period.year],
        )
        items.append(
            schemas.PayrollPeriodListRow(
                id=period.id,
                year=period.year,
                month=period.month,
                status=period.status,
                payment_due_date=period.payment_due_date,
                paid_at=period.paid_at,
                personnel_count=ozet.line_count,
                gross_total=ozet.gross_total,
                sgk_employer_total=ozet.sgk_employer_total,
                net_total=ozet.net_total,
                total_cost=ozet.total_employer_cost,
            )
        )
    return schemas.PayrollPeriodListResponse(items=items, total=total, limit=limit, offset=offset)


async def _locked_line(
    session: AsyncSession, line_id: uuid.UUID
) -> tuple[PayrollPeriod, PayrollLine]:
    """Dönemi ve satırı SABİT SIRAYLA (dönem → satır) `FOR UPDATE` ile okur.

    İlk okuma (satırın dönemini bulmak) kilitsizdir ve bu güvenlidir: bir satır
    dönem DEĞİŞTİRMEZ (UQ `(dönem, personel)` ve CASCADE bunu zaten varsayar).
    Kilit alındıktan sonra satır YENİDEN okunur — arada silinmiş olabilir.
    """
    period_id = (
        await session.execute(
            select(PayrollLine.payroll_period_id).where(PayrollLine.id == line_id)
        )
    ).scalar_one_or_none()
    if period_id is None:
        raise NotFoundError(guards.LINE_MISSING)

    period = await _lock_period(session, period_id)
    line = (
        await session.execute(
            select(PayrollLine).where(PayrollLine.id == line_id).with_for_update()
        )
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError(guards.LINE_MISSING)
    return period, line


def _assert_line_editable(period: PayrollPeriod, line: PayrollLine) -> None:
    """Üç kapı, bu SIRAYLA — hepsi 409 (durum engeli, yetki değil).

    1. **Dönem** `approved`/`paid` (S5'in dönem tarafı): onaylanmış dönemin
       toplamları raporlanmıştır, içine sonradan satır büyütmek o raporu
       sessizce yalanlardı. Dönem kapısı ÖNCE gelir çünkü daha genel olandır.
    2. **K2 — `excluded` satır:** banka/elden ÖDEMEYE dair alanlardır; taşeron
       bordrodan ödenmez (ödemesi hakediş üzerinden yapılır) ve bölüşümünün
       doldurulabilmesi ödenmeyecek bir satır için ödeme talimatı hazırlanmasını,
       yani ÇİFT ÖDEMEYİ mümkün kılardı. Brüt override'ı da aynı kapıdan döner:
       `transitions.py` `excluded`ı terminal sayar, satır hiçbir hedefe geçemez.
       K2 kapısı S5'ten ÖNCEDİR ki taşeron satırı için AÇIKLAYICI mesaj dönsün —
       taşeron satırı zaten hiçbir zaman `approved` olamaz.
    3. **S5 — `approved`/`paid` satır:** ödeme izi.
    """
    if period.status in LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED_FOR_EDIT)
    if line.status is PayrollLineStatus.excluded:
        raise ConflictError(guards.LINE_EXCLUDED)
    if line.status in LOCKED_LINE_STATUSES:
        raise ConflictError(guards.LINE_LOCKED)


async def _apply_gross_override(
    session: AsyncSession,
    period: PayrollPeriod,
    line: PayrollLine,
    actor_id: uuid.UUID,
    gross_amount: Decimal,
) -> None:
    """K3 — brüt elle değişir, İZ BIRAKIR, kesinti/net/bölüşüm YENİDEN TÜRER.

    Kesinti gövdeden alınmaz ve eski kesinti KORUNMAZ: korunsaydı brütü
    büyütmek neti orantısız şişirirdi. Hesap `compute.deduction_and_net`tir —
    otomatik satırlarla AYNI kural (kopyalanmaz, ÇAĞRILIR).

    Bölüşüm de netten yeniden türer (`compute.split_payment`): eski banka tutarı
    bırakılsaydı satır S3'ü İHLAL EDER durumda DB'ye yazılmış olurdu. Aynı
    gövdede açık bir bölüşüm geldiyse çağıran onu bunun ÜZERİNE yazar ve YENİ
    nete göre doğrular.

    Oran seti yoksa **422** (ŞEF KARARI 2, T2): kesintisi bilinmeyen bir brütten
    net türetmek, kesintiyi 0 saymak demektir.
    """
    rate = (await rates_by_source(session, period.year)).get(line.personnel_source)
    if rate is None:
        raise PayrollValidationError(guards.RATE_MISSING)

    person = (
        await session.execute(select(Personnel).where(Personnel.id == line.personnel_id))
    ).scalar_one()

    line.previous_gross_amount = line.gross_amount
    line.is_overridden = True
    line.overridden_by_id = actor_id
    line.overridden_at = datetime.now(UTC)

    deduction, net = compute.deduction_and_net(gross_amount, rate)
    line.gross_amount = gross_amount
    line.deduction_amount = deduction
    line.net_amount = net
    line.bank_amount, line.cash_amount = compute.split_payment(net, person.payment_method)

    if line.status is PayrollLineStatus.uncomputed:
        # S4'ün çıkış kapısı: elle girilen brüt satırı ödenebilir kılar.
        transitions.assert_line_transition(line.status, PayrollLineStatus.pending)
        line.status = PayrollLineStatus.pending


def _apply_split(line: PayrollLine, bank_amount: Decimal, cash_amount: Decimal) -> None:
    """🔴 S3 — `banka + elden = net`, KURUŞ hassasiyetinde (`Decimal`, asla `float`).

    Doğrulama SUNUCUDADIR ve istemci hesabına GÜVENİLMEZ (spec §6/1): BY
    142-147'de iki ayrı `input` vardır, kullanıcı ikisini bağımsız yazabilir.
    Neti `null` olan satırda bölüşüm TANIMSIZDIR → 422 (S4).
    """
    if line.net_amount is None:
        raise PayrollValidationError(guards.SPLIT_WITHOUT_NET)
    if bank_amount + cash_amount != line.net_amount:
        raise PayrollValidationError(
            guards.split_mismatch(bank_amount, cash_amount, line.net_amount)
        )
    line.bank_amount = bank_amount
    line.cash_amount = cash_amount


async def update_line(
    session: AsyncSession,
    actor_id: uuid.UUID,
    line_id: uuid.UUID,
    data: schemas.PayrollLineUpdate,
) -> tuple[schemas.PayrollLineResponse, str]:
    """`PATCH /payroll/lines/{id}` — K3 override + S3 bölüşümü, TEK atomik işlem.

    Sıra ANLAMLIDIR: önce brüt (neti değiştirir), sonra bölüşüm — bölüşüm YENİ
    nete göre doğrulanır. Ters sırada eski nete göre doğru olan bir bölüşüm
    kabul edilir, ardından brüt onu sessizce ezerdi.

    Aynı brüt yeniden gönderilirse override İZİ YAZILMAZ: değişmeyen bir değer
    için "elle düzeltildi" damgası basmak, S6'nın koruma listesini gerçek
    düzeltmeler dışındaki satırlarla kirletirdi.
    """
    period, line = await _locked_line(session, line_id)
    _assert_line_editable(period, line)

    if data.gross_amount is not None and data.gross_amount != line.gross_amount:
        await _apply_gross_override(session, period, line, actor_id, data.gross_amount)
    if data.bank_amount is not None and data.cash_amount is not None:
        _apply_split(line, data.bank_amount, data.cash_amount)

    await session.flush()
    full_name = (
        await session.execute(select(Personnel.full_name).where(Personnel.id == line.personnel_id))
    ).scalar_one()
    return _line_response(line, full_name), messages.payroll_line_updated(
        full_name, period.year, period.month
    )
