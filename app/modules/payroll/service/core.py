"""Bordronun ORTAK tabani: kilit noktalari, oran okuma, satir yanit govdesi.

Bu dosya paketin EN ALT katmanidir ve paket ICINDEN hicbir seyi ithal etmez —
cember olusamaz. Buradaki adlarin ortak yani "birden fazla ucun ayni sekilde
kullandigi" olmalaridir; bir tanesinin davranisi degisirse T2/T3/T4/T5 hep
birlikte degisir, o yuzden TEK KOPYA burada durur.

🔴 `_lock_period` EŞİK = KİLİT'in serilestirme noktasidir (WORKFLOW §4) ve
kilit SIRASI tum uclarda SABITTIR: donem -> satir. Ters sira bir `compute` ile
bir `PATCH`i karsilikli bekletip deadlock'a dusururdu; bu yuzden `_locked_line`
de once `_lock_period`i cagirir, sonra satiri kilitler.
"""

import calendar
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.payroll import guards, schemas
from app.modules.payroll.models import (
    PayrollLine,
    PayrollLineStatus,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRate,
)
from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource

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


async def _full_name(session: AsyncSession, personnel_id: uuid.UUID) -> str:
    return (
        await session.execute(select(Personnel.full_name).where(Personnel.id == personnel_id))
    ).scalar_one()
