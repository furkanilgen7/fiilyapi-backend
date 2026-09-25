"""EV-BORC-3 — PLN-F3 veri boşlukları G1–G7 (yalnız EK alan; ölçüm: F0 §4.3 ↔ B3 yanıtları).

Kurgu: conftest `baseline` + `saha_gunu` (05.05.2026). Baseline'da oranı boş yaprak YOK
(`_rates` dört yaprağın hepsine oran yazar) → G3 için ayrı kurgu `_baseline_bos_oranla`.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.site_diary.models import DiaryStatus
from tests.earned_value.test_settings import bands, body, pacal

from .conftest import DAY
from .test_reports import _allocate, _rep

D = Decimal


def _panel(site) -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/panel"


async def _get(client, headers, url: str, **params) -> dict:  # noqa: ANN001, ANN003
    resp = await client.get(url, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- G1 ---------------------------------------------------------------------------------


async def test_G1_panel_discipline_list_ignores_filter(
    client, saha, admin, santiye, boq, baseline, saha_gunu, disiplinler
) -> None:
    kab, duv = disiplinler
    full = await _get(client, admin, _panel(santiye), date=DAY.isoformat())
    filtered = await _get(
        client, admin, _panel(santiye), date=DAY.isoformat(), discipline_id=f"d:{kab.id}"
    )
    expected = [
        {"id": f"d:{kab.id}", "name": "Kaba İnşaat", "contractor_mix": "own"},
        {"id": f"d:{duv.id}", "name": "Duvar & Sıva", "contractor_mix": "subcon"},
    ]
    assert full["disciplines"] == expected
    assert filtered["disciplines"] == expected  # filtre listeyi DARALTMAZ
    assert [r["scope"] for r in filtered["rows"]] == ["overall", "discipline", "item"]


# --- G2 ---------------------------------------------------------------------------------


def _band_triplet(b: dict) -> tuple:
    return (
        D(b["red_below"]),
        D(b["green_from"]),
        None if b["high_above"] is None else D(b["high_above"]),
    )


async def test_G2_pf_bands_in_panel_daily_and_qurr(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    daily = (await _get(client, admin, _rep(santiye, "/daily"), date=DAY.isoformat()))["pf_bands"]
    panel = (await _get(client, admin, _panel(santiye), date=DAY.isoformat()))["pf_bands"]
    qurr = (await _get(client, admin, _rep(santiye, "/weekly"), week=1))["pf_bands"]
    assert daily == panel == qurr
    assert _band_triplet(daily["daily"]) == (D("0.95"), D("0.95"), D("1.05"))
    assert _band_triplet(daily["cumulative"]) == (D("0.95"), D("1.00"), None)


async def test_G2_approved_snapshot_keeps_its_own_bands_after_settings_change(
    client, sef, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    saha_gunu["diary"].status = DiaryStatus.submitted
    await seeded_db.flush()
    ok = await client.post(_rep(santiye, f"/daily/{DAY.isoformat()}/approve"), headers=sef)
    assert ok.status_code == 200, ok.text
    changed = await client.put(
        f"/sites/{santiye.id}/earned-value/settings",
        headers=admin,
        json=body(
            week_start_dow=0,
            pf_bands=bands(daily=("0.80", "0.90", "1.20"), weekly=("0.85", "0.90")),
        ),
    )
    assert changed.status_code == 200, changed.text
    snap = await _get(client, admin, _rep(santiye, "/daily"), date=DAY.isoformat())
    assert snap["status"] == "approved"
    assert snap["pf_bands"] is not None, "onaylı snapshot eşiksiz"
    assert _band_triplet(snap["pf_bands"]["daily"]) == (D("0.95"), D("0.95"), D("1.05"))  # ESKİ
    live = (await _get(client, admin, _panel(santiye), date=DAY.isoformat()))["pf_bands"]
    assert _band_triplet(live["daily"]) == (D("0.80"), D("0.90"), D("1.20"))  # canlı YENİ


# --- G3 + G7 ----------------------------------------------------------------------------


async def test_G3_empty_rate_leaf_warns_without_any_entry_and_G7_fields(
    client, admin, santiye, boq, disiplinler
) -> None:
    from .test_budget_api import _map, _url

    i1, i2, s1, s2 = boq["i1"], boq["i2"], boq["s1"], boq["s2"]
    await _map(client, santiye, admin, boq, disiplinler)
    leaves = [  # S2 yaprağı ORANSIZ bırakılır
        {"boq_item_id": str(i1.id), "section_id": str(s1.id), "unit_mhr": "2"},
        {"boq_item_id": str(i1.id), "section_id": None, "unit_mhr": "2"},
        {"boq_item_id": str(i2.id), "section_id": str(s1.id), "unit_mhr": "0.5"},
    ]
    assert (
        await client.patch(_url(santiye, "/leaves"), headers=admin, json={"leaves": leaves})
    ).status_code == 200
    assert (await client.post(_url(santiye, "/freeze"), headers=admin, json={})).status_code == 200
    panel = await _get(client, admin, _panel(santiye), date=DAY.isoformat())
    empty = [w for w in panel["warnings"] if w["code"] == "empty_rate"]
    assert [w["target_id"] for w in empty] == [f"l:{i1.id}:{s2.id}"]
    (w,) = empty
    assert (w["target"], w["item_name"], w["section_name"], w["uom"]) == (
        "leaf",
        "01.001 Beton",
        "B Blok",
        "m3",
    )
    assert all(w["item_name"] is None for w in panel["warnings"] if w["target"] != "leaf")


async def test_G7_overrun_warning_carries_leaf_fields(
    client, saha, admin, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    saha_gunu["line"].quantity = D(15)  # Bölümsüz planlı 10 → aşım
    await seeded_db.flush()
    rep = await _get(client, admin, _rep(santiye, "/daily"), date=DAY.isoformat())
    (w,) = [x for x in rep["warnings"] if x["code"] == "qty_overrun"]
    assert (w["item_name"], w["section_name"], w["uom"], D(w["value"])) == (
        "01.001 Beton",
        None,
        "m3",
        5,
    )


# --- G4 + G5 + G6 -----------------------------------------------------------------------


async def test_G4_G5_G6_qurr_generated_at_composite_names_calendar(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    i1, i2 = boq["i1"], boq["i2"]
    saved = await client.put(
        f"/sites/{santiye.id}/earned-value/settings",
        headers=admin,
        json=body(week_start_dow=0, composite_metrics=[pacal("Karma", [i1, i2], i1)]),
    )
    assert saved.status_code == 200, saved.text
    q = await _get(client, admin, _rep(santiye, "/weekly"), week=1)
    assert q["generated_at"] is not None
    (card,) = q["composites"]
    assert (card["numerator_names"], card["denominator_name"]) == (["Beton", "Tuğla"], "Beton")
    assert (q["calendar_start"], q["last_week_no"]) == ("2026-05-04", _last_week(q))
    panel = await _get(client, admin, _panel(santiye), date=DAY.isoformat())
    daily = await _get(client, admin, _rep(santiye, "/daily"), date=DAY.isoformat())
    assert panel["calendar_start"] == daily["calendar_start"] == "2026-05-04"
    assert panel["calendar_end"] == daily["calendar_end"] == "2026-05-29"


def _last_week(q: dict) -> int:
    """Takvim sonu haftası: hafta 1 = 04.05 Pzt; takvim `as_of = bugün` ile bugüne uzar."""
    from datetime import date

    end = date.fromisoformat(q["calendar_end"])
    return (end - date(2026, 5, 4)).days // 7 + 1


async def test_pre_evborc3_snapshot_payload_still_validates(
    client, admin, santiye, baseline, saha_gunu
) -> None:
    """Bu dilimden ÖNCE onaylanmış snapshot yeni alanları TAŞIMAZ; okunurken 500 olmamalı."""
    from app.modules.earned_value.schemas_reports import DailyReport

    payload = await _get(client, admin, _rep(santiye, "/daily"), date=DAY.isoformat())
    for key in ("pf_bands", "calendar_start", "calendar_end"):
        payload.pop(key)
    for w in payload["warnings"]:
        for key in ("item_name", "section_name", "uom"):
            w.pop(key)
    old = DailyReport.model_validate(payload)
    assert (old.pf_bands, old.calendar_start, old.warnings[0].item_name) == (None, None, None)
