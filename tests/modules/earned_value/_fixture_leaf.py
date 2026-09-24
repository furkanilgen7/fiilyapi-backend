"""PLN-B1.1 K9 varyantı: B0 kabul fikstürü + YAPRAK anahtarlı planlı eğri.

`_fixture.py` DEĞİŞMEZ; bu dosya onun girdisinin kopyasını kurar ve `planned_mhr`ı
yaprak eğrileriyle değiştirir (ya da `mixed=True` ile disiplin eğrisinin YANINA ekler).
Beklenenler ve elle hesap `test_engine_leaf_curves.py` docstring'indedir.

Yaprak eğrileri (gün 1..10; gün 4 tatil = 0; Σ = yaprak bütçesi). L5 dolaylı → eğrisiz:
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.modules.earned_value.engine import EngineInput, PlannedMhr

from ._fixture import PLANNED, build_input, day

LEAF_CURVES = {
    "L1": (20, 20, 20, 0, 20, 20, 20, 30, 30, 20),  # Σ 200
    "L2": (0, 10, 10, 0, 10, 10, 10, 20, 20, 10),  # Σ 100 (subcon)
    "L3": (25, 25, 25, 0, 25, 0, 0, 0, 0, 0),  # Σ 100
    "L4": (0, 0, 0, 0, 10, 10, 10, 20, 20, 30),  # Σ 100
}


def leaf_points(curves: dict[str, tuple[int, ...]] = LEAF_CURVES) -> tuple[PlannedMhr, ...]:
    return tuple(
        PlannedMhr.for_leaf(node_id, day(i + 1), Decimal(mhr))
        for node_id, values in curves.items()
        for i, mhr in enumerate(values)
        if mhr
    )


def build_leaf_input(*, mixed: bool = False, tolerance_points: Decimal = Decimal(0)) -> EngineInput:
    base = build_input(tolerance_points)
    planned = (*PLANNED, *leaf_points()) if mixed else leaf_points()
    return replace(base, planned_mhr=planned)
