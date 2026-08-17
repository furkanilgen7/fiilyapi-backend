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
from app.modules.payroll import (
    compute,
    guards,
    income_tax,
    schemas,
    sgk,
    summary,
    transitions,
)
from app.modules.payroll.models import (
    IncomeKind,
    PayrollLine,
    PayrollLineStatus,
    PayrollMinimumWage,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRate,
    PayrollTaxBracket,
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

    `populate_existing` ZORUNLUDUR (EŞİK=KİLİT şartı b): kilit altında okunan
    durum TAZE olmalıdır. Session'ın kimlik haritasında eski bir kopya varsa
    SQLAlchemy onu geri verir ve kilit doğru alınmış olsa bile karar ESKİ durum
    üzerinden verilir — kilidin tek işi budur, sessizce boşa çıkmamalıdır.
    """
    period = (
        await session.execute(
            select(PayrollPeriod)
            .where(PayrollPeriod.id == period_id)
            .with_for_update()
            .execution_options(populate_existing=True)
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


# --- IK3-GV: dilimli vergi bağlamı ----------------------------------------
#
# 🔴 KÜMÜLATİF MATRAH SNAPSHOT'TIR, `SUM` DEĞİLDİR (K1). Gerekçe modelde
# (`models.py` `PayrollLine`) yazılıdır ve ÖLÇÜLMÜŞTÜR: `create_period` ay
# sırasını hiç zorlamaz, onaylanan dönem geri alınamaz (`transitions.py` tek
# yönlü, DELETE ucu yok) → `SUM` yolu ödenmiş bir dönemin vergisini kalıcı ve
# SESSİZ biçimde yanlış bırakırdı.
#
# Zincir şöyle kurulur: bir ayın tabanı, **daha erken bir ayın satırına
# YAZILMIŞ** `cumulative_tax_base`tir. Böylece Temmuz onaylandıktan sonra Mart
# açılıp hesaplansa bile Temmuz'un vergisi DEĞİŞMEZ (KK-8: geçmiş dönemler
# donmuş kalır) ve Mart kendi doğru tabanından hesaplanır.


async def _tax_brackets(
    session: AsyncSession, year: int
) -> tuple[income_tax.TaxBracket, ...] | None:
    """Yılın ÜCRET tarifesi — satırı yoksa **`None`** (fail-closed, K3).

    Yalnız `is_active` satırlar okunur (`payroll_rates` kuralıyla aynı: eski
    yılın tarifesi silinmez, pasifleştirilir).

    🔴 Set BURADA doğrulanmaz; doğrulama `income_tax.normalize_brackets`tadır ve
    `compute` onu bir istisnayla karşılayıp satırı `uncomputed`a düşürür. Burada
    doğrulansaydı bozuk bir set TÜM dönemi 500'e düşürür, tek bir tipin satırı
    yüzünden bordronun tamamı hesaplanamaz olurdu.
    """
    rows = (
        (
            await session.execute(
                select(PayrollTaxBracket).where(
                    PayrollTaxBracket.year == year,
                    PayrollTaxBracket.income_kind == IncomeKind.wage,
                    PayrollTaxBracket.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    return tuple(
        income_tax.TaxBracket(
            ordinal=row.ordinal, upper_bound=row.upper_bound, rate_pct=row.rate_pct
        )
        for row in rows
    )


async def _minimum_wage_gross(session: AsyncSession, year: int) -> Decimal | None:
    """Yılın BRÜT asgari ücreti — satırı yoksa **`None`** (fail-closed, KK-7).

    İstisnayı 0 saymak asgari ücretliden ayda ~4.500 TL fazla kesmek olurdu.
    """
    return (
        await session.execute(
            select(PayrollMinimumWage.gross_amount).where(
                PayrollMinimumWage.year == year, PayrollMinimumWage.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()


async def _prior_cumulative_bases(
    session: AsyncSession, year: int, month: int
) -> dict[uuid.UUID, Decimal]:
    """Personel başına, AYNI YILIN daha erken bir ayına YAZILMIŞ son kümülatif.

    🔴 `SUM(tax_base_amount)` DEĞİL: en yakın önceki ayın **snapshot**ı okunur
    (K1). Aradaki bir ay eksikse ya da hesaplanmamışsa taban o eksikliği
    sessizce yutmaz — eksik ay `missing_prior_period_count` sayacında GÖRÜNÜR
    (K4). Fark ölçüldü: `SUM` yolunda sonradan açılan bir ay, ÖNCEDEN ONAYLANMIŞ
    sonraki ayların tabanını geriye dönük değiştirirdi ve o aylar
    düzeltilemezdi.

    `DISTINCT ON (personnel_id) … ORDER BY personnel_id, month DESC` PostgreSQL
    özelliğidir ve N+1'i önler: 48 kişilik bir dönemde tek sorgu koşar.
    """
    rows = await session.execute(
        select(PayrollLine.personnel_id, PayrollLine.cumulative_tax_base)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.payroll_period_id)
        .where(
            PayrollPeriod.year == year,
            PayrollPeriod.month < month,
            PayrollLine.cumulative_tax_base.is_not(None),
        )
        .distinct(PayrollLine.personnel_id)
        .order_by(PayrollLine.personnel_id, PayrollPeriod.month.desc())
    )
    return {personnel_id: taban for personnel_id, taban in rows.all()}


def _opening_tax_base(person: Personnel, year: int) -> Decimal:
    """K7 devir matrahı — YALNIZ yılı tutuyorsa kullanılır (fail-closed).

    Kolon AÇIKTIR ama hiçbir uç onu DOLDURMAZ (GV GT 311 md.21/5: devir
    çalışanın talebine bağlıdır, otomatik değildir), varsayılan 0'dır ve
    bugünkü davranış değişmez. Yıl niteleyicisi `NULL` ya da farklıysa devir
    YOK sayılır: aksi hâlde 2026'da girilen bir devir 2027'de de uygulanır ve
    "31 Aralık → 1 Ocak sıfırlanır" kuralını sessizce bozardı.
    """
    if person.opening_tax_base_year != year:
        return Decimal("0.00")
    return person.opening_tax_base


async def _missing_prior_period_count(session: AsyncSession, year: int, month: int) -> int:
    """🔴 K4 — SIRASIZ DÖNEM: fail-closed SAYAÇ, sessiz geçiş YOK.

    Aynı yılın daha erken bir ayı `payroll_periods`ta YOKSA ya da hâlâ `draft`
    ise, o ayın matrahı kümülatife GİRMEMİŞTİR ve bu dönemin vergisi olması
    gerekenden DÜŞÜK çıkar. Sayaç bunu görünür kılar (İK-2'nin
    `unknown_entitlement_personnel` emsali).

    🔴 **409 ile REDDEDİLMEZ:** yıl ortasında sisteme geçişi imkânsız kılardı
    (Ağustos'ta başlayan bir şirket Ocak-Temmuz'u açmak zorunda kalırdı).
    🔴 **SESSİZ DE GEÇİLMEZ:** "aynı yeşil iki anlam taşır" — doğru sırayla
    hesaplanmış bir dönem ile sırasız hesaplanmış bir dönem AYIRT EDİLEBİLİR
    olmalıdır.
    """
    if month <= 1:
        return 0
    hazir = set(
        (
            await session.execute(
                select(PayrollPeriod.month).where(
                    PayrollPeriod.year == year,
                    PayrollPeriod.month < month,
                    PayrollPeriod.status != PayrollPeriodStatus.draft,
                )
            )
        )
        .scalars()
        .all()
    )
    return len([ay for ay in range(1, month) if ay not in hazir])


async def _tax_context_for_line(
    session: AsyncSession, period: PayrollPeriod, person: Personnel
) -> compute.TaxContext:
    """TEK bir satır için vergi bağlamı — override yolunun (K3) girdisi.

    `compute_period`in toplu okumalarının tek kişilik eşidir ve AYNI
    kaynaklardan besleneceği için iki yol aynı girdide aynı sayıyı üretir
    (T4 kabul şartı). Toplu yolla tek fonksiyonda birleştirilmedi çünkü toplu
    yol N+1'den kaçınmak için `DISTINCT ON` kullanır; burada tek kişi vardır ve
    aynı sorgunun sözlüğünden okunur.
    """
    prior = await _prior_cumulative_bases(session, period.year, period.month)
    return compute.TaxContext(
        month=period.month,
        prior_cumulative_base=prior.get(person.id, _opening_tax_base(person, period.year)),
        brackets=await _tax_brackets(session, period.year),
        minimum_wage_gross=await _minimum_wage_gross(session, period.year),
    )


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

    Kaydı olmayan kişi sözlükte BULUNMAZ ve çağıran 0 sayar; ama o 0'ın anlamı
    `_personnel_with_timesheet_records` ile belirlenir: kaydı hiç yoksa sayı
    BİLİNMİYOR demektir (fail-closed), kaydı varken 0 çıkmışsa (izin/tatil ayı)
    sayı GERÇEKTİR. İki durum burada karıştırılmaz.
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


async def _personnel_with_timesheet_records(
    session: AsyncSession, year: int, month: int
) -> set[uuid.UUID]:
    """🔴 Dönemde HERHANGİ bir puantaj hücresi olan personel (YÖNETİM KARARI T4b).

    `_man_day_counts`ten AYRI bir sorgudur ve ayrı olması ZORUNLUDUR: orası
    `MAN_DAY_CODES` süzer, burası **kod ayrımı YAPMAZ**. Tek sorguya
    indirgenseydi izin/tatil kodlu bir ay ile hiç girilmemiş bir ay aynı sonucu
    (0) verir, ikisi ayırt edilemezdi — birinde gün 0 GERÇEKTİR, ötekinde
    BİLİNMEZ.

    Pencere gün sayımıyla AYNIDIR (`month_bounds`): geçen ayın kaydı bu ayın
    eksik verisini kapatsaydı, işten geçen ay ayrılmış birine maaş hesaplanırdı.
    """
    ilk, son = month_bounds(year, month)
    rows = await session.execute(
        select(TimesheetEntry.personnel_id)
        .where(TimesheetEntry.work_date >= ilk, TimesheetEntry.work_date <= son)
        .distinct()
    )
    return set(rows.scalars().all())


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
    # IK3-GV K1 — vergi snapshot'ı satırla BİRLİKTE yazılır: ayrı yazılsaydı
    # yarım dolu bir satır ("matrahı var, vergisi yok") DB'ye düşebilirdi.
    line.tax_base_amount = hesap.tax_base_amount
    line.cumulative_tax_base = hesap.cumulative_tax_base
    line.income_tax_amount = hesap.income_tax_amount
    line.status = hesap.status
    line.excluded_reason = hesap.excluded_reason


def _promote_period_after_compute(period: PayrollPeriod, lines: list[PayrollLine]) -> None:
    """🔴 T6 YÖNETİM KARARI — hesaplanan dönem KENDİLİĞİNDEN "onay bekliyor" olur.

    BY 63 banner'ı "Temmuz 2026 bordrosu onay bekliyor" yazar: mockup'ta hesap
    ile onay arasında bir "onaya gönder" tıkı YOKTUR. Kullanıcının tek tıkı
    BY 56 "Ödemeyi Onayla"dır (`pending_approval → approved`). Tetikleyici
    `approve_period`in İLK çağrısı olsaydı aynı düğmeye iki kez basmak gerekir,
    ilk basış kullanıcıya hiçbir şey yapmamış gibi görünürdü.

    **Geçiş KÜMESİ değişmedi (S8).** Değişen yalnız `draft → pending_approval`
    çiftinin tetikleyicisidir; geçiş yine `transitions.assert_period_transition`
    kapısından geçer — durum elle atanıp tablo ATLANMAZ, yoksa zincirin şekli
    ikinci bir yerde yaşamaya başlardı.

    **Boş dönem onaya DÜŞMEZ:** hesaplanabilir (`pending`) tek satır bile yoksa
    dönem `draft` KALIR. Düşseydi kullanıcı onaylayacak satırı olmayan bir
    dönemi `approved` yapabilir ve `compute` kapısı (S5) o ayın üzerine
    kapanırdı — geri dönüşü olmayan bir boş onay.

    Çağıran `compute_period`in KİLİDİ altındadır (EŞİK = KİLİT): durum yazımı
    `_lock_period`in aldığı `FOR UPDATE` penceresinin içindedir.
    """
    if period.status is not PayrollPeriodStatus.draft:
        return
    if not any(line.status is PayrollLineStatus.pending for line in lines):
        return
    transitions.assert_period_transition(period.status, PayrollPeriodStatus.pending_approval)
    period.status = PayrollPeriodStatus.pending_approval


async def compute_period(session: AsyncSession, period_id: uuid.UUID) -> PayrollComputeResult:
    """Dönemin satırlarını puantaj + ücret + oranlardan ÜRETİR/GÜNCELLER.

    Korunanlar (ikisi de AYRI sayılır, sessiz atlama yok):

    * `is_overridden` satır — kullanıcının düzeltmesi (K3/S6) ezilmez;
    * `approved`/`paid` satır — ödeme izi (S5) bozulmaz.

    Dönem `approved`/`paid` ise hiç başlanmaz: **409**.

    En az bir ödenebilir (`pending`) satır çıktıysa dönem `pending_approval`a
    ilerler — gerekçe `_promote_period_after_compute`tedir (T6).
    """
    period = await _lock_period(session, period_id)
    if period.status in LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED)

    rates = await rates_by_source(session, period.year)
    man_days = await _man_day_counts(session, period.year, period.month)
    kayitli = await _personnel_with_timesheet_records(session, period.year, period.month)
    existing = await _existing_lines(session, period.id)
    # IK3-GV: tarife/asgari ücret DÖNEM BAŞINA BİR KEZ, kümülatif tabanlar TEK
    # sorguda okunur — kişi başına sorgu açılsaydı 48 kişilik bir dönem N+1
    # üretirdi. Hepsi `_lock_period`in `FOR UPDATE` penceresinin İÇİNDEDİR
    # (EŞİK = KİLİT): eşzamanlı bir `compute` aynı tabanı okuyup iki kez
    # yazamaz.
    brackets = await _tax_brackets(session, period.year)
    minimum_wage = await _minimum_wage_gross(session, period.year)
    prior_bases = await _prior_cumulative_bases(session, period.year, period.month)
    missing_prior = await _missing_prior_period_count(session, period.year, period.month)

    created = updated = skipped_overridden = skipped_approved = 0
    #: Bu koşuda ÜRETİLEN ya da KORUNAN satırlar — dönem ilerletmesinin tabanı.
    #: Kapsam dışına düşmüş kişilerin eski satırları (modül notundaki bilinçli
    #: sınır) burada YOKTUR: `compute` onlara artık dokunmuyor, o hâlde "bu
    #: hesap ödenebilir bir şey üretti mi" sorusuna da cevap veremezler.
    dokunulan: list[PayrollLine] = []
    for person in await _payroll_personnel(session):
        line = existing.get(person.id)
        if line is not None and line.is_overridden:
            skipped_overridden += 1
            dokunulan.append(line)
            continue
        if line is not None and line.status in LOCKED_LINE_STATUSES:
            skipped_approved += 1
            dokunulan.append(line)
            continue

        hesap = compute.compute_line(
            personnel_source=person.source,
            wage_type=person.wage_type,
            wage_amount=person.wage_amount,
            payment_method=person.payment_method,
            man_days=man_days.get(person.id, 0),
            has_timesheet_records=person.id in kayitli,
            rate=rates.get(person.source),
            tax=compute.TaxContext(
                month=period.month,
                prior_cumulative_base=prior_bases.get(
                    person.id, _opening_tax_base(person, period.year)
                ),
                brackets=brackets,
                minimum_wage_gross=minimum_wage,
            ),
        )
        if line is None:
            line = PayrollLine(payroll_period_id=period.id, personnel_id=person.id)
            session.add(line)
            created += 1
        else:
            updated += 1
        _apply(line, person.source, hesap)
        dokunulan.append(line)

    _promote_period_after_compute(period, dokunulan)

    await session.flush()
    return PayrollComputeResult(
        created=created,
        updated=updated,
        skipped_overridden=skipped_overridden,
        skipped_approved=skipped_approved,
        missing_prior_period_count=missing_prior,
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


#: Ödeme TAKVİMİNİ donduran dönem durumları (T4b). Bugün `LOCKED_PERIOD_STATUSES`
#: ile aynı ikiliyi taşır ama ona BAĞLANMAZ ve bu bilinçlidir: o küme "yeniden
#: HESAP" kapısıdır, bu küme "ödeme TARİHİ" kapısı. Takma ad verilseydi birinin
#: yarın gevşetilmesi ötekini sessizce sürükler ve ödenmiş bir bordronun tarihi
#: kimse istemeden yazılabilir hâle gelirdi.
SCHEDULE_LOCKED_PERIOD_STATUSES = frozenset(
    {PayrollPeriodStatus.approved, PayrollPeriodStatus.paid}
)


async def update_period(
    session: AsyncSession, period_id: uuid.UUID, data: schemas.PayrollPeriodUpdate
) -> tuple[PayrollPeriod, str]:
    """`PATCH /payroll/periods/{id}` — ödeme takvimi (BY 63) düzeltmesi.

    🔴 **EŞİK = KİLİT (WORKFLOW §4):** dönem satırı `FOR UPDATE` ile ve DURUM
    DENETİMİNDEN ÖNCE okunur, sıra tüm uçlardaki gibi dönem → satır (burada
    satır tarafı yoktur). Kilit denetimden sonra alınsaydı eşzamanlı bir
    `approve` ile bu PATCH aynı `draft` durumunu okur, dönem onaylanırken tarihi
    de kayardı.

    Yalnız `draft` ve `pending_approval` yazılabilir; `approved`/`paid` **409**
    (gerekçe `guards.PERIOD_LOCKED_FOR_SCHEDULE`).
    """
    period = await _lock_period(session, period_id)
    if period.status in SCHEDULE_LOCKED_PERIOD_STATUSES:
        raise ConflictError(guards.PERIOD_LOCKED_FOR_SCHEDULE)

    period.payment_due_date = data.payment_due_date
    await session.flush()
    return period, messages.payroll_period_updated(
        period.year, period.month, period.payment_due_date
    )


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
        tax_base_amount=line.tax_base_amount,
        cumulative_tax_base=line.cumulative_tax_base,
        income_tax_amount=line.income_tax_amount,
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
            select(PayrollLine)
            .where(PayrollLine.id == line_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError(guards.LINE_MISSING)
    return period, line


async def _locked_period_lines(session: AsyncSession, period_id: uuid.UUID) -> list[PayrollLine]:
    """Dönemin TÜM satırlarını `FOR UPDATE` ile okur (toplu onay + ödeme).

    Sıra `id`ye göre SABİTTİR: iki toplu işlem satırları farklı sıralarda
    kilitleseydi ikisi birbirinin ortasında sıkışıp deadlock'a düşerdi.
    Dönem kilidi zaten alınmış durumdadır (sıra dönem → satır, WORKFLOW §4/d);
    satır kilidi savunmanın YERELLİĞİDİR — yarın dönemi kilitlemeyen ikinci bir
    yol eklenirse koruma burada durursa ayakta kalır.
    """
    return list(
        (
            await session.execute(
                select(PayrollLine)
                .where(PayrollLine.payroll_period_id == period_id)
                .order_by(PayrollLine.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


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

    🔴 **IK3-GV — `deduction_and_net`in İKİNCİ ÇAĞIRANI BURASIDIR.** Vergi
    bağlamı (`TaxContext`) otomatik yolla AYNI yardımcıdan kurulur
    (`_tax_context_for_line`): kümülatif taban aynı snapshot zincirinden, tarife
    ve asgari ücret aynı yıldan gelir. İkinci bir bağlam kurulsaydı elle
    düzeltilen satır ile otomatik satır aynı girdide FARKLI vergi üretirdi.

    Dilimli rejimde tarife/asgari ücret satırı yoksa yine **422**dir (K3
    fail-closed): 0 vergiyle "düzeltilmiş" bir satır yazmak, kullanıcının elle
    girdiği brütü vergisiz ödemek olurdu.
    """
    rate = (await rates_by_source(session, period.year)).get(line.personnel_source)
    if rate is None:
        raise PayrollValidationError(guards.RATE_MISSING)

    person = (
        await session.execute(select(Personnel).where(Personnel.id == line.personnel_id))
    ).scalar_one()

    tax = await _tax_context_for_line(session, period, person)
    sonuc = compute.deduction_and_net(gross_amount, rate, tax)
    if sonuc is None:
        raise PayrollValidationError(guards.TAX_BRACKETS_MISSING)

    line.previous_gross_amount = line.gross_amount
    line.is_overridden = True
    line.overridden_by_id = actor_id
    line.overridden_at = datetime.now(UTC)

    kesintiler, net = sonuc
    line.gross_amount = gross_amount
    line.deduction_amount = kesintiler.total
    line.net_amount = net
    line.tax_base_amount = kesintiler.tax_base
    line.cumulative_tax_base = kesintiler.cumulative_tax_base
    line.income_tax_amount = kesintiler.income_tax
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
    full_name = await _full_name(session, line.personnel_id)
    return _line_response(line, full_name), messages.payroll_line_updated(
        full_name, period.year, period.month
    )


async def _full_name(session: AsyncSession, personnel_id: uuid.UUID) -> str:
    return (
        await session.execute(select(Personnel.full_name).where(Personnel.id == personnel_id))
    ).scalar_one()


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
    session: AsyncSession, actor_id: uuid.UUID, period_id: uuid.UUID
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
    """
    period = await _lock_period(session, period_id)
    hedef = transitions.next_period_step(period.status)
    if hedef is None or hedef is PayrollPeriodStatus.paid:
        raise ConflictError(guards.PERIOD_NOT_APPROVABLE)
    transitions.assert_period_transition(period.status, hedef)

    onaylanan = atlanan_uncomputed = atlanan_excluded = atlanan_onayli = 0
    for line in await _locked_period_lines(session, period.id):
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
        period.approved_by_id = actor_id
        period.approved_at = datetime.now(UTC)

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


# --- T5: SGK bildirimi + oran tablosu + Excel ------------------------------
#
# ## SGK özeti neden `summary.py`de DEĞİL de `sgk.py`de?
#
# İkisi FARKLI SORULARA cevap verir ve tabanları da farklıdır: BY kartları
# ÖDEME ile MALİYETİ ayırır, SGK ekranı ise BİLDİRİM tabanını kullanır (taşeron
# DAHİL, oran seti olmayan satır HARİÇ). Tek fonksiyona sıkıştırılsaydı bir
# ekranın kuralını değiştirmek ötekini sessizce bozardı.
#
# ## Excel ikinci bir okuma yolu AÇMAZ
#
# `GET .../export` dönem detayını `get_period_detail` ile — ekran ucuyla AYNI
# çağrıdan — alır ve yalnızca biçimlendirir. İkinci bir sorgu yazılsaydı dosya
# ile ekran zamanla ayrışır ve hangisinin doğru olduğu tartışılırdı.


async def sgk_summary(
    session: AsyncSession, period_id: uuid.UUID
) -> schemas.PayrollSgkSummaryResponse:
    """`GET /payroll/periods/{id}/sgk-summary` — SGK **55-95** (spec §5).

    Görünmeyen dönem var olmayanla AYNI 404'ü alır. Okuma ucudur: kilit ALMAZ
    (yazma yollarının aksine) ve denetim YAZMAZ.

    🔴 Hesabın tamamı `sgk.py`dedir ve o da `compute.rate_share`e dayanır —
    burada tek bir çarpma bile yapılmaz.
    """
    period = await get_period(session, period_id)
    lines = [line for line, _ in await _lines_with_names(session, [period.id])]
    ozet = sgk.build_sgk_summary(lines, await rates_by_source(session, period.year))
    return schemas.PayrollSgkSummaryResponse(
        period_id=period.id,
        year=period.year,
        month=period.month,
        sgk_submitted_at=period.sgk_submitted_at,
        **vars(ozet),
    )


async def submit_sgk(
    session: AsyncSession, period_id: uuid.UUID
) -> tuple[schemas.PayrollSgkSubmitResult, str]:
    """`POST /payroll/periods/{id}/sgk-submit` — YALNIZ `sgk_submitted_at` damgası.

    * **Dış sistem entegrasyonu YOKTUR** (spec §1): ne HTTP isteği, ne kuyruk,
      ne dosya gönderimi. SGK 44'ün düğmesi bir ELLE İŞARETLEMEDİR.
    * **Tekrar damgalama 409** (idempotent DEĞİL): damga bir OLAYIN zamanıdır ve
      SGK 46'daki son bildirim tarihiyle karşılaştırılır. Sessizce yeniden
      yazılsaydı geç kalınmış bir bildirim ikinci bir tıklamayla zamanında
      yapılmış gibi görünürdü. `/pay`in "ikinci ödeme 409" kuralıyla aynı aile.
    * **Dönem DURUMU ön koşul DEĞİLDİR** ve bu bir eksiklik değil bir karardır:
      SGK 44-47 banner'ı bildirimin beklediğini söylerken BY 61 aynı dönemin
      bordrosunun HÂLÂ onay beklediğini yazar — mockup bildirimin ödeme
      onayından ÖNCE yapılabildiğini gösteriyor. Onay şartı koymak mockup'ın
      çizdiği durumu imkânsız kılardı (WORKFLOW §3: icat yasağı).

    🔴 **EŞİK = KİLİT (WORKFLOW §4):** dönem `FOR UPDATE` ile ve DAMGA
    DENETİMİNDEN ÖNCE okunur; sıra tüm uçlardaki gibi dönem → satır (burada
    satır tarafı yoktur). Kilitsiz iki eşzamanlı istek aynı `None` damgayı okur
    ve İKİSİ DE geçerdi.
    """
    period = await _lock_period(session, period_id)
    if period.sgk_submitted_at is not None:
        raise ConflictError(guards.SGK_ALREADY_SUBMITTED)

    period.sgk_submitted_at = datetime.now(UTC)
    await session.flush()
    return (
        schemas.PayrollSgkSubmitResult(
            period_id=period.id, sgk_submitted_at=period.sgk_submitted_at
        ),
        messages.payroll_sgk_submitted(period.year, period.month),
    )


async def list_rates(
    session: AsyncSession, year: int | None = None
) -> schemas.PayrollRateListResponse:
    """`GET /payroll/rates` — oran setleri (K1).

    Pasif setler de DÖNER (`is_active` alanıyla birlikte): geçmiş bir bordronun
    hangi oranla hesaplandığı okunabilir kalmalıdır (models.py). Sıra
    `(yıl azalan, tip)`tir — en yeni yıl başta.
    """
    sorgu = select(PayrollRate)
    if year is not None:
        sorgu = sorgu.where(PayrollRate.year == year)
    rows = list(
        (
            await session.execute(
                sorgu.order_by(PayrollRate.year.desc(), PayrollRate.personnel_source)
            )
        )
        .scalars()
        .all()
    )
    return schemas.PayrollRateListResponse(
        items=[schemas.PayrollRateResponse.model_validate(row) for row in rows], total=len(rows)
    )


async def _year_has_locked_period(session: AsyncSession, year: int) -> bool:
    """O yılda `approved`/`paid` bir dönem var mı? (T5 oran korkuluğu)

    `LOCKED_PERIOD_STATUSES` YENİDEN KULLANILIR ve bu bilinçlidir: "hesabı
    donmuş dönem" tanımı tek yerde durmalıdır — `compute` kapısıyla oran kapısı
    aynı olguyu ölçer.

    🔴 **EŞİK = KİLİT (WORKFLOW §4).** Yılın TÜM dönemleri `FOR UPDATE` ile ve
    DURUM SÜZGECİ OLMADAN okunur. İki ayrıntı da zorunludur:

    * **Süzgeçsiz:** `WHERE status IN (...)` ile kilitlenseydi "hiç onaylı dönem
      yok" hâlinde HİÇBİR satır kilitlenmez, koruma da olmazdı. Eşzamanlı bir
      `approve_period` tam bu anda dönemi onaylayıp commit edebilir ve oran
      yazısı onaylanmış bir dönemin hesabını yine değiştirirdi (TOCTOU).
    * **Sıra:** `approve_period` de aynı dönem satırlarını kilitler ve zincir
      her yerde dönem → satırdır; ters sıra olmadığı için deadlock doğmaz.

    Kilitlenen satır sayısı bir yılda en çok 12'dir (UQ `(year, month)`).
    """
    periods = (
        (
            await session.execute(
                select(PayrollPeriod)
                .where(PayrollPeriod.year == year)
                .order_by(PayrollPeriod.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return any(period.status in LOCKED_PERIOD_STATUSES for period in periods)


async def upsert_rate(
    session: AsyncSession,
    year: int,
    source: WorkerSource,
    data: schemas.PayrollRateUpdate,
) -> tuple[PayrollRate, str]:
    """`PUT /payroll/rates/{year}/{source}` — set açar ya da DEĞİŞTİRİR (K1).

    🔴 **GEÇMİŞ DÖNEM DEĞİŞMEZ (para korkuluğu).** O yılda `approved`/`paid` bir
    dönem varsa yazma **409**dur. Gerekçe: K1 gereği oran satıra KOPYALANMAZ
    (tek gerçek kaynak `payroll_rates`) ve `summary.py`/`sgk.py` işveren tarafını
    dönemin yılına ait CANLI setten türetir; oran değişince onaylanmış dönemin
    raporlanmış toplamları ve SGK bildiriminin TAMAMI geriye dönük değişirdi.

    Kapı GÜNCELLEMEYE değil YILA kapanır: oran satırı olmayan bir tip için YENİ
    set açmak da o tipin satırlarını `unknown_cost_count`tan çıkarıp maliyete
    eklerdi — sonuç aynı şekilde değişirdi.

    Kural bordroyu TIKAMAZ: başka yıl serbesttir (mevzuat değişimi engellenmez)
    ve `draft`/`pending_approval` dönemli yıl da serbesttir.

    PUT TAM SETTİR (`PayrollRateUpdate`): kısmi gönderim yoktur, eksik alan
    sessizce 0 olamaz.
    """
    if await _year_has_locked_period(session, year):
        raise ConflictError(guards.RATES_LOCKED_BY_PERIOD)

    rate = (
        await session.execute(
            select(PayrollRate).where(
                PayrollRate.year == year, PayrollRate.personnel_source == source
            )
        )
    ).scalar_one_or_none()
    if rate is None:
        rate = PayrollRate(year=year, personnel_source=source)
        session.add(rate)

    degerler = data.model_dump()
    for alan, deger in degerler.items():
        setattr(rate, alan, deger)

    await session.flush()
    return rate, messages.payroll_rate_updated(year, source.value, degerler)
