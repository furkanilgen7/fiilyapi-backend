"""Puantaj matrisinin kurulumu ve TÜREV toplamları (spec §3) — mockup ŞP + E5.

Bu dosya `site_diary/summary.py`nin kardeşidir: hiçbir şey YAZMAZ, kapsam kararı
VERMEZ (onu `service.visible_site` verir), yalnız hücreleri ekranın gördüğü
şekle getirir.

## Toplam kuralları ve mockup gerekçeleri

* **Adam-gün = `worked` + `overtime`** — E5 122'de Mehmet'in 6. günü FM'dir,
  diğer üçü Ç'dir ve E5 203'te o sütunun toplamı **4**'tür: FM'li gün çalışılmış
  sayılır. Aynısı E5 149 (Ali'nin FM'i) → E5 210 "4".
* **`temporary_duty` adam-güne GİRMEZ** — ŞP 245'te 13. sütun **"3G"**dir: o gün
  dört kişinin dördü de kayıtlıdır (Hasan `G`, ŞP 203) ama sayı 3'tür. `G` sayıya
  katılmaz, ayrı işaretlenir.
* **`+` yalnız bir işarettir** — ŞP 237 "4+": sayı (4) değişmez, sütunda en az bir
  FM olduğu bildirilir.
* **`İ` ve `T` sayılmaz** — ŞP 235-236'da tatil sütunlarının toplamı 0'dır.
* **Toplam adam-gün = kişi toplamlarının toplamı** — ŞP 248 "86" = 22+20+23+21
  (ŞP 166/186/206/226). Ayrı bir sorgudan gelmez, satırlardan toplanır.
* **FM saat toplamı YALNIZ girilmiş saatlerden** (spec §7 S2) — saat opsiyoneldir;
  girilmemiş bir FM hücresi ŞP 119'un "128 saat" toplamına 0 katar.

## Boş dönemde ne dönülür?

Satır listesi BOŞTUR ama gün iskeleti ve sıfır toplamlar DURUR. Mockup'ta boş
durum ekranı yoktur ve matris kişi ÖNERMEZ: ŞP 118 "48 işçi" rozeti tablodaki
satırları sayar, kartoteksin tamamını değil. Satır ekleme kartoteksten seçmedir
(`GET /personnel`, T2) — bu uç o kararı vermez.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import Personnel
from app.modules.projects.models import Project
from app.modules.sites.models import Section, Site
from app.modules.timesheet import repository
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from app.modules.timesheet.schemas import (
    TimesheetCell,
    TimesheetDayTotal,
    TimesheetMatrix,
    TimesheetMatrixRow,
)

_ZERO_HOURS = Decimal("0.0")

MAN_DAY_CODES = frozenset({TimesheetCode.worked, TimesheetCode.overtime})
"""Adam-güne sayılan kodlar — TEK tanım.

Kişi toplamı, günlük sayı ve genel toplam bu kümeyi kullanmazsa ekranın üç
yerinde üç farklı sayı görünür.
"""


class _Row:
    """Bir personelin biriktiricisi. Sözlük EKLEME SIRASINI korur ve sorgu
    `Personnel.full_name` ile sıralı gelir — çıktı da ada göre sıralıdır."""

    __slots__ = ("personnel", "subcontractor_name", "cells")

    def __init__(self, personnel: Personnel, subcontractor_name: str | None) -> None:
        self.personnel = personnel
        self.subcontractor_name = subcontractor_name
        self.cells: list[TimesheetCell] = []


class _DayTotal:
    """Bir gün sütununun biriktiricisi (ŞP 230-247)."""

    __slots__ = ("worked_count", "has_overtime", "temporary_duty_count")

    def __init__(self) -> None:
        self.worked_count = 0
        self.has_overtime = False
        self.temporary_duty_count = 0

    def add(self, entry: TimesheetEntry) -> None:
        if entry.code in MAN_DAY_CODES:
            self.worked_count += 1
        if entry.code is TimesheetCode.overtime:
            self.has_overtime = True
        if entry.code is TimesheetCode.temporary_duty:
            self.temporary_duty_count += 1


def _to_row(row: _Row) -> TimesheetMatrixRow:
    personnel = row.personnel
    return TimesheetMatrixRow(
        personnel_id=personnel.id,
        full_name=personnel.full_name,
        trade=personnel.trade,
        source=personnel.source,
        subcontractor_name=row.subcontractor_name,
        man_days=sum(1 for cell in row.cells if cell.code in MAN_DAY_CODES),
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
    day_totals = {day: _DayTotal() for day in repository.period_days(year, month)}
    total_overtime_hours = _ZERO_HOURS

    section_id = section.id if section is not None else None
    for entry, personnel, subcontractor_name in await repository.matrix_rows(
        session, site.id, year=year, month=month, section_id=section_id
    ):
        row = rows.get(personnel.id)
        if row is None:
            row = rows[personnel.id] = _Row(personnel, subcontractor_name)
        row.cells.append(
            TimesheetCell(
                work_date=entry.work_date,
                code=entry.code,
                overtime_hours=entry.overtime_hours,
                section_id=entry.section_id,
            )
        )
        day_totals[entry.work_date].add(entry)
        if entry.overtime_hours is not None:
            total_overtime_hours += entry.overtime_hours

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
        total_man_days=sum(row.man_days for row in matrix_rows_out),
        total_overtime_hours=total_overtime_hours,
        rows=matrix_rows_out,
        day_totals=[
            TimesheetDayTotal(
                work_date=day,
                worked_count=total.worked_count,
                has_overtime=total.has_overtime,
                temporary_duty_count=total.temporary_duty_count,
            )
            for day, total in day_totals.items()
        ],
    )
