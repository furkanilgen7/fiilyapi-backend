"""Bütçe ağacı → motor adaptörü: düğüm eşlemesi, L1/L2 varsayılanları, K7 takvim sınırı."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.earned_value.budget_engine import calendar_bounds, to_engine_nodes
from app.modules.earned_value.budget_tree import build_tree, leaf_node_id
from app.modules.earned_value.engine import (
    CalendarSettings,
    ContractorType,
    EngineInput,
    QtyEntry,
    compute_daily_report,
)

from .test_budget_tree import BOQ, DISCIPLINES, DUV, G2, I1, I2, INPUTS, S1, WORKDAY

D = Decimal


def _tree():  # noqa: ANN202
    return build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY)


def test_nodes_mirror_tree_ids_and_parents() -> None:
    nodes = {n.id: n for n in to_engine_nodes(_tree())}
    leaf = nodes[leaf_node_id(I1, S1)]
    assert (leaf.parent_id, leaf.planned_qty, leaf.unit_mhr) == (f"i:{I1}", D(60), D(2))
    assert nodes[f"i:{I1}"].parent_id.startswith("g:")
    assert nodes[f"d:{DUV}"].curve_discipline == f"d:{DUV}"


def test_l1_l2_carry_discipline_default_contractor() -> None:
    nodes = {n.id: n for n in to_engine_nodes(_tree())}
    assert nodes[f"d:{DUV}"].contractor_type is ContractorType.SUBCON
    assert nodes[f"g:{G2}"].contractor_type is ContractorType.SUBCON  # L2 = disiplinin varsayılanı
    assert nodes[f"g:{G2}"].is_direct is True
    assert nodes[leaf_node_id(I2, S1)].contractor_type is ContractorType.OWN  # yaprak ezmesi


def test_engine_accepts_adapter_output() -> None:
    tree = _tree()
    start, end = calendar_bounds(tree, [date(2026, 5, 1)])
    assert (start, end) == (date(2026, 5, 1), date(2026, 5, 29))  # K7: giriş pencereden önce
    report = compute_daily_report(
        EngineInput(
            calendar=CalendarSettings(start, end),
            nodes=to_engine_nodes(tree),
            qty_entries=(QtyEntry(leaf_node_id(I1, S1), date(2026, 5, 5), D(10)),),
        ),
        date(2026, 5, 6),
    )
    assert report.nodes[leaf_node_id(I1, S1)].earned_cum == 20


def test_calendar_bounds_none_without_windows_or_entries() -> None:
    empty = build_tree(BOQ.__class__((), (), {}, ()), DISCIPLINES, INPUTS, WORKDAY)
    assert calendar_bounds(empty) is None


def test_empty_headers_are_not_sent_to_engine() -> None:
    import uuid

    from app.modules.earned_value.budget_tree import BoqSnapshot, GroupInfo

    empty_group = uuid.uuid4()
    boq = BoqSnapshot(
        (*BOQ.groups, GroupInfo(empty_group, "Boş", 9)), BOQ.items, BOQ.allocations, BOQ.sections
    )
    ids = {n.id for n in to_engine_nodes(build_tree(boq, DISCIPLINES, INPUTS, WORKDAY))}
    assert f"g:{empty_group}" not in ids
