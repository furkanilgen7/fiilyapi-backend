"""Task C9 — taşeron kartoteksi uçları (spec §6.4).

Kapsam: `GET /subcontractors`, `POST /subcontractors`, `PATCH /subcontractors/{id}`.
`employers_router` deseninin birebiri (`app/modules/projects/router.py`).

DELETE bu task'ta AÇILMAZ — C12'nin işi.
"""

import uuid

import pytest

from app.modules.contracts.models import Subcontractor


@pytest.fixture
async def pasif_taseron(seeded_db) -> uuid.UUID:
    taseron = Subcontractor(name="Pasif Taşeron", is_active=False)
    seeded_db.add(taseron)
    await seeded_db.flush()
    return taseron.id


@pytest.mark.asyncio
async def test_ayni_vkn_409(client, admin_headers):
    govde = {"name": "Akın İnşaat", "tax_number": "1234567890"}
    ilk = await client.post("/subcontractors", json=govde, headers=admin_headers)
    assert ilk.status_code == 201
    ikinci = await client.post(
        "/subcontractors", json={**govde, "name": "Başka"}, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_vkn_siz_iki_kayit_serbest(client, admin_headers):
    for ad in ("A Ltd", "B Ltd"):
        yanit = await client.post("/subcontractors", json={"name": ad}, headers=admin_headers)
        assert yanit.status_code == 201


@pytest.mark.asyncio
async def test_listede_olmayan_kategori_kabul_edilir(client, admin_headers):
    """Spec §3.4: sunucu kategori listesini ZORLAMAZ."""
    yanit = await client.post(
        "/subcontractors", json={"name": "X", "category": "Peyzaj"}, headers=admin_headers
    )
    assert yanit.status_code == 201


@pytest.mark.asyncio
async def test_active_only_suzgeci(client, admin_headers, pasif_taseron):
    govde = (await client.get("/subcontractors?active_only=true", headers=admin_headers)).json()
    assert all(t["id"] != str(pasif_taseron) for t in govde["items"])


@pytest.mark.asyncio
async def test_active_only_false_pasifi_de_dondurur(client, admin_headers, pasif_taseron):
    govde = (await client.get("/subcontractors?active_only=false", headers=admin_headers)).json()
    assert any(t["id"] == str(pasif_taseron) for t in govde["items"])


@pytest.mark.asyncio
async def test_ada_gore_arama(client, admin_headers):
    await client.post("/subcontractors", json={"name": "Zirve Elektrik"}, headers=admin_headers)
    yanit = await client.get("/subcontractors?q=zirve", headers=admin_headers)
    assert yanit.status_code == 200
    isimler = [t["name"] for t in yanit.json()["items"]]
    assert "Zirve Elektrik" in isimler


@pytest.mark.asyncio
async def test_kismi_guncelleme_gonderilmeyen_alan_degismez(client, admin_headers):
    olustur = await client.post(
        "/subcontractors",
        json={"name": "Akın İnşaat", "phone": "0532 000 00 00", "category": "Elektrik"},
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    taseron_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/subcontractors/{taseron_id}",
        json={"phone": "0533 111 11 11"},
        headers=admin_headers,
    )
    assert guncelle.status_code == 200, guncelle.text
    govde = guncelle.json()
    assert govde["phone"] == "0533 111 11 11"
    assert govde["name"] == "Akın İnşaat"
    assert govde["category"] == "Elektrik"


@pytest.mark.asyncio
async def test_var_olmayan_taseron_404(client, admin_headers):
    yanit = await client.patch(
        f"/subcontractors/{uuid.uuid4()}", json={"name": "X"}, headers=admin_headers
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_guncellemede_vkn_cakismasi_409(client, admin_headers):
    ilk = await client.post(
        "/subcontractors", json={"name": "A", "tax_number": "1111111111"}, headers=admin_headers
    )
    assert ilk.status_code == 201
    ikinci = await client.post("/subcontractors", json={"name": "B"}, headers=admin_headers)
    assert ikinci.status_code == 201
    ikinci_id = ikinci.json()["id"]

    yanit = await client.patch(
        f"/subcontractors/{ikinci_id}",
        json={"tax_number": "1111111111"},
        headers=admin_headers,
    )
    assert yanit.status_code == 409


@pytest.mark.asyncio
async def test_yetkisiz_rol_403(client, site_chief_headers):
    yanit = await client.get("/subcontractors", headers=site_chief_headers)
    assert yanit.status_code == 403
