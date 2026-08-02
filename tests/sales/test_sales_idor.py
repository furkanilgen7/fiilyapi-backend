"""P8 T3 — satış uçlarının IDOR ve yetki kapıları (spec §6, §8 S1).

İKİ AYRI katman test edilir:
1. **İzin** (`sales` matrisi) → yetkisi olmayan **403**.
2. **Kapsam** (`visible_projects`) → yetkisi olan ama projeyi görmeyen **404**,
   ve bu 404 var olmayan projeninkiyle AYIRT EDİLEMEZ olmalıdır.

`units` modülünün IDOR-4..IDOR-9 dersleri birebir geçerlidir: görünmeyen kayıt
403 DEĞİL 404 döner, aksi hâlde elinde UUID olan kullanıcı kaydın var olduğunu
ve başkasına ait olduğunu ayırt edebilirdi.
"""

import uuid

import pytest

from app.modules.sales.guards import PROJECT_MISSING, SALE_MISSING

from .test_sales_api import _govde, _olustur

# --- Kapsam: görünmeyen proje → 404 (var olmayanla aynı gövde) ---


@pytest.mark.asyncio
async def test_gorunmeyen_projede_liste_404(client, kapsam_disi_headers, proje):
    gorunmeyen = await client.get(f"/projects/{proje.id}/sales", headers=kapsam_disi_headers)
    olmayan = await client.get(f"/projects/{uuid.uuid4()}/sales", headers=kapsam_disi_headers)

    assert gorunmeyen.status_code == olmayan.status_code == 404
    assert gorunmeyen.json() == olmayan.json() == {"detail": PROJECT_MISSING}


@pytest.mark.asyncio
async def test_gorunmeyen_projede_satis_acilamaz(
    client, kapsam_disi_headers, proje, unite, musteri
):
    gorunmeyen = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=kapsam_disi_headers
    )
    olmayan = await client.post(
        f"/projects/{uuid.uuid4()}/sales", json=_govde(unite, musteri), headers=kapsam_disi_headers
    )

    assert gorunmeyen.status_code == olmayan.status_code == 404
    assert gorunmeyen.json() == olmayan.json() == {"detail": PROJECT_MISSING}


@pytest.mark.asyncio
async def test_gorunmeyen_projenin_satisi_detayda_404(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri
):
    """Satış → proje → görünürlük (units `visible_unit` deseni)."""
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    gorunmeyen = await client.get(f"/sales/{satis['id']}", headers=kapsam_disi_headers)
    olmayan = await client.get(f"/sales/{uuid.uuid4()}", headers=kapsam_disi_headers)

    assert gorunmeyen.status_code == olmayan.status_code == 404
    assert gorunmeyen.json() == olmayan.json() == {"detail": SALE_MISSING}


@pytest.mark.asyncio
async def test_gorunmeyen_projenin_satisi_patch_edilemez(
    client, admin_headers, kapsam_disi_headers, proje, unite, musteri
):
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    resp = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=kapsam_disi_headers
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == SALE_MISSING


# --- İzin: yetkisiz → 403 ---


@pytest.mark.asyncio
async def test_yetkisiz_rol_her_ucta_403(
    client, admin_headers, yetkisiz_headers, proje, unite, musteri
):
    """`site_chief` — `sales=_N`: kapsamı `all_projects` olsa bile hiçbir uç açık değil."""
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    yanitlar = [
        await client.get(f"/projects/{proje.id}/sales", headers=yetkisiz_headers),
        await client.post(
            f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=yetkisiz_headers
        ),
        await client.get(f"/sales/{satis['id']}", headers=yetkisiz_headers),
        await client.patch(
            f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=yetkisiz_headers
        ),
        await client.delete(f"/sales/{satis['id']}", headers=yetkisiz_headers),
    ]

    assert [r.status_code for r in yanitlar] == [403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_view_rolu_okur_yazamaz(client, admin_headers, view_headers, proje, unite, musteri):
    """`accounting` — `sales=(view, finance)`: tahsilatı izler, satış AÇMAZ."""
    satis = await _olustur(client, admin_headers, proje, unite, musteri)

    liste = await client.get(f"/projects/{proje.id}/sales", headers=view_headers)
    detay = await client.get(f"/sales/{satis['id']}", headers=view_headers)
    yazma = await client.post(
        f"/projects/{proje.id}/sales", json=_govde(unite, musteri), headers=view_headers
    )
    guncelleme = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=view_headers
    )

    assert liste.status_code == 200
    assert detay.status_code == 200
    assert yazma.status_code == 403
    assert guncelleme.status_code == 403


@pytest.mark.asyncio
async def test_full_rolu_yazar_ama_silemez(client, full_headers, proje, unite, musteri):
    """KALICI KARAR (2026-07-30): `full` silmeyi KAPSAMAZ (`app/core/access.py`).

    `project_manager` satış açar/günceller ama rezervasyonu bile silemez.
    """
    satis = await _olustur(client, full_headers, proje, unite, musteri, sale_type="reservation")

    guncelleme = await client.patch(
        f"/sales/{satis['id']}", json={"sale_price": "1.00"}, headers=full_headers
    )
    silme = await client.delete(f"/sales/{satis['id']}", headers=full_headers)

    assert guncelleme.status_code == 200
    assert silme.status_code == 403
