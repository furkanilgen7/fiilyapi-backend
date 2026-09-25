"""PLN-B2.x-A — ESKİ İSTEMCİ BEKÇİSİ (frontend F2 merge'ünün ön koşulu).

`PUT …/lines` ve `PATCH …` (`worker_counts`) DEĞİŞTİRME semantiğidir: B2 öncesi bir
istemci bölüm / firma alanlarını hiç bilmez, kaydettiğinde yeni alanlı satırları SESSİZCE
silerdi (bölümlü satırları Bölümsüz'e çevirir, firma satırını düşürür).

Kural: kayıtta yeni alanlı satır varken gövdedeki HİÇBİR satır o ANAHTARI taşımıyorsa
(eski imza) → 409 "Sayfa güncellendi…", veri KORUNUR. Anahtarın VARLIĞINA bakılır:
yeni istemci `section_id: null` yollar ve geçer. Kayıtta yeni alanlı satır yoksa eski
imza da geçer (bugünkü canlı akış). Boş gövde ayırt edilemez ("hepsini temizle") →
eski imza SAYILMAZ.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.site_diary import guards
from tests.site_diary.test_b21_bolum_satiri import _satir, _tahsis
from tests.site_diary.test_b21_taseron_satiri import (  # noqa: F401
    _firma,
    _isciler,
    _kayit,
    firmalar,
)

pytestmark = pytest.mark.asyncio


async def _lines(client: AsyncClient, headers, entry_id: str, satirlar: list[dict]):  # noqa: ANN001, ANN202
    return await client.put(f"/diary/{entry_id}/lines", json={"lines": satirlar}, headers=headers)


async def _detail(client: AsyncClient, headers, entry_id: str) -> dict:  # noqa: ANN001
    resp = await client.get(f"/diary/{entry_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _eski(item, qty: str) -> dict:  # noqa: ANN001
    """B2 öncesi satır: `section_id` ANAHTARI hiç yok."""
    return {"boq_item_id": str(item.id), "quantity": qty}


# --- miktar satırları -------------------------------------------------------------------


async def _bolumlu_kayit(client, headers, santiye, bolum, seeded_db) -> tuple[str, object]:  # noqa: ANN001
    site, _, items = santiye
    await _tahsis(seeded_db, items[0], bolum, "50")
    entry_id = await _kayit(client, headers, site.id)
    ok = await _lines(client, headers, entry_id, [_satir(items[0], "4", section=bolum)])
    assert ok.status_code == 200, ok.text
    return entry_id, items[0]


async def test_B2xA_old_line_signature_with_sectioned_rows_is_409_and_keeps_data(
    client: AsyncClient, admin_headers, santiye, bolum, seeded_db
) -> None:
    entry_id, item = await _bolumlu_kayit(client, admin_headers, santiye, bolum, seeded_db)
    resp = await _lines(client, admin_headers, entry_id, [_eski(item, "7")])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.STALE_CLIENT
    (line,) = (await _detail(client, admin_headers, entry_id))["lines"]
    assert (line["section_id"], Decimal(line["quantity"])) == (str(bolum.id), 4)


async def test_B2xA_new_line_signature_passes(
    client: AsyncClient, admin_headers, santiye, bolum, seeded_db
) -> None:
    entry_id, item = await _bolumlu_kayit(client, admin_headers, santiye, bolum, seeded_db)
    body = [_satir(item, "4", section=bolum), {**_eski(item, "2"), "section_id": None}]
    resp = await _lines(client, admin_headers, entry_id, body)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["lines"]) == 2


async def test_B2xA_old_line_signature_without_sectioned_rows_still_passes(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, items = santiye
    entry_id = await _kayit(client, admin_headers, site.id)
    assert (
        await _lines(client, admin_headers, entry_id, [_eski(items[0], "3")])
    ).status_code == 200
    again = await _lines(client, admin_headers, entry_id, [_eski(items[0], "5")])
    assert again.status_code == 200, again.text  # bugünkü canlı akış bozulmaz


async def test_B2xA_empty_line_body_is_not_old_signature(
    client: AsyncClient, admin_headers, santiye, bolum, seeded_db
) -> None:
    entry_id, _ = await _bolumlu_kayit(client, admin_headers, santiye, bolum, seeded_db)
    resp = await _lines(client, admin_headers, entry_id, [])
    assert resp.status_code == 200, resp.text  # "hepsini temizle" yeni istemcide de boştur
    assert resp.json()["lines"] == []


# --- işçi kırılımı ----------------------------------------------------------------------


def _eski_isci(count: int = 3) -> dict:
    """B2 öncesi işçi satırı: `subcontractor_id` ve `hours` ANAHTARLARI yok."""
    return {"trade": "Kalıpçı", "source": "company", "count": count}


async def test_B2xA_old_worker_signature_with_firm_rows_is_409_and_keeps_data(
    client: AsyncClient,
    admin_headers,
    santiye,
    firmalar,  # noqa: F811
) -> None:
    site, _, _ = santiye
    entry_id = await _kayit(client, admin_headers, site.id)
    kaya, _ = firmalar
    assert (await _isciler(client, admin_headers, entry_id, [_firma(kaya, 5)])).status_code == 200
    resp = await _isciler(client, admin_headers, entry_id, [_eski_isci()])
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == guards.STALE_CLIENT
    (row,) = (await _detail(client, admin_headers, entry_id))["worker_counts"]
    assert (row["subcontractor_id"], row["count"]) == (str(kaya.id), 5)


async def test_B2xA_new_worker_signature_passes(
    client: AsyncClient,
    admin_headers,
    santiye,
    firmalar,  # noqa: F811
) -> None:
    site, _, _ = santiye
    entry_id = await _kayit(client, admin_headers, site.id)
    kaya, _ = firmalar
    assert (await _isciler(client, admin_headers, entry_id, [_firma(kaya, 5)])).status_code == 200
    body = [_firma(kaya, 6), {**_eski_isci(), "subcontractor_id": None, "hours": None}]
    resp = await _isciler(client, admin_headers, entry_id, body)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["worker_counts"]) == 2


async def test_B2xA_old_worker_signature_without_new_rows_still_passes(
    client: AsyncClient, admin_headers, santiye
) -> None:
    site, _, _ = santiye
    entry_id = await _kayit(client, admin_headers, site.id)
    assert (await _isciler(client, admin_headers, entry_id, [_eski_isci(3)])).status_code == 200
    again = await _isciler(client, admin_headers, entry_id, [_eski_isci(4)])
    assert again.status_code == 200, again.text
