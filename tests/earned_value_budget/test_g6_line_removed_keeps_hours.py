"""G6 (CEO bilgi talebi) — günlükte BÖLÜMLÜ satır kaldırılınca o koda dağıtılmış saat KORUNUR.

Bugünkü davranışı ölçer ve çiviler (değişiklik YOK): dağıtım hücreleri (site, gün, kod)
anahtarlıdır, günlük satırına FK taşımaz; satır silinince yalnız o günün miktarı düşer.
Saat, bir sonraki dağıtım kaydına kadar kodda kalır; direct kuralda yaprakta, motor da
harcananı sayar (earned 0 → PF None, harcanan görünür).
"""

from __future__ import annotations

from decimal import Decimal

from .conftest import DAY
from .test_day_allocation import _day

D = Decimal


async def test_G6_removed_sectioned_line_keeps_allocated_hours(
    client, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    i1, s1 = boq["i1"], boq["s1"]
    leaf = f"l:{i1.id}:{s1.id}"
    saha_gunu["line"].section_id = s1.id  # bölümlü satır: I1 × S1, 5 m3
    await seeded_db.flush()
    body = {
        "codes": [{"node_id": leaf, "rule": "direct"}],
        "cells": [
            {
                "row": {"kind": "personnel", "ref_id": str(saha_gunu["ali"].id)},
                "node_id": leaf,
                "hours": "9",
            },
            {
                "row": {"kind": "personnel", "ref_id": str(saha_gunu["veli"].id)},
                "node_id": leaf,
                "hours": "8",
            },
        ],
    }
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    ).status_code == 200
    removed = await client.put(
        f"/diary/{saha_gunu['diary'].id}/lines", json={"lines": []}, headers=admin
    )
    assert removed.status_code == 200, removed.text
    view = (await client.get(_day(santiye), headers=saha)).json()
    assert [c["node_id"] for c in view["codes"]] == [leaf]
    assert sum(D(c["hours"]) for c in view["cells"] if c["node_id"] == leaf) == 17
    report = (
        await client.get(
            f"/sites/{santiye.id}/earned-value/reports/daily",
            headers=admin,
            params={"date": DAY.isoformat()},
        )
    ).json()
    overall = next(k for k in report["kpis"] if k["kind"] == "overall")
    assert (D(overall["spent_day"]), D(overall["earned_day"])) == (17, 0)
