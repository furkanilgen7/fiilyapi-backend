"""Aylık matrisin kurulumu ve TÜREV toplamları — **saat bazlı** (PUAN-SAAT).

Bu dosya `site_diary/summary.py`nin kardeşidir: hiçbir şey YAZMAZ, kapsam kararı
VERMEZ (onu `service.visible_site` verir), yalnız hücreleri ekranın/Excel'in
gördüğü şekle getirir.

## Toplam kuralları

* **Toplam saat = girilmiş `hours` alanlarının toplamı.** Kodlu hücre (izin /
  tatil / geçici görev) saate 0 katar — E5 191'deki "İzin 27 saat" bir SUNUM
  çarpımıdır (3 gün × 9), gerçek bir çalışma saati değildir ve toplamların
  içine KARIŞTIRILMAZ.
* **Adam-gün = `toplam saat ÷ 9`** (E5 349-350: `588 ÷ 9 = 65,3`). 🔴 Bu artık
  bir GÜN SAYISI değil bir TÜREVDİR; tam sayı değildir.
* **Genel adam-gün, satır adam-günlerinin TOPLAMI DEĞİLDİR:** aylık toplam
  saatten bir kez türer. Satır bazında yuvarlanıp toplansaydı ekranın iki yeri
  farklı sayı gösterirdi (yuvarlama hatası birikirdi).
* **`worked_day_count` SAATLİ hücreleri sayar.** Kaç kişinin o gün sahada
  olduğudur; 4 saatlik gün de 1 kişidir — ama adam-güne 4/9 katar.

## Boş dönemde ne dönülür?

Satır listesi BOŞTUR ama gün iskeleti ve sıfır toplamlar DURUR. Matris kişi
ÖNERMEZ: rozet tablodaki satırları sayar, kartoteksin tamamını değil.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import Personnel
from app.modules.projects.models import Project
from app.modules.sites.models import Section, Site
from app.modules.timesheet import hours as hours_rules
from app.modules.timesheet import repository
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from app.modules.timesheet.schemas import (
    TimesheetCell,
    TimesheetDayTotal,
    TimesheetMatrix,
    TimesheetMatrixRow,
)

_ZERO_HOURS = hours_rules.ZERO_HOURS


def worked_day_clause():
    """ "Sahada geçmiş gün" ölçütünün TEK tanımı: hücrede SAAT vardır.

    🔴 Eski `MAN_DAY_CODES` kümesinin yerini alır. Bordro (`payroll`) ve puantaj
    aynı ölçütü kullanmazsa bir kişinin "kaç gün çalıştığı" iki ekranda iki
    farklı sayı olur. Kod taşıyan hücre (izin/tatil/görev) çalışılmış DEĞİLDİR.
    """
    return TimesheetEntry.hours.is_not(None)


class _Row:
    """Bir personelin biriktiricisi. Sözlük EKLEME SIRASINI korur ve sorgu
    `Personnel.full_name` ile sıralı gelir — çıktı da ada göre sıralıdır."""

    __slots__ = ("personnel", "subcontractor_name", "cells", "total_hours")

    def __init__(self, personnel: Personnel, subcontractor_name: str | None) -> None:
        self.personnel = personnel
        self.subcontractor_name = subcontractor_name
        self.cells: list[TimesheetCell] = []
        self.total_hours = _ZERO_HOURS


class DayAccumulator:
    """Bir gün sütununun biriktiricisi (E5 320-326). Haftalık ekran da kullanır."""

    __slots__ = ("total_hours", "worked_day_count", "leave_count", "temporary_duty_count")

    def __init__(self) -> None:
        self.total_hours = _ZERO_HOURS
        self.worked_day_count = 0
        self.leave_count = 0
        self.temporary_duty_count = 0

    def add(self, entry: TimesheetEntry) -> None:
        if entry.hours is not None:
            self.total_hours += entry.hours
            self.worked_day_count += 1
            return
        if entry.code is TimesheetCode.leave:
            self.leave_count += 1
        elif entry.code is TimesheetCode.temporary_duty:
            self.temporary_duty_count += 1

    def to_schema(self, work_date) -> TimesheetDayTotal:
        return TimesheetDayTotal(
            work_date=work_date,
            total_hours=self.total_hours,
            worked_day_count=self.worked_day_count,
            leave_count=self.leave_count,
            temporary_duty_count=self.temporary_duty_count,
        )


def to_cell(entry: TimesheetEntry) -> TimesheetCell:
    return TimesheetCell(
        work_date=entry.work_date,
        hours=entry.hours,
        code=entry.code,
        section_id=entry.section_id,
    )


def _to_row(row: _Row) -> TimesheetMatrixRow:
    personnel = row.personnel
    return TimesheetMatrixRow(
        personnel_id=personnel.id,
        full_name=personnel.full_name,
        trade=personnel.trade,
        source=personnel.source,
        subcontractor_name=row.subcontractor_name,
        total_hours=row.total_hours,
        man_days=hours_rules.man_days(row.total_hours),
        cells=row.cells,
    )


async def build(
    session: AsyncSession,
    site: Site,
    project: Project,
    section: Section | None,
    *,
    year: int,
    month: int,
) -> TimesheetMatrix:
    """Matrisi TEK hücre sorgusundan kurar; satır ya da gün başına sorgu koşmaz."""
    rows: dict[uuid.UUID, _Row] = {}
    day_totals = {day: DayAccumulator() for day in repository.period_days(year, month)}
    total_hours: Decimal = _ZERO_HOURS

    section_id = section.id if section is not None else None
    for entry, personnel, subcontractor_name in await repository.matrix_rows(
        session, site.id, year=year, month=month, section_id=section_id
    ):
        row = rows.get(personnel.id)
        if row is None:
            row = rows[personnel.id] = _Row(personnel, subcontractor_name)
        row.cells.append(to_cell(entry))
        if entry.hours is not None:
            row.total_hours += entry.hours
            total_hours += entry.hours
        day_totals[entry.work_date].add(entry)

    matrix_rows_out = [_to_row(row) for row in rows.values()]
    return TimesheetMatrix(
        site_id=site.id,
        site_name=site.name,
        project_id=project.id,
        project_name=project.name,
        year=year,
        month=month,
        section_id=section_id,
        section_name=section.name if section is not None else None,
        worker_count=len(matrix_rows_out),
        total_hours=total_hours,
        total_man_days=hours_rules.man_days(total_hours),
        rows=matrix_rows_out,
        day_totals=[total.to_schema(day) for day, total in day_totals.items()],
    )
