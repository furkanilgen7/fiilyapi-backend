"""Performans ölçümü (spec §2.6 / §7): 1.500 düğüm × 1.000 gün, bir günlük rapor < 2 sn;
PLN-B3.1 seri (`compute_series`, 8 kapsam) son 90 gün ve tüm aralık, her biri < 2 sn.

🔴 Ölçüm testi CI'da KOŞMAZ (paylaşılan makinede süre kırılgandır): yalnız `EV_PERF=1`
ile açılır. Her koşuda çalışan duman testi ise aynı üreteci küçük boyutta sürer —
üreteç bozulursa ölçüm sessizce yanlış veriyi ölçmesin diye.

    EV_PERF=1 .venv/bin/pytest -q -s tests/modules/earned_value/test_engine_performance.py
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import timedelta

import pytest

from app.modules.earned_value.engine import (
    ContractorType,
    RowKind,
    Scope,
    compute_daily_report,
    compute_series,
    scope_for_row,
)

from ._synthetic import build

BUDGET_SECONDS = 2.0


@pytest.mark.parametrize("leaf_curves", [False, True], ids=["egri", "yaprak"])
def test_synthetic_generator_smoke(leaf_curves: bool) -> None:
    inp, report_date = build(
        disciplines=2, subgroups=2, job_types=3, leaves_total=30, days=80, leaf_curves=leaf_curves
    )
    assert len(inp.nodes) == 2 + 4 + 12 + 30
    report = compute_daily_report(inp, report_date)
    assert report.totals.spent_cum == report.totals.source_hours_cum > 0
    assert report.row(RowKind.OVERALL).earned_cum > 0
    assert report.row(RowKind.OVERALL).planned_pct_cum is not None
    has_node_plan = report.nodes["D0"].planned_pct_cum is not None
    assert has_node_plan is leaf_curves
    if leaf_curves:
        assert all(p.node_id is not None for p in inp.planned_mhr)
        assert len(inp.planned_mhr) == 30 * 60


@pytest.mark.skipif(os.environ.get("EV_PERF") != "1", reason="ölçüm: EV_PERF=1 ile koşar")
@pytest.mark.parametrize("leaf_curves", [False, True], ids=["egri", "yaprak"])
def test_daily_report_1500_nodes_1000_days_under_budget(leaf_curves: bool) -> None:
    inp, report_date = build(leaf_curves=leaf_curves)
    assert len(inp.nodes) == 1500
    runs = []
    for _ in range(3):
        t0 = time.perf_counter()
        report = compute_daily_report(inp, report_date)
        runs.append(time.perf_counter() - t0)
    print(
        f"\n[EV_PERF] mode={'yaprak' if leaf_curves else 'egri'} nodes={len(inp.nodes)} "
        f"qty={len(inp.qty_entries)} "
        f"hours={len(inp.hours_entries)} planned={len(inp.planned_mhr)} "
        f"runs={[round(r, 3) for r in runs]} best={min(runs):.3f}s"
    )
    assert report.totals.spent_cum == report.totals.source_hours_cum
    assert min(runs) < BUDGET_SECONDS


#: Panel: Overall + Own + Subcon + 5 disiplin = 8 kapsam (sentetik ağaç: D0..D4).
PANEL_SCOPES = (
    Scope(),
    Scope(contractor=ContractorType.OWN),
    Scope(contractor=ContractorType.SUBCON),
    *(Scope(root=f"D{d}") for d in range(5)),
)
S_CURVE_DAYS = 90
TREND_REPORTS = 7


def _best_of(fn: Callable[[], object], runs: int = 3) -> tuple[float, object]:
    times, result = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return min(times), result


@pytest.mark.parametrize("leaf_curves", [False, True], ids=["egri", "yaprak"])
def test_synthetic_series_smoke_matches_daily_report(leaf_curves: bool) -> None:
    inp, report_date = build(
        disciplines=2, subgroups=2, job_types=3, leaves_total=30, days=80, leaf_curves=leaf_curves
    )
    report = compute_daily_report(inp, report_date)
    scopes = [scope_for_row(r) for r in report.rows]
    series = compute_series(inp, report_date - timedelta(days=9), report_date, scopes)
    for row in report.rows:
        p = series.get(scope_for_row(row)).at(report_date)
        assert (p.earned_cum, p.spent_cum, p.planned_pct_cum, p.status) == (
            row.earned_cum,
            row.spent_cum,
            row.planned_pct_cum,
            row.status,
        )


@pytest.mark.skipif(os.environ.get("EV_PERF") != "1", reason="ölçüm: EV_PERF=1 ile koşar")
@pytest.mark.parametrize("leaf_curves", [False, True], ids=["egri", "yaprak"])
def test_series_1500_nodes_1000_days_under_budget(leaf_curves: bool) -> None:
    inp, end = build(leaf_curves=leaf_curves)
    start = inp.calendar.start_date
    s_curve_start = end - timedelta(days=S_CURVE_DAYS - 1)
    t_90, last_90 = _best_of(
        lambda: compute_series(inp, s_curve_start, end, PANEL_SCOPES, as_of=end)
    )
    t_all, whole = _best_of(lambda: compute_series(inp, start, end, PANEL_SCOPES, as_of=end))
    trend_days = [end - timedelta(days=k) for k in range(TREND_REPORTS)]
    t_daily, _ = _best_of(lambda: [compute_daily_report(inp, d) for d in trend_days], runs=1)
    print(
        f"\n[EV_PERF] series mode={'yaprak' if leaf_curves else 'egri'} "
        f"scopes={len(PANEL_SCOPES)} son{S_CURVE_DAYS}g={t_90:.3f}s tum={t_all:.3f}s · "
        f"{TREND_REPORTS}×compute_daily_report={t_daily:.3f}s "
        f"(×{t_daily / t_all:.1f} tum-aralik serisine gore)"
    )
    report = compute_daily_report(inp, end)
    overall = report.row(RowKind.OVERALL)
    for result in (last_90, whole):
        p = result.get(Scope()).at(end)  # type: ignore[attr-defined]
        assert (p.earned_cum, p.spent_cum, p.planned_pct_cum) == (
            overall.earned_cum,
            overall.spent_cum,
            overall.planned_pct_cum,
        )
    assert len(whole.get(Scope()).points) == (end - start).days + 1  # type: ignore[attr-defined]
    assert t_90 < BUDGET_SECONDS
    assert t_all < BUDGET_SECONDS
