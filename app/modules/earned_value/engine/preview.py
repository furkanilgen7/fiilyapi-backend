"""Butce ONIZLEMESI: yaprak × gun egrisi → disiplin/toplam S-egrisi + gereken isci (§2.5).

* Her dogrudan yaprak `spread.spread_leaf` ile yayilir (K9: yayma yaprak duzeyinde).
* `is_direct=False` yaprak egriye GIRMEZ (S3); yalniz `indirect_budget_mhr`a eklenir.
* Penceresinde is gunu olmayan yaprak hata ATMAZ: `unspreadable`da doner, egriye girmez.
* Aralik = egriye giren yaprak pencerelerinin birlesimi [min start, max end]; gunluk seriler
  bu araligin HER takvim gunu icin yogundur (0 dahil) → disiplin serileri hizali.
* Haftalik kova `calendar.ProjectCalendar` kuraliyla: hafta `week_start_dow` gunu baslar,
  ilk hafta kisa olabilir (hafta basi aralik basindan once olmaz), son hafta aralik sonuna
  kirpilir (`policy.WEEK_LOAD_CLIPPED_TO_RANGE_END`).
* Gereken kisi = hafta a-s ÷ (is gunu × standart gunluk saat) (K10, `policy.required_people`).
* Tepe hafta = en yuksek gereken kisi; esitlikte EN ERKEN; hic pozitif hafta yoksa None.

Σ(yaprak egrisi) == yaprak butcesi, Σ disiplin == Σ yapraklari, Σ toplam == Σ disiplin TAM.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext

from .calendar import ProjectCalendar, working_day_predicate
from .numeric import ENGINE_CONTEXT, ZERO, ratio
from .policy import (
    DEFAULT_STANDARD_DAILY_HOURS,
    DEFAULT_WEEKLY_HOLIDAYS,
    WEEK_LOAD_CLIPPED_TO_RANGE_END,
    required_people,
)
from .spread import NoWorkingDayError, spread_leaf
from .types import SUNDAY, CalendarSettings, CurveKey, NodeId, SpreadLeaf


@dataclass(frozen=True, slots=True)
class WeekLoad:
    week_no: int  # ilk (kisa) hafta 1
    week_start: date
    week_end: date  # aralik sonuna kirpilmis
    mhr: Decimal
    working_days: int
    required_people: Decimal | None  # is gunu 0 → None


@dataclass(frozen=True, slots=True)
class SeriesPreview:
    budget_mhr: Decimal  # = Σ daily
    start: date | None  # sifir olmayan en erken gun
    end: date | None  # sifir olmayan en gec gun
    daily: Mapping[date, Decimal]
    cumulative: Mapping[date, Decimal]
    planned_pct_cum: Mapping[date, Decimal | None]  # kumulatif / butce; butce 0 → None
    weeks: tuple[WeekLoad, ...]
    peak_week: WeekLoad | None


@dataclass(frozen=True, slots=True)
class DisciplinePreview:
    discipline: CurveKey
    share: Decimal | None  # disiplin butcesi ÷ toplam dogrudan butce; toplam 0 → None
    series: SeriesPreview


@dataclass(frozen=True, slots=True)
class SpreadPreview:
    start: date | None  # aralik (egriye giren yaprak pencereleri); egri yoksa None
    end: date | None
    leaf_curves: Mapping[NodeId, Mapping[date, Decimal]]
    disciplines: Mapping[CurveKey, DisciplinePreview]  # ilk gorulme sirasi
    total: SeriesPreview
    indirect_budget_mhr: Decimal
    unspreadable: tuple[NodeId, ...]


def _empty_series() -> SeriesPreview:
    return SeriesPreview(ZERO, None, None, {}, {}, {}, (), None)


@dataclass(frozen=True, slots=True)
class _Week:
    week_no: int
    start: date
    end: date
    working_days: int


@dataclass(frozen=True, slots=True)
class _Settings:
    week_start_dow: int
    weekly: frozenset[int]
    extra: frozenset[date]
    is_working_day: Callable[[date], bool]
    hours: Decimal


def _settings(
    week_start_dow: int,
    weekly_holidays: frozenset[int] | None,
    extra_holidays: frozenset[date],
    standard_daily_hours: Decimal,
) -> _Settings:
    if not isinstance(standard_daily_hours, Decimal):
        raise TypeError("standard_daily_hours Decimal olmali")
    if not standard_daily_hours.is_finite() or standard_daily_hours <= 0:
        raise ValueError(f"standard_daily_hours pozitif olmali: {standard_daily_hours}")
    if not 0 <= week_start_dow <= SUNDAY:
        raise ValueError(f"week_start_dow 0..6 olmali: {week_start_dow}")
    weekly = DEFAULT_WEEKLY_HOLIDAYS if weekly_holidays is None else weekly_holidays
    return _Settings(
        week_start_dow,
        weekly,
        extra_holidays,
        working_day_predicate(weekly, extra_holidays),
        standard_daily_hours,
    )


def compute_spread_preview(
    leaves: Sequence[SpreadLeaf],
    *,
    week_start_dow: int = 0,
    weekly_holidays: frozenset[int] | None = None,
    extra_holidays: frozenset[date] = frozenset(),
    standard_daily_hours: Decimal = DEFAULT_STANDARD_DAILY_HOURS,
) -> SpreadPreview:
    """Taslak revizyon: yapraklari yayar, sonra toplar (aralik = yaprak pencereleri)."""
    cfg = _settings(week_start_dow, weekly_holidays, extra_holidays, standard_daily_hours)
    with localcontext(ENGINE_CONTEXT):
        spread = _spread_all(leaves, cfg.is_working_day)
        return _assemble(spread, cfg)


def preview_from_curves(
    curves: Mapping[NodeId, Mapping[date, Decimal]],
    disciplines: Mapping[NodeId, CurveKey],
    *,
    indirect_budget_mhr: Decimal = ZERO,
    start: date | None = None,
    end: date | None = None,
    week_start_dow: int = 0,
    weekly_holidays: frozenset[int] | None = None,
    extra_holidays: frozenset[date] = frozenset(),
    standard_daily_hours: Decimal = DEFAULT_STANDARD_DAILY_HOURS,
) -> SpreadPreview:
    """DONMUS revizyon (K8): snapshot'taki yaprak × gun egrisinden onizleme — YENIDEN YAYMAZ.

    `curves` yalniz dogrudan yapraklari tasir (S3); `disciplines` yaprak → disiplin.
    Aralik varsayilani egri gunlerinin min/max'i; yaprak penceresi tatilde basliyor/bitiyorsa
    `compute_spread_preview` ile BIREBIR ayni haftalar icin `start`/`end` (pencere birlesimi)
    verilmelidir. `unspreadable` her zaman bos.
    """
    cfg = _settings(week_start_dow, weekly_holidays, extra_holidays, standard_daily_hours)
    if not isinstance(indirect_budget_mhr, Decimal):
        raise TypeError("indirect_budget_mhr Decimal olmali")
    with localcontext(ENGINE_CONTEXT):
        spread = _Spread({}, {}, indirect_budget_mhr, (), None, None)
        for node_id, curve in curves.items():
            if node_id not in disciplines:
                raise ValueError(f"Yaprak {node_id!r}: disiplin eslemesi yok")
            for t, v in curve.items():
                if not isinstance(v, Decimal):
                    raise TypeError(f"Yaprak {node_id!r} {t}: pay Decimal olmali")
            _add_curve(spread, node_id, disciplines[node_id], dict(curve))
            if curve:
                _widen(spread, min(curve), max(curve))
        if spread.curves and (start is not None or end is not None):
            _override_range(spread, start, end)
        return _assemble(spread, cfg)


def _override_range(spread: _Spread, start: date | None, end: date | None) -> None:
    lo = start if start is not None else spread.start
    hi = end if end is not None else spread.end
    if lo is None or hi is None:
        spread.start, spread.end = lo, hi
        return
    if (spread.start is not None and spread.start < lo) or (
        spread.end is not None and spread.end > hi
    ):
        raise ValueError(f"Egri gunleri verilen aralik disinda: {lo} – {hi}")
    spread.start, spread.end = lo, hi


def _assemble(spread: _Spread, cfg: _Settings) -> SpreadPreview:
    """Ortak toplama: gunluk/kumulatif seriler, haftalik kova, tepe hafta, disiplin payi."""
    if spread.start is None or spread.end is None:
        return SpreadPreview(None, None, {}, {}, _empty_series(), spread.indirect, spread.bad)
    calendar = ProjectCalendar(
        CalendarSettings(spread.start, spread.end, cfg.week_start_dow, cfg.weekly, cfg.extra)
    )
    days = [spread.start + timedelta(days=i) for i in range((spread.end - spread.start).days + 1)]
    weeks = _weeks(calendar, days, cfg.is_working_day)
    series = {
        key: _series(daily, days, weeks, cfg.hours) for key, daily in spread.by_discipline.items()
    }
    total_daily: dict[date, Decimal] = {}
    for daily in spread.by_discipline.values():
        for t, v in daily.items():
            total_daily[t] = total_daily.get(t, ZERO) + v
    total = _series(total_daily, days, weeks, cfg.hours)
    disciplines = {
        key: DisciplinePreview(key, ratio(s.budget_mhr, total.budget_mhr), s)
        for key, s in series.items()
    }
    return SpreadPreview(
        start=spread.start,
        end=spread.end,
        leaf_curves=spread.curves,
        disciplines=disciplines,
        total=total,
        indirect_budget_mhr=spread.indirect,
        unspreadable=spread.bad,
    )


@dataclass(slots=True)
class _Spread:
    curves: dict[NodeId, dict[date, Decimal]]
    by_discipline: dict[CurveKey, dict[date, Decimal]]
    indirect: Decimal
    bad: tuple[NodeId, ...]
    start: date | None
    end: date | None


def _spread_all(leaves: Sequence[SpreadLeaf], is_working_day: Callable[[date], bool]) -> _Spread:
    seen: set[NodeId] = set()
    out = _Spread({}, {}, ZERO, (), None, None)
    bad: list[NodeId] = []
    for leaf in leaves:
        if leaf.node_id in seen:
            raise ValueError(f"Yaprak tekrar ediyor: {leaf.node_id!r}")
        seen.add(leaf.node_id)
        if not leaf.is_direct:
            out.indirect += leaf.budget  # S3: ne butceye ne egriye
            continue
        try:
            curve = spread_leaf(
                leaf.budget, leaf.start, leaf.end, leaf.distribution, is_working_day
            )
        except NoWorkingDayError:
            bad.append(leaf.node_id)
            continue
        _add_curve(out, leaf.node_id, leaf.discipline, curve)
        _widen(out, leaf.start, leaf.end)
    out.bad = tuple(bad)
    return out


def _add_curve(
    out: _Spread, node_id: NodeId, discipline: CurveKey, curve: dict[date, Decimal]
) -> None:
    out.curves[node_id] = curve
    daily = out.by_discipline.setdefault(discipline, {})
    for t, v in curve.items():
        daily[t] = daily.get(t, ZERO) + v


def _widen(out: _Spread, start: date, end: date) -> None:
    out.start = start if out.start is None else min(out.start, start)
    out.end = end if out.end is None else max(out.end, end)


def _weeks(
    calendar: ProjectCalendar, days: list[date], is_working_day: Callable[[date], bool]
) -> list[_Week]:
    weeks: list[_Week] = []
    for t in days:
        start = calendar.week_start(t)
        if weeks and weeks[-1].start == start:
            continue
        end = calendar.week_end(t)
        if WEEK_LOAD_CLIPPED_TO_RANGE_END:
            end = min(end, calendar.end_date)
        span = (start + timedelta(days=i) for i in range((end - start).days + 1))
        working = sum(1 for d in span if is_working_day(d))
        weeks.append(_Week(calendar.week_no(t), start, end, working))
    return weeks


def _series(
    sparse: Mapping[date, Decimal],
    days: list[date],
    weeks: list[_Week],
    standard_daily_hours: Decimal,
) -> SeriesPreview:
    daily = {t: sparse.get(t, ZERO) for t in days}
    budget = sum(daily.values(), ZERO)
    cumulative: dict[date, Decimal] = {}
    running = ZERO
    for t in days:
        running += daily[t]
        cumulative[t] = running
    nonzero = [t for t in days if daily[t] != 0]
    loads = tuple(_week_load(w, sparse, standard_daily_hours) for w in weeks)
    return SeriesPreview(
        budget_mhr=budget,
        start=nonzero[0] if nonzero else None,
        end=nonzero[-1] if nonzero else None,
        daily=daily,
        cumulative=cumulative,
        planned_pct_cum={t: ratio(c, budget) for t, c in cumulative.items()},
        weeks=loads,
        peak_week=_peak(loads),
    )


def _week_load(week: _Week, sparse: Mapping[date, Decimal], hours: Decimal) -> WeekLoad:
    span = (week.start + timedelta(days=i) for i in range((week.end - week.start).days + 1))
    mhr = sum((sparse.get(t, ZERO) for t in span), ZERO)
    return WeekLoad(
        week_no=week.week_no,
        week_start=week.start,
        week_end=week.end,
        mhr=mhr,
        working_days=week.working_days,
        required_people=required_people(mhr, week.working_days, hours),
    )


def _peak(loads: tuple[WeekLoad, ...]) -> WeekLoad | None:
    """En yuksek gereken kisi; esitlikte en erken (kesin `>`); pozitif hafta yoksa None."""
    best: WeekLoad | None = None
    for w in loads:
        people = w.required_people
        if people is None or people <= 0:
            continue
        if best is None or people > (best.required_people or ZERO):
            best = w
    return best
