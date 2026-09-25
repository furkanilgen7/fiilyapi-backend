"""Günlük saat dağıtımı adaptörü (PLN-B2.2) — EV uçları + gün kilidi.

Kurgu (conftest + dondurulmuş baseline): gün = 05.05.2026 Salı (S1 penceresi içinde).
Puantaj: Ali 9 sa · Veli 8 sa. Günlük satırı: I1 Bölümsüz (l:I1:none) 5 m3 (oran 2).
Dağıtım: Ali → l:I1:none 9 sa (direct) · Veli → i:I1 8 sa (prorata; o gün miktarı olan tek
yaprak l:I1:none → 8 sa oraya iner).
Beklenen (elle): earned l:I1:none = 5 × 2 = 10 · spent = 9 + 8 = 17 · PF = 10/17.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.modules.earned_value.models import EvReportApproval

from .conftest import DAY

D = Decimal


def _day(site, tail: str = "") -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/days/{DAY.isoformat()}{tail}"


def _body(boq, ali, veli) -> dict:  # noqa: ANN001
    none_leaf = f"l:{boq['i1'].id}:none"
    return {
        "codes": [
            {"node_id": none_leaf, "rule": "direct"},
            {"node_id": f"i:{boq['i1'].id}", "rule": "prorata_by_daily_qty"},
        ],
        "cells": [
            {
                "row": {"kind": "personnel", "ref_id": str(ali.id)},
                "node_id": none_leaf,
                "hours": "9",
            },
            {
                "row": {"kind": "personnel", "ref_id": str(veli.id)},
                "node_id": f"i:{boq['i1'].id}",
                "hours": "8",
            },
        ],
    }


async def test_day_view_rows_from_timesheet(client, admin, santiye, baseline, saha_gunu) -> None:
    resp = await client.get(_day(santiye), headers=admin)
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert view["has_baseline"] is True and view["revision_number"] == 0
    assert [(r["label"], D(r["hours"])) for r in view["rows"]] == [
        ("Ali Usta", 9),
        ("Veli Usta", 8),
    ]
    assert D(view["totals"]["unallocated_hours"]) == 17
    assert view["day_no"] == 2  # baseline 04.05'te başlar
    assert view["lock"]["locked"] is False


async def test_save_allocation_and_engine_progress(
    client, saha, santiye, boq, baseline, saha_gunu
) -> None:
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    resp = await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    assert resp.status_code == 200, resp.text
    view = resp.json()
    assert D(view["totals"]["allocated_hours"]) == 17
    assert D(view["totals"]["unallocated_hours"]) == 0
    leaf = next(x for x in view["progress"]["leaves"] if x["node_id"] == f"l:{boq['i1'].id}:none")
    assert (D(leaf["earned_day"]), D(leaf["spent_day"])) == (10, 17)
    assert D(leaf["pf_day"]) == D(10) / D(17)
    assert {c["rule"] for c in view["codes"]} == {"direct", "prorata_by_daily_qty"}


async def test_unknown_code_and_foreign_row_are_422(
    client, saha, santiye, boq, baseline, saha_gunu
) -> None:
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    bad = {**body, "codes": [*body["codes"], {"node_id": "l:yok:none", "rule": "direct"}]}
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=bad)
    ).status_code == 422
    stranger = {**body}
    stranger["cells"] = [
        {
            "row": {"kind": "personnel", "ref_id": str(boq["i1"].id)},
            "node_id": body["codes"][0]["node_id"],
            "hours": "1",
        }
    ]
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=stranger)
    ).status_code == 422


async def test_allocation_requires_active_baseline(client, saha, santiye, boq, saha_gunu) -> None:
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    resp = await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    assert resp.status_code == 409


async def test_timesheet_change_after_allocation_is_flagged(
    client, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await client.put(
        _day(santiye, "/allocation"),
        headers=saha,
        json=_body(boq, saha_gunu["ali"], saha_gunu["veli"]),
    )
    saha_gunu["ts"]["Ali Usta"].hours = D(11)
    await seeded_db.flush()
    view = (await client.get(_day(santiye), headers=saha)).json()
    ali = next(r for r in view["rows"] if r["label"] == "Ali Usta")
    assert (D(ali["saved_hours"]), D(ali["hours"]), ali["changed"]) == (9, 11, True)
    assert D(view["totals"]["unallocated_hours"]) == 2  # K14: 19 kaynak − 17 dağıtılan


async def test_permission_view_vs_write(
    client, muhasebe, ik, santiye, boq, baseline, saha_gunu
) -> None:
    assert (await client.get(_day(santiye), headers=muhasebe)).status_code == 200
    assert (await client.get(_day(santiye), headers=ik)).status_code == 403
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    assert (
        await client.put(_day(santiye, "/allocation"), headers=muhasebe, json=body)
    ).status_code == 403


# ------------------------------------------------------------------ gün kilidi (B2-6)


async def _approve(seeded_db, santiye, report_date: date, at: datetime) -> None:  # noqa: ANN001
    seeded_db.add(EvReportApproval(site_id=santiye.id, report_date=report_date, approved_at=at))
    await seeded_db.flush()


async def test_report_approval_locks_days_up_to_its_date(
    client, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(seeded_db, santiye, DAY, datetime(2026, 5, 6, tzinfo=UTC))
    view = (await client.get(_day(santiye), headers=saha)).json()
    assert view["lock"]["locked"] is True and view["lock"]["report_date"] == "2026-05-05"
    resp = await client.put(
        _day(santiye, "/allocation"),
        headers=saha,
        json=_body(boq, saha_gunu["ali"], saha_gunu["veli"]),
    )
    assert resp.status_code == 409
    assert "raporuyla kilitli" in resp.json()["detail"]
    after = f"/sites/{santiye.id}/earned-value/days/{(DAY + timedelta(days=1)).isoformat()}"
    assert (await client.get(after, headers=saha)).json()["lock"]["locked"] is False


async def test_day_unlock_is_day_level_and_reapproval_relocks(
    client, sef, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _approve(seeded_db, santiye, DAY + timedelta(days=2), datetime(2026, 5, 8, tzinfo=UTC))
    body = {"reason": "Puantaj düzeltmesi"}
    assert (await client.post(_day(santiye, "/unlock"), headers=saha, json=body)).status_code == 403
    resp = await client.post(_day(santiye, "/unlock"), headers=sef, json=body)
    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["locked"] is False and resp.json()["unlock"]["reason"] == "Puantaj düzeltmesi"
    )
    # yalnız O GÜN açıldı; ertesi gün hâlâ kilitli
    nxt = f"/sites/{santiye.id}/earned-value/days/{(DAY + timedelta(days=1)).isoformat()}"
    assert (await client.get(nxt, headers=saha)).json()["lock"]["locked"] is True
    ok = await client.put(
        _day(santiye, "/allocation"),
        headers=saha,
        json=_body(boq, saha_gunu["ali"], saha_gunu["veli"]),
    )
    assert ok.status_code == 200
    # B3'te yeniden onay (istisnadan SONRA) → gün yeniden kilitlenir
    await _approve(
        seeded_db, santiye, DAY + timedelta(days=2), datetime.now(UTC) + timedelta(minutes=1)
    )
    assert (await client.get(_day(santiye), headers=saha)).json()["lock"]["locked"] is True
    # kilitli olmayan gün açılamaz
    free = f"/sites/{santiye.id}/earned-value/days/{(DAY + timedelta(days=9)).isoformat()}/unlock"
    assert (await client.post(free, headers=sef, json=body)).status_code == 409


async def test_code_tree_marks_rated_leaves(client, admin, santiye, boq, baseline) -> None:
    nodes = (await client.get(f"/sites/{santiye.id}/earned-value/code-tree", headers=admin)).json()
    levels = {n["level"] for n in nodes}
    assert levels == {1, 2, 3, 4}
    leaf = next(n for n in nodes if n["id"] == f"l:{boq['i1'].id}:none")
    assert (leaf["has_rate"], leaf["label"]) == (True, "Bölümsüz")
