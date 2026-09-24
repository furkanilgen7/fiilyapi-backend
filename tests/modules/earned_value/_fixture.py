"""PLN-B0 kabul fikstürü (PLANLAMA-SPEC §7 / Ek A §8) — girdinin TEK tanımı.

Beklenen değerler ve elle hesap tablosu `test_engine_fixture.py` docstring'indedir;
bu dosya yalnız GİRDİYİ kurar ki iki test dosyası aynı veriye baksın.

Kurgu (2 disiplin · 3 iş tipi · 5 yaprak · 10 gün / 1 tatil · 2 saat kodu · 1 eğri
seti · 2 revizyon):

```
D1 Kaba (own, direct, eğri KAB)             ← karışık disiplin (own + subcon)
├── T1 Beton  [iş tipi]
│   ├── L1 Beton·A   m3   pq 100 · oran 2,00   own     (Rev0: 90 · 2,20)
│   └── L2 Beton·B   m3   pq  50 · oran 2,00   SUBCON  (Rev0: 50 · 2,00)
└── T2 Kalıp  [iş tipi]
    └── L3 Kalıp·A   m2   pq 200 · oran 0,50   own     (Rev0: 200 · 0,50)
D2 Tesisat (own, direct, eğri MEK)          ← tek tip disiplin (own)
├── T3 Boru   [iş tipi]
│   └── L4 Boru·A    m    pq  80 · oran 1,25   own     (Rev0: 80 · 1,00)
└── L5 Mobilizasyon  adet pq 1 · oran 40       own, is_direct=FALSE
```

Takvim: 2026-09-03 (Perşembe) … 2026-09-12 · hafta başı Pazartesi · tatil Pazar
(2026-09-06 = gün 4). İlk hafta KISMİ: 03–06 Eylül (4 gün).

Saat kodları (kod = iş kırılımı düğümü):
* A → T1, `prorata_by_daily_qty`
* B → D2 (BAŞLIK), `direct`
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    ContractorType,
    EngineInput,
    HoursEntry,
    Node,
    PlannedMhr,
    QtyEntry,
)

D = Decimal
OWN = ContractorType.OWN
SUBCON = ContractorType.SUBCON

START = date(2026, 9, 3)
END = date(2026, 9, 12)


def day(n: int) -> date:
    """Proje günü n (1 = başlangıç) → tarih."""
    return START + timedelta(days=n - 1)


#: Rapor günü: gün 7 = 2026-09-09 Çarşamba (2. hafta; pencere 07–09 Eylül).
REPORT_DATE = day(7)

NODES = (
    Node("D1", None, contractor_type=OWN, curve_discipline="KAB"),
    Node("T1", "D1", contractor_type=OWN),
    Node(
        "L1",
        "T1",
        uom="m3",
        planned_qty=D("100"),
        unit_mhr=D("2.00"),
        contractor_type=OWN,
        prev_planned_qty=D("90"),
        prev_unit_mhr=D("2.20"),
    ),
    Node(
        "L2",
        "T1",
        uom="m3",
        planned_qty=D("50"),
        unit_mhr=D("2.00"),
        contractor_type=SUBCON,
        prev_planned_qty=D("50"),
        prev_unit_mhr=D("2.00"),
    ),
    Node("T2", "D1", contractor_type=OWN),
    Node(
        "L3",
        "T2",
        uom="m2",
        planned_qty=D("200"),
        unit_mhr=D("0.50"),
        contractor_type=OWN,
        prev_planned_qty=D("200"),
        prev_unit_mhr=D("0.50"),
    ),
    Node("D2", None, contractor_type=OWN, curve_discipline="MEK"),
    Node("T3", "D2", contractor_type=OWN),
    Node(
        "L4",
        "T3",
        uom="m",
        planned_qty=D("80"),
        unit_mhr=D("1.25"),
        contractor_type=OWN,
        prev_planned_qty=D("80"),
        prev_unit_mhr=D("1.00"),
    ),
    Node(
        "L5",
        "D2",
        uom="adet",
        planned_qty=D("1"),
        unit_mhr=D("40"),
        contractor_type=OWN,
        is_direct=False,
        prev_planned_qty=D("1"),
        prev_unit_mhr=D("40"),
    ),
)

_QTY = {
    "L1": {1: "5", 2: "5", 3: "10", 5: "10", 7: "20", 8: "10"},
    "L2": {2: "4", 5: "6", 7: "5", 9: "5"},
    "L3": {1: "20", 3: "20", 6: "40"},
    "L4": {5: "8", 6: "8", 7: "8"},
    "L5": {1: "1"},
}

_HOURS = {
    ("T1", AllocationRule.PRORATA_BY_DAILY_QTY): {
        1: "12",
        2: "18",
        3: "20",
        5: "32",
        6: "8",
        7: "30",
        8: "10",
    },
    ("D2", AllocationRule.DIRECT): {1: "10", 3: "12", 6: "20", 7: "6"},
}

#: Tek eğri seti (disiplin × gün matrisi); tatil (gün 4) = 0.
#: KAB Σ = 400 = D1 direct bütçesi · MEK Σ = 100 = D2 direct bütçesi.
_CURVE = {
    "KAB": (30, 30, 30, 0, 30, 30, 30, 70, 70, 80),
    "MEK": (0, 0, 0, 0, 5, 5, 10, 20, 30, 30),
}

QTY_ENTRIES = tuple(
    QtyEntry(node_id, day(n), D(qty)) for node_id, days in _QTY.items() for n, qty in days.items()
)
HOURS_ENTRIES = tuple(
    HoursEntry(node_id, day(n), D(hours), rule)
    for (node_id, rule), days in _HOURS.items()
    for n, hours in days.items()
)
PLANNED = tuple(
    PlannedMhr(curve, day(i + 1), D(mhr))
    for curve, values in _CURVE.items()
    for i, mhr in enumerate(values)
)

CALENDAR = CalendarSettings(start_date=START, end_date=END, week_start_dow=0)


def build_input(tolerance_points: Decimal = Decimal(0)) -> EngineInput:
    return EngineInput(
        calendar=CALENDAR,
        nodes=NODES,
        qty_entries=QTY_ENTRIES,
        hours_entries=HOURS_ENTRIES,
        planned_mhr=PLANNED,
        tolerance_points=tolerance_points,
    )
