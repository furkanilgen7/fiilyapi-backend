"""Adam-saat kazanilmis deger HESAP MOTORU — saf Python (PLANLAMA-SPEC §3).

🔴 Bu paket DB, ORM, FastAPI, pydantic IMPORT ETMEZ; yalniz standart kutuphane ve
kendi alt modulleri. Bekcisi: `tests/modules/earned_value/test_engine_isolation.py`.
Girdi duz dataclass'lardir (`types`); B1/B2/B3 adaptorleri DB'den bunlari kurar.

## Neden `Decimal`, `float` degil (olculdu, 2026-09-25)
* Adam-saat para degil ama raporun B3'te GOLDEN JSON'u olacak: `float`ta toplama
  sirasi sonucu degistirir ve `0.1 + 0.2 = 0.30000000000000004` payload'a sizar.
  `Decimal`de toplama/carpma kesin → "baslik = Σ yaprak" ve "Σ prorata payi = kaynak"
  `==` ile (yaklasik degil) dogrulanir.
* Girdi zaten `Decimal` gelir: `Numeric` kolonlar asyncpg'den `Decimal` doner
  (`site_diary_lines.quantity`, `timesheet_entries.hours`).
* Bedel: 1,5 M carpma+toplama `float`ta 0,12 sn, `Decimal`de 0,37 sn (bu makine) —
  2 sn butcesinin icinde; tam olcum `test_engine_performance.py`.
* Yuvarlama motorda YOK; yalniz bolme 28 anlamli haneye iner (`numeric.ENGINE_CONTEXT`).
"""

from .calendar import CalendarPosition, ProjectCalendar
from .classify import classify_status, pf_band
from .report import compute_daily_report
from .results import DailyReport, NodeMetrics, SummaryRow, Totals
from .types import (
    AllocationRule,
    CalendarSettings,
    ContractorMix,
    ContractorType,
    EngineInput,
    HoursEntry,
    Node,
    PfBand,
    PfBands,
    PlannedMhr,
    QtyEntry,
    RowKind,
    Status,
)

__all__ = [
    "AllocationRule",
    "CalendarPosition",
    "CalendarSettings",
    "ContractorMix",
    "ContractorType",
    "DailyReport",
    "EngineInput",
    "HoursEntry",
    "Node",
    "NodeMetrics",
    "PfBand",
    "PfBands",
    "PlannedMhr",
    "ProjectCalendar",
    "QtyEntry",
    "RowKind",
    "Status",
    "SummaryRow",
    "Totals",
    "classify_status",
    "compute_daily_report",
    "pf_band",
]
