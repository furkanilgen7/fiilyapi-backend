"""Planlama paneli (PLN-B3 PNL): filtre bütün panele · pencereler · histogram tabanı.

Kurgu = conftest `baseline` + `saha_gunu` (05.05.2026, takvim 04.05 başlar):
KAB (kendi) I1 bütçe 100 × 2 = 200 · DUV (taşeron) I2 50 × 0,5 = 25.
05.05: I1 5 m3 → earned 10 · Ali 9 + Veli 8 (şirket personeli) → spent 17 (hepsi I1).
"""

from __future__ import annotations

from decimal import Decimal

from .conftest import DAY
from .test_reports import _allocate

D = Decimal


def _panel(site) -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/panel"


async def _get(client, headers, site, **params):  # noqa: ANN001, ANN003, ANN202
    resp = await client.get(
        _panel(site), headers=headers, params={"date": DAY.isoformat(), **params}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_panel_without_baseline(client, admin, santiye, boq) -> None:
    p = await _get(client, admin, santiye)
    assert (p["has_baseline"], p["kpi"], p["rows"]) == (False, None, [])


async def test_panel_unfiltered(client, saha, admin, santiye, boq, baseline, saha_gunu) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    p = await _get(client, admin, santiye)
    k = p["kpi"]
    assert (D(k["budget_mhr"]), D(k["earned_cum"]), D(k["spent_day"])) == (225, 10, 17)
    assert D(k["pf_cum"]) == D(10) / D(17) and D(k["pf_week"]) == D(10) / D(17)
    assert (D(k["timesheet_total_day"]), D(k["undistributed_day"])) == (17, 0)
    assert (p["has_field_data"], p["day_no"], p["week_no"]) == (True, 2, 1)
    # çubuk = son 28 gün, takvim başında kırpılır; günlük durumu işaretli
    assert [(b["day"], b["diary_status"]) for b in p["bars"]] == [
        ("2026-05-04", "none"),
        (DAY.isoformat(), "draft"),
    ]
    # S-eğrisi 4w: d+28'e kadar gelecek planlı dahil (takvimle kırpılır)
    assert p["s_curve"][-1]["is_future"] is True and p["s_curve"][0]["day"] == "2026-05-04"
    week1 = p["histogram"][0]
    assert p["actual_basis"] == "headcount"
    assert D(week1["actual_people"]) == 1  # (0 + 2 kişi) ÷ 2 geçen iş günü
    assert week1["planned_people"] is not None
    scopes = [(r["scope"], r["name"]) for r in p["rows"]]
    assert scopes[:3] == [
        ("overall", "Genel"),
        ("overall_own", "Genel – Kendi"),
        ("overall_subcon", "Genel – Taşeron"),
    ]
    assert [s for s, _ in scopes[3:]] == [
        "discipline",
        "item",
        "discipline",
        "item",
        "non_direct",
    ]
    item = next(r for r in p["rows"] if r["node_id"] == f"i:{boq['i1'].id}")
    assert (D(item["earned_cum"]), D(item["spent_cum"]), item["parent_id"]) == (
        10,
        17,
        p["rows"][3]["node_id"],
    )


async def test_panel_discipline_filter_switches_to_equivalent(
    client, saha, admin, santiye, boq, baseline, saha_gunu, disiplinler
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    kab = f"d:{disiplinler[0].id}"
    p = await _get(client, admin, santiye, discipline_id=kab)
    assert D(p["kpi"]["budget_mhr"]) == 200
    assert p["actual_basis"] == "equivalent"
    assert D(p["histogram"][0]["actual_people"]) == D(17) / (2 * D(9))  # harcanan ÷ (2 × 9)
    assert [r["scope"] for r in p["rows"]] == ["overall", "discipline", "item"]
    missing = await client.get(
        _panel(santiye), headers=admin, params={"date": DAY.isoformat(), "discipline_id": "d:x"}
    )
    assert missing.status_code == 404


async def test_panel_contractor_filter_applies_to_whole_panel(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    p = await _get(client, admin, santiye, contractor_type="subcon")
    assert (D(p["kpi"]["budget_mhr"]), D(p["kpi"]["earned_cum"])) == (25, 0)
    assert all(D(b["spent_day"] or 0) == 0 for b in p["bars"])  # grafikler de filtreli
    assert p["actual_basis"] == "headcount"
    assert D(p["histogram"][0]["actual_people"]) == 0  # şirket personeli taşeron sayımına girmez
    assert [r["scope"] for r in p["rows"]] == ["overall", "discipline", "item", "non_direct"]
    own = await _get(client, admin, santiye, contractor_type="own")
    assert D(own["histogram"][0]["actual_people"]) == 1


async def test_panel_ranges(client, admin, santiye, boq, baseline, saha_gunu) -> None:
    for rng in ("4w", "3m", "all"):
        p = await _get(client, admin, santiye, range=rng)
        assert p["range"] == rng and p["histogram"][0]["week_start"] == "2026-05-04"
    bad = await client.get(
        _panel(santiye), headers=admin, params={"date": DAY.isoformat(), "range": "1y"}
    )
    assert bad.status_code == 422
