"""GOLDEN — günlük rapor + haftalık QURR + panel API yükü (PLN-B3), ELLE incelendi.

Kurgu = conftest `baseline` + `saha_gunu` + dağıtım (05.05.2026, gün 2 · hafta 1). Uçucu
alanlar normalize: uuid → `U<n>` (ilk görünüş sırası), zaman damgası → `<ts>`. Yeniden
üretmek: `UPDATE_GOLDEN=1 pytest tests/earned_value_budget/test_golden_reports.py` — sonra
FARKI elle incele (golden'ın değeri, onu değiştiren commit'in gözden geçirilmesidir).

Elle kontrol (golden/daily.json): Overall bütçe 225 = I1 100 × 2 + I2 50 × 0,5 · earned
10 = 5 m3 × 2 · spent 17 = Ali 9 + Veli 8 · pf_cum 10/17 = 0,588… (kırmızı) · footer
puantaj 17, dağıtılmamış 0 · draft 05.05, eksik 04.05. weekly.json: I1 satırı c=5, h=10,
i=17, j = d × n = 95 × 2 = 190 (K26), q = 10/17.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .conftest import DAY
from .test_reports import _allocate, _rep

GOLDEN = Path(__file__).parent / "golden"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_VOLATILE = {"generated_at", "frozen_at", "approved_at"}


def normalize(payload: object) -> object:
    labels: dict[str, str] = {}

    def label(m: re.Match[str]) -> str:
        return labels.setdefault(m.group(0), f"U{len(labels) + 1}")

    def walk(v: object, key: str | None = None) -> object:
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if key in _VOLATILE and v is not None:
            return "<ts>"
        if isinstance(v, str):
            return _UUID.sub(label, v)
        return v

    return walk(payload)


def _check(name: str, payload: object) -> None:
    path = GOLDEN / f"{name}.json"
    got = normalize(payload)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    assert got == json.loads(path.read_text()), f"{name}: golden farkı — elle incele"


async def test_golden_daily_weekly_panel(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    daily = await client.get(
        _rep(santiye, "/daily"), headers=admin, params={"date": DAY.isoformat()}
    )
    weekly = await client.get(_rep(santiye, "/weekly"), headers=admin, params={"week": 1})
    panel = await client.get(
        f"/sites/{santiye.id}/earned-value/panel",
        headers=admin,
        params={"date": DAY.isoformat()},
    )
    assert {daily.status_code, weekly.status_code, panel.status_code} == {200}
    _check("daily", daily.json())
    _check("weekly", weekly.json())
    _check("panel", panel.json())
