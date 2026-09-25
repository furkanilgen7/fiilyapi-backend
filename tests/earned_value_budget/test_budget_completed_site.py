"""§3.11 B1-12: tamamlanmış şantiyede bütçe YAZMALARI salt okunur (409); OKUMALAR serbest.

Ayarlar ucunun (§3.10 F0-8, `test_settings_completed.py`) bütçe kardeşi. Kural TEK yerdedir
(`budget_service._writable_site`); her yazma ucu oradan geçer.

Her yazma ucu İKİ kez koşar (parametrize × durum):
* `active`  → aynı istek 2xx döner: istek GEÇERLİDİR, 409'un sebebi yalnız durumdur
  (kontrol vakası — 409'u yanlış sebepten, ör. eksik taslaktan, alan bir test yeşil kalamaz);
* `completed` → 409 + "salt okunur", ve revizyon listesi DEĞİŞMEZ (yazma sızmadı).

"Boşları doldur"un doldurulacak yaprağı OLMAYAN hâli ayrıca çivilidir: o yol taslağa hiç
dokunmaz (`_draft_for_write` çağrılmaz), kontrol yalnız taslak yoluna konsaydı 200 dönerdi.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import Response

from app.modules.sites.models import SiteStatus
from tests.earned_value_budget.test_budget_api import _map, _rates, _url

pytestmark = pytest.mark.asyncio


class _Ortam:
    def __init__(self, client, headers, santiye, boq, disiplinler) -> None:  # noqa: ANN001
        self.client, self.headers, self.santiye = client, headers, santiye
        self.boq, self.disiplinler = boq, disiplinler

    async def map(self) -> dict:
        return await _map(self.client, self.santiye, self.headers, self.boq, self.disiplinler)

    async def rates(self) -> dict:
        return await _rates(self.client, self.santiye, self.headers, self.boq)


_Hazirla = Callable[[_Ortam], Awaitable[dict]]
_Cagir = Callable[[_Ortam, dict], Awaitable[Response]]


async def _yok(o: _Ortam) -> dict:
    return {}


async def _taslakli(o: _Ortam) -> dict:
    view = await o.map()
    return {"rev_id": view["revision"]["id"]}


async def _donabilir(o: _Ortam) -> dict:
    await o.map()
    await o.rates()
    return {}


def _grup_govdesi(o: _Ortam) -> dict:
    kab, _ = o.disiplinler
    return {"items": [{"boq_group_id": str(o.boq["g1"].id), "discipline_id": str(kab.id)}]}


# (ad, hazırlık, çağrı, active'te beklenen durum)
_YAZMALAR: list[tuple[str, _Hazirla, _Cagir, int]] = [
    (
        "group-disciplines",
        _yok,
        lambda o, _: o.client.put(
            _url(o.santiye, "/group-disciplines"), headers=o.headers, json=_grup_govdesi(o)
        ),
        200,
    ),
    (
        "items-patch",
        _yok,
        lambda o, _: o.client.patch(
            _url(o.santiye, f"/items/{o.boq['i1'].id}"),
            headers=o.headers,
            json={"contractor_type": "subcon"},
        ),
        200,
    ),
    (
        "leaves-patch",
        _yok,
        lambda o, _: o.client.patch(
            _url(o.santiye, "/leaves"),
            headers=o.headers,
            json={
                "leaves": [
                    {
                        "boq_item_id": str(o.boq["i2"].id),
                        "section_id": str(o.boq["s1"].id),
                        "unit_mhr": "0.5",
                    }
                ]
            },
        ),
        200,
    ),
    (
        "fill-from-catalog",
        _taslakli,
        lambda o, _: o.client.post(_url(o.santiye, "/fill-from-catalog"), headers=o.headers),
        200,
    ),
    (
        "distributions",
        _yok,
        lambda o, _: o.client.put(
            _url(o.santiye, "/distributions"),
            headers=o.headers,
            json={"items": [{"discipline_id": str(o.disiplinler[0].id), "distribution": "bell"}]},
        ),
        200,
    ),
    (
        "windows",
        _yok,
        lambda o, _: o.client.put(
            _url(o.santiye, "/windows"),
            headers=o.headers,
            json={
                "windows": [
                    {
                        "discipline_id": str(o.disiplinler[0].id),
                        "section_id": str(o.boq["s2"].id),
                        "start_date": "2026-05-20",
                        "end_date": "2026-05-27",
                    }
                ]
            },
        ),
        200,
    ),
    (
        "taslak-ac",
        _yok,
        lambda o, _: o.client.post(_url(o.santiye, "/revisions"), headers=o.headers),
        201,
    ),
    (
        "taslak-sil",
        _taslakli,
        lambda o, h: o.client.delete(
            _url(o.santiye, f"/revisions/{h['rev_id']}"), headers=o.headers
        ),
        204,
    ),
    (
        "freeze",
        _donabilir,
        lambda o, _: o.client.post(_url(o.santiye, "/freeze"), headers=o.headers, json={}),
        200,
    ),
]


_HER_YAZMA = pytest.mark.parametrize(
    ("ad", "hazirla", "cagir", "beklenen"), _YAZMALAR, ids=[y[0] for y in _YAZMALAR]
)


@pytest.fixture
async def ortam(client, admin, santiye, boq, disiplinler, katalog) -> _Ortam:
    return _Ortam(client, admin, santiye, boq, disiplinler)


async def _revizyonlar(o: _Ortam) -> list[dict]:
    resp = await o.client.get(_url(o.santiye, "/revisions"), headers=o.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _tamamla(seeded_db, santiye) -> None:  # noqa: ANN001
    santiye.status = SiteStatus.completed
    await seeded_db.flush()


@_HER_YAZMA
async def test_B1_12_write_succeeds_on_active_site(ortam, ad, hazirla, cagir, beklenen) -> None:
    """KONTROL: aynı istek aktif şantiyede geçerlidir — 409'un tek sebebi durum olmalı."""
    hazir = await hazirla(ortam)
    resp = await cagir(ortam, hazir)
    assert resp.status_code == beklenen, f"{ad}: {resp.status_code} {resp.text}"


@_HER_YAZMA
async def test_B1_12_write_on_completed_site_is_409(
    ortam, seeded_db, ad, hazirla, cagir, beklenen
) -> None:
    hazir = await hazirla(ortam)
    once = await _revizyonlar(ortam)
    await _tamamla(seeded_db, ortam.santiye)
    resp = await cagir(ortam, hazir)
    assert resp.status_code == 409, f"{ad}: {resp.status_code} {resp.text}"
    assert "salt okunur" in resp.json()["detail"]
    assert await _revizyonlar(ortam) == once, f"{ad}: 409'a rağmen revizyon kümesi değişti"


async def test_B1_12_fill_with_nothing_to_fill_is_still_409(
    client, admin, seeded_db, santiye, boq, disiplinler
) -> None:
    """Katalog YOK → doldurulacak plan boş → servis taslağa hiç dokunmaz; yine de 409."""
    o = _Ortam(client, admin, santiye, boq, disiplinler)
    await o.map()
    active = await client.post(_url(santiye, "/fill-from-catalog"), headers=admin)
    assert (active.status_code, active.json()["filled_leaf_count"]) == (200, 0)
    await _tamamla(seeded_db, santiye)
    resp = await client.post(_url(santiye, "/fill-from-catalog"), headers=admin)
    assert resp.status_code == 409, resp.text


async def test_B1_12_reads_stay_open_on_completed_site(ortam, seeded_db) -> None:
    """Okumalar (GET bütçe/revizyonlar/fark/takvim/öneri + kalıcı olmayan POST önizleme) SERBEST."""
    view = await ortam.map()
    await ortam.rates()
    rev_id = view["revision"]["id"]
    await _tamamla(seeded_db, ortam.santiye)
    c, h, s = ortam.client, ortam.headers, ortam.santiye
    okumalar = {
        "budget": await c.get(_url(s), headers=h),
        "budget?revision_id": await c.get(_url(s), headers=h, params={"revision_id": rev_id}),
        "revisions": await c.get(_url(s, "/revisions"), headers=h),
        "diff": await c.get(_url(s, f"/revisions/{rev_id}/diff"), headers=h),
        "schedule": await c.get(_url(s, "/schedule"), headers=h),
        "suggestions": await c.get(_url(s, f"/items/{ortam.boq['i1'].id}/suggestions"), headers=h),
        "preview": await c.post(_url(s, "/preview"), headers=h, json={}),
    }
    durumlar = {ad: r.status_code for ad, r in okumalar.items()}
    assert durumlar == dict.fromkeys(okumalar, 200), durumlar
