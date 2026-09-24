"""Motorun girdi ve cikti tipleri — duz, degismez dataclass'lar.

Girdi tipleri yapildiklari anda dogrulanir (`__post_init__`): motorun icine yanlis
tipte deger ULASMAZ. Sayilar YALNIZ `Decimal`dir; `float` reddedilir (ikili kesir
artigi golden JSON'u kararsiz yapar — gerekce `__init__.py`de).
"""

from __future__ import annotations

import enum
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

NodeId = Hashable
CurveKey = Hashable

#: Python `date.weekday()` numaralamasi: 0 = Pazartesi … 6 = Pazar.
SUNDAY = 6


class ContractorType(str, enum.Enum):
    OWN = "own"
    SUBCON = "subcon"


class AllocationRule(str, enum.Enum):
    DIRECT = "direct"
    PRORATA_BY_DAILY_QTY = "prorata_by_daily_qty"


class Status(str, enum.Enum):
    NORMAL = "normal"
    AHEAD = "ahead"
    LATE = "late"


class PfBand(str, enum.Enum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"
    #: Gunluk PF'de ust bandin ustu: "supheli yuksek" (cok iyi gun ya da eksik saat girisi).
    HIGH = "high"


class ContractorMix(str, enum.Enum):
    OWN = "own"
    SUBCON = "subcon"
    MIXED = "mixed"


class RowKind(str, enum.Enum):
    OVERALL = "overall"
    OVERALL_OWN = "overall_own"
    OVERALL_SUBCON = "overall_subcon"
    DISCIPLINE = "discipline"
    DISCIPLINE_OWN = "discipline_own"
    DISCIPLINE_SUBCON = "discipline_subcon"
    NON_DIRECT = "non_direct"


def _require_decimal(owner: object, name: str, value: object, *, optional: bool) -> None:
    if value is None and optional:
        return
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{type(owner).__name__}.{name} Decimal olmali, {type(value).__name__} geldi"
        )
    if not value.is_finite():
        raise ValueError(f"{type(owner).__name__}.{name} sonlu olmali: {value}")


@dataclass(frozen=True, slots=True)
class Node:
    """Is kirilimi dugumu. Yaprak olup olmadigi TUREVDIR (cocugu yoksa yapraktir).

    Yaprak: `uom`, `planned_qty`, `unit_mhr` ZORUNLU. Baslik: uc alan da BOS olmali —
    baslik miktar/oran tutmaz, her sey alt toplamdan turer (Ek A §2 wbs_node).
    `curve_discipline` bos ise en yakin atadan miras alinir.
    `prev_*` onceki revizyonun degeri (QURR a/f/m kolonlari); yoksa bos.
    """

    id: NodeId
    parent_id: NodeId | None
    uom: str | None = None
    planned_qty: Decimal | None = None
    unit_mhr: Decimal | None = None
    contractor_type: ContractorType = ContractorType.OWN
    is_direct: bool = True
    curve_discipline: CurveKey | None = None
    prev_planned_qty: Decimal | None = None
    prev_unit_mhr: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("planned_qty", "unit_mhr", "prev_planned_qty", "prev_unit_mhr"):
            _require_decimal(self, name, getattr(self, name), optional=True)
        if not isinstance(self.contractor_type, ContractorType):
            raise TypeError(f"Node.contractor_type ContractorType olmali: {self.contractor_type!r}")
        if (self.prev_planned_qty is None) != (self.prev_unit_mhr is None):
            raise ValueError(
                f"Node {self.id!r}: prev_planned_qty ve prev_unit_mhr birlikte verilir"
            )


@dataclass(frozen=True, slots=True)
class QtyEntry:
    """Yaprak × gun miktar hareketi (duzeltme icin negatif serbest — Ek A §2)."""

    node_id: NodeId
    day: date
    qty: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self, "qty", self.qty, optional=False)


@dataclass(frozen=True, slots=True)
class HoursEntry:
    """Bir dugume (kod = dugum) yazilan saat ve dagitim kurali."""

    node_id: NodeId
    day: date
    hours: Decimal
    rule: AllocationRule

    def __post_init__(self) -> None:
        _require_decimal(self, "hours", self.hours, optional=False)
        if not isinstance(self.rule, AllocationRule):
            raise TypeError(f"HoursEntry.rule AllocationRule olmali: {self.rule!r}")


@dataclass(frozen=True, slots=True)
class PlannedMhr:
    """Planli egri noktasi: planned_mhr(D, d). B0'da girdi; B1'de yaymadan uretilir."""

    curve: CurveKey
    day: date
    mhr: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self, "mhr", self.mhr, optional=False)


@dataclass(frozen=True, slots=True)
class PfBands:
    """PF bant sinirlari (ayar). Karar HAM degerle verilir (spec §3.6).

    v < red_below → RED · v < green_from → AMBER · high_above varsa ve v > high_above → HIGH
    · aksi → GREEN.
    """

    red_below: Decimal
    green_from: Decimal
    high_above: Decimal | None = None

    def __post_init__(self) -> None:
        _require_decimal(self, "red_below", self.red_below, optional=False)
        _require_decimal(self, "green_from", self.green_from, optional=False)
        _require_decimal(self, "high_above", self.high_above, optional=True)
        if self.green_from < self.red_below:
            raise ValueError("PfBands: green_from >= red_below olmali")
        if self.high_above is not None and self.high_above < self.green_from:
            raise ValueError("PfBands: high_above >= green_from olmali")


@dataclass(frozen=True, slots=True)
class CalendarSettings:
    """Proje takvimi ayari (spec §2.6: takvim TABLOSU yok, saf fonksiyon)."""

    start_date: date
    end_date: date
    week_start_dow: int = 0
    weekly_holidays: frozenset[int] | None = None  # None → policy.DEFAULT_WEEKLY_HOLIDAYS
    extra_holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("CalendarSettings: end_date >= start_date olmali")
        if not 0 <= self.week_start_dow <= SUNDAY:
            raise ValueError(f"CalendarSettings.week_start_dow 0..6 olmali: {self.week_start_dow}")
        if self.weekly_holidays is not None and not all(
            0 <= dow <= SUNDAY for dow in self.weekly_holidays
        ):
            raise ValueError("CalendarSettings.weekly_holidays 0..6 olmali")


@dataclass(frozen=True, slots=True)
class EngineInput:
    calendar: CalendarSettings
    nodes: Sequence[Node]
    qty_entries: Sequence[QtyEntry] = ()
    hours_entries: Sequence[HoursEntry] = ()
    planned_mhr: Sequence[PlannedMhr] = ()
    #: Status toleransi PUAN birimindedir (K27: 2,0 = ± 2,0 puan). Varsayilan 0.
    tolerance_points: Decimal = Decimal(0)
    daily_pf_bands: PfBands | None = None  # None → policy.DEFAULT_DAILY_PF_BANDS
    cumulative_pf_bands: PfBands | None = None  # None → policy.DEFAULT_CUMULATIVE_PF_BANDS

    def __post_init__(self) -> None:
        _require_decimal(self, "tolerance_points", self.tolerance_points, optional=False)
        if self.tolerance_points < 0:
            raise ValueError("EngineInput.tolerance_points negatif olamaz")
