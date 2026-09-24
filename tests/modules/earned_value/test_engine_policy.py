"""PLANLAMA-SPEC §3.7 kararları — ADLI çiviler. Karar değişirse `engine/policy.py`deki tek
nokta değişir ve buradaki adlı test kırmızı olur."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    ContractorMix,
    ContractorType,
    EngineInput,
    HoursEntry,
    Node,
    PfBand,
    ProjectCalendar,
    QtyEntry,
    RowKind,
    Status,
    classify_status,
    compute_daily_report,
    pf_band,
)
from app.modules.earned_value.engine.policy import (
    DEFAULT_CUMULATIVE_PF_BANDS,
    DEFAULT_DAILY_PF_BANDS,
)

from ._fixture import NODES, REPORT_DATE, build_input

D = Decimal


def _report(nodes: tuple[Node, ...] = NODES):  # noqa: ANN202
    return compute_daily_report(replace(build_input(), nodes=nodes), REPORT_DATE)


def _swap(node_id: str, **changes: object) -> tuple[Node, ...]:
    return tuple(replace(n, **changes) if n.id == node_id else n for n in NODES)


def test_S1_own_subcon_planned_pct_is_budget_share_of_curves() -> None:
    report = _report()
    # own = ¾·KAB + MEK (Σ 400, küm 155) · subcon = ¼·KAB (Σ 100, küm 45)
    own, subcon = report.row(RowKind.OVERALL_OWN), report.row(RowKind.OVERALL_SUBCON)
    assert own.planned_pct_cum == D(155) / D(400)
    assert own.planned_pct_day == D("32.5") / D(400)
    assert subcon.planned_pct_cum == D(45) / D(100)
    # tek eğride pay ölçeği sadeleşir: disiplin–own planlı % = disiplin planlı %
    d1 = report.row(RowKind.DISCIPLINE, "D1")
    assert report.row(RowKind.DISCIPLINE_OWN, "D1").planned_pct_cum == d1.planned_pct_cum
    assert own.status is not None and subcon.status is not None


def test_S2_header_hours_use_landing_node_fields() -> None:
    # D2 başlığı subcon olursa üstüne yazılan 48 sa Overall–Subcon'a geçer
    report = _report(_swap("D2", contractor_type=ContractorType.SUBCON))
    assert report.row(RowKind.OVERALL_SUBCON).spent_cum == 26 + 48
    assert report.row(RowKind.OVERALL_OWN).spent_cum == 142 - 48
    # T1 unallocated (8 sa) T1'in kendi alanıyla: own
    assert report.row(RowKind.DISCIPLINE_OWN, "D1").unallocated_cum == 8
    assert report.row(RowKind.DISCIPLINE_SUBCON, "D1").unallocated_cum == 0


def test_S3_kpi_rows_direct_only_and_single_non_direct_row() -> None:
    report = _report()
    assert report.row(RowKind.DISCIPLINE, "D2").budget_mhr == 100  # L5 (40) yok
    assert report.nodes["D2"].budget_mhr == 140  # ağaç metriği tüm alt ağaç
    assert report.row(RowKind.OVERALL).budget_mhr == 500
    non_direct = [r for r in report.rows if r.kind is RowKind.NON_DIRECT]
    assert len(non_direct) == 1 and non_direct[0].budget_mhr == 40
    assert (non_direct[0].planned_pct_cum, non_direct[0].status) == (None, None)


def test_S4_mixed_uom_header_qty_fields_are_none() -> None:
    report = _report()
    d1 = report.nodes["D1"]  # m3 + m2
    assert d1.uom is None
    assert (d1.qty_cum, d1.planned_qty, d1.remaining_qty, d1.planned_unit_mhr) == (None,) * 4
    assert (d1.actual_unit_mhr_cum, d1.unit_rate_pf_cum) == (None, None)
    assert d1.earned_cum == 170 and d1.togo_mhr == 230  # adam-saat her zaman Σ
    t1 = report.nodes["T1"]  # m3 + m3
    assert t1.planned_unit_mhr == D(300) / D(150)


def test_S5_holiday_rule_is_weekday_set_default_sunday() -> None:
    cal = ProjectCalendar(CalendarSettings(date(2026, 9, 3), date(2026, 9, 30)))
    assert cal.is_holiday(date(2026, 9, 6))  # Pazar
    assert not cal.is_holiday(date(2026, 9, 5))  # Cumartesi
    sat = ProjectCalendar(
        CalendarSettings(date(2026, 9, 3), date(2026, 9, 30), weekly_holidays=frozenset({5}))
    )
    assert sat.is_holiday(date(2026, 9, 5)) and not sat.is_holiday(date(2026, 9, 6))
    manual = ProjectCalendar(
        CalendarSettings(
            date(2026, 9, 3), date(2026, 9, 30), extra_holidays=frozenset({date(2026, 9, 9)})
        )
    )
    assert manual.is_holiday(date(2026, 9, 9))


def test_S6_K19_daily_pf_band_green_95_to_105_and_high_above() -> None:
    b = DEFAULT_DAILY_PF_BANDS
    assert pf_band(D("0.9449"), b) is PfBand.RED  # → 0,94
    assert pf_band(D("0.95"), b) is PfBand.GREEN
    assert pf_band(D("1.05"), b) is PfBand.GREEN
    assert pf_band(D("1.06"), b) is PfBand.HIGH
    assert pf_band(D("5"), b) is PfBand.HIGH


def test_S6_cumulative_pf_band_red_amber_green() -> None:
    b = DEFAULT_CUMULATIVE_PF_BANDS
    assert pf_band(D("0.94"), b) is PfBand.RED
    assert pf_band(D("0.95"), b) is PfBand.AMBER
    assert pf_band(D("0.99"), b) is PfBand.AMBER
    assert pf_band(D("1.00"), b) is PfBand.GREEN
    assert pf_band(D("5"), b) is PfBand.GREEN  # kümülatifte HIGH yok
    assert pf_band(None, b) is None


def test_K18_pf_band_uses_value_rounded_half_up_to_two_decimals() -> None:
    cum, daily = DEFAULT_CUMULATIVE_PF_BANDS, DEFAULT_DAILY_PF_BANDS
    assert pf_band(D("0.9499"), cum) is PfBand.AMBER  # panel sorunu: "0,95" ekranda → sarı
    assert pf_band(D("0.945"), cum) is PfBand.AMBER  # HALF_UP: 0,945 → 0,95 (HALF_EVEN 0,94)
    assert pf_band(D("0.94499"), cum) is PfBand.RED  # → 0,94
    assert pf_band(D("0.9951"), cum) is PfBand.GREEN  # → 1,00
    assert pf_band(D("1.0549"), daily) is PfBand.GREEN  # → 1,05
    assert pf_band(D("1.055"), daily) is PfBand.HIGH  # → 1,06
    assert pf_band(D("0.9450"), daily) is PfBand.GREEN  # → 0,95


@pytest.mark.parametrize(
    ("variance", "expected"),
    [
        ("-0.0204", Status.NORMAL),  # −2,04 → −2,0 → tolerans 2,0 ile Normal
        ("-0.0205", Status.LATE),  # −2,05 → HALF_UP (sıfırdan uzağa) → −2,1
        ("0.0205", Status.AHEAD),  # +2,05 → +2,1
        ("0.0204", Status.NORMAL),  # +2,04 → +2,0
        ("-0.02049999", Status.NORMAL),  # −2,049999 → −2,0
    ],
)
def test_K27_status_uses_points_rounded_half_up_to_one_decimal(
    variance: str, expected: Status
) -> None:
    assert classify_status(D(variance), D("2.0")) is expected


def _mini(leaves: tuple[Node, ...], qty: tuple[QtyEntry, ...], hours: D) -> object:
    nodes = (Node("M", None), *leaves)
    inp = EngineInput(
        calendar=CalendarSettings(date(2026, 9, 1), date(2026, 9, 30)),
        nodes=nodes,
        qty_entries=qty,
        hours_entries=(
            HoursEntry("M", date(2026, 9, 1), hours, AllocationRule.PRORATA_BY_DAILY_QTY),
        ),
    )
    return compute_daily_report(inp, date(2026, 9, 1))


def test_K11_prorata_same_uom_uses_qty_share() -> None:
    day1 = date(2026, 9, 1)
    leaves = (
        Node("A", "M", uom="m3", planned_qty=D(100), unit_mhr=D(2)),
        Node("B", "M", uom="m3", planned_qty=D(100), unit_mhr=D("0.5")),
    )
    r = _mini(leaves, (QtyEntry("A", day1, D(5)), QtyEntry("B", day1, D(20))), D(50))
    # qty payı 5 : 20 (kazanılmış payı 10 : 10 olurdu)
    assert (r.nodes["A"].spent_day, r.nodes["B"].spent_day) == (10, 40)


def test_K11_prorata_mixed_uom_uses_earned_share() -> None:
    day1 = date(2026, 9, 1)
    leaves = (
        Node("A", "M", uom="m3", planned_qty=D(100), unit_mhr=D(2)),
        Node("B", "M", uom="m2", planned_qty=D(100), unit_mhr=D("0.5")),
    )
    r = _mini(leaves, (QtyEntry("A", day1, D(5)), QtyEntry("B", day1, D(20))), D(50))
    # kazanılmış payı 5×2 = 10 : 20×0,5 = 10 (qty payı 5 : 20 olurdu)
    assert (r.nodes["A"].spent_day, r.nodes["B"].spent_day) == (25, 25)
    assert r.nodes["M"].unallocated_day == 0


def test_K11_mixed_uom_all_unrated_is_unallocated() -> None:
    day1 = date(2026, 9, 1)
    leaves = (
        Node("A", "M", uom="m3", planned_qty=D(100)),
        Node("B", "M", uom="m2", planned_qty=D(100), unit_mhr=D(0)),
    )
    r = _mini(leaves, (QtyEntry("A", day1, D(5)), QtyEntry("B", day1, D(20))), D(50))
    assert r.nodes["M"].unallocated_day == r.nodes["M"].spent_day == 50


@pytest.mark.parametrize("rate", [None, D(0)], ids=["bos", "sifir"])
def test_K12_unrated_leaf_qty_is_kept_but_earns_nothing(rate: D | None) -> None:
    day1 = date(2026, 9, 1)
    leaves = (
        Node("A", "M", uom="m3", planned_qty=D(100), unit_mhr=rate),
        Node("B", "M", uom="m3", planned_qty=D(100), unit_mhr=D(2)),
    )
    entry = QtyEntry("A", day1, D(7))
    r = _mini(leaves, (entry, QtyEntry("B", day1, D(3))), D(10))
    a = r.nodes["A"]
    assert a.qty_day == 7  # kaydedildi
    assert (a.earned_day, a.budget_mhr) == (0, 0)  # kazanılmışa girmedi
    assert r.nodes["M"].earned_day == 6  # yalnız B
    assert r.unrated_entries == (entry,)  # "oransız giriş" uyarısı


def test_S7_split_rows_only_for_mixed_discipline() -> None:
    report = _report()
    kinds = {(r.kind, r.node_id) for r in report.rows}
    assert (RowKind.DISCIPLINE_OWN, "D1") in kinds  # karma
    assert (RowKind.DISCIPLINE_OWN, "D2") not in kinds  # tek tip
    assert (RowKind.DISCIPLINE_SUBCON, "D2") not in kinds
    assert report.row(RowKind.DISCIPLINE, "D2").contractor_mix is ContractorMix.OWN
    # tamamen taşeron disiplin: alt satır yok, rozet SUBCON
    all_subcon = _swap("L1", contractor_type=ContractorType.SUBCON)
    all_subcon = tuple(
        replace(n, contractor_type=ContractorType.SUBCON) if n.id == "L3" else n for n in all_subcon
    )
    r2 = _report(all_subcon)
    assert r2.row(RowKind.DISCIPLINE, "D1").contractor_mix is ContractorMix.SUBCON
    assert (RowKind.DISCIPLINE_SUBCON, "D1") not in {(r.kind, r.node_id) for r in r2.rows}
