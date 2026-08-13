"""Bordro servisi — İK-3 T2: `compute` akışı.

Hesabın kendisi `compute.py`dedir (saf, DB'siz). Bu dosya AKIŞTIR: kimin satırı
açılır, gün nereden okunur, hangi satır KORUNUR, kapı ne zaman kapalıdır.
Router T3'te açılır; buradaki `DomainError` türevleri orada HTTP'ye çevrilir.

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
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.payroll import compute, guards
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


async def _rates_by_source(session: AsyncSession, year: int) -> dict[WorkerSource, PayrollRate]:
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

    rates = await _rates_by_source(session, period.year)
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
