"""Task C11 — taşeron sözleşmesi kalem uçları + `load-from-employer` (spec §6.5).

Kapsam: `POST /subcontractor-contracts/{id}/items`,
`PATCH /subcontractor-contracts/items/{item_id}`,
`POST /subcontractor-contracts/{id}/items/load-from-employer`.

DELETE bu task'ta DEĞİL (C12).
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.contracts.models import (
    EmployerContractGroup,
    EmployerContractItem,
    Subcontractor,
    SubcontractorContract,
)
from app.modules.projects.models import ProjectContract


@pytest.fixture
async def proje_isveren_pozlu(seeded_db, project_factory) -> uuid.UUID:
    """İşveren sözleşmesi + 2 grup + 3 kalem olan proje (`A` grubunda 2, `B`

    grubunda 1 kalem) — `load-from-employer`in kopyalayacağı kaynak.
    """
    project = await project_factory(code="TKL-001", name="Kalem Test Projesi")
    contract = ProjectContract(
        project_id=project.id, contract_no="SZL-2026-KLM", amount=Decimal("1000000")
    )
    seeded_db.add(contract)
    await seeded_db.flush()

    group_a = EmployerContractGroup(
        project_id=project.id, name="A — Betonarme İşleri", sort_order=0
    )
    group_b = EmployerContractGroup(project_id=project.id, name="B — Kaba İnşaat", sort_order=1)
    seeded_db.add_all([group_a, group_b])
    await seeded_db.flush()

    seeded_db.add_all(
        [
            EmployerContractItem(
                project_id=project.id,
                group_id=group_a.id,
                code="03.001",
                description="Beton",
                unit="m³",
                quantity=Decimal("100"),
                unit_price=Decimal("1850"),
                sort_order=0,
            ),
            EmployerContractItem(
                project_id=project.id,
                group_id=group_a.id,
                code="03.002",
                description="Demir",
                unit="Ton",
                quantity=Decimal("20"),
                unit_price=Decimal("30000"),
                sort_order=1,
            ),
            EmployerContractItem(
                project_id=project.id,
                group_id=group_b.id,
                code="04.001",
                description="Kalıp",
                unit="m²",
                quantity=Decimal("500"),
                unit_price=Decimal("250"),
                sort_order=0,
            ),
        ]
    )
    await seeded_db.flush()
    return project.id


@pytest.fixture
async def proje_pozsuz(seeded_db, project_factory) -> uuid.UUID:
    """İşveren sözleşmesi (dolayısıyla kalemi) OLMAYAN proje."""
    project = await project_factory(code="TKL-002", name="Pozsuz Proje")
    return project.id


@pytest.fixture
async def taseron(seeded_db) -> uuid.UUID:
    subcontractor = Subcontractor(name="Akın İnşaat Ltd. Şti.", category="Betonarme")
    seeded_db.add(subcontractor)
    await seeded_db.flush()
    return subcontractor.id


@pytest.fixture
async def taseron_sozlesmesi(
    seeded_db, user_factory, proje_isveren_pozlu: uuid.UUID, taseron: uuid.UUID
) -> uuid.UUID:
    owner = await user_factory(
        email="taseron-kalem@subcontracts.co", password="parola1234", role_key="system_admin"
    )
    contract = SubcontractorContract(
        project_id=proje_isveren_pozlu,
        subcontractor_id=taseron,
        is_draft=True,
        created_by=owner.id,
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return contract.id


@pytest.fixture
async def pozsuz_sozlesme(
    seeded_db, user_factory, proje_pozsuz: uuid.UUID, taseron: uuid.UUID
) -> uuid.UUID:
    owner = await user_factory(
        email="pozsuz-kalem@subcontracts.co", password="parola1234", role_key="system_admin"
    )
    contract = SubcontractorContract(
        project_id=proje_pozsuz,
        subcontractor_id=taseron,
        is_draft=True,
        created_by=owner.id,
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return contract.id


@pytest.mark.asyncio
async def test_isverenden_yukleme_fiyatsiz_gelir(client, admin_headers, taseron_sozlesmesi):
    yanit = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == {"created_count": 3, "skipped_count": 0}
    detay = (
        await client.get(f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers)
    ).json()
    assert all(k["unit_price"] is None for k in detay["items"])
    assert detay["items_missing_price"] == 3


@pytest.mark.asyncio
async def test_ikinci_yukleme_idempotent(client, admin_headers, taseron_sozlesmesi):
    await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    ikinci = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    assert ikinci.json() == {"created_count": 0, "skipped_count": 3}


@pytest.mark.asyncio
async def test_isveren_sozlesmesi_pozsuzsa_422(client, admin_headers, pozsuz_sozlesme):
    yanit = await client.post(
        f"/subcontractor-contracts/{pozsuz_sozlesme}/items/load-from-employer",
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_grup_isveren_kaleminden_turer(client, admin_headers, taseron_sozlesmesi):
    await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items/load-from-employer",
        headers=admin_headers,
    )
    detay = (
        await client.get(f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers)
    ).json()
    # `group` `SubcontractorContractItemGroup` nesnesidir (C10'da kurulan şema,
    # spec §3.6) — brief'in taslak test kod bloğu düz string varsayıyordu, gerçek
    # arayüz `{id, name}` döner.
    assert detay["items"][0]["group"]["name"] == "A — Betonarme İşleri"


@pytest.mark.asyncio
async def test_bagsiz_kalem_grupsuz(client, admin_headers, taseron_sozlesmesi):
    olustur = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items",
        json={
            "code": "99.001",
            "description": "Ek iş",
            "unit": "m²",
            "quantity": 5,
            "unit_price": 100,
        },
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    assert olustur.json()["group"] is None
    detay = (
        await client.get(f"/subcontractor-contracts/{taseron_sozlesmesi}", headers=admin_headers)
    ).json()
    ek = next(k for k in detay["items"] if k["code"] == "99.001")
    assert ek["group"] is None


# --- Ek doğrulamalar: task brief'in 5 testinin ötesinde ---


@pytest.mark.asyncio
async def test_ayni_kod_409(client, admin_headers, taseron_sozlesmesi):
    govde = {
        "code": "77.001",
        "description": "Sıva",
        "unit": "m²",
        "quantity": 10,
        "unit_price": 50,
    }
    ilk = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items", json=govde, headers=admin_headers
    )
    assert ilk.status_code == 201, ilk.text
    ikinci = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items", json=govde, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_kalem_patch_kismi_guncelleme(client, admin_headers, taseron_sozlesmesi):
    olustur = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items",
        json={
            "code": "88.001",
            "description": "Sıva",
            "unit": "m²",
            "quantity": 10,
            "unit_price": 50,
        },
        headers=admin_headers,
    )
    item_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/subcontractor-contracts/items/{item_id}",
        json={"unit_price": 75},
        headers=admin_headers,
    )
    assert guncelle.status_code == 200, guncelle.text
    assert Decimal(guncelle.json()["unit_price"]) == Decimal("75")
    assert guncelle.json()["description"] == "Sıva"


@pytest.mark.asyncio
async def test_var_olmayan_kalem_patch_404(client, admin_headers):
    yanit = await client.patch(
        f"/subcontractor-contracts/items/{uuid.uuid4()}",
        json={"unit_price": 10},
        headers=admin_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_gorunmeyen_sozlesmeye_kalem_eklenemez_404(
    client, kisitli_headers, taseron_sozlesmesi
):
    yanit = await client.post(
        f"/subcontractor-contracts/{taseron_sozlesmesi}/items",
        json={"code": "01.001", "description": "Kazı", "unit": "m³", "quantity": 1},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_var_olmayan_sozlesmeden_yukleme_404(client, admin_headers):
    yanit = await client.post(
        f"/subcontractor-contracts/{uuid.uuid4()}/items/load-from-employer",
        headers=admin_headers,
    )
    assert yanit.status_code == 404
