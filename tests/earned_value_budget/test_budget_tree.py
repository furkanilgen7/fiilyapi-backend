"""Bütçe ağacı saf kurulumu (budget_tree) — elle kurulmuş örnek.

```
KAB (own)  ← G1 Betonarme
  I1 Beton m3 qty 100 → S1 60 · S2 30 · Bölümsüz 10 (kalan)
     l:I1:S1  oran 2 (elle)     → bütçe 120 · pencere S1 04–15.05 (section)
     l:I1:S2  oran yok          → bütçe 0   · pencere ezme 18–29.05 (override)
     l:I1:none oran 2 (katalog) → bütçe 20  · pencere birleşim 04–29.05 (union)
DUV (subcon) ← G2 Duvar
  I2 Tuğla m2 qty 50 → S1 50
     l:I2:S1  oran 0,5, yaprakta OWN ezmesi → bütçe 25 · pencere S1
Disiplinsiz ← G3 Genel
  I3 Temizlik gtr qty 1 → Bölümsüz 1, oran yok → bütçe 0, pencere yok
```
S2'nin tarihi YOK (pencere yalnız ezmeden gelir). Pazar tatil.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.modules.earned_value.budget_tree import (
    BLOCKER_DISCIPLINELESS_GROUP,
    BLOCKER_MISSING_WINDOW,
    BLOCKER_NO_WORKING_DAY,
    WARNING_DISCIPLINELESS_GROUP,
    WARNING_EMPTY_RATE,
    BoqSnapshot,
    DisciplineInfo,
    GroupInfo,
    ItemInfo,
    ItemSetting,
    LeafSetting,
    RevisionInputs,
    SectionInfo,
    build_tree,
    leaf_node_id,
)
from app.modules.earned_value.engine import ContractorType, working_day_predicate
from app.modules.earned_value.models import RateSource

D = Decimal
U = uuid.uuid4
KAB, DUV = U(), U()
S1, S2, S3 = U(), U(), U()
G1, G2, G3 = U(), U(), U()
I1, I2, I3 = U(), U(), U()
WORKDAY = working_day_predicate()

DISCIPLINES = (
    DisciplineInfo(KAB, "KAB", "Kaba İnşaat", "#2563eb", ContractorType.OWN, 1),
    DisciplineInfo(DUV, "DUV", "Duvar", "#16a34a", ContractorType.SUBCON, 2),
)
SECTIONS = (
    SectionInfo(S1, "A Blok", date(2026, 5, 4), date(2026, 5, 15), 12, 1),
    SectionInfo(S2, "B Blok", None, None, None, 2),
)
BOQ = BoqSnapshot(
    groups=(GroupInfo(G1, "Betonarme", 1), GroupInfo(G2, "Duvar", 2), GroupInfo(G3, "Genel", 3)),
    items=(
        ItemInfo(I1, G1, "01.001", "Beton", "m3", D(100), 1),
        ItemInfo(I2, G2, "02.001", "Tuğla", "m2", D(50), 1),
        ItemInfo(I3, G3, "03.001", "Temizlik", "gtr", D(1), 1),
    ),
    allocations={I1: {S1: D(60), S2: D(30)}, I2: {S1: D(50)}},
    sections=SECTIONS,
)
INPUTS = RevisionInputs(
    group_disciplines={G1: KAB, G2: DUV},
    items={I2: ItemSetting()},
    leaves={
        (I1, S1): LeafSetting(D(2), RateSource.MANUAL),
        (I1, None): LeafSetting(D(2), RateSource.CATALOG),
        (I2, S1): LeafSetting(D("0.5"), RateSource.CATALOG, contractor_type=ContractorType.OWN),
    },
    windows={(KAB, S2): (date(2026, 5, 18), date(2026, 5, 29))},
)


def _leaves(tree) -> dict:  # noqa: ANN001
    return {leaf.id: leaf for _, _, _, leaf in tree.leaves()}


def test_hierarchy_order_and_ids() -> None:
    tree = build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY)
    assert [d.id for d in tree.disciplines] == [f"d:{KAB}", f"d:{DUV}", "d:none"]
    kab = tree.disciplines[0]
    assert [g.id for g in kab.groups] == [f"g:{G1}"]
    assert [i.id for i in kab.groups[0].items] == [f"i:{I1}"]
    assert [lf.id for lf in kab.groups[0].items[0].leaves] == [
        leaf_node_id(I1, S1),
        leaf_node_id(I1, S2),
        leaf_node_id(I1, None),
    ]
    assert leaf_node_id(I1, None) == f"l:{I1}:none"


def test_quantities_come_from_allocation_and_remainder_is_unsectioned() -> None:
    lv = _leaves(build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY))
    assert lv[leaf_node_id(I1, S1)].planned_qty == 60
    assert lv[leaf_node_id(I1, S2)].planned_qty == 30
    assert lv[leaf_node_id(I1, None)].planned_qty == 10  # 100 − 90
    assert lv[leaf_node_id(I3, None)].planned_qty == 1  # hiç tahsis yok → tamamı


def test_budget_is_qty_times_rate_and_unrated_contributes_zero() -> None:
    lv = _leaves(build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY))
    assert lv[leaf_node_id(I1, S1)].budget_mhr == 120
    assert lv[leaf_node_id(I1, None)].budget_mhr == 20
    assert lv[leaf_node_id(I1, S2)].budget_mhr == 0
    assert lv[leaf_node_id(I2, S1)].budget_mhr == D("25.0")


def test_contractor_inheritance_and_override_flags() -> None:
    tree = build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY)
    item2 = tree.disciplines[1].groups[0].items[0]
    assert (item2.contractor_type, item2.contractor_inherited) == (ContractorType.SUBCON, True)
    leaf = item2.leaves[0]
    assert (leaf.contractor_type, leaf.contractor_overridden) == (ContractorType.OWN, True)
    item1_leaf = _leaves(tree)[leaf_node_id(I1, S1)]
    assert (item1_leaf.contractor_type, item1_leaf.contractor_overridden) == (
        ContractorType.OWN,
        False,
    )
    assert (item1_leaf.is_direct, item1_leaf.is_direct_overridden) == (True, False)
    # disiplinsiz grupta varsayılan own
    assert tree.disciplines[2].groups[0].items[0].contractor_type is ContractorType.OWN


def test_window_priority_override_section_union_none() -> None:
    lv = _leaves(build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY))
    s1 = lv[leaf_node_id(I1, S1)]
    assert (s1.window_start, s1.window_end, s1.window_source) == (
        date(2026, 5, 4),
        date(2026, 5, 15),
        "section",
    )
    s2 = lv[leaf_node_id(I1, S2)]
    assert (s2.window_start, s2.window_end, s2.window_source) == (
        date(2026, 5, 18),
        date(2026, 5, 29),
        "override",
    )
    none = lv[leaf_node_id(I1, None)]
    assert (none.window_start, none.window_end, none.window_source) == (
        date(2026, 5, 4),
        date(2026, 5, 29),
        "union",
    )
    assert lv[leaf_node_id(I3, None)].window_source is None


def test_findings_warnings_without_blockers() -> None:
    tree = build_tree(BOQ, DISCIPLINES, INPUTS, WORKDAY)
    assert tree.blockers == ()
    warnings = {w.code: w for w in tree.warnings}
    assert set(warnings[WARNING_EMPTY_RATE].node_ids) == {
        leaf_node_id(I1, S2),
        leaf_node_id(I3, None),
    }
    assert warnings[WARNING_EMPTY_RATE].count == 2
    assert warnings[WARNING_DISCIPLINELESS_GROUP].node_ids == (f"g:{G3}",)


def test_blockers_disciplineless_budget_missing_window_and_no_working_day() -> None:
    sections = (*SECTIONS, SectionInfo(S3, "C Blok", None, None, None, 3))
    boq = BoqSnapshot(
        groups=BOQ.groups,
        items=BOQ.items,
        allocations={I1: {S1: D(60), S2: D(30), S3: D(10)}, I2: {S1: D(50)}},
        sections=sections,
    )
    sunday = date(2026, 5, 17)
    inputs = RevisionInputs(
        group_disciplines=INPUTS.group_disciplines,
        items=INPUTS.items,
        leaves={
            **INPUTS.leaves,
            (I1, S2): LeafSetting(D(1), RateSource.MANUAL),
            (I1, S3): LeafSetting(D(1), RateSource.MANUAL),
            (I3, None): LeafSetting(D(5), RateSource.MANUAL),
        },
        windows={(KAB, S2): (sunday, sunday)},
    )
    tree = build_tree(boq, DISCIPLINES, inputs, WORKDAY)
    blockers = {b.code: b.node_ids for b in tree.blockers}
    assert blockers[BLOCKER_DISCIPLINELESS_GROUP] == (f"g:{G3}",)
    assert blockers[BLOCKER_MISSING_WINDOW] == (leaf_node_id(I1, S3),)
    assert blockers[BLOCKER_NO_WORKING_DAY] == (leaf_node_id(I1, S2),)


def test_indirect_leaf_never_blocks() -> None:
    inputs = RevisionInputs(
        group_disciplines={G1: KAB},
        items={I1: ItemSetting(is_direct=False)},
        leaves={(I1, S2): LeafSetting(D(1), RateSource.MANUAL)},
    )
    boq = BoqSnapshot(BOQ.groups[:1], BOQ.items[:1], {I1: {S2: D(30)}}, SECTIONS)
    tree = build_tree(boq, DISCIPLINES, inputs, WORKDAY)
    assert tree.blockers == ()  # S2 tarihsiz ama yaprak dolaylı
