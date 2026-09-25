"""TEK GECISLI seri — panel/rapor trendleri tek cagrida (PLN-B3.1; spec §3, §3.13 B3-4).

Her gun icin ayri `compute_daily_report` yerine hareketler BIR KEZ taranir:

1. Her nokta (yaprak kazanilmisi, saat inisi) "kovasina" yazilir: kova = (disiplin koku,
   `policy.point_class`) — S2 ayni fonksiyonla; kapsam (`scope.Scope`) kovalarin birlesimidir
   ve kova uyeligi `scope.scope_keep` ile karar verilir (KPI satirlariyla AYNI yuklem).
2. Saat dagitimi `accumulate.land_hours` ile (direct / prorata / unallocated — ayni kural);
   prorata payi yalniz O GUNUN miktarina bagli oldugu icin rapor gununden bagimsizdir.
3. Kapsam × gun dizileri → onek toplamlari (kumulatif). Planli %: yaprak modunda kapsamdaki
   yaprak egrileri, disiplin modunda `scope.curve_weights` + `summary.curve_mix` (S1) —
   ikisi de `plan.planned_pct` formulunden.

BIREBIRLIK (bekcisi `test_engine_series.py`): her gun t ve her KPI satiri icin seri degeri
`compute_daily_report(t)` satiriyla `==`. Gerekce: toplamlar KESIN (Decimal; prorata payi
1e-12 kuantumlu — `accumulate.prorata_parts`), dolayisiyla toplama SIRASI sonucu degistirmez;
bolme ve S1 carpimi ayni islenenlerle ayni sirada yapilir.

`as_of`: t > as_of gunlerinde gerceklesen alanlar None (planli dolu) — gelecek gunler
S-egrisi penceresine girebilir. `pf_rolling` (B3-4): t'de biten son N IS gunu Σearned /
Σspent; tatil pencereye GIRMEZ (tatile yazilmis deger de), saatsiz is gunu GIRER; takvim
basinda pencere eldeki is gunleriyle kisalir.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from itertools import accumulate as prefix_sums

from .accumulate import Resolved, resolve_all
from .calendar import ProjectCalendar
from .classify import classify_status
from .metrics import leaf_budgets
from .numeric import ENGINE_CONTEXT, ZERO, diff, ratio
from .plan import plan_uses_leaf_curves, planned_pct
from .policy import point_class
from .scope import Scope, curve_weights, has_plan, root_index, scope_keep
from .summary import CurveTotals, curve_mix, share_fn
from .tree import Tree, build_tree
from .types import CurveKey, EngineInput, Node, Status

PlannedPair = tuple[Decimal | None, Decimal | None]


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """Bir kapsamin t gunu. `is_future` (t > as_of) iken gerceklesen alanlar None."""

    day: date
    is_holiday: bool
    is_future: bool
    budget_mhr: Decimal  # kapsamda sabit
    planned_pct_day: Decimal | None
    planned_pct_cum: Decimal | None
    # gerceklesen (t > as_of → None)
    earned_day: Decimal | None = None
    spent_day: Decimal | None = None
    earned_cum: Decimal | None = None
    spent_cum: Decimal | None = None
    progress_pct_cum: Decimal | None = None
    variance: Decimal | None = None
    status: Status | None = None
    pf_day: Decimal | None = None
    pf_cum: Decimal | None = None
    pf_rolling: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ScopeSeries:
    scope: Scope
    budget_mhr: Decimal
    points: tuple[SeriesPoint, ...]  # [start, end] her takvim gunu, sirali

    def at(self, d: date) -> SeriesPoint:
        if self.points:
            k = (d - self.points[0].day).days
            if 0 <= k < len(self.points):
                return self.points[k]
        raise KeyError(d)


@dataclass(frozen=True, slots=True)
class SeriesResult:
    start: date
    end: date
    as_of: date | None
    rolling_working_days: int
    series: tuple[ScopeSeries, ...]  # istenen kapsam sirasiyla

    def get(self, scope: Scope) -> ScopeSeries:
        """Kapsamin serisi (`label` esitlige girmez)."""
        for s in self.series:
            if s.scope == scope:
                return s
        raise KeyError(scope)


class _Buckets:
    """Nokta kovalari: (disiplin koku, point_class). Kapsam = kovalarin birlesimi."""

    def __init__(self, tree: Tree) -> None:
        keys: dict[object, int] = {}
        self.of: list[int] = [0] * len(tree)
        self.sample: list[Node] = []  # kova basina bir temsilci dugum (point_class kovada sabit)
        self.root: list[int] = []
        for i, node in enumerate(tree.nodes):
            key = (tree.root_of[i], point_class(node))
            b = keys.get(key)
            if b is None:
                b = keys[key] = len(self.sample)
                self.sample.append(node)
                self.root.append(tree.root_of[i])
            self.of[i] = b

    def __len__(self) -> int:
        return len(self.sample)

    def members(self, tree: Tree, scope: Scope) -> list[int]:
        r = root_index(tree, scope)
        keep = scope_keep(scope)
        return [
            b for b in range(len(self)) if (r is None or self.root[b] == r) and keep(self.sample[b])
        ]


def _grid(rows: int, days: int) -> list[list[Decimal]]:
    return [[ZERO] * days for _ in range(rows)]


def _actuals(
    resolved: Resolved, calendar: ProjectCalendar, buckets: _Buckets, days: int
) -> tuple[list[list[Decimal]], list[list[Decimal]]]:
    """Kova × gun kazanilmis ve harcanan (gun < days). Girisler `resolve_all`da dogrulandi."""
    earned, spent = _grid(len(buckets), days), _grid(len(buckets), days)
    rates, of = resolved.rates, buckets.of
    base = calendar.start_date.toordinal()
    for i, e in resolved.qty:
        k = e.day.toordinal() - base
        if k < days:
            earned[of[i]][k] += e.qty * rates[i]
    for h in resolved.hours:
        k = h.day.toordinal() - base
        if k < days:
            for i, part in h.parts:
                spent[of[i]][k] += part
    return earned, spent


def _sum_rows(grid: list[list[Decimal]], members: list[int], days: int) -> list[Decimal]:
    out = [ZERO] * days
    for b in members:
        out = [a + v for a, v in zip(out, grid[b], strict=True)]
    return out


class _Planner:
    """Kapsamin gun basina planli %'si — K9 mod secimi `plan.plan_uses_leaf_curves`."""

    def __init__(
        self,
        tree: Tree,
        calendar: ProjectCalendar,
        inp: EngineInput,
        buckets: _Buckets,
        budget: list[Decimal],
        days: int,
    ) -> None:
        self._tree, self._buckets, self._days = tree, buckets, days
        self.leaf_mode = plan_uses_leaf_curves(tree, calendar, inp.planned_mhr)
        base = calendar.start_date.toordinal()
        if self.leaf_mode:
            self._leaf_day = _grid(len(buckets), days)
            self._leaf_total = [ZERO] * len(buckets)
            for p in inp.planned_mhr:
                if p.node_id is None:
                    continue  # K9: karisik girdide disiplin noktalari yok sayilir
                b = buckets.of[tree.index[p.node_id]]
                self._leaf_total[b] += p.mhr
                k = p.day.toordinal() - base
                if k < days:
                    self._leaf_day[b][k] += p.mhr
            return
        curve_day: dict[CurveKey, list[Decimal]] = {}
        curve_total: dict[CurveKey, Decimal] = {}
        for p in inp.planned_mhr:  # `summary.curve_totals` ile ayni anahtar sirasi
            if p.curve is None:
                continue
            series = curve_day.setdefault(p.curve, [ZERO] * days)
            curve_total[p.curve] = curve_total.get(p.curve, ZERO) + p.mhr
            k = p.day.toordinal() - base
            if k < days:
                series[k] += p.mhr
        cum = {c: list(prefix_sums(v)) for c, v in curve_day.items()}
        self._curves_at = [
            {c: CurveTotals(curve_day[c][k], cum[c][k], curve_total[c]) for c in curve_day}
            for k in range(days)
        ]
        self._share = share_fn(tree, budget)
        self._curve_keys = tuple(curve_day)

    def pct(self, scope: Scope, members: list[int]) -> list[PlannedPair]:
        none: list[PlannedPair] = [(None, None)] * self._days
        if not has_plan(scope):
            return none
        if self.leaf_mode:
            day = _sum_rows(self._leaf_day, members, self._days)
            total = sum((self._leaf_total[b] for b in members), ZERO)
            return [planned_pct(d, c, total) for d, c in zip(day, prefix_sums(day), strict=True)]
        weights = curve_weights(self._tree, scope, self._curve_keys, self._share)
        if weights is None:
            return none
        return [planned_pct(*curve_mix(curves, weights)) for curves in self._curves_at]


def _rolling(
    earned: list[Decimal], spent: list[Decimal], work: list[int], n: int
) -> list[Decimal | None]:
    """B3-4: gun k'da biten son n IS gununun Σearned / Σspent (tatil gunleri atlanir)."""
    we, ws = [ZERO], [ZERO]
    for k in work:
        we.append(we[-1] + earned[k])
        ws.append(ws[-1] + spent[k])
    out: list[Decimal | None] = []
    for k in range(len(earned)):
        c = bisect_right(work, k)
        lo = max(0, c - n)
        out.append(ratio(we[c] - we[lo], ws[c] - ws[lo]))
    return out


def validate_window(calendar: ProjectCalendar, start: date, end: date, rolling: int) -> None:
    if start > end:
        raise ValueError(f"compute_series: start > end ({start} > {end})")
    for d in (start, end):
        if not calendar.contains(d):
            raise ValueError(
                f"compute_series: {d} proje takvimi disinda "
                f"({calendar.start_date} – {calendar.end_date})"
            )
    if rolling < 1:
        raise ValueError(f"compute_series: rolling_working_days >= 1 olmali: {rolling}")


def compute_series(
    inp: EngineInput,
    start: date,
    end: date,
    scopes: Sequence[Scope],
    *,
    as_of: date | None = None,
    rolling_working_days: int = 7,
) -> SeriesResult:
    """[start, end] (takvim icinde) her gun × her kapsam — tek gecis.

    Kumulatifler TAKVIM BASINDAN (start'tan degil). `as_of` None → gelecek gun yok.
    """
    with localcontext(ENGINE_CONTEXT):
        calendar = ProjectCalendar(inp.calendar)
        validate_window(calendar, start, end, rolling_working_days)
        tree = build_tree(inp.nodes)
        for scope in scopes:
            root_index(tree, scope)  # disiplin koku degilse ValueError
        resolved = resolve_all(tree, calendar, inp.qty_entries, inp.hours_entries)
        return series_from(
            inp, calendar, tree, resolved, start, end, scopes, as_of, rolling_working_days
        )


def series_from(
    inp: EngineInput,
    calendar: ProjectCalendar,
    tree: Tree,
    resolved: Resolved,
    start: date,
    end: date,
    scopes: Sequence[Scope],
    as_of: date | None,
    rolling_working_days: int,
) -> SeriesResult:
    """`compute_series` govdesi — agac ve inisler disaridan (panel paylasimi; ENGINE_CONTEXT'te
    ve dogrulanmis girdiyle cagrilir)."""
    base = calendar.start_date
    days = (end - base).days + 1
    until = end if as_of is None else min(end, as_of)
    actual_days = max(0, (until - base).days + 1)
    buckets = _Buckets(tree)
    budget_by_node = leaf_budgets(tree)
    planner = _Planner(tree, calendar, inp, buckets, budget_by_node, days)
    earned, spent = _actuals(resolved, calendar, buckets, actual_days)
    holiday = [calendar.is_holiday(base + timedelta(days=k)) for k in range(days)]
    work = [k for k in range(actual_days) if not holiday[k]]
    budget_of = [ZERO] * len(buckets)
    for i, b in enumerate(budget_by_node):
        budget_of[buckets.of[i]] += b
    first = (start - base).days
    out = []
    for scope in scopes:
        members = buckets.members(tree, scope)
        budget = sum((budget_of[b] for b in members), ZERO)
        ed = _sum_rows(earned, members, actual_days)
        sd = _sum_rows(spent, members, actual_days)
        ctx = _ScopeDays(
            budget=budget,
            earned_day=ed,
            spent_day=sd,
            earned_cum=list(prefix_sums(ed)),
            spent_cum=list(prefix_sums(sd)),
            rolling=_rolling(ed, sd, work, rolling_working_days),
            planned=planner.pct(scope, members),
        )
        points = tuple(
            ctx.point(base + timedelta(days=k), k, holiday[k], inp.tolerance_points)
            for k in range(first, days)
        )
        out.append(ScopeSeries(scope, budget, points))
    return SeriesResult(start, end, as_of, rolling_working_days, tuple(out))


@dataclass(frozen=True, slots=True)
class _ScopeDays:
    """Bir kapsamin gun dizileri (gerceklesen: as_of'a kadar; planli: end'e kadar)."""

    budget: Decimal
    earned_day: list[Decimal]
    spent_day: list[Decimal]
    earned_cum: list[Decimal]
    spent_cum: list[Decimal]
    rolling: list[Decimal | None]
    planned: list[PlannedPair]

    def point(self, t: date, k: int, is_holiday: bool, tolerance: Decimal) -> SeriesPoint:
        planned_day, planned_cum = self.planned[k]
        if k >= len(self.earned_day):  # t > as_of: yalniz planli
            return SeriesPoint(
                day=t,
                is_holiday=is_holiday,
                is_future=True,
                budget_mhr=self.budget,
                planned_pct_day=planned_day,
                planned_pct_cum=planned_cum,
            )
        ed, sd = self.earned_day[k], self.spent_day[k]
        ec, sc = self.earned_cum[k], self.spent_cum[k]
        progress = ratio(ec, self.budget)
        variance = diff(progress, planned_cum)
        return SeriesPoint(
            day=t,
            is_holiday=is_holiday,
            is_future=False,
            budget_mhr=self.budget,
            planned_pct_day=planned_day,
            planned_pct_cum=planned_cum,
            earned_day=ed,
            spent_day=sd,
            earned_cum=ec,
            spent_cum=sc,
            progress_pct_cum=progress,
            variance=variance,
            status=classify_status(variance, tolerance),
            pf_day=ratio(ed, sd),
            pf_cum=ratio(ec, sc),
            pf_rolling=self.rolling[k],
        )
