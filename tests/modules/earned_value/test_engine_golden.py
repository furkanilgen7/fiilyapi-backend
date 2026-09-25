"""GOLDEN — §7 kabul fikstürünün (PLN-B0) rapor yükü: gün 7 raporu + hafta serisi (PLN-B3).

Rapor/panel/QURR katmanı bu iki yapıyı sunar; golden, sunumdan ÖNCEKİ motor çıktısını
dondurur ve elle tabloyla (`test_engine_fixture.py` docstring §3–§6) çapraz bağlanır:
Overall earned/spent küm 200/168, T1 pf_cum 130/120, D2 70/48, T1 unallocated küm 8.
Yeniden üretmek: `UPDATE_GOLDEN=1 pytest tests/modules/earned_value/test_engine_golden.py`.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.earned_value.engine import RowKind, Scope, compute_panel, scope_for_row

from ._fixture import START, build_input, day

GOLDEN = Path(__file__).parent / "golden" / "engine_fixture_day7.json"


def _plain(v: object) -> object:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    if isinstance(v, Decimal):
        return format(v, "f")  # sabit gosterim (API ile ayni; "0E+7" yazilmaz)
    if isinstance(v, date):
        return str(v)
    if isinstance(v, enum.Enum):
        return v.value
    return v


def test_golden_fixture_day7_report_and_week_series() -> None:
    inp = build_input(Decimal(0))
    d7 = day(7)
    first = compute_panel(inp, START, d7, [Scope()], as_of=d7)[1]
    scopes = [scope_for_row(r) for r in first.rows]
    series, report = compute_panel(inp, START, day(10), scopes, as_of=d7)
    payload = {
        "report": _plain(report),
        "series": [
            {"scope": _plain(s.scope), "budget_mhr": str(s.budget_mhr), "points": _plain(s.points)}
            for s in series.series
        ],
    }
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    assert payload == json.loads(GOLDEN.read_text()), "golden farkı — elle incele"
    # elle tablo çaprazı (golden kendi kendini doğrulamasın)
    overall = report.row(RowKind.OVERALL)
    assert (overall.earned_cum, overall.spent_cum) == (200, 168)
    assert report.nodes["T1"].pf_cum == Decimal(130) / Decimal(120)
    assert (report.nodes["D2"].earned_cum, report.nodes["D2"].spent_cum) == (70, 48)
    assert report.nodes["T1"].unallocated_cum == 8
    p7 = series.get(Scope()).at(d7)
    assert (p7.earned_cum, p7.spent_cum, p7.pf_rolling) == (200, 168, Decimal(200) / 168)
    assert series.get(Scope()).at(day(9)).is_future
