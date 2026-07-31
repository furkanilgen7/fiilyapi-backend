"""Task H4 — spec §9.0 negatif seti: görünmeyen kayıt VE olmayan kimlik ayırt

edilemez 404 döner; modül izni yetersizse 403 (kapı, görünürlükten ÖNCE)."""

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_gorunmeyen_hakedis_ile_olmayan_id_ayni_yanit(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    gercek = await client.get(f"/progress-payments/{gorunmeyen_hakedis}", headers=kisitli_headers)
    sahte = await client.get(f"/progress-payments/{uuid.uuid4()}", headers=kisitli_headers)
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


async def test_sef_atanmadigi_projede_olusturamaz_404(
    client: AsyncClient, site_chief_headers: dict[str, str], gorunmeyen_proje: uuid.UUID
) -> None:
    """Şef `scope=project`: atanmamış proje 403 DEĞİL 404 (varlık sızdırmaz)."""
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje}/progress-payments", json={}, headers=site_chief_headers
    )
    assert yanit.status_code == 404


async def test_gorunmeyen_hakedis_patch_404(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    yanit = await client.patch(
        f"/progress-payments/{gorunmeyen_hakedis}",
        json={"description": "x"},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


async def test_olmayan_hakedis_get_404(
    client: AsyncClient, kisitli_headers: dict[str, str]
) -> None:
    yanit = await client.get(f"/progress-payments/{uuid.uuid4()}", headers=kisitli_headers)
    assert yanit.status_code == 404


async def test_yetkisiz_rol_403(
    client: AsyncClient, hr_headers: dict[str, str], gorunmeyen_hakedis: uuid.UUID
) -> None:
    """İK matris satırı `_N`: modül izni yetersiz -> 403 (kapı, görünürlükten ÖNCE)."""
    yanit = await client.get(f"/progress-payments/{gorunmeyen_hakedis}", headers=hr_headers)
    assert yanit.status_code == 403


async def test_yetkisiz_rol_olusturma_403(
    client: AsyncClient, hr_headers: dict[str, str], gorunmeyen_proje: uuid.UUID
) -> None:
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje}/progress-payments", json={}, headers=hr_headers
    )
    assert yanit.status_code == 403


async def test_kisitli_kullanici_listede_gorunmeyen_projeyi_goremez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    kisitli_headers: dict[str, str],
    gorunmeyen_hakedis: uuid.UUID,
) -> None:
    """Liste ucu da görünürlük süzgecinden geçer (spec §9.0) — başka projenin

    hakedişi `kisitli_headers` kullanıcısının listesinde HİÇ görünmez.
    """
    yanit = await client.get("/progress-payments", headers=kisitli_headers)
    assert yanit.status_code == 200
    ids = [item["id"] for item in yanit.json()["items"]]
    assert str(gorunmeyen_hakedis) not in ids
