"""PLN-B3 — `compute_panel`: seri + rapor günü raporu TEK iniş, sonuç ayrı çağrılarla `==`.

Bekçi: iniş (`resolve_all`) paylaşılınca ne seri ne rapor değişmemeli. Karşılaştırma
dataclass eşitliğiyle (her alan, her düğüm, her KPI satırı, her gün × kapsam).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    Scope,
    compute_daily_report,
    compute_panel,
    compute_series,
    scope_for_row,
)

from ._fixture import END, START, build_input, day
from ._fixture_leaf import build_leaf_input
from .test_engine_series import _random_input


def _check(inp, start, end, as_of) -> None:  # noqa: ANN001
    scopes = [scope_for_row(r) for r in compute_daily_report(inp, as_of).rows]
    scopes.append(Scope(direct_only=False))
    series, report = compute_panel(inp, start, end, scopes, as_of=as_of)
    assert series == compute_series(inp, start, end, scopes, as_of=as_of)
    assert report == compute_daily_report(inp, as_of)


@pytest.mark.parametrize("mode", ["egri", "yaprak", "karisik"])
@pytest.mark.parametrize("n", [1, 4, 8, 10])
def test_panel_equals_separate_calls_on_fixture(mode: str, n: int) -> None:
    inp = (
        build_input(Decimal(2))
        if mode == "egri"
        else build_leaf_input(mixed=mode == "karisik", tolerance_points=Decimal(2))
    )
    _check(inp, START, END, day(n))
    _check(inp, day(max(1, n - 2)), day(n), day(n))  # dar pencere: kümülatif yine takvim başından


@pytest.mark.parametrize("plan_mode", ["egri", "yaprak", "karisik"])
@pytest.mark.parametrize("seed", range(6))
def test_panel_equals_separate_calls_on_random_trees(seed: int, plan_mode: str) -> None:
    inp = _random_input(seed, plan_mode)
    first, last = inp.calendar.start_date, inp.calendar.end_date
    for as_of in (first, first + timedelta(days=20), last):
        _check(inp, first, last, as_of)


def test_panel_rejects_as_of_outside_calendar() -> None:
    inp = build_input(Decimal(0))
    with pytest.raises(ValueError, match="takvim"):
        compute_panel(inp, START, END, [Scope()], as_of=END + timedelta(days=1))
