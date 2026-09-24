"""Alt agac toplamlari (baslik = Σ yaprak) ve dugum turevleri (spec §3.2–§3.4).

Toplanabilir buyuklukler (miktar, earned, spent, butce, togo) noktalardan TEK geriye
tarama ile yukari toplanir; oranlar HER dugumde kendi toplamlarinin orani olarak
hesaplanir (pf_cum = earned_cum / spent_cum — ortalamalarin ortalamasi DEGIL).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .accumulate import Points, Triple
from .classify import pf_band
from .numeric import ZERO, diff, ratio
from .plan import LeafPlan
from .policy import HEADER_QTY_REQUIRES_UNIFORM_UOM
from .results import NodeMetrics
from .tree import Tree
from .types import PfBands


@dataclass(slots=True)
class Rollup:
    qty: Triple
    earned: Triple
    spent: Triple
    unallocated: Triple
    budget: list[Decimal]
    planned_qty: list[Decimal]
    togo: list[Decimal]
    prev_budget: list[Decimal | None]
    prev_planned_qty: list[Decimal | None]


def _copy(t: Triple) -> Triple:
    out = Triple(0)
    out.day, out.cum, out.week = list(t.day), list(t.cum), list(t.week)
    return out


def _add_opt(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if b is None:
        return a
    return b if a is None else a + b


def rollup(tree: Tree, points: Points) -> Rollup:
    n = len(tree)
    budget, planned_qty, togo = [ZERO] * n, [ZERO] * n, [ZERO] * n
    prev_budget: list[Decimal | None] = [None] * n
    prev_planned_qty: list[Decimal | None] = [None] * n
    for i, node in enumerate(tree.nodes):
        if not tree.is_leaf[i]:
            continue
        pq = node.planned_qty
        assert pq is not None  # build_tree dogruladi
        rate = node.unit_mhr if node.unit_mhr is not None else ZERO  # K12: oransiz → 0
        budget[i] = pq * rate
        planned_qty[i] = pq
        togo[i] = (pq - points.qty.cum[i]) * rate  # togo = remaining_qty × unit_mhr
        if node.prev_planned_qty is not None and node.prev_unit_mhr is not None:
            prev_planned_qty[i] = node.prev_planned_qty
            prev_budget[i] = node.prev_planned_qty * node.prev_unit_mhr

    r = Rollup(
        qty=_copy(points.qty),
        earned=_copy(points.earned),
        spent=_copy(points.spent),
        unallocated=_copy(points.unallocated),
        budget=budget,
        planned_qty=planned_qty,
        togo=togo,
        prev_budget=prev_budget,
        prev_planned_qty=prev_planned_qty,
    )
    triples = (r.qty, r.earned, r.spent, r.unallocated)
    for i in range(n - 1, 0, -1):
        p = tree.parent[i]
        if p < 0:
            continue
        for t in triples:
            t.day[p] += t.day[i]
            t.cum[p] += t.cum[i]
            t.week[p] += t.week[i]
        budget[p] += budget[i]
        planned_qty[p] += planned_qty[i]
        togo[p] += togo[i]
        prev_budget[p] = _add_opt(prev_budget[p], prev_budget[i])
        prev_planned_qty[p] = _add_opt(prev_planned_qty[p], prev_planned_qty[i])
    return r


def node_metrics(
    tree: Tree,
    r: Rollup,
    daily_bands: PfBands,
    cumulative_bands: PfBands,
    plan: LeafPlan | None = None,
) -> dict[object, NodeMetrics]:
    out: dict[object, NodeMetrics] = {}
    planned = plan.subtree_pct(tree) if plan is not None else [(None, None)] * len(tree)
    for i, node in enumerate(tree.nodes):
        uom = tree.uom_of[i]
        # S4: karma birimli baslikta qty tabanli alanlar tanimsiz.
        qty_ok = uom is not None or not HEADER_QTY_REQUIRES_UNIFORM_UOM
        leaf = tree.is_leaf[i]
        budget = r.budget[i]
        qd, qc, qw = (r.qty.day[i], r.qty.cum[i], r.qty.week[i]) if qty_ok else (None,) * 3
        ed, ec, ew = r.earned.day[i], r.earned.cum[i], r.earned.week[i]
        sd, sc, sw = r.spent.day[i], r.spent.cum[i], r.spent.week[i]
        pq = r.planned_qty[i] if qty_ok else None
        planned_rate = node.unit_mhr if leaf else ratio(budget, pq)
        aum = (ratio(sd, qd), ratio(sc, qc), ratio(sw, qw))
        pf = (ratio(ed, sd), ratio(ec, sc), ratio(ew, sw))
        prev_pq = r.prev_planned_qty[i] if qty_ok else None
        out[node.id] = NodeMetrics(
            node_id=node.id,
            is_leaf=leaf,
            uom=uom,
            qty_day=qd,
            qty_cum=qc,
            qty_week=qw,
            planned_qty=pq,
            remaining_qty=diff(pq, qc),
            budget_mhr=budget,
            earned_day=ed,
            earned_cum=ec,
            earned_week=ew,
            spent_day=sd,
            spent_cum=sc,
            spent_week=sw,
            unallocated_day=r.unallocated.day[i],
            unallocated_cum=r.unallocated.cum[i],
            unallocated_week=r.unallocated.week[i],
            remaining_mhr=budget - ec,
            togo_mhr=r.togo[i],
            planned_unit_mhr=planned_rate,
            actual_unit_mhr_day=aum[0],
            actual_unit_mhr_cum=aum[1],
            actual_unit_mhr_week=aum[2],
            unit_rate_pf_day=ratio(planned_rate, aum[0]),
            unit_rate_pf_cum=ratio(planned_rate, aum[1]),
            unit_rate_pf_week=ratio(planned_rate, aum[2]),
            pf_day=pf[0],
            pf_cum=pf[1],
            pf_week=pf[2],
            pf_day_band=pf_band(pf[0], daily_bands),
            pf_cum_band=pf_band(pf[1], cumulative_bands),
            pf_week_band=pf_band(pf[2], cumulative_bands),
            progress_pct_day=ratio(ed, budget),
            progress_pct_cum=ratio(ec, budget),
            progress_pct_week=ratio(ew, budget),
            planned_pct_day=planned[i][0],
            planned_pct_cum=planned[i][1],
            prev_planned_qty=prev_pq,
            prev_unit_mhr=node.prev_unit_mhr if leaf else ratio(r.prev_budget[i], prev_pq),
            prev_budget_mhr=r.prev_budget[i],
        )
    return out
