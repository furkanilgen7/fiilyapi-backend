"""AYP canlı önizleme (PLN-B3): bugünün sapması (K27 puan) · PF · hafta no · paçal (B3-3).

Kurgu: `baseline` + `saha_gunu` + dağıtım (05.05: earned 10 · spent 17, hepsi I1).
Overall (direct, bütçe 225): variance = 10/225 − planlı → puan K27 ile 1 ondalık.
Paçal "spent I1 ÷ I1": gerçek 17 / 5 = 3,4 · planlı 200 / 100 = 2 · sapma 0,7.
"""

from __future__ import annotations

from decimal import Decimal

from tests.earned_value.test_settings import body, pacal

from .conftest import DAY
from .test_reports import _allocate

D = Decimal


def _url(site, tail: str = "") -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/settings/preview{tail}"


async def test_preview_without_baseline(client, admin, santiye, boq) -> None:
    resp = await client.get(_url(santiye), headers=admin, params={"date": DAY.isoformat()})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["has_baseline"], resp.json()["week_no"]) == (False, None)


async def test_preview_live_values_and_saved_composite(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    i1 = boq["i1"]
    saved = await client.put(
        f"/sites/{santiye.id}/earned-value/settings",
        headers=admin,
        json=body(week_start_dow=0, composite_metrics=[pacal("I1 oranı", [i1], i1)]),
    )
    assert saved.status_code == 200, saved.text
    p = (await client.get(_url(santiye), headers=admin, params={"date": DAY.isoformat()})).json()
    assert (p["has_baseline"], p["day_no"], p["week_no"], p["week_start"]) == (
        True,
        2,
        1,
        "2026-05-04",
    )
    variance = D(p["variance"])
    assert D(p["variance_points"]) == (variance * 100).quantize(D("0.1"))
    assert p["status"] == "late" and D(p["variance_points"]) < -2
    assert D(p["pf_day"]) == D(10) / D(17) and p["pf_day_band"] == "red"
    [card] = p["composites"]
    assert (D(card["actual"]), D(card["planned"]), D(card["deviation"])) == (
        D("3.4"),
        2,
        D("0.7"),
    )
    assert card["unit"] == "m3"


async def test_composite_preview_for_unsaved_metric(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    i1, i2 = boq["i1"], boq["i2"]
    params = {
        "date": DAY.isoformat(),
        "measure": "earned",
        "numerator_item_id": [str(i1.id), str(i2.id)],
        "denominator_item_id": str(i1.id),
    }
    resp = await client.get(_url(santiye, "/composite"), headers=admin, params=params)
    assert resp.status_code == 200, resp.text
    v = resp.json()
    assert (D(v["actual"]), D(v["planned"])) == (2, D(225) / 100)  # (10 + 0) / 5 · 225 / 100
    missing = await client.get(
        _url(santiye, "/composite"),
        headers=admin,
        params={**params, "numerator_item_id": []},
    )
    assert missing.status_code == 422
