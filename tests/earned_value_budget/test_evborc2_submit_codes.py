"""EV-BORC-2 (1) — Gönder 422 `reason_items[]`: her engel YAPISAL `code` taşır (EK alan).

Frontend bugün backend METNİNE regex'le bakıyordu; metin değişince ekran bozulurdu. `reasons`
(metin listesi) geri uyum için AYNEN kalır; `reason_items` aynı sırada {code, message} verir.
Aynı kodlar gün ekranının `submit.reason_items`inde de döner (Gönder'e basmadan önce).
"""

from __future__ import annotations

from app.modules.earned_value import diary_adapter as adp

from .test_day_allocation import _day
from .test_day_integration import _submit


async def test_submit_422_carries_structured_codes_in_order(
    client, saha, santiye, baseline, saha_gunu
) -> None:
    resp = await _submit(client, saha, saha_gunu["diary"])
    assert resp.status_code == 422, resp.text
    body = resp.json()
    items = body["reason_items"]
    assert [i["code"] for i in items] == [adp.SUBMIT_WEATHER, adp.SUBMIT_UNDISTRIBUTED]
    assert [i["message"] for i in items] == body["reasons"]  # metin listesiyle birebir


async def test_day_view_submit_check_has_same_codes(
    client, saha, santiye, baseline, saha_gunu
) -> None:
    view = (await client.get(_day(santiye), headers=saha)).json()
    codes = [i["code"] for i in view["submit"]["reason_items"]]
    assert codes == [adp.SUBMIT_WEATHER, adp.SUBMIT_UNDISTRIBUTED]
    assert [i["message"] for i in view["submit"]["reason_items"]] == view["submit"]["reasons"]
