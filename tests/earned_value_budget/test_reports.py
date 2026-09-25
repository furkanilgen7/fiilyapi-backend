"""Rapor uçları (PLN-B3): günlük rapor · onay + snapshot + kilit · haftalık QURR · Excel.

Kurgu = conftest `baseline` + `saha_gunu` (05.05.2026, baseline 04.05 başlar → gün 2, hafta 1):
I1 Bölümsüz 5 m3 × oran 2 → earned 10 · dağıtım Ali 9 direct + Veli 8 prorata → spent 17.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.site_diary.models import DiaryStatus

from .conftest import DAY
from .test_day_allocation import _body, _day

D = Decimal


def _rep(site, tail: str = "") -> str:  # noqa: ANN001
    return f"/sites/{site.id}/earned-value/reports{tail}"


async def _allocate(client, saha, santiye, boq, saha_gunu) -> None:  # noqa: ANN001
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    ).status_code == 200


async def test_daily_not_generated_without_diary(client, admin, santiye, baseline) -> None:
    resp = await client.get(_rep(santiye, "/daily"), headers=admin, params={"date": "2026-05-06"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "not_generated"


async def test_daily_report_values(client, saha, admin, santiye, boq, baseline, saha_gunu) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    rep = (
        await client.get(_rep(santiye, "/daily"), headers=admin, params={"date": DAY.isoformat()})
    ).json()
    assert (rep["status"], rep["report_no"], rep["day_no"], rep["week_no"]) == ("draft", 2, 2, 1)
    overall = next(k for k in rep["kpis"] if k["kind"] == "overall")
    assert (D(overall["earned_cum"]), D(overall["spent_cum"])) == (10, 17)
    assert rep["draft_diary_dates"] == [DAY.isoformat()]
    assert D(rep["footer"]["timesheet_total_day"]) == 17
    assert D(rep["footer"]["undistributed_day"]) == 0
    assert len(rep["weather"]) == 7 and len(rep["trend"]) == 7
    assert [t["is_future"] for t in rep["trend"]][:2] == [False, False]
    assert rep["trend"][2]["is_future"] is True
    item = next(q for q in rep["quantities"] if q["node_id"] == f"i:{boq['i1'].id}")
    assert (D(item["qty_cum"]), D(item["spent_day"])) == (5, 17)


async def test_approve_requires_submitted_diaries_then_locks_and_snapshots(
    client, sef, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    url = _rep(santiye, f"/daily/{DAY.isoformat()}/approve")
    blocked = await client.post(url, headers=sef)
    assert blocked.status_code == 422 and "gönderilmeli" in blocked.json()["detail"]
    saha_gunu["diary"].status = DiaryStatus.submitted
    await seeded_db.flush()
    assert (await client.post(url, headers=saha)).status_code == 403  # saha: draft < approve
    ok = await client.post(url, headers=sef)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert (body["report"]["status"], body["report"]["version"]) == ("approved", 1)
    assert body["missing_diary_dates"] == ["2026-05-04"]  # günlüğü hiç olmayan iş günü (B3-1)
    # gün kilitlendi: dağıtım yazması 409
    again = await client.put(
        _day(santiye, "/allocation"),
        headers=saha,
        json=_body(boq, saha_gunu["ali"], saha_gunu["veli"]),
    )
    assert again.status_code == 409
    # onaylı rapor DEĞİŞMEZ: puantaj sonradan değişse de snapshot aynı
    saha_gunu["ts"]["Ali Usta"].hours = D(12)
    await seeded_db.flush()
    rep = (
        await client.get(_rep(santiye, "/daily"), headers=sef, params={"date": DAY.isoformat()})
    ).json()
    assert (rep["status"], D(rep["footer"]["timesheet_total_day"])) == ("approved", 17)


async def test_reapproval_after_unlock_writes_new_version(
    client, sef, saha, seeded_db, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    saha_gunu["diary"].status = DiaryStatus.submitted
    await seeded_db.flush()
    url = _rep(santiye, f"/daily/{DAY.isoformat()}/approve")
    assert (await client.post(url, headers=sef)).status_code == 200
    assert (
        await client.post(_day(santiye, "/unlock"), headers=sef, json={"reason": "düzeltme"})
    ).status_code == 200
    second = await client.post(url, headers=sef)
    assert second.status_code == 200
    assert second.json()["report"]["version"] == 2  # B3-5: tarihçe, no aynı


async def test_weekly_qurr_rows_and_totals(
    client, saha, admin, santiye, boq, baseline, saha_gunu
) -> None:
    await _allocate(client, saha, santiye, boq, saha_gunu)
    resp = await client.get(_rep(santiye, "/weekly"), headers=admin, params={"week": 1})
    assert resp.status_code == 200, resp.text
    q = resp.json()
    row = next(r for r in q["rows"] if r["node_id"] == f"i:{boq['i1'].id}")
    assert (D(row["c_qty_cum"]), D(row["h_earned_cum"]), D(row["i_spent_cum"])) == (5, 10, 17)
    assert D(row["j_remaining_mhr"]) == D(row["d_remaining_qty"]) * D(row["n_unit_mhr"])  # K26
    assert D(row["q_pf_cum"]) == D(10) / D(17)
    assert (row["a_prev_qty"], q["previous_revision"]) == (None, None)  # tek revizyon
    kinds = [t["kind"] for t in q["totals"]]
    assert kinds[-2:] == ["direct_total", "all_total"]
    assert {k["scope"] for k in q["kpis"]} == {"overall_own", "overall_subcon"}
    assert (
        await client.get(_rep(santiye, "/weekly"), headers=admin, params={"week": 99})
    ).status_code == 404


async def test_weekly_xlsx_export(client, admin, santiye, baseline, saha_gunu) -> None:
    resp = await client.get(_rep(santiye, "/weekly.xlsx"), headers=admin, params={"week": 1})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert resp.content[:2] == b"PK"


async def _freeze_with_rates(client, admin, santiye, boq, disiplinler, s2_rate: str) -> None:  # noqa: ANN001
    from .test_budget_api import _map, _url

    i1, i2, s1, s2 = boq["i1"], boq["i2"], boq["s1"], boq["s2"]
    await _map(client, santiye, admin, boq, disiplinler)
    leaves = [
        {"boq_item_id": str(i1.id), "section_id": str(s1.id), "unit_mhr": "2"},
        {"boq_item_id": str(i1.id), "section_id": str(s2.id), "unit_mhr": s2_rate},
        {"boq_item_id": str(i1.id), "section_id": None, "unit_mhr": "2"},
        {"boq_item_id": str(i2.id), "section_id": str(s1.id), "unit_mhr": "0.5"},
    ]
    assert (
        await client.patch(_url(santiye, "/leaves"), headers=admin, json={"leaves": leaves})
    ).status_code == 200
    assert (await client.post(_url(santiye, "/freeze"), headers=admin, json={})).status_code == 200


async def _i1_row(client, admin, santiye, boq) -> dict:  # noqa: ANN001
    q = (await client.get(_rep(santiye, "/weekly"), headers=admin, params={"week": 1})).json()
    return next(r for r in q["rows"] if r["node_id"] == f"i:{boq['i1'].id}")


async def test_weekly_qurr_j_is_leaf_sum_not_average_rate(
    client, saha, admin, santiye, boq, disiplinler, saha_gunu
) -> None:
    """K26 (CEO kararı): j = Σ yaprak (kalan × YAPRAĞIN oranı) — ortalama oran × toplam kalan
    DEĞİL. I1 = S1 60 × 2 + S2 30 × 3 + Bölümsüz 10 × 2 = 230; Bölümsüz'e 5 m3 →
    j = 60·2 + 30·3 + 5·2 = 220 (d × n = 95 × 2,3 = 218,5 olurdu)."""
    await _freeze_with_rates(client, admin, santiye, boq, disiplinler, "3")
    await _allocate(client, saha, santiye, boq, saha_gunu)
    row = await _i1_row(client, admin, santiye, boq)
    assert (D(row["g_budget_mhr"]), D(row["h_earned_cum"]), D(row["n_unit_mhr"])) == (
        230,
        10,
        D("2.3"),
    )
    assert D(row["j_remaining_mhr"]) == 220


async def test_weekly_qurr_j_overrun_is_unclipped_negative_contribution(
    client, saha, admin, seeded_db, santiye, boq, disiplinler, saha_gunu
) -> None:
    """K26 (CEO kararı, spec §3.4 aynen): togo KIRPMASIZ — aşan yaprağın kalanı negatif katkı
    verir, j = Σ yaprak = g − h. Bölümsüz planlı 10, girilen 15: j = 60·2 + 30·3 + (−5)·2 =
    200 = 230 − 30. (Kırpma olsaydı 210; kırpma kullanıcı kararı bekliyor.) d = 85."""
    await _freeze_with_rates(client, admin, santiye, boq, disiplinler, "3")
    saha_gunu["line"].quantity = D(15)
    await seeded_db.flush()
    await _allocate(client, saha, santiye, boq, saha_gunu)
    row = await _i1_row(client, admin, santiye, boq)
    assert (D(row["h_earned_cum"]), D(row["d_remaining_qty"])) == (30, 85)
    assert D(row["j_remaining_mhr"]) == 200
    assert D(row["j_remaining_mhr"]) == D(row["g_budget_mhr"]) - D(row["h_earned_cum"])


async def test_approve_not_generated_is_409(client, sef, santiye, boq, baseline) -> None:
    """B3-1: d günü günlüğü HİÇ yoksa rapor üretilmez → onay 409 (kilit/snapshot yazılmaz)."""
    url = _rep(santiye, "/daily/2026-05-06/approve")
    resp = await client.post(url, headers=sef)
    assert resp.status_code == 409 and "günlüğü yok" in resp.json()["detail"]
