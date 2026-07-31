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
from app.modules.contracts.models import (
    EmployerContractGroup,
    EmployerContractItem,
    SubcontractorContract,
)
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site


async def _employer_contract(session, project_id, **kwargs) -> ProjectContract:
    defaults = {"contract_no": "SZL-2026-TSZ", "amount": Decimal("11200000")}
    defaults.update(kwargs)
    contract = ProjectContract(project_id=project_id, **defaults)
    session.add(contract)
    await session.flush()
    return contract


async def _group(session, project_id, **kwargs) -> EmployerContractGroup:
    defaults = {"name": "A — Betonarme İşleri", "sort_order": 0}
    defaults.update(kwargs)
    group = EmployerContractGroup(project_id=project_id, **defaults)
    session.add(group)
    await session.flush()
    return group


async def _item(session, project_id, group_id, **kwargs) -> EmployerContractItem:
    defaults = {
        "code": "04.001",
        "description": "Demir donatı",
        "unit": "Ton",
        "quantity": Decimal("200"),
        "unit_price": Decimal("21500"),
    }
    defaults.update(kwargs)
    item = EmployerContractItem(project_id=project_id, group_id=group_id, **defaults)
    session.add(item)
    await session.flush()
    return item


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


# --- Dal geneli son inceleme: iç içe kalem yazma yolundaki korkuluklar ---


@pytest.fixture
async def baska_projenin_kalemi(seeded_db, project_factory) -> uuid.UUID:
    """Başka bir projenin işveren sözleşmesi kalemi — İÇ İÇE yazılan taşeron

    kalemi buna bağlanamamalı (`test_delete.py.test_source_item_baska_
    projeden_baglanamaz`'ın nested karşılığı, tekil POST kalem ucu korunuyordu
    ama `POST /projects/{id}/subcontractor-contracts` gövdesindeki `items`
    hiç doğrulanmıyordu — IDOR).
    """
    project = await project_factory(code="TSZ-IDOR-01", name="Gizli Proje")
    await _employer_contract(seeded_db, project.id, contract_no="SZL-2026-TSZIDOR")
    group = await _group(seeded_db, project.id, name="Gizli Grup")
    item = await _item(seeded_db, project.id, group.id, code="99.001")
    return item.id


@pytest.mark.asyncio
async def test_ic_ice_source_item_baska_projeden_baglanamaz(
    client, admin_headers, proje, taseron, baska_projenin_kalemi
):
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "items": [
                {
                    "code": "77.001",
                    "description": "Sızıntı denemesi",
                    "unit": "m³",
                    "quantity": 10,
                    "source_contract_item_id": str(baska_projenin_kalemi),
                }
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_ic_ice_source_item_baska_projeden_baglanamazsa_sozlesme_de_yazilmaz(
    client, admin_headers, proje, taseron, baska_projenin_kalemi
):
    """Atomiklik: IDOR reddedilince sözleşmenin KENDİSİ de yazılmamalı —

    aksi hâlde aynı `contract_no` ile tekrar denemek 409'a düşer.
    """
    govde = {
        "is_draft": True,
        "subcontractor_id": str(taseron),
        "contract_no": "TSZ-IDOR-ATOMIK",
        "items": [
            {
                "code": "77.001",
                "description": "Sızıntı denemesi",
                "unit": "m³",
                "quantity": 10,
                "source_contract_item_id": str(baska_projenin_kalemi),
            }
        ],
    }
    ilk = await client.post(
        f"/projects/{proje}/subcontractor-contracts", json=govde, headers=admin_headers
    )
    assert ilk.status_code == 404

    yeniden = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron), "contract_no": "TSZ-IDOR-ATOMIK"},
        headers=admin_headers,
    )
    assert yeniden.status_code == 201, yeniden.text


@pytest.mark.asyncio
async def test_ic_ice_govde_ici_kod_cakismasi_409(client, admin_headers, proje, taseron):
    """Gövde içinde aynı `code` iki kez geçerse DB'ye hiç gitmeden anlaşılır

    409 `DUPLICATE_ITEM_CODE` dönmeli — ham `IntegrityError` DEĞİL.
    """
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "items": [
                {
                    "code": "01.001",
                    "description": "Kazı",
                    "unit": "m³",
                    "quantity": 10,
                    "unit_price": 50,
                },
                {
                    "code": "01.001",
                    "description": "Kazı (tekrar)",
                    "unit": "m³",
                    "quantity": 5,
                    "unit_price": 50,
                },
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 409
    assert yanit.json()["detail"] == guards.DUPLICATE_ITEM_CODE


@pytest.mark.asyncio
async def test_ic_ice_sort_order_bilincli_sifir_ezilmez(client, admin_headers, proje, taseron):
    """İstemci ikinci kalem için bilinçli `sort_order: 0` gönderirse `index`

    ile SESSİZCE ezilmemeli (falsy `or` tuzağı).
    """
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "items": [
                {
                    "code": "01.001",
                    "description": "Kazı",
                    "unit": "m³",
                    "quantity": 10,
                    "unit_price": 50,
                    "sort_order": 5,
                },
                {
                    "code": "01.002",
                    "description": "Dolgu",
                    "unit": "m³",
                    "quantity": 8,
                    "unit_price": 40,
                    "sort_order": 0,
                },
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    items_by_code = {item["code"]: item for item in yanit.json()["items"]}
    assert items_by_code["01.001"]["sort_order"] == 5
    assert items_by_code["01.002"]["sort_order"] == 0


@pytest.mark.asyncio
async def test_contract_total_satir_bazinda_yuvarlanmis_toplamla_esit(
    client, admin_headers, proje, taseron
):
    """Karar (P5 dal geneli son inceleme): `contract_total` = Σ (kuruşa

    yuvarlanmış `line_total`), satırların çarpımlarının HAM toplamı DEĞİL —
    aksi hâlde `Σ line_total != contract_total` olabilir. İki satır, her
    biri tam kuruş sınırında (`1.005`) yuvarlanacak şekilde seçildi: satır
    bazında yuvarlarsa her biri `1.01`'e yuvarlanıp toplam `2.02` olur; ham
    toplam ÖNCE alınıp SONRA yuvarlanırsa `2.01` çıkar (yanlış).
    """
    yanit = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={
            "is_draft": True,
            "subcontractor_id": str(taseron),
            "items": [
                {
                    "code": "01.001",
                    "description": "Kazı",
                    "unit": "m³",
                    "quantity": "1.005",
                    "unit_price": "1.00",
                },
                {
                    "code": "01.002",
                    "description": "Dolgu",
                    "unit": "m³",
                    "quantity": "1.005",
                    "unit_price": "1.00",
                },
            ],
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    line_total_sum = sum(Decimal(item["line_total"]) for item in govde["items"])
    assert line_total_sum == Decimal("2.02")
    assert Decimal(govde["contract_total"]) == line_total_sum
