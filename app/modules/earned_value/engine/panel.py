"""PANEL girisi — seri + rapor gunu raporu TEK agac ve TEK inisle (PLN-B3; hedef < 2 sn).

Panel hem grafik serisini (`compute_series`) hem disiplin/is tipi tablosunu
(`compute_daily_report(as_of)`) ister; ikisi ayri cagrilinca butun saat gecmisi IKI KEZ
indirilir (1.500 dugum × 1.000 gun: 218 bin prorata inisi, cagri basina ~1,2 sn). Inis
rapor gunune bagli olmadigi icin (`accumulate.resolve_all`) bir kez kurulup paylasilir.
Sonuc, iki fonksiyonun ayri ayri verdigiyle `==` (bekcisi `test_engine_panel.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import localcontext

from .accumulate import resolve_all
from .calendar import ProjectCalendar
from .numeric import ENGINE_CONTEXT
from .report import report_from
from .results import DailyReport
from .scope import Scope, root_index
from .series import SeriesResult, series_from, validate_window
from .tree import build_tree
from .types import EngineInput


def compute_panel(
    inp: EngineInput,
    start: date,
    end: date,
    scopes: Sequence[Scope],
    *,
    as_of: date,
    rolling_working_days: int = 7,
) -> tuple[SeriesResult, DailyReport]:
    """(`compute_series(inp, start, end, scopes, as_of=as_of)`, `compute_daily_report(inp,
    as_of)`) — ayni sonuc, tek inis."""
    with localcontext(ENGINE_CONTEXT):
        calendar = ProjectCalendar(inp.calendar)
        validate_window(calendar, start, end, rolling_working_days)
        calendar.position(as_of)  # takvim disi as_of → ValueError
        tree = build_tree(inp.nodes)
        for scope in scopes:
            root_index(tree, scope)
        resolved = resolve_all(tree, calendar, inp.qty_entries, inp.hours_entries)
        series = series_from(
            inp, calendar, tree, resolved, start, end, scopes, as_of, rolling_working_days
        )
        return series, report_from(inp, calendar, tree, resolved, as_of)
