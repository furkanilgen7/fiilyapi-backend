"""Gunluk rapor hesabi — motorun tek giris noktasi (spec §3; ilk surumde anlik hesap, §2.6)."""

from __future__ import annotations

from datetime import date
from decimal import localcontext

from .accumulate import accumulate
from .calendar import ProjectCalendar
from .metrics import node_metrics, rollup
from .numeric import ENGINE_CONTEXT, ZERO
from .plan import leaf_plan
from .policy import DEFAULT_CUMULATIVE_PF_BANDS, DEFAULT_DAILY_PF_BANDS
from .results import DailyReport, Totals
from .summary import curve_totals, summary_rows
from .tree import build_tree
from .types import EngineInput


def compute_daily_report(inp: EngineInput, report_date: date) -> DailyReport:
    """Rapor gunu d icin tum dugum metrikleri + KPI satirlari + mutabakat.

    d'den SONRAKI hareketler hicbir toplama girmez; hafta toplamlari W(d)'de kapanir.
    """
    with localcontext(ENGINE_CONTEXT):
        calendar = ProjectCalendar(inp.calendar)
        position = calendar.position(report_date)  # takvim disi d → ValueError
        tree = build_tree(inp.nodes)
        # K9: noktalar dogrulanir; yaprak noktasi varsa planli yaprak egrilerinden kurulur.
        plan = leaf_plan(tree, calendar, inp.planned_mhr, report_date)
        points = accumulate(tree, calendar, inp.qty_entries, inp.hours_entries, report_date)
        rolled = rollup(tree, points)
        daily_bands = inp.daily_pf_bands or DEFAULT_DAILY_PF_BANDS
        cumulative_bands = inp.cumulative_pf_bands or DEFAULT_CUMULATIVE_PF_BANDS
        leaf_budget = [rolled.budget[i] if tree.is_leaf[i] else ZERO for i in range(len(tree))]
        rows = summary_rows(
            tree,
            points,
            leaf_budget,
            {} if plan is not None else curve_totals(inp.planned_mhr, report_date),
            plan,
            inp.tolerance_points,
            daily_bands,
            cumulative_bands,
        )
        roots = tree.roots
        totals = Totals(
            source_hours_day=points.source_hours_day,
            source_hours_cum=points.source_hours_cum,
            spent_day=sum((rolled.spent.day[r] for r in roots), ZERO),
            spent_cum=sum((rolled.spent.cum[r] for r in roots), ZERO),
            unallocated_day=sum((rolled.unallocated.day[r] for r in roots), ZERO),
            unallocated_cum=sum((rolled.unallocated.cum[r] for r in roots), ZERO),
        )
        return DailyReport(
            report_date=report_date,
            position=position,
            nodes=node_metrics(tree, rolled, daily_bands, cumulative_bands, plan),
            rows=rows,
            totals=totals,
            unrated_entries=points.unrated_entries,
        )
