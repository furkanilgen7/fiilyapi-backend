"""EV-BORC-8 — baseline'ı OLMAYAN şantiyede günlük rapor ONAYI 409 döner ama yanlış
metinle: `report_daily.NOT_GENERATED` ("Bu günün günlüğü yok — rapor üretilemedi").
Gerçek sebep günlük yokluğu değil, baseline yokluğudur — GET `/weekly` zaten bunu
`diary_adapter.NO_BASELINE` ile ayırt ediyor
(bkz. test_evborc3_s315.py::test_S6_no_baseline_is_409_not_404), onay ucu da aynı
ayrımı yapmalı.

Kurgu: `santiye` + `boq` fikstürleri baseline'SIZ (dondurma yok) — `baseline` fikstürü
bilerek kullanılmıyor. Regresyon: `baseline` VARKEN günlüksüz günde davranış AYNI
kalmalı (409 NOT_GENERATED) — bkz. test_reports.py::test_approve_not_generated_is_409.
"""

from __future__ import annotations

from app.modules.earned_value import diary_adapter, report_daily

from .conftest import DAY
from .test_reports import _rep


async def test_approve_without_baseline_is_no_baseline_409(client, sef, santiye, boq) -> None:
    """Baseline hiç dondurulmamış şantiyede onay → 409 `diary_adapter.NO_BASELINE`,
    `report_daily.NOT_GENERATED` DEĞİL (gerçek sebep baseline yokluğu)."""
    url = _rep(santiye, f"/daily/{DAY.isoformat()}/approve")
    resp = await client.post(url, headers=sef)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == diary_adapter.NO_BASELINE


async def test_approve_without_diary_on_baselined_day_stays_not_generated(
    client, sef, santiye, boq, baseline
) -> None:
    """Regresyon: baseline VAR ama d günü günlüğü yoksa davranış AYNI kalır (409
    `report_daily.NOT_GENERATED`) — bkz. test_reports.py::test_approve_not_generated_is_409."""
    url = _rep(santiye, "/daily/2026-05-06/approve")
    resp = await client.post(url, headers=sef)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == report_daily.NOT_GENERATED


def test_approve_409_openapi_description_mentions_no_baseline() -> None:
    """Sözleşme: onay ucunun beyan ettiği 409 açıklaması `NO_BASELINE` metnini de
    taşımalı — çağıran taraf yanıtı görmeden bile gerçek sebebi bilebilmeli."""
    from app.main import app

    schema = app.openapi()
    path = schema["paths"]["/sites/{site_id}/earned-value/reports/daily/{day}/approve"]
    description = path["post"]["responses"]["409"]["description"]
    assert diary_adapter.NO_BASELINE in description
