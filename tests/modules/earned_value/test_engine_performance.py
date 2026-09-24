"""Performans ölçümü (spec §2.6 / §7): 1.500 düğüm × 1.000 gün, bir günlük rapor < 2 sn.

🔴 Ölçüm testi CI'da KOŞMAZ (paylaşılan makinede süre kırılgandır): yalnız `EV_PERF=1`
ile açılır. Her koşuda çalışan duman testi ise aynı üreteci küçük boyutta sürer —
üreteç bozulursa ölçüm sessizce yanlış veriyi ölçmesin diye.

    EV_PERF=1 .venv/bin/pytest -q -s tests/modules/earned_value/test_engine_performance.py
"""

from __future__ import annotations

import os
import time

import pytest

from app.modules.earned_value.engine import RowKind, compute_daily_report

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
