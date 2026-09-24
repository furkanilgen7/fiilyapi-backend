"""PLN-B1.1 K9 — motor YAPRAK anahtarlı planlı eğriyi kabul eder (spec §3.8 K9).

Girdi: `_fixture_leaf.py` = B0 fikstürü (`_fixture.py`) + yaprak eğrileri. Rapor günü
d = gün 7 (2026-09-09). Gerçekleşenler (earned/spent/progress) B0 ile AYNIDIR; yalnız
planlı % ve variance/status değişir.

## Yaprak eğrileri — d = gün 7
| yaprak | tip    | eğri (gün 1..10)             | Σ   | gün 7 | küm ≤ 7 |
|--------|--------|------------------------------|-----|-------|---------|
| L1     | own    | 20 20 20 0 20 20 20 30 30 20 | 200 | 20    | 120     |
| L2     | subcon | 0 10 10 0 10 10 10 20 20 10  | 100 | 10    | 50      |
| L3     | own    | 25 25 25 0 25 0 0 0 0 0      | 100 | 0     | 100     |
| L4     | own    | 0 0 0 0 10 10 10 20 20 30    | 100 | 10    | 30      |
| L5     | dolaylı| — (eğrisiz)                  | –   | –     | –       |

## KPI satırları — satırın planlı serisi = nokta kümesindeki YAPRAK eğrilerinin toplamı
| satır      | yapraklar | Σ   | gün | küm | plan g · küm     | gerç. küm (B0) | variance | durum  |
|------------|-----------|-----|-----|-----|------------------|----------------|----------|--------|
| Overall    | L1–L4     | 500 | 40  | 300 | 40/500 · 0,6     | 200/500 = 0,4  | −0,2     | Late   |
| Ov.–Own    | L1 L3 L4  | 400 | 30  | 250 | 30/400 · 0,625   | 170/400        | −0,2     | Late   |
| Ov.–Subcon | L2        | 100 | 10  | 50  | 0,1 · 0,5        | 0,3            | −0,2     | Late   |
| D1         | L1 L2 L3  | 400 | 30  | 270 | 30/400 · 0,675   | 170/400        | −0,25    | Late   |
| D1–own     | L1 L3     | 300 | 20  | 220 | 20/300 · 220/300 | 140/300        | −80/300  | Late   |
| D1–subcon  | L2        | 100 | 10  | 50  | 0,1 · 0,5        | 0,3            | −0,2     | Late   |
| D2 (own)   | L4        | 100 | 10  | 30  | 0,1 · 0,3        | 0,3            | 0        | Normal |
| Doğr. değil| —         | –   | –   | –   | – · –            | 1              | –        | –      |

S1 (bütçe payı) ile farkı: Ov.–Own S1'de 155/400 = 0,3875 idi, yaprakla 0,625 — kesin.
D1–own S1'de D1 ile AYNI (180/400) idi, yaprakla 220/300 ≠ D1 (270/400).

## Ağaç düğümleri (alt ağaçtaki eğrili yapraklar)
L1 0,1 · 0,6 · L2 0,1 · 0,5 · L3 0 · 1 · L4 0,1 · 0,3 · L5 – · – ·
T1 (L1+L2) 30/300 · 170/300 · T2 (L3) 0 · 1 · D1 30/400 · 270/400 · T3 = D2 (L4) 0,1 · 0,3.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    DailyReport,
    PlannedMhr,
    RowKind,
    Status,
    compute_daily_report,
)

from ._fixture import REPORT_DATE, build_input, day
from ._fixture_leaf import LEAF_CURVES, build_leaf_input, leaf_points

D = Decimal


def q(a: int | str, b: int | str) -> Decimal:
    return D(a) / D(b)


@pytest.fixture(scope="module")
def report() -> DailyReport:
    return compute_daily_report(build_leaf_input(), REPORT_DATE)


LATE, NORMAL = Status.LATE, Status.NORMAL
ROWS = {
    # (kind, node_id): planned gün, planned küm, progress küm, durum
    (RowKind.OVERALL, None): (q(40, 500), q(300, 500), q(200, 500), LATE),
    (RowKind.OVERALL_OWN, None): (q(30, 400), q(250, 400), q(170, 400), LATE),
    (RowKind.OVERALL_SUBCON, None): (q(10, 100), q(50, 100), q(30, 100), LATE),
    (RowKind.DISCIPLINE, "D1"): (q(30, 400), q(270, 400), q(170, 400), LATE),
    (RowKind.DISCIPLINE_OWN, "D1"): (q(20, 300), q(220, 300), q(140, 300), LATE),
    (RowKind.DISCIPLINE_SUBCON, "D1"): (q(10, 100), q(50, 100), q(30, 100), LATE),
    (RowKind.DISCIPLINE, "D2"): (q(10, 100), q(30, 100), q(30, 100), NORMAL),
}


@pytest.mark.parametrize("key", list(ROWS), ids=lambda k: f"{k[0].value}-{k[1]}")
def test_kpi_rows_planned_from_leaf_curves(
    report: DailyReport, key: tuple[RowKind, str | None]
) -> None:
    plan_day, plan_cum, prog_cum, status = ROWS[key]
    r = report.row(*key)
    assert (r.planned_pct_day, r.planned_pct_cum) == (plan_day, plan_cum)
    assert r.progress_pct_cum == prog_cum
    assert r.variance == prog_cum - plan_cum
    assert r.status is status


def test_non_direct_row_has_no_plan(report: DailyReport) -> None:
    r = report.row(RowKind.NON_DIRECT)
    assert (r.planned_pct_day, r.planned_pct_cum, r.variance, r.status) == (None,) * 4


NODES = {
    "L1": (q(20, 200), q(120, 200)),
    "L2": (q(10, 100), q(50, 100)),
    "L3": (D(0), D(1)),
    "L4": (q(10, 100), q(30, 100)),
    "L5": (None, None),
    "T1": (q(30, 300), q(170, 300)),
    "T2": (D(0), D(1)),
    "D1": (q(30, 400), q(270, 400)),
    "T3": (q(10, 100), q(30, 100)),
    "D2": (q(10, 100), q(30, 100)),
}


@pytest.mark.parametrize("node_id", list(NODES))
def test_node_planned_pct_from_subtree_leaf_curves(report: DailyReport, node_id: str) -> None:
    m = report.nodes[node_id]
    assert (m.planned_pct_day, m.planned_pct_cum) == NODES[node_id]


def test_actuals_do_not_change_with_leaf_curves(report: DailyReport) -> None:
    b0 = compute_daily_report(build_input(), REPORT_DATE)
    for kind_id in ROWS:
        a, b = report.row(*kind_id), b0.row(*kind_id)
        assert (a.budget_mhr, a.earned_cum, a.spent_cum) == (
            b.budget_mhr,
            b.earned_cum,
            b.spent_cum,
        )
    assert report.totals == b0.totals


def test_curve_mode_node_planned_pct_is_none() -> None:
    b0 = compute_daily_report(build_input(), REPORT_DATE)
    assert all((m.planned_pct_day, m.planned_pct_cum) == (None, None) for m in b0.nodes.values())
    # B0 davranışı AYNEN (S1 bütçe payı)
    assert b0.row(RowKind.OVERALL_OWN).planned_pct_cum == q(155, 400)


def test_leaf_mode_leaf_without_curve_is_out_of_the_plan() -> None:
    curves = {k: v for k, v in LEAF_CURVES.items() if k != "L4"}
    inp = replace(build_input(), planned_mhr=leaf_points(curves))
    r = compute_daily_report(inp, REPORT_DATE)
    # D2'nin tek direct yaprağı eğrisiz → planlı yok; disiplin eğrisine GERİ DÖNÜLMEZ
    assert r.row(RowKind.DISCIPLINE, "D2").planned_pct_cum is None
    assert r.row(RowKind.OVERALL).planned_pct_cum == q(270, 400)
    assert r.nodes["D2"].planned_pct_cum is None


def test_planned_mhr_requires_exactly_one_key() -> None:
    with pytest.raises(ValueError):
        PlannedMhr(None, day(1), D(1))
    with pytest.raises(ValueError):
        PlannedMhr("KAB", day(1), D(1), node_id="L1")
    assert PlannedMhr.for_leaf("L1", day(1), D(1)) == PlannedMhr(None, day(1), D(1), "L1")


def test_planned_mhr_for_leaf_rejects_float() -> None:
    with pytest.raises(TypeError):
        PlannedMhr.for_leaf("L1", day(1), 1.0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("node_id", "when", "match"),
    [
        ("T1", day(1), "yaprak"),  # başlık
        ("YOK", day(1), "bilinmeyen"),
        ("L1", date(2026, 9, 13), "takvim"),  # takvim dışı
    ],
    ids=["baslik", "bilinmeyen", "takvim-disi"],
)
def test_leaf_point_validation(node_id: str, when: date, match: str) -> None:
    bad = PlannedMhr.for_leaf(node_id, when, D(1))
    inp = replace(build_leaf_input(), planned_mhr=(*leaf_points(), bad))
    with pytest.raises(ValueError, match=match):
        compute_daily_report(inp, REPORT_DATE)
