"""PLN-B0 §7 kural testleri: earned = qty × oran · başlık = Σ alt · hafta penceresi d'de
kapanır · prorata toplamı kaynağa eşit + miktarsız günde unallocated · sıfıra bölme None ·
status tolerans sınırları · girdi doğrulaması."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    EngineInput,
    HoursEntry,
    Node,
    QtyEntry,
    RowKind,
    Status,
    classify_status,
    compute_daily_report,
)
from app.modules.earned_value.engine.accumulate import prorata_parts
from app.modules.earned_value.engine.numeric import PRORATA_QUANTUM, ratio

from ._fixture import HOURS_ENTRIES, NODES, REPORT_DATE, build_input, day

D = Decimal
#: Yapraktan türeyen toplanabilir alanlar: başlık = Σ çocuk (birebir).
LEAF_ADDITIVE = (
    "earned_day",
    "earned_cum",
    "earned_week",
    "budget_mhr",
    "remaining_mhr",
    "togo_mhr",
)
#: Saat alanları: başlık = Σ çocuk + başlığın KENDİSİNE inen saat (spec §3.3).
HOUR_FIELDS = ("spent", "unallocated")
QTY_ADDITIVE = ("qty_day", "qty_cum", "qty_week", "planned_qty", "remaining_qty")


# --- earned = qty × yaprağın kendi oranı -------------------------------------------------


def test_earned_is_qty_times_leaf_rate() -> None:
    report = compute_daily_report(build_input(), REPORT_DATE)
    for node in NODES:
        m = report.nodes[node.id]
        if not m.is_leaf:
            continue
        assert m.earned_day == m.qty_day * node.unit_mhr, node.id
        assert m.earned_cum == m.qty_cum * node.unit_mhr, node.id
        assert m.earned_week == m.qty_week * node.unit_mhr, node.id
        assert m.budget_mhr == node.planned_qty * node.unit_mhr, node.id


# --- başlık = Σ alt ------------------------------------------------------------------


def _children(nodes: tuple[Node, ...]) -> dict[object, list[object]]:
    out: dict[object, list[object]] = {n.id: [] for n in nodes}
    for n in nodes:
        if n.parent_id is not None:
            out[n.parent_id].append(n.id)
    return out


def _own_landing(inp: EngineInput, report_date: date, node_id: object) -> dict[str, D]:
    """Girdiden BAĞIMSIZ kâhin: başlığın kendisine inen saat (direct + miktarsız prorata)."""
    parent_of = {n.id: n.parent_id for n in inp.nodes}

    def under(leaf: object) -> bool:
        while leaf is not None:
            if leaf == node_id:
                return True
            leaf = parent_of[leaf]
        return False

    back = (report_date.weekday() - inp.calendar.week_start_dow) % 7
    window_start = max(report_date - timedelta(days=back), inp.calendar.start_date)
    out = {f"{k}_{w}": D(0) for k in HOUR_FIELDS for w in ("day", "cum", "week")}
    for h in inp.hours_entries:
        if h.node_id != node_id or h.day > report_date:
            continue
        rate = {n.id: n.unit_mhr or D(0) for n in inp.nodes}
        mixed = len({n.uom for n in inp.nodes if n.uom is not None and under(n.id)}) > 1
        todays = [e for e in inp.qty_entries if e.day == h.day and under(e.node_id)]
        # K11: karma birimde pay = qty × oran
        net = sum((e.qty * rate[e.node_id] if mixed else e.qty for e in todays), D(0))
        kinds = ["spent"]
        if h.rule is AllocationRule.PRORATA_BY_DAILY_QTY:
            if net > 0:
                continue  # yapraklara dağıldı
            kinds.append("unallocated")
        for k in kinds:
            out[f"{k}_cum"] += h.hours
            if h.day >= window_start:
                out[f"{k}_week"] += h.hours
            if h.day == report_date:
                out[f"{k}_day"] += h.hours
    return out


def _assert_header_is_sum(inp: EngineInput, report_date: date) -> int:
    report = compute_daily_report(inp, report_date)
    checked = 0
    for parent, kids in _children(tuple(inp.nodes)).items():
        if not kids:
            continue
        m = report.nodes[parent]
        fields = LEAF_ADDITIVE + (QTY_ADDITIVE if m.uom is not None else ())
        for field in fields:
            expected = sum((getattr(report.nodes[k], field) for k in kids), D(0))
            assert getattr(m, field) == expected, (parent, field)
        own = _own_landing(inp, report_date, parent)
        for field, own_part in own.items():
            expected = sum((getattr(report.nodes[k], field) for k in kids), D(0)) + own_part
            assert getattr(m, field) == expected, (parent, field)
        checked += 1
    return checked


def test_header_equals_sum_of_children_in_fixture() -> None:
    assert _assert_header_is_sum(build_input(), REPORT_DATE) == 5
    assert _own_landing(build_input(), REPORT_DATE, "D2")["spent_cum"] == 48  # kâhin kör değil
    assert _own_landing(build_input(), REPORT_DATE, "T1")["unallocated_cum"] == 8


def _random_project(seed: int) -> tuple[tuple[Node, ...], EngineInput, date]:
    rng = random.Random(seed)
    start = date(2026, 1, 5)
    days = 40
    nodes: list[Node] = []
    leaves: list[str] = []
    headers: list[str] = []

    def grow(parent: str | None, depth: int, prefix: str) -> None:
        for k in range(rng.randint(1, 3)):
            node_id = f"{prefix}{k}"
            if depth >= 3 or (depth > 0 and rng.random() < 0.35):
                nodes.append(
                    Node(
                        node_id,
                        parent,
                        uom=rng.choice(("m3", "m3", "t")),
                        planned_qty=D(rng.randint(10, 500)),
                        unit_mhr=D(rng.randint(5, 300)) / 100,
                        is_direct=rng.random() > 0.1,
                    )
                )
                leaves.append(node_id)
            else:
                nodes.append(Node(node_id, parent, curve_discipline="C" if depth == 0 else None))
                headers.append(node_id)
                grow(node_id, depth + 1, node_id + ".")

    grow(None, 0, "N")
    qty = [
        QtyEntry(leaf, start + timedelta(days=rng.randrange(days)), D(rng.randint(-5, 40)) / 4)
        for leaf in leaves
        for _ in range(rng.randint(0, 12))
    ]
    hours = [
        HoursEntry(
            rng.choice(leaves + headers),
            start + timedelta(days=rng.randrange(days)),
            D(rng.randint(1, 120)) / 10,
            rng.choice(tuple(AllocationRule)),
        )
        for _ in range(150)
    ]
    inp = EngineInput(
        calendar=CalendarSettings(start, start + timedelta(days=days - 1), week_start_dow=4),
        nodes=tuple(nodes),
        qty_entries=tuple(qty),
        hours_entries=tuple(hours),
    )
    return tuple(nodes), inp, start + timedelta(days=rng.randrange(days))


@pytest.mark.parametrize("seed", range(12))
def test_header_equals_sum_of_children_random_trees(seed: int) -> None:
    _, inp, report_date = _random_project(seed)
    assert _assert_header_is_sum(inp, report_date) > 0
    report = compute_daily_report(inp, report_date)
    # Mutabakat: koklere inen saat = kaynaga yazilan saat (prorata dahil, kayipsiz).
    assert report.totals.spent_cum == report.totals.source_hours_cum
    assert report.totals.spent_day == report.totals.source_hours_day


# --- hafta penceresi W(d) = [week_start(d), min(week_end(d), d)] ----------------------


def test_week_window_closes_at_report_date() -> None:
    report = compute_daily_report(build_input(), REPORT_DATE)  # gün 7; gün 8 girişleri dışarıda
    assert report.nodes["L1"].qty_week == 30  # gün 5 (10) + gün 7 (20); gün 8 (10) YOK
    assert report.nodes["L1"].qty_cum == 50
    assert report.nodes["T1"].spent_week == 70  # gün 5+6+7; gün 8 (10 sa) YOK


def test_week_window_of_partial_first_week_starts_at_project_start() -> None:
    report = compute_daily_report(build_input(), day(3))  # Cmt 05.09 — 1. hafta 03–06
    assert report.position.window_start == day(1)
    assert report.position.window_end == day(3)
    assert report.nodes["L1"].qty_week == report.nodes["L1"].qty_cum == 20
    assert report.nodes["T1"].spent_week == 50  # 12 + 18 + 20


def test_week_window_excludes_previous_week() -> None:
    report = compute_daily_report(build_input(), day(5))  # Pzt 07.09 — yeni hafta
    assert report.position.window_start == report.position.window_end == day(5)
    assert report.nodes["L1"].qty_week == report.nodes["L1"].qty_day == 10


# --- prorata ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(1, 11))
def test_prorata_distribution_sums_to_source_every_day(n: int) -> None:
    report = compute_daily_report(build_input(), day(n))
    source_a = sum((h.hours for h in HOURS_ENTRIES if h.node_id == "T1" and h.day == day(n)), D(0))
    t1 = report.nodes["T1"]
    leaves = report.nodes["L1"].spent_day + report.nodes["L2"].spent_day
    assert leaves + t1.unallocated_day == source_a
    assert t1.spent_day == source_a
    assert report.totals.spent_day == report.totals.source_hours_day


def test_prorata_on_day_without_qty_stays_unallocated_on_node() -> None:
    report = compute_daily_report(build_input(), day(6))  # T1 yapraklarında gün 6 miktar yok
    assert report.nodes["T1"].unallocated_day == 8
    assert report.nodes["T1"].spent_day == 8
    assert report.nodes["L1"].spent_day == report.nodes["L2"].spent_day == 0
    # yine M ve ATALARINDA sayılır
    assert report.nodes["D1"].spent_day == 8
    assert report.nodes["D1"].unallocated_day == 8


def test_prorata_residual_keeps_sum_exact() -> None:
    parts = prorata_parts(D(10), [(1, D(1)), (2, D(1)), (3, D(1))])
    assert parts is not None
    assert sum((p for _, p in parts), D(0)) == 10  # == ile, yaklaşık DEĞİL
    third = (D(10) / 3).quantize(PRORATA_QUANTUM)
    assert parts[0][1] == parts[1][1] == third
    assert parts[2][1] == 10 - 2 * third  # kalan son yaprağa


def test_prorata_sum_stays_exact_after_accumulating_many_parts() -> None:
    # Ölçülen kusurun bekçisi: 28 haneli ham paylar binlerce kez toplanınca sapıyordu.
    leaves = [(i, D(k)) for i, k in enumerate((3, 7, 11), start=1)]
    totals = {i: D(0) for i, _ in leaves}
    source = D(0)
    for n in range(1, 3001):
        hours = D(n) / 10
        source += hours
        for i, part in prorata_parts(hours, leaves) or []:
            totals[i] += part
    assert sum(totals.values(), D(0)) == source


def test_prorata_uses_daily_qty_share_not_cumulative() -> None:
    # Gün 2: L1 5 · L2 4 → 18 saat 10 / 8 (kümülatif pay olsaydı 10 / 4 → farklı)
    report = compute_daily_report(build_input(), day(2))
    assert report.nodes["L1"].spent_day == 10
    assert report.nodes["L2"].spent_day == 8


def test_prorata_net_zero_qty_is_unallocated() -> None:
    assert prorata_parts(D(5), [(1, D(3)), (2, D(-3))]) is None
    assert prorata_parts(D(5), []) is None


def test_direct_hours_on_header_do_not_flow_to_leaves() -> None:
    report = compute_daily_report(build_input(), REPORT_DATE)
    assert report.nodes["D2"].spent_cum == 48
    assert report.nodes["T3"].spent_cum == report.nodes["L4"].spent_cum == 0
    assert report.nodes["D2"].unallocated_cum == 0  # direct unallocated DEĞİL


# --- sıfıra bölme → None ---------------------------------------------------------------


def test_ratio_zero_denominator_is_none() -> None:
    assert ratio(D(5), D(0)) is None
    assert ratio(D(0), D(0)) is None
    assert ratio(None, D(1)) is None
    assert ratio(D(1), None) is None
    assert ratio(D(0), D(4)) == 0


def test_empty_curve_and_empty_budget_give_none() -> None:
    inp = replace(build_input(), planned_mhr=())
    overall = compute_daily_report(inp, REPORT_DATE).row(RowKind.OVERALL)
    assert (overall.planned_pct_day, overall.planned_pct_cum) == (None, None)
    assert (overall.variance, overall.status) == (None, None)


# --- status tolerans sınırları ---------------------------------------------------------


# variance 0–1 kesir; tolerans PUAN (K27). Puan = round_half_up(variance × 100, 1).
@pytest.mark.parametrize(
    ("variance", "tolerance_points", "expected"),
    [
        ("0", "0", Status.NORMAL),
        ("0.001", "0", Status.AHEAD),  # +0,1 puan
        ("-0.001", "0", Status.LATE),  # −0,1 puan
        ("0.02", "2.0", Status.NORMAL),  # tam sınırda Normal
        ("-0.02", "2.0", Status.NORMAL),  # tam sınırda Normal
        ("0.021", "2.0", Status.AHEAD),  # +2,1
        ("-0.021", "2.0", Status.LATE),  # −2,1
    ],
)
def test_status_tolerance_boundaries(
    variance: str, tolerance_points: str, expected: Status
) -> None:
    assert classify_status(D(variance), D(tolerance_points)) is expected


def test_status_none_variance_is_none() -> None:
    assert classify_status(None, D(0)) is None


def test_status_tolerance_flows_from_input() -> None:
    # D1 variance = 170/400 − 180/400 = −0,025 → −2,5 puan
    at_edge = compute_daily_report(build_input(D("2.5")), REPORT_DATE)
    assert at_edge.row(RowKind.DISCIPLINE, "D1").status is Status.NORMAL
    inside = compute_daily_report(build_input(D("2.4")), REPORT_DATE)
    assert inside.row(RowKind.DISCIPLINE, "D1").status is Status.LATE
    assert at_edge.row(RowKind.DISCIPLINE, "D1").variance == D("-0.025")  # variance ham kalır


# --- girdi doğrulaması -----------------------------------------------------------------


def _with(**changes: object) -> EngineInput:
    return replace(build_input(), **changes)


def test_qty_on_header_is_rejected() -> None:
    with pytest.raises(ValueError, match="yalniz yapraga"):
        compute_daily_report(_with(qty_entries=(QtyEntry("T1", day(1), D(1)),)), REPORT_DATE)


def test_unknown_node_is_rejected() -> None:
    bad = (HoursEntry("YOK", day(1), D(1), AllocationRule.DIRECT),)
    with pytest.raises(ValueError, match="bilinmeyen"):
        compute_daily_report(_with(hours_entries=bad), REPORT_DATE)


def test_entry_outside_calendar_is_rejected() -> None:
    bad = (QtyEntry("L1", day(0), D(1)),)
    with pytest.raises(ValueError, match="takvimi disinda"):
        compute_daily_report(_with(qty_entries=bad), REPORT_DATE)


def test_report_date_outside_calendar_is_rejected() -> None:
    with pytest.raises(ValueError, match="takvimi disinda"):
        compute_daily_report(build_input(), day(11))


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        QtyEntry("L1", day(1), 1.5)  # type: ignore[arg-type]


def test_header_holding_rate_is_rejected() -> None:
    nodes = (
        Node("H", None, unit_mhr=D(1)),
        Node("L", "H", uom="m", planned_qty=D(1), unit_mhr=D(1)),
    )
    with pytest.raises(ValueError, match="miktar/oran tutmaz"):
        compute_daily_report(_with(nodes=nodes, qty_entries=(), hours_entries=()), REPORT_DATE)


def test_leaf_without_planned_qty_is_rejected() -> None:
    nodes = (Node("L", None, uom="m", unit_mhr=D(1)),)
    with pytest.raises(ValueError, match="planned_qty zorunlu"):
        compute_daily_report(_with(nodes=nodes, qty_entries=(), hours_entries=()), REPORT_DATE)


def test_cycle_is_rejected() -> None:
    nodes = (
        Node("R", None, uom="m", planned_qty=D(1), unit_mhr=D(1)),
        Node("A", "B"),
        Node("B", "A"),
    )
    with pytest.raises(ValueError, match="dongu"):
        compute_daily_report(_with(nodes=nodes, qty_entries=(), hours_entries=()), REPORT_DATE)


def test_duplicate_node_id_is_rejected() -> None:
    nodes = (NODES[2], NODES[2])
    with pytest.raises(ValueError, match="tekrar"):
        compute_daily_report(_with(nodes=nodes, qty_entries=(), hours_entries=()), REPORT_DATE)
