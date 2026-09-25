"""KPI satirlari: Overall, Overall–Own/Subcon, disiplin (+ own/subcon), dogrudan olmayan.

Satirlar AGAC TOPLAMINDAN degil NOKTALARDAN kurulur: her nokta (yaprak degeri ya da
saat inisi) dustugu dugumun `is_direct` / `contractor_type` alanlariyla siniflanir
(S2). Own/Subcon ayrimi alanla yapilir, satir konumuyla DEGIL (Ek A §7).

Planli %: satirin egri agirliklari `w_D` ile
    planned_mhr_row(d) = Σ_D w_D × planned_mhr(D, d)
    planned_pct_day = planned_mhr_row(d) / Σ_t planned_mhr_row(t)
    planned_pct_cum = Σ_{t<=d} planned_mhr_row(t) / Σ_t planned_mhr_row(t)
Overall ve disiplin icin w_D = 1; own/subcon icin w_D = budget_part(D) / budget(D) (S1).

K9 — yaprak egrisi verildiyse (`plan.LeafPlan`) satirin planli serisi, satirin nokta
kumesindeki YAPRAKLARIN egri toplamidir; own/subcon ve disiplin–own/subcon da boylece KESIN
olur, S1 bu modda kullanilmaz. "Dogrudan olmayan" satirinin planlisi her iki modda yok (S3).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .accumulate import Points
from .classify import classify_status, pf_band
from .numeric import ZERO, diff, ratio
from .plan import LeafPlan, planned_pct
from .policy import (
    OWN_SUBCON_PLAN_BY_BUDGET_SHARE,
    contractor_mix,
    discipline_has_split_rows,
    point_class,
)
from .results import SummaryRow
from .scope import Scope, ShareFn, curve_weights, has_plan, row_scope, scope_keep, scope_span
from .tree import Tree
from .types import (
    ContractorMix,
    ContractorType,
    CurveKey,
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
    """Disiplin (curve) anahtarli noktalarin toplamlari; yaprak noktalari atlanir."""
    acc: dict[CurveKey, list[Decimal]] = {}
    for p in planned:
        if p.curve is None:
            continue
        day, cum, total = acc.setdefault(p.curve, [ZERO, ZERO, ZERO])
        acc[p.curve] = [
            day + (p.mhr if p.day == report_date else ZERO),
            cum + (p.mhr if p.day <= report_date else ZERO),
            total + p.mhr,
        ]
    return {k: CurveTotals(*v) for k, v in acc.items()}


def share_weights(
    tree: Tree, budget: Sequence[Decimal], kind: ContractorType
) -> dict[CurveKey, Decimal] | None:
    """S1: w_D = budget_kind(D) / budget(D), direct yapraklar uzerinden (bayrak kapali → None)."""
    if not OWN_SUBCON_PLAN_BY_BUDGET_SHARE:
        return None
    whole: dict[CurveKey, Decimal] = {}
    part: dict[CurveKey, Decimal] = {}
    for i, node in enumerate(tree.nodes):
        curve = tree.curve_of[i]
        is_direct, contractor = point_class(node)
        if not tree.is_leaf[i] or not is_direct or curve is None:
            continue
        whole[curve] = whole.get(curve, ZERO) + budget[i]
        if contractor is kind:
            part[curve] = part.get(curve, ZERO) + budget[i]
    return {
        curve: share
        for curve, total in whole.items()
        if (share := ratio(part.get(curve, ZERO), total)) is not None
    }


def share_fn(tree: Tree, budget: Sequence[Decimal]) -> ShareFn:
    """Iki yuklenici tipinin S1 paylarini BIR KEZ hesaplar."""
    shares = {kind: share_weights(tree, budget, kind) for kind in ContractorType}
    return shares.__getitem__


def curve_mix(
    curves: Mapping[CurveKey, CurveTotals], weights: Mapping[CurveKey, Decimal]
) -> tuple[Decimal, Decimal, Decimal]:
    """Disiplin egrisi modu: satirin planli (gun, kum, toplam) = Σ_D w_D × egri(D)."""
    day = cum = total = ZERO
    for curve, w in weights.items():
        c = curves.get(curve)
        if c is None:
            continue
        day += w * c.day
        cum += w * c.cum
        total += w * c.total
    return day, cum, total


@dataclass(frozen=True, slots=True)
class _Context:
    tree: Tree
    points: Points
    budget: list[Decimal]  # yaprak nokta butcesi (baslik 0)
    curves: Mapping[CurveKey, CurveTotals]
    leaf_plan: LeafPlan | None
    share: ShareFn
    tolerance_points: Decimal
    daily_bands: PfBands
    cumulative_bands: PfBands


#: Satirin secili dugum dizinlerinden (gun, kum) planli %.
PlanFn = Callable[[list[int]], tuple[Decimal | None, Decimal | None]]


def _plan(ctx: _Context, scope: Scope) -> PlanFn | None:
    """K9: yaprak modunda HER KPI satiri yaprak egrisinden; aksi halde disiplin egrisi (S1)."""
    if not has_plan(scope):
        return None
    if ctx.leaf_plan is not None:
        return ctx.leaf_plan.pct
    weights = curve_weights(ctx.tree, scope, ctx.curves, ctx.share)
    if weights is None:
        return None
    return lambda _sel: planned_pct(*curve_mix(ctx.curves, weights))


def _row(
    ctx: _Context,
    kind: RowKind,
    node_id: NodeId | None = None,
    mix: ContractorMix | None = None,
) -> SummaryRow:
    scope = row_scope(kind, node_id)
    p, nodes = ctx.points, ctx.tree.nodes
    keep = scope_keep(scope)
    sel = [i for i in scope_span(ctx.tree, scope) if keep(nodes[i])]

    def total(values: list[Decimal]) -> Decimal:
        return sum((values[i] for i in sel), ZERO)

    budget = total(ctx.budget)
    ed, ec, ew = total(p.earned.day), total(p.earned.cum), total(p.earned.week)
    sd, sc, sw = total(p.spent.day), total(p.spent.cum), total(p.spent.week)
    pf_day, pf_cum, pf_week = ratio(ed, sd), ratio(ec, sc), ratio(ew, sw)
    progress_cum = ratio(ec, budget)
    plan = _plan(ctx, scope)
    planned_day, planned_cum = (None, None) if plan is None else plan(sel)
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
    leaf_plan: LeafPlan | None,
    tolerance_points: Decimal,
    daily_bands: PfBands,
    cumulative_bands: PfBands,
) -> tuple[SummaryRow, ...]:
    ctx = _Context(
        tree,
        points,
        budget,
        curves,
        leaf_plan,
        share_fn(tree, budget),
        tolerance_points,
        daily_bands,
        cumulative_bands,
    )
    rows = [
        _row(ctx, RowKind.OVERALL),
        _row(ctx, RowKind.OVERALL_OWN),
        _row(ctx, RowKind.OVERALL_SUBCON),
    ]
    for r in tree.roots:
        rows.extend(_discipline_rows(ctx, r))
    non_direct = scope_keep(row_scope(RowKind.NON_DIRECT, None))
    if any(non_direct(node) for node in tree.nodes):
        rows.append(_row(ctx, RowKind.NON_DIRECT))
    return tuple(rows)


def _discipline_rows(ctx: _Context, root: int) -> list[SummaryRow]:
    tree = ctx.tree
    node_id = tree.nodes[root].id
    scope = row_scope(RowKind.DISCIPLINE, node_id)
    keep = scope_keep(scope)
    mix = contractor_mix(
        {
            point_class(tree.nodes[i])[1]
            for i in scope_span(tree, scope)
            if tree.is_leaf[i] and keep(tree.nodes[i])
        }
    )
    rows = [_row(ctx, RowKind.DISCIPLINE, node_id, mix)]
    if not discipline_has_split_rows(mix):
        return rows
    rows.append(_row(ctx, RowKind.DISCIPLINE_OWN, node_id))
    rows.append(_row(ctx, RowKind.DISCIPLINE_SUBCON, node_id))
    return rows
