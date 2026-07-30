"""Task C10 — taşeron sözleşmesi POST / GET / PATCH uçları (spec §6.5).

Kapsam: `POST /projects/{id}/subcontractor-contracts` (kalemler iç içe,
atomik), `GET /subcontractor-contracts/{id}`, `PATCH /subcontractor-contracts/{id}`
(taslak→yayın geçişinde tüm kuralların koşması dahil).

DELETE, kalem uçları ve `load-from-employer` bu task'ta DEĞİL (C11/C12).
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.contracts import guards
from app.modules.contracts.models import SubcontractorContract
from app.modules.sites.models import Site


@pytest.fixture
async def proje(seeded_db, project_factory) -> uuid.UUID:
    project = await project_factory(code="TSZ-001", name="Taşeron Test Projesi")
    return project.id


@pytest.fixture
async def baska_proje(seeded_db, project_factory) -> uuid.UUID:
    project = await project_factory(code="TSZ-002", name="Başka Proje")
    return project.id


@pytest.fixture
async def taseron(seeded_db) -> uuid.UUID:
    from app.modules.contracts.models import Subcontractor

    subcontractor = Subcontractor(name="Akın İnşaat Ltd. Şti.", category="Betonarme")
    seeded_db.add(subcontractor)
    await seeded_db.flush()
    return subcontractor.id


@pytest.fixture
async def baska_santiye(seeded_db, baska_proje: uuid.UUID) -> uuid.UUID:
    """`baska_proje`'ye ait şantiye — `proje` altında sözleşme kurulurken

    proje-şantiye uyuşmazlığını (422 `SITE_PROJECT_MISMATCH`) tetiklemek içindir.
    """
    site = Site(project_id=baska_proje, code="SNT-BSK-001", name="Başka Şantiye")
    seeded_db.add(site)
    await seeded_db.flush()
    return site.id


@pytest.fixture
async def eksik_taslak(seeded_db, user_factory, proje: uuid.UUID) -> uuid.UUID:
    """Yalnız `is_draft=True` ile kaydedilmiş, zorunlu alanları BOŞ bir taslak —

    yayına geçiş denemesi `validate_subcontract`in zorunluluk kurallarına takılır.
    """
    owner = await user_factory(
        email="taslak-sahibi@subcontracts.co", password="parola1234", role_key="system_admin"
    )
    contract = SubcontractorContract(project_id=proje, is_draft=True, created_by=owner.id)
    seeded_db.add(contract)
    await seeded_db.flush()
    return contract.id


@pytest.mark.asyncio
async def test_taslak_eksik_alanlarla_kaydedilir(client, admin_headers, proje):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "contract_no": None},
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["is_draft"] is True


@pytest.mark.asyncio
async def test_yayinda_eksik_alan_422(client, admin_headers, proje):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": False, "contract_no": None},
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_santiyesiz_sozlesme_gecerli(client, admin_headers, proje, taseron):
    """K4: site_id boşsa sözleşme proje genelidir."""
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": False,
            "subcontractor_id": str(taseron),
            "work_category": "Betonarme",
            "contract_no": "TSZ-2026-004",
            "signature_date": "2026-01-01",
            "start_date": "2026-01-05",
            "end_date": "2026-12-31",
            "site_id": None,
            "items": [
                {
                    "code": "03.001",
                    "description": "Beton",
                    "unit": "m³",
                    "quantity": 100,
                    "unit_price": 1200,
                }
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert Decimal(yanit.json()["contract_total"]) == Decimal("120000")
    assert yanit.json()["site_id"] is None


@pytest.mark.asyncio
async def test_baska_projenin_santiyesi_422(client, admin_headers, proje, baska_santiye, taseron):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron), "site_id": str(baska_santiye)},
        headers=admin_headers,
    )
    assert yanit.status_code == 422
    assert yanit.json()["detail"] == guards.SITE_PROJECT_MISMATCH


@pytest.mark.asyncio
async def test_taseron_adi_anlik_goruntu_olarak_kopyalanir(client, admin_headers, proje, taseron):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["subcontractor_name"] == "Akın İnşaat Ltd. Şti."


@pytest.mark.asyncio
async def test_taslaktan_yayina_gecis_kurallari_kosar(client, admin_headers, eksik_taslak):
    yanit = await client.patch(
        f"/subcontractor-contracts/{eksik_taslak}",
        json={"is_draft": False},
        headers=admin_headers,
    )
    assert yanit.status_code == 422


# --- Ek doğrulamalar: task brief'in 6 testinin ötesinde, atomiklik + IDOR + PATCH ---


@pytest.mark.asyncio
async def test_kalem_gecersizse_sozlesme_de_yazilmaz(client, admin_headers, proje, taseron):
    """Atomiklik (C8 dersi): bir kalem `quantity <= 0` ile geçersizse HİÇBİR

    satır yazılmaz — sonraki istekte aynı `contract_no` yeniden kullanılabilir.
    """
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "contract_no": "TSZ-ATOMIK-001",
            "items": [
                {
                    "code": "01.001",
                    "description": "Kazı",
                    "unit": "m³",
                    "quantity": 0,
                    "unit_price": 10,
                }
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422

    yeniden = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron), "contract_no": "TSZ-ATOMIK-001"},
        headers=admin_headers,
    )
    assert yeniden.status_code == 201, yeniden.text


@pytest.mark.asyncio
async def test_ayni_sozlesme_no_409(client, admin_headers, proje, taseron):
    govde = {"is_draft": True, "subcontractor_id": str(taseron), "contract_no": "TSZ-DUP-001"}
    ilk = await client.post(
        f"/projects/{proje}/subcontractor-contracts", json=govde, headers=admin_headers
    )
    assert ilk.status_code == 201, ilk.text
    ikinci = await client.post(
        f"/projects/{proje}/subcontractor-contracts", json=govde, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_gorunmeyen_projede_olusturma_404(client, kisitli_headers, gorunmeyen_proje):
    yanit = await client.post(
        f"/projects/{gorunmeyen_proje.id}/subcontractor-contracts",
        json={"is_draft": True},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_var_olmayan_projede_olusturma_ayni_govde(client, admin_headers, gorunmeyen_proje):
    """Görünmeyen projedeki 404 ile var olmayan projedeki 404 AYIRT EDİLEMEZ olmalı."""
    var_olmayan = await client.post(
        f"/projects/{uuid.uuid4()}/subcontractor-contracts",
        json={"is_draft": True},
        headers=admin_headers,
    )
    assert var_olmayan.status_code == 404


@pytest.mark.asyncio
async def test_okuma_ve_toplam_kalemler_ile(client, admin_headers, proje, taseron):
    olustur = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            # Taslak: "girilmiş kalemlerin hepsinde birim fiyat" kuralı YALNIZ
            # yayında koşar (spec §4) — fiyatsız kalem burada kabul edilir.
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "work_category": "Betonarme",
            "contract_no": "TSZ-2026-010",
            "signature_date": "2026-01-01",
            "start_date": "2026-01-05",
            "end_date": "2026-12-31",
            "items": [
                {
                    "code": "03.001",
                    "description": "Beton",
                    "unit": "m³",
                    "quantity": 10,
                    "unit_price": 100,
                },
                {
                    "code": "03.002",
                    "description": "Demir",
                    "unit": "Ton",
                    "quantity": 5,
                    "unit_price": None,
                },
            ],
        },
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    contract_id = olustur.json()["id"]

    okuma = await client.get(f"/subcontractor-contracts/{contract_id}", headers=admin_headers)
    assert okuma.status_code == 200, okuma.text
    govde = okuma.json()
    assert Decimal(govde["contract_total"]) == Decimal("1000")
    assert govde["items_missing_price"] == 1
    assert len(govde["items"]) == 2


@pytest.mark.asyncio
async def test_var_olmayan_sozlesme_okuma_404(client, admin_headers):
    yanit = await client.get(f"/subcontractor-contracts/{uuid.uuid4()}", headers=admin_headers)
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_genel_patch_zorunluluk_kosmaz(client, admin_headers, eksik_taslak):
    """`sites` §0.3/3 dersi: genel PATCH dalında zorunluluk kuralları koşmaz —

    yalnız `work_category` gibi tekil bir alan güncellenebilmelidir.
    """
    yanit = await client.patch(
        f"/subcontractor-contracts/{eksik_taslak}",
        json={"work_category": "Elektrik"},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["work_category"] == "Elektrik"
    assert yanit.json()["is_draft"] is True


@pytest.mark.asyncio
async def test_patch_taseron_adini_yeniden_kopyalar(client, admin_headers, proje, taseron):
    olustur = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True},
        headers=admin_headers,
    )
    contract_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/subcontractor-contracts/{contract_id}",
        json={"subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    assert guncelle.status_code == 200, guncelle.text
    assert guncelle.json()["subcontractor_name"] == "Akın İnşaat Ltd. Şti."


@pytest.mark.asyncio
async def test_patchte_baska_projenin_santiyesi_422(client, admin_headers, proje, baska_santiye):
    olustur = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True},
        headers=admin_headers,
    )
    contract_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/subcontractor-contracts/{contract_id}",
        json={"site_id": str(baska_santiye)},
        headers=admin_headers,
    )
    assert guncelle.status_code == 422
    assert guncelle.json()["detail"] == guards.SITE_PROJECT_MISMATCH


@pytest.mark.asyncio
async def test_patch_ile_yayina_gecis_basarili(client, admin_headers, proje, taseron):
    olustur = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    contract_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/subcontractor-contracts/{contract_id}",
        json={
            "is_draft": False,
            "work_category": "Betonarme",
            "contract_no": "TSZ-2026-020",
            "signature_date": "2026-01-01",
            "start_date": "2026-01-05",
            "end_date": "2026-12-31",
        },
        headers=admin_headers,
    )
    assert guncelle.status_code == 200, guncelle.text
    assert guncelle.json()["is_draft"] is False
