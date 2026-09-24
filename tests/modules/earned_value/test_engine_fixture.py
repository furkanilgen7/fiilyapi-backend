"""PLN-B0 kabul fikstürü — ELLE hesaplanmış beklenenler (PLANLAMA-SPEC §7, §3, §3.7).

Girdi: `_fixture.py` (ağaç, miktarlar, saatler, eğri). Rapor günü d = gün 7 (2026-09-09 Çar).
Hafta penceresi W(d) = [gün 5 (Pzt 07.09), gün 7] · gün 8+ girdileri rapora GİRMEZ.

## 1. Takvim
gün_no 7 · hafta_no 2 · hafta başı 07.09 · hafta sonu 13.09 · pencere 07.09–09.09 · tatil değil.
(1. hafta KISMİ: 03.09 Per – 06.09 Paz; 06.09 = tatil.)

## 2. Miktar (≤ d) — gün / kümülatif / hafta
| yaprak | girişler (gün:miktar)            | gün | küm | hafta | oran | earned g/k/h  | bütçe |
|--------|----------------------------------|-----|-----|-------|------|---------------|-------|
| L1 m3  | 1:5 2:5 3:10 5:10 7:20 (8:10 ✗)  | 20  | 50  | 30    | 2,00 | 40 / 100 / 60 | 200   |
| L2 m3  | 2:4 5:6 7:5 (9:5 ✗)              | 5   | 15  | 11    | 2,00 | 10 / 30 / 22  | 100   |
| L3 m2  | 1:20 3:20 6:40                   | 0   | 80  | 40    | 0,50 | 0 / 40 / 20   | 100   |
| L4 m   | 5:8 6:8 7:8                      | 8   | 24  | 24    | 1,25 | 10 / 30 / 30  | 100   |
| L5 adet| 1:1                              | 0   | 1   | 0     | 40   | 0 / 40 / 0    | 40    |

## 3. Saat → düğüm
A (T1, prorata; T1 yaprakları L1, L2 — o günkü qty payıyla):
| gün | saat | T1 qty (L1+L2) | L1   | L2   | T1 unallocated |
|-----|------|----------------|------|------|----------------|
| 1   | 12   | 5+0            | 12   | 0    | 0              |
| 2   | 18   | 5+4 = 9        | 10   | 8    | 0              |
| 3   | 20   | 10+0           | 20   | 0    | 0              |
| 5   | 32   | 10+6 = 16      | 20   | 12   | 0              |
| 6   | 8    | 0 (miktar yok) | 0    | 0    | **8**          |
| 7   | 30   | 20+5 = 25      | 24   | 6    | 0              |
| 8   | 10   | ✗ (d'den sonra)|      |      |                |
L1 spent g/k/h = 24 / 86 / 44 · L2 = 6 / 26 / 18 · T1 unallocated = 0 / 8 / 8
T1 spent = 30 / 120 / 70  (86 + 26 + 8 = 120 ✓ kaynak toplamı)

B (D2 BAŞLIK, direct): 1:10 3:12 6:20 7:6 → D2 spent = 6 / 48 / 26; T3, L4, L5 spent = 0.

## 4. Ağaç düğümleri (tüm alt ağaç; S3)
| düğüm | uom  | qty g/k/h | earned g/k/h | spent g/k/h | bütçe | pf_cum        |
|-------|------|-----------|--------------|-------------|-------|---------------|
| T1    | m3   | 25/65/41  | 50/130/82    | 30/120/70   | 300   | 130/120       |
| T2    | m2   | 0/80/40   | 0/40/20      | 0/0/0       | 100   | – (÷0)        |
| D1    | karma| –         | 50/170/102   | 30/120/70   | 400   | 170/120       |
| T3    | m    | 8/24/24   | 10/30/30     | 0/0/0       | 100   | – (÷0)        |
| D2    | karma| –         | 10/70/30     | 6/48/26     | 140   | 70/48         |
T1 planned_qty 150 · planned_unit_mhr = 300/150 = 2 (S4) · remaining_qty 85 · remaining/togo 170.
L1 remaining_qty 50 · togo 100 · actual_unit_mhr g/k/h = 24/20 · 86/50 · 44/30.
Rev0 bütçe: L1 90×2,2 = 198 · T1 198+100 = 298 (prev pq 140) · D1 398 · D2 80+40 = 120.

## 5. Eğri (planned_mhr) — gün 1..10
KAB 30 30 30 0 30 30 30 70 70 80 (Σ 400) · MEK 0 0 0 0 5 5 10 20 30 30 (Σ 100)
d = gün 7: KAB gün 30 / küm 180 · MEK gün 10 / küm 20.

S1 (bütçe payı): KAB direct bütçe 400 = own 300 (L1, L3) + subcon 100 (L2) → pay ¾ / ¼.
MEK direct bütçe 100 = own 100.
own eğrisi = ¾·KAB + MEK → Σ 400 · küm 155 · gün 32,5
subcon eğrisi = ¼·KAB → Σ 100 · küm 45 · gün 7,5

## 6. KPI satırları (yalnız direct; S3) — tolerans 0
| satır | bütçe | earned g/k/h | spent g/k/h | plan g · küm | gerç. küm | variance | durum |
|---|---|---|---|---|---|---|---|
| Overall | 500 | 60/200/132 | 36/168/96 | 40/500 · 200/500 | 200/500 | 0 | Normal |
| Ov.–Own | 400 | 50/170/110 | 30/142/78 | 32,5/400 · 155/400| 170/400 | +0,0375 | Ahead |
| Ov.–Subcon | 100 | 10/30/22 | 6/26/18 | 7,5/100 · 45/100 | 30/100 | −0,15 | Late |
| D1 (karma) | 400 | 50/170/102 | 30/120/70 | 30/400 · 180/400 | 170/400 | −0,025 | Late |
| D1–own | 300 | 40/140/80 | 24/94/52 | 30/400 · 180/400 | 140/300 | +1/60 | Ahead |
| D1–subcon | 100 | 10/30/22 | 6/26/18 | 30/400 · 180/400 | 30/100 | −0,15 | Late |
| D2 (own) | 100 | 10/30/30 | 6/48/26 | 10/100 · 20/100 | 30/100 | +0,1 | Ahead |
| Doğr. değil| 40 | 0/40/0 | 0/0/0 | – | 40/40 | – | – |
Overall–Own spent: L1 (86) + T1 unallocated (8, T1 own; S2) + D2 başlığı (48, D2 own; S2) = 142.
D2 için alt satır YOK (tek tip; S7), contractor_mix = own; D1 contractor_mix = mixed.

## 7. PF bantları (S6)
Günlük: < 0,95 kırmızı · [0,95; 1,05] yeşil · > 1,05 HIGH. Küm/hafta: < 0,95 kırmızı ·
[0,95; 1,00) amber · ≥ 1,00 yeşil.
Overall pf_day 60/36 → HIGH · pf_cum 200/168 → yeşil · D2 satırı pf_cum 30/48 = 0,625 → kırmızı.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    ContractorMix,
    DailyReport,
    PfBand,
    RowKind,
    Status,
    compute_daily_report,
)

from ._fixture import REPORT_DATE, build_input

D = Decimal


def q(a: int | str, b: int | str) -> Decimal:
    """Elle kesir a/b — motorla aynı 28 hanelik bağlamda (Python varsayılanı)."""
    return D(a) / D(b)


@pytest.fixture(scope="module")
def report() -> DailyReport:
    return compute_daily_report(build_input(), REPORT_DATE)


def test_calendar_position(report: DailyReport) -> None:
    pos = report.position
    assert (pos.day_no, pos.week_no) == (7, 2)
    assert pos.week_start == date(2026, 9, 7)
    assert pos.week_end == date(2026, 9, 13)
    assert (pos.window_start, pos.window_end) == (date(2026, 9, 7), date(2026, 9, 9))
    assert pos.is_holiday is False


LEAVES = {
    # qty g/k/h, earned g/k/h, budget, spent g/k/h
    "L1": ((20, 50, 30), (40, 100, 60), 200, (24, 86, 44)),
    "L2": ((5, 15, 11), (10, 30, 22), 100, (6, 26, 18)),
    "L3": ((0, 80, 40), (0, 40, 20), 100, (0, 0, 0)),
    "L4": ((8, 24, 24), (10, 30, 30), 100, (0, 0, 0)),
    "L5": ((0, 1, 0), (0, 40, 0), 40, (0, 0, 0)),
}


@pytest.mark.parametrize("node_id", sorted(LEAVES))
def test_leaf_quantities_earned_spent(report: DailyReport, node_id: str) -> None:
    (qd, qc, qw), (ed, ec, ew), budget, (sd, sc, sw) = LEAVES[node_id]
    m = report.nodes[node_id]
    assert (m.qty_day, m.qty_cum, m.qty_week) == (qd, qc, qw)
    assert (m.earned_day, m.earned_cum, m.earned_week) == (ed, ec, ew)
    assert m.budget_mhr == budget
    assert (m.spent_day, m.spent_cum, m.spent_week) == (sd, sc, sw)
    assert (m.unallocated_day, m.unallocated_cum, m.unallocated_week) == (0, 0, 0)


HEADERS = {
    # uom, qty g/k/h (None = karma birim), earned g/k/h, spent g/k/h, unalloc g/k/h, budget
    "T1": ("m3", (25, 65, 41), (50, 130, 82), (30, 120, 70), (0, 8, 8), 300),
    "T2": ("m2", (0, 80, 40), (0, 40, 20), (0, 0, 0), (0, 0, 0), 100),
    "D1": (None, None, (50, 170, 102), (30, 120, 70), (0, 8, 8), 400),
    "T3": ("m", (8, 24, 24), (10, 30, 30), (0, 0, 0), (0, 0, 0), 100),
    "D2": (None, None, (10, 70, 30), (6, 48, 26), (0, 0, 0), 140),
}


@pytest.mark.parametrize("node_id", sorted(HEADERS))
def test_header_rollups(report: DailyReport, node_id: str) -> None:
    uom, qty, earned, spent, unalloc, budget = HEADERS[node_id]
    m = report.nodes[node_id]
    assert m.uom == uom
    assert (m.qty_day, m.qty_cum, m.qty_week) == (qty or (None, None, None))
    assert (m.earned_day, m.earned_cum, m.earned_week) == earned
    assert (m.spent_day, m.spent_cum, m.spent_week) == spent
    assert (m.unallocated_day, m.unallocated_cum, m.unallocated_week) == unalloc
    assert m.budget_mhr == budget


def test_leaf_l1_derivatives(report: DailyReport) -> None:
    m = report.nodes["L1"]
    assert (m.planned_qty, m.planned_unit_mhr) == (100, D("2.00"))
    assert (m.remaining_qty, m.remaining_mhr, m.togo_mhr) == (50, 100, 100)
    assert (m.pf_day, m.pf_cum, m.pf_week) == (q(40, 24), q(100, 86), q(60, 44))
    assert (m.actual_unit_mhr_day, m.actual_unit_mhr_cum, m.actual_unit_mhr_week) == (
        q(24, 20),
        q(86, 50),
        q(44, 30),
    )
    assert m.unit_rate_pf_day == D("2.00") / q(24, 20)
    assert m.unit_rate_pf_cum == D("2.00") / q(86, 50)
    assert (m.progress_pct_day, m.progress_pct_cum, m.progress_pct_week) == (
        q(40, 200),
        q(100, 200),
        q(60, 200),
    )
    assert (m.prev_planned_qty, m.prev_unit_mhr, m.prev_budget_mhr) == (90, D("2.20"), 198)


def test_header_t1_derivatives(report: DailyReport) -> None:
    m = report.nodes["T1"]
    assert (m.planned_qty, m.planned_unit_mhr) == (150, 2)
    assert (m.remaining_qty, m.remaining_mhr, m.togo_mhr) == (85, 170, 170)
    assert (m.pf_day, m.pf_cum, m.pf_week) == (q(50, 30), q(130, 120), q(82, 70))
    assert m.actual_unit_mhr_cum == q(120, 65)
    assert m.unit_rate_pf_cum == 2 / q(120, 65)
    assert m.progress_pct_cum == q(130, 300)
    assert (m.prev_planned_qty, m.prev_budget_mhr) == (140, D("298.00"))
    assert m.prev_unit_mhr == q("298.00", 140)


def test_discipline_nodes_carry_whole_subtree(report: DailyReport) -> None:
    d1, d2 = report.nodes["D1"], report.nodes["D2"]
    assert (d1.remaining_mhr, d1.togo_mhr, d1.pf_cum) == (230, 230, q(170, 120))
    assert d1.prev_budget_mhr == D("398.00")
    # D2 non-direct L5'i de taşır (S3: ağaç metrikleri tüm alt ağaç)
    assert (d2.budget_mhr, d2.pf_cum, d2.progress_pct_cum) == (140, q(70, 48), q(70, 140))
    assert d2.prev_budget_mhr == D("120.00")


def test_zero_division_is_none_in_fixture(report: DailyReport) -> None:
    for node_id in ("L3", "L4", "L5", "T2", "T3"):
        m = report.nodes[node_id]
        assert (m.pf_day, m.pf_cum, m.pf_week) == (None, None, None), node_id
    l3 = report.nodes["L3"]
    assert l3.actual_unit_mhr_day is None  # 0 saat / 0 miktar
    assert l3.actual_unit_mhr_cum == 0  # 0 saat / 80 miktar
    assert l3.unit_rate_pf_cum is None  # oran / 0


ROWS = {
    # (kind, node_id): budget, earned g/k/h, spent g/k/h, planned g, planned küm, progress küm,
    #                  variance, status
    (RowKind.OVERALL, None): (
        500,
        (60, 200, 132),
        (36, 168, 96),
        q(40, 500),
        q(200, 500),
        q(200, 500),
        D(0),
        Status.NORMAL,
    ),
    (RowKind.OVERALL_OWN, None): (
        400,
        (50, 170, 110),
        (30, 142, 78),
        q("32.5", 400),
        q(155, 400),
        q(170, 400),
        q(170, 400) - q(155, 400),
        Status.AHEAD,
    ),
    (RowKind.OVERALL_SUBCON, None): (
        100,
        (10, 30, 22),
        (6, 26, 18),
        q("7.5", 100),
        q(45, 100),
        q(30, 100),
        q(30, 100) - q(45, 100),
        Status.LATE,
    ),
    (RowKind.DISCIPLINE, "D1"): (
        400,
        (50, 170, 102),
        (30, 120, 70),
        q(30, 400),
        q(180, 400),
        q(170, 400),
        q(170, 400) - q(180, 400),
        Status.LATE,
    ),
    (RowKind.DISCIPLINE_OWN, "D1"): (
        300,
        (40, 140, 80),
        (24, 94, 52),
        q(30, 400),
        q(180, 400),
        q(140, 300),
        q(140, 300) - q(180, 400),
        Status.AHEAD,
    ),
    (RowKind.DISCIPLINE_SUBCON, "D1"): (
        100,
        (10, 30, 22),
        (6, 26, 18),
        q(30, 400),
        q(180, 400),
        q(30, 100),
        q(30, 100) - q(180, 400),
        Status.LATE,
    ),
    (RowKind.DISCIPLINE, "D2"): (
        100,
        (10, 30, 30),
        (6, 48, 26),
        q(10, 100),
        q(20, 100),
        q(30, 100),
        q(30, 100) - q(20, 100),
        Status.AHEAD,
    ),
    (RowKind.NON_DIRECT, None): (
        40,
        (0, 40, 0),
        (0, 0, 0),
        None,
        None,
        q(40, 40),
        None,
        None,
    ),
}


def test_row_set_and_order(report: DailyReport) -> None:
    assert [(r.kind, r.node_id) for r in report.rows] == [
        (RowKind.OVERALL, None),
        (RowKind.OVERALL_OWN, None),
        (RowKind.OVERALL_SUBCON, None),
        (RowKind.DISCIPLINE, "D1"),
        (RowKind.DISCIPLINE_OWN, "D1"),
        (RowKind.DISCIPLINE_SUBCON, "D1"),
        (RowKind.DISCIPLINE, "D2"),
        (RowKind.NON_DIRECT, None),
    ]


@pytest.mark.parametrize("key", list(ROWS), ids=lambda k: f"{k[0].value}-{k[1]}")
def test_kpi_rows(report: DailyReport, key: tuple[RowKind, str | None]) -> None:
    budget, earned, spent, plan_day, plan_cum, prog_cum, variance, status = ROWS[key]
    r = report.row(*key)
    assert r.budget_mhr == budget
    assert (r.earned_day, r.earned_cum, r.earned_week) == earned
    assert (r.spent_day, r.spent_cum, r.spent_week) == spent
    assert (r.planned_pct_day, r.planned_pct_cum) == (plan_day, plan_cum)
    assert r.progress_pct_cum == prog_cum
    assert r.variance == variance
    assert r.status is status


def test_contractor_mix_badges(report: DailyReport) -> None:
    assert report.row(RowKind.DISCIPLINE, "D1").contractor_mix is ContractorMix.MIXED
    assert report.row(RowKind.DISCIPLINE, "D2").contractor_mix is ContractorMix.OWN


def test_pf_bands(report: DailyReport) -> None:
    overall = report.row(RowKind.OVERALL)
    assert overall.pf_day == q(60, 36)
    assert overall.pf_day_band is PfBand.HIGH
    assert overall.pf_cum == q(200, 168)
    assert overall.pf_cum_band is PfBand.GREEN
    assert overall.pf_week_band is PfBand.GREEN
    d2 = report.row(RowKind.DISCIPLINE, "D2")
    assert d2.pf_cum == q(30, 48)
    assert d2.pf_cum_band is PfBand.RED
    assert report.row(RowKind.NON_DIRECT).pf_cum_band is None


def test_reconciliation_totals(report: DailyReport) -> None:
    t = report.totals
    assert (t.source_hours_day, t.source_hours_cum) == (36, 168)
    assert (t.spent_day, t.spent_cum) == (36, 168)
    assert (t.unallocated_day, t.unallocated_cum) == (0, 8)
