"""Haftalık puantaj ekranının kurulumu (PUAN-SAAT) — mockup `Ekran 5 - Puantaj.dc.html`.

`matrix.py`nin hafta kapsamlı kardeşi: hiçbir şey YAZMAZ, kapsam kararı VERMEZ.

## Neden ay değil hafta?

Mockup'ın tamamı haftalıktır: başlık *"Haftalık giriş · saat bazlı"* (E5 71),
seçici *"13 – 19 Temmuz 2026 · 29. Hafta"* (E5 96-97), düğme *"Haftayı Kaydet"*
(E5 76), ızgara YEDİ sütundur (E5 216-223) ve Normal/FM kolonları (E5 225-227)
**haftalık 45 saat tavanıyla** hesaplanır — o tavan bir ay ızgarasında hesaplanamaz.

## Ay şeridi neden burada?

E5 137-176'daki "27. … 31. Hafta" şeridi ile E5 347-350'deki "Ay Kümülatif
588 saat · 65,3 adam/gün" AYNI ekranın parçasıdır. Ayrı bir uçtan gelseydi ekran
iki isteği birleştirir ve iki farklı ana ait kutular gösterebilirdi. TEK ek
sorgudur (`repository.daily_hours_between`), hafta başına sorgu koşulmaz.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import Personnel
from app.modules.projects.models import Project
from app.modules.sites.models import Section, Site
from app.modules.timesheet import hours as hours_rules
from app.modules.timesheet import repository
from app.modules.timesheet.matrix import DayAccumulator, to_cell
from app.modules.timesheet.models import TimesheetCode
from app.modules.timesheet.schemas import (
    TimesheetCell,
    TimesheetRowTotals,
    TimesheetWeek,
    TimesheetWeekRow,
    TimesheetWeekSummary,
)

_ZERO_HOURS = hours_rules.ZERO_HOURS


class _Row:
    __slots__ = ("personnel", "subcontractor_name", "cells", "daily_hours")

    def __init__(self, personnel: Personnel, subcontractor_name: str | None) -> None:
        self.personnel = personnel
        self.subcontractor_name = subcontractor_name
        self.cells: list[TimesheetCell] = []
        self.daily_hours: list[Decimal] = []


def _to_row(row: _Row) -> TimesheetWeekRow:
    personnel = row.personnel
    return TimesheetWeekRow(
        personnel_id=personnel.id,
        full_name=personnel.full_name,
        trade=personnel.trade,
        source=personnel.source,
        subcontractor_name=row.subcontractor_name,
        cells=row.cells,
        totals=TimesheetRowTotals(**hours_rules.week_totals(row.daily_hours)._asdict()),
    )


def _week_totals_from_rows(rows: list[TimesheetWeekRow]) -> TimesheetRowTotals:
    """Haftalık tfoot (E5 328-330) — satır türevlerinin TOPLAMI.

    🔴 Tüm saatleri tek havuzda toplayıp `week_totals` çağırmak YANLIŞ olurdu:
    45 saatlik tavan KİŞİ BAŞINADIR. Dört kişilik mockup haftasında havuz kuralı
    normal saati 45'te keser (171 yerine 45 verirdi); satır toplamı 45+36+45+45
    = **171** üretir ve tfoot 171 yazar (E5 328).
    """
    return TimesheetRowTotals(
        normal_hours=sum((row.totals.normal_hours for row in rows), _ZERO_HOURS),
        overtime_hours=sum((row.totals.overtime_hours for row in rows), _ZERO_HOURS),
        total_hours=sum((row.totals.total_hours for row in rows), _ZERO_HOURS),
    )


async def _month_strip(
    session: AsyncSession, site: Site, year: int, month: int
) -> tuple[list[TimesheetWeekSummary], Decimal]:
    """Ay içi hafta kutuları + ay toplamı (E5 141-176).

    Ay toplamı, ayla KESİŞEN haftaların toplamıdır — takvim ayının günlerinin
    değil. Mockup'ın kendi aritmetiği budur: `186 + 204 + 198 = 588` (E5 152/162/
    172 → E5 174) ve 27. hafta 29 Haziran'da başlar. Serit ile "Ay Toplamı"
    aynı kapsamdan gelmezse ekranda toplanmayan sayılar görünürdü.
    """
    weeks = repository.weeks_of_month(year, month)
    first, _ = repository.week_bounds(*weeks[0])
    _, last = repository.week_bounds(*weeks[-1])
    daily = await repository.daily_hours_between(session, site.id, first, last)

    summaries: list[TimesheetWeekSummary] = []
    month_total = _ZERO_HOURS
    for iso_year, iso_week in weeks:
        days = repository.week_days(iso_year, iso_week)
        week_total = sum((daily.get(day, _ZERO_HOURS) for day in days), _ZERO_HOURS)
        month_total += week_total
        summaries.append(
            TimesheetWeekSummary(
                iso_year=iso_year,
                iso_week=iso_week,
                start_date=days[0],
                end_date=days[-1],
                total_hours=week_total,
                has_entries=any(day in daily for day in days),
            )
        )
    return summaries, month_total


async def build(
    session: AsyncSession,
    site: Site,
    project: Project,
    section: Section | None,
    *,
    iso_year: int,
    iso_week: int,
) -> TimesheetWeek:
    """Haftalık ekranın tamamını İKİ sorgudan kurar (hücreler + ay şeridi)."""
    rows: dict[uuid.UUID, _Row] = {}
    days = repository.week_days(iso_year, iso_week)
    day_totals = {day: DayAccumulator() for day in days}

    section_id = section.id if section is not None else None
    for entry, personnel, subcontractor_name in await repository.week_rows(
        session, site.id, iso_year=iso_year, iso_week=iso_week, section_id=section_id
    ):
        row = rows.get(personnel.id)
        if row is None:
            row = rows[personnel.id] = _Row(personnel, subcontractor_name)
        row.cells.append(to_cell(entry))
        if entry.hours is not None:
            row.daily_hours.append(entry.hours)
        day_totals[entry.work_date].add(entry)

    week_rows = [_to_row(row) for row in rows.values()]
    totals = _week_totals_from_rows(week_rows)

    # Ay şeridi, haftanın İÇİNDE bulunduğu takvim ayıdır: haftanın PAZARTESİSİ
    # değil, haftanın çoğunluğu değil — mockup'ta seçili hafta (13-19 Temmuz)
    # tamamen Temmuz'dadır ve şerit "Temmuz 2026"dır. Sınır haftasında (29 Haz -
    # 5 Tem) tek bir ay seçmek gerekir; PERŞEMBE kuralı ISO'nun kendi kuralıdır
    # (haftanın ISO yılı perşembesinin yılıdır) ve aynı hafta iki ayrı şeritte
    # görünmesin diye burada da o kullanılır.
    anchor = days[3]
    month_weeks, month_total = await _month_strip(session, site, anchor.year, anchor.month)

    return TimesheetWeek(
        site_id=site.id,
        site_name=site.name,
        project_id=project.id,
        project_name=project.name,
        iso_year=iso_year,
        iso_week=iso_week,
        start_date=days[0],
        end_date=days[-1],
        section_id=section_id,
        section_name=section.name if section is not None else None,
        normal_day_hours=hours_rules.NORMAL_DAY_HOURS,
        weekly_normal_hours=hours_rules.WEEKLY_NORMAL_HOURS,
        worker_count=len(week_rows),
        totals=totals,
        leave_day_count=sum(
            1 for row in week_rows for cell in row.cells if cell.code is TimesheetCode.leave
        ),
        temporary_duty_day_count=sum(
            1
            for row in week_rows
            for cell in row.cells
            if cell.code is TimesheetCode.temporary_duty
        ),
        rows=week_rows,
        day_totals=[total.to_schema(day) for day, total in day_totals.items()],
        month_year=anchor.year,
        month_month=anchor.month,
        month_total_hours=month_total,
        month_man_days=hours_rules.man_days(month_total),
        month_weeks=month_weeks,
    )
