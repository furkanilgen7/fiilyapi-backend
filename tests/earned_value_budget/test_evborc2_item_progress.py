"""EV-BORC-2 (2) — gün `progress.items[]`: kalem (`i:<kalem>`) düğümü earned/spent/pf taşır.

`direct` kuralla KALEM koduna yazılan saat yapraklara dağılmaz (spec §3.3): yalnız yaprak
listesine bakan ekran kalem PF'sini "—" gösteriyordu. Kalem düğümü TÜM alt ağacı + kaleme
doğrudan inen saati taşır. Kurgu: Ali 9 sa → l:I1:Bölümsüz (direct) · Veli 8 sa → i:I1
(direct) · I1 Bölümsüz 5 m3 × 2 = 10 earned.
"""

from __future__ import annotations

from decimal import Decimal

from .test_day_allocation import _day

D = Decimal


async def test_item_node_carries_hours_written_directly_to_item(
    client, saha, santiye, boq, baseline, saha_gunu
) -> None:
    item = f"i:{boq['i1'].id}"
    leaf = f"l:{boq['i1'].id}:none"
    body = {
        "codes": [{"node_id": leaf, "rule": "direct"}, {"node_id": item, "rule": "direct"}],
        "cells": [
            {
                "row": {"kind": "personnel", "ref_id": str(saha_gunu["ali"].id)},
                "node_id": leaf,
                "hours": "9",
            },
            {
                "row": {"kind": "personnel", "ref_id": str(saha_gunu["veli"].id)},
                "node_id": item,
                "hours": "8",
            },
        ],
    }
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    ).status_code == 200
    progress = (await client.get(_day(santiye), headers=saha)).json()["progress"]

    by_leaf = {lf["node_id"]: lf for lf in progress["leaves"]}
    assert D(by_leaf[leaf]["spent_day"]) == 9  # kaleme yazılan 8 sa yaprakta YOK
    items = {i["node_id"]: i for i in progress["items"]}
    assert item in items, f"kalem düğümü yok: {sorted(items)}"
    i1 = items[item]
    assert (D(i1["earned_day"]), D(i1["spent_day"]), D(i1["qty_day"])) == (10, 17, 5)
    assert i1["pf_day"] is not None and D(i1["pf_day"]) == D(10) / D(17)
    i2 = items[f"i:{boq['i2'].id}"]
    assert (D(i2["spent_day"]), i2["pf_day"]) == (0, None)
    assert D(progress["spent_day"]) == 17
