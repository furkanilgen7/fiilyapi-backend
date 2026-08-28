"""İK-3 T2 — `compute` akisi: kimin satiri acilir, gun nereden okunur, ne KORUNUR.

Hesabin kendisi `compute.py`dedir (saf, DB'siz); burasi AKISTIR. Iki koruma
AYRI AYRI sayilir ve karistirilmaz: `is_overridden` kullanicinin duzeltmesidir
(K3/S6), `approved`/`paid` ise odeme izidir (S5).

`_man_day_counts` ile `_personnel_with_timesheet_records` bilincli olarak IKI
AYRI sorgudur: biri "sahada gecmis gun"u suzer, oteki hic suzmez. Tek sorguya
indirgenseydi izin/tatil kodlu bir ay ile hic girilmemis bir ay ayni sonucu (0)
verir, ikisi ayirt edilemezdi — birinde gun 0 GERCEKTIR, otekinde BILINMEZ.

🔴 **PUAN-SAAT (2026-08-28) — BORDRONUN GUNU SAAT'E DONMEDI, BILINCLI KARAR.**
Puantaj hucresi artik "kod" degil "saat" tasiyor; bu dosyanin tek uyarlamasi
sudur: adam-gun olcutunun ADI degisti (`MAN_DAY_CODES` -> `matrix.worked_day_clause`,
"kodu Ç/FM olan hucre" -> "SAATI olan hucre"), SAYDIGI SEY degismedi. Ayni
satirlar, ayni sayi: goc `worked`/`overtime` hucrelerinin hepsine saat yazar,
kodlu hucreler kodlu kalir.

**Neden `SUM(saat)/9` DEGIL?** Cunku o bir PARA degisikligidir, semasal degil:
canlida 269 adam-gunluk bir ay `SUM(saat)/9` ile 272,3'e cikardi (goc FM saatini
de `hours`a katiyor) ve **hesaplanmamis her donemin brutu sessizce artardi.**
Bordronun saate gecisi (saatlik ucret + FM x1,5) AYRI bir dilimdir ve orada
`PayrollLine.days` tipiyle birlikte ele alinir.

⚠️ **ACIK BORC (rapor: KAPSAM DISI):** yeni ekran YARIM GUN girilmesine izin
veriyor (E5 305 `value="4"`). Bu dosya 4 saatlik gunu de TAM GUN sayar —
yevmiyeli personel icin FAZLA ODEME. Bugun boyle bir veri YOKTUR (eski semada
yarim gun temsil edilemiyordu); PUAN-SAAT-2 gelmeden once ekran yayina girerse
bu bir canli para kusuruna DONUSUR.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.payroll import compute, guards, transitions
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
)
from app.modules.payroll.schemas import PayrollComputeResult
from app.modules.payroll.service.core import (
    LOCKED_LINE_STATUSES,
    LOCKED_PERIOD_STATUSES,
    _lock_period,
    month_bounds,
    rates_by_source,
)
from app.modules.payroll.service.tax_context import (
    _minimum_wage_gross,
    _missing_prior_period_count,
    _opening_tax_base,
    _prior_cumulative_bases,
    _tax_brackets,
)
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource
from app.modules.timesheet.matrix import worked_day_clause
from app.modules.timesheet.models import TimesheetEntry


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
    """Kişi başına adam-gün — `matrix.worked_day_clause` kanonu (S7).

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
            worked_day_clause(),
        )
        .group_by(TimesheetEntry.personnel_id)
    )
    return {personnel_id: sayi for personnel_id, sayi in rows.all()}


async def _personnel_with_timesheet_records(
    session: AsyncSession, year: int, month: int
) -> set[uuid.UUID]:
    """🔴 Dönemde HERHANGİ bir puantaj hücresi olan personel (YÖNETİM KARARI T4b).

    `_man_day_counts`ten AYRI bir sorgudur ve ayrı olması ZORUNLUDUR: orası
    "saati olan hücre"yi süzer, burası **hiç süzmez**. Tek sorguya
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
