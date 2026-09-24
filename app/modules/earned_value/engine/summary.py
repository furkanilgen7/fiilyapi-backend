"""KPI satirlari: Overall, Overall–Own/Subcon, disiplin (+ own/subcon), dogrudan olmayan.

Satirlar AGAC TOPLAMINDAN degil NOKTALARDAN kurulur: her nokta (yaprak degeri ya da
saat inisi) dustugu dugumun `is_direct` / `contractor_type` alanlariyla siniflanir
(S2). Own/Subcon ayrimi alanla yapilir, satir konumuyla DEGIL (Ek A §7).

Planli %: satirin egri agirliklari `w_D` ile
    planned_mhr_row(d) = Σ_D w_D × planned_mhr(D, d)
    planned_pct_day = planned_mhr_row(d) / Σ_t planned_mhr_row(t)
    planned_pct_cum = Σ_{t<=d} planned_mhr_row(t) / Σ_t planned_mhr_row(t)
Overall ve disiplin icin w_D = 1; own/subcon icin w_D = budget_part(D) / budget(D) (S1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .accumulate import Points
from .classify import classify_status, pf_band
from .numeric import ZERO, diff, ratio
from .policy import (
    KPI_ROWS_DIRECT_ONLY,
    OWN_SUBCON_PLAN_BY_BUDGET_SHARE,
    contractor_mix,
    discipline_has_split_rows,
    point_class,
)
from .results import SummaryRow
from .tree import Tree
from .types import (
    ContractorMix,
    ContractorType,
    CurveKey,
    Node,
    NodeId,
    PfBands,
    PlannedMhr,
    RowKind,
)


@dataclass(frozen=True, slots=True)
class CurveTotals:
    day: Decimal
    cum: Decimal
    total: Decimal


def curve_totals(planned: Iterable[PlannedMhr], report_date: date) -> dict[CurveKey, CurveTotals]:
    acc: dict[CurveKey, list[Decimal]] = {}
    for p in planned:
        day, cum, total = acc.setdefault(p.curve, [ZERO, ZERO, ZERO])
        acc[p.curve] = [
            day + (p.mhr if p.day == report_date else ZERO),
            cum + (p.mhr if p.day <= report_date else ZERO),
            total + p.mhr,
        ]
    return {k: CurveTotals(*v) for k, v in acc.items()}


@dataclass(frozen=True, slots=True)
class _Context:
    tree: Tree
    points: Points
    budget: list[Decimal]  # yaprak nokta butcesi (baslik 0)
    curves: Mapping[CurveKey, CurveTotals]
    tolerance_points: Decimal
    daily_bands: PfBands
    cumulative_bands: PfBands


Predicate = Callable[[Node], bool]


def _is_direct(node: Node) -> bool:
    return point_class(node)[0]


def _is_non_direct(node: Node) -> bool:
    return not point_class(node)[0]


def _direct_of(kind: ContractorType) -> Predicate:
    return lambda node: point_class(node) == (True, kind)


def _discipline_filter(node: Node) -> bool:
    # S3: disiplin KPI satiri yalniz direct noktalari tasir.
    return point_class(node)[0] or not KPI_ROWS_DIRECT_ONLY


def _share_weights(ctx: _Context, kind: ContractorType) -> dict[CurveKey, Decimal] | None:
    """S1: w_D = budget_kind(D) / budget(D), direct yapraklar uzerinden."""
    if not OWN_SUBCON_PLAN_BY_BUDGET_SHARE:
        return None
    whole: dict[CurveKey, Decimal] = {}
    part: dict[CurveKey, Decimal] = {}
    for i, node in enumerate(ctx.tree.nodes):
        curve = ctx.tree.curve_of[i]
        is_direct, contractor = point_class(node)
        if not ctx.tree.is_leaf[i] or not is_direct or curve is None:
            continue
        whole[curve] = whole.get(curve, ZERO) + ctx.budget[i]
        if contractor is kind:
            part[curve] = part.get(curve, ZERO) + ctx.budget[i]
    return {
        curve: share
        for curve, total in whole.items()
        if (share := ratio(part.get(curve, ZERO), total)) is not None
    }


def _planned(
    ctx: _Context, weights: Mapping[CurveKey, Decimal] | None
) -> tuple[Decimal | None, Decimal | None]:
    if weights is None:
        return None, None
    day = cum = total = ZERO
    for curve, w in weights.items():
        c = ctx.curves.get(curve)
        if c is None:
            continue
        day += w * c.day
        cum += w * c.cum
        total += w * c.total
    return ratio(day, total), ratio(cum, total)


def _row(
    ctx: _Context,
    kind: RowKind,
    indices: range,
    keep: Predicate,
    weights: Mapping[CurveKey, Decimal] | None,
    node_id: NodeId | None = None,
    mix: ContractorMix | None = None,
) -> SummaryRow:
    p, nodes = ctx.points, ctx.tree.nodes
    sel = [i for i in indices if keep(nodes[i])]

    def total(values: list[Decimal]) -> Decimal:
        return sum((values[i] for i in sel), ZERO)

    budget = total(ctx.budget)
    ed, ec, ew = total(p.earned.day), total(p.earned.cum), total(p.earned.week)
    sd, sc, sw = total(p.spent.day), total(p.spent.cum), total(p.spent.week)
    pf_day, pf_cum, pf_week = ratio(ed, sd), ratio(ec, sc), ratio(ew, sw)
    progress_cum = ratio(ec, budget)
    planned_day, planned_cum = _planned(ctx, weights)
    variance = diff(progress_cum, planned_cum)
    return SummaryRow(
        kind=kind,
        node_id=node_id,
        contractor_mix=mix,
        budget_mhr=budget,
        earned_day=ed,
        earned_cum=ec,
        earned_week=ew,
        spent_day=sd,
        spent_cum=sc,
        spent_week=sw,
        unallocated_day=total(p.unallocated.day),
        unallocated_cum=total(p.unallocated.cum),
        unallocated_week=total(p.unallocated.week),
        remaining_mhr=budget - ec,
        pf_day=pf_day,
        pf_cum=pf_cum,
        pf_week=pf_week,
        pf_day_band=pf_band(pf_day, ctx.daily_bands),
        pf_cum_band=pf_band(pf_cum, ctx.cumulative_bands),
        pf_week_band=pf_band(pf_week, ctx.cumulative_bands),
        progress_pct_day=ratio(ed, budget),
        progress_pct_cum=progress_cum,
        progress_pct_week=ratio(ew, budget),
        planned_pct_day=planned_day,
        planned_pct_cum=planned_cum,
        variance=variance,
        status=classify_status(variance, ctx.tolerance_points),
    )


def summary_rows(
    tree: Tree,
    points: Points,
    budget: list[Decimal],
    curves: Mapping[CurveKey, CurveTotals],
    tolerance_points: Decimal,
    daily_bands: PfBands,
    cumulative_bands: PfBands,
) -> tuple[SummaryRow, ...]:
    ctx = _Context(tree, points, budget, curves, tolerance_points, daily_bands, cumulative_bands)
    everything = range(len(tree))
    all_curves = dict.fromkeys(curves, Decimal(1))
    own, subcon = ContractorType.OWN, ContractorType.SUBCON
    own_w, subcon_w = _share_weights(ctx, own), _share_weights(ctx, subcon)
    rows = [
        _row(ctx, RowKind.OVERALL, everything, _is_direct, all_curves),
        _row(ctx, RowKind.OVERALL_OWN, everything, _direct_of(own), own_w),
        _row(ctx, RowKind.OVERALL_SUBCON, everything, _direct_of(subcon), subcon_w),
    ]
    for r in tree.roots:
        rows.extend(_discipline_rows(ctx, r, own_w, subcon_w))
    if any(_is_non_direct(node) for node in tree.nodes):
        rows.append(_row(ctx, RowKind.NON_DIRECT, everything, _is_non_direct, None))
    return tuple(rows)


def _discipline_rows(
    ctx: _Context,
    root: int,
    own_w: Mapping[CurveKey, Decimal] | None,
    subcon_w: Mapping[CurveKey, Decimal] | None,
) -> list[SummaryRow]:
    tree = ctx.tree
    span = range(root, tree.subtree_end[root])
    node_id = tree.nodes[root].id
    mix = contractor_mix(
        {
            point_class(tree.nodes[i])[1]
            for i in span
            if tree.is_leaf[i] and _discipline_filter(tree.nodes[i])
        }
    )
    curve = tree.curve_of[root]
    weights = None if curve is None else {curve: Decimal(1)}
    rows = [_row(ctx, RowKind.DISCIPLINE, span, _discipline_filter, weights, node_id, mix)]
    if not discipline_has_split_rows(mix):
        return rows
    for kind, row_kind, share in (
        (ContractorType.OWN, RowKind.DISCIPLINE_OWN, own_w),
        (ContractorType.SUBCON, RowKind.DISCIPLINE_SUBCON, subcon_w),
    ):
        w = None if curve is None or share is None else {curve: share.get(curve, ZERO)}
        keep = _split_filter(kind)
        rows.append(_row(ctx, row_kind, span, keep, w, node_id))
    return rows


def _split_filter(kind: ContractorType) -> Predicate:
    return lambda node: _discipline_filter(node) and point_class(node)[1] is kind
