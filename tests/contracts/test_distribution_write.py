"""Task C8 — Poz dağılımı toplu YAZMA ucu (spec §6.3 PUT kısmı, `POZ` 24/72).

Kapsam: yalnız `PUT /projects/{id}/contract/distribution`. Okuma C7'de test
edilir, burada yalnız yazmanın sonucunu DOĞRULAMAK için çağrılır.

Senaryo: bir proje, iki şantiye (A, B), bir sözleşme poz grubu
("A — Betonarme İşleri"), 200 Ton / ₺21.500 birim fiyatlı bir kalem.

Spec §6.3'ün dört davranışının hepsi test edilir:
1. kaldırma (`quantity: null`) — satır SİLİNMEZ, bağ kopar
2. yeni çift — BOQ satırı + gerekirse grup oluşur
3. mevcut çift — yalnız `quantity` güncellenir
4. aşım 422 + ATOMİKLİK / şantiye-proje eşleşmesi 422
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site

GRUP_ADI = "A — Betonarme İşleri"


async def _contract(session, project_id, contract_no="SZL-2026-088") -> ProjectContract:
    contract = ProjectContract(
        project_id=project_id,
        contract_no=contract_no,
        amount=Decimal("50000000"),
        advance_pct=Decimal("20"),
    )
    session.add(contract)
    await session.flush()
    return contract


async def _site(session, project_id, code, name) -> Site:
    site = Site(project_id=project_id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


async def _employer_item(session, project_id, group_id, **kwargs) -> EmployerContractItem:
    defaults = {
        "code": "04.001",
        "description": "Demir donatı",
        "unit": "Ton",
        "quantity": Decimal("200"),
        "unit_price": Decimal("21500"),
        "sort_order": 0,
    }
    defaults.update(kwargs)
    item = EmployerContractItem(project_id=project_id, group_id=group_id, **defaults)
    session.add(item)
    await session.flush()
    return item


@pytest.fixture
async def _kurulum(seeded_db, project_factory):
    project = await project_factory(code="CL-DW-01", name="Dağılım Yazma Projesi")
    await _contract(seeded_db, project.id)

    site_a = await _site(seeded_db, project.id, "SNT-DWA", "Şantiye A")
    site_b = await _site(seeded_db, project.id, "SNT-DWB", "Şantiye B")

    group = EmployerContractGroup(project_id=project.id, name=GRUP_ADI, sort_order=0)
    seeded_db.add(group)
    await seeded_db.flush()

    item = await _employer_item(seeded_db, project.id, group.id)

    return {
        "project_id": project.id,
        "site_a_id": site_a.id,
        "site_b_id": site_b.id,
        "group_id": group.id,
        "item_id": item.id,
    }


@pytest.fixture
async def sozlesmeli_proje(_kurulum) -> uuid.UUID:
    return _kurulum["project_id"]


@pytest.fixture
async def santiye(_kurulum) -> uuid.UUID:
    return _kurulum["site_a_id"]


@pytest.fixture
async def santiye2(_kurulum) -> uuid.UUID:
    return _kurulum["site_b_id"]


@pytest.fixture
async def sozlesme_kalemi(_kurulum) -> uuid.UUID:
    return _kurulum["item_id"]


@pytest.fixture
async def baska_projenin_santiyesi(seeded_db, project_factory) -> uuid.UUID:
    other = await project_factory(code="CL-DW-99", name="Başka Proje")
    site = await _site(seeded_db, other.id, "SNT-DWX", "Yabancı Şantiye")
    return site.id


@pytest.fixture
async def dagitimli_proje(seeded_db, _kurulum) -> uuid.UUID:
    """`_kurulum`'un üstüne A şantiyesinde 120 Ton'luk BAĞLI bir BOQ satırı kurar."""
    boq_group = BoqGroup(site_id=_kurulum["site_a_id"], name=GRUP_ADI)
    seeded_db.add(boq_group)
    await seeded_db.flush()
    seeded_db.add(
        BoqItem(
            site_id=_kurulum["site_a_id"],
            group_id=boq_group.id,
            contract_item_id=_kurulum["item_id"],
            code="04.001",
            description="Demir donatı",
            unit="Ton",
            quantity=Decimal("120"),
            unit_price=Decimal("21500"),
        )
    )
    await seeded_db.flush()
    return _kurulum["project_id"]


@pytest.fixture
async def iki_kalem_ayni_grup(seeded_db, _kurulum) -> tuple[uuid.UUID, uuid.UUID]:
    """Aynı sözleşme grubunda iki kalem — tek BOQ grubuna düşmelidirler."""
    kalem_a = await _employer_item(
        seeded_db,
        _kurulum["project_id"],
        _kurulum["group_id"],
        code="15.001",
        description="Kalıp",
        unit="m²",
        quantity=Decimal("100"),
        unit_price=Decimal("300"),
        sort_order=1,
    )
    kalem_b = await _employer_item(
        seeded_db,
        _kurulum["project_id"],
        _kurulum["group_id"],
        code="15.002",
        description="İskele",
        unit="m²",
        quantity=Decimal("100"),
        unit_price=Decimal("120"),
        sort_order=2,
    )
    return kalem_a.id, kalem_b.id


@pytest.mark.asyncio
async def test_yeni_kota_boq_satiri_ve_grubu_olusturur(
    client, admin_headers, sozlesmeli_proje, santiye, sozlesme_kalemi
):
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(santiye),
                    "quantity": 120,
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text

    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert boq["groups"][0]["name"] == GRUP_ADI  # grup otomatik açıldı
    kalem = boq["groups"][0]["items"][0]
    assert Decimal(kalem["quantity"]) == Decimal("120")
    assert Decimal(kalem["unit_price"]) == Decimal("21500")  # sözleşmeden kopyalandı
    assert kalem["code"] == "04.001"


@pytest.mark.asyncio
async def test_asim_422_ve_hicbir_sey_yazilmaz(
    client, admin_headers, sozlesmeli_proje, santiye, santiye2, sozlesme_kalemi
):
    """200 Ton'luk kaleme 120 + 100 dağıtılamaz; ilk satır da yazılmamalıdır."""
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(santiye),
                    "quantity": 120,
                },
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(santiye2),
                    "quantity": 100,
                },
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text

    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert boq["groups"] == []  # ATOMİKLİK


@pytest.mark.asyncio
async def test_kota_kaldirilinca_boq_satiri_silinmez_bag_kopar(
    client, admin_headers, dagitimli_proje, santiye, sozlesme_kalemi
):
    yanit = await client.put(
        f"/projects/{dagitimli_proje}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(santiye),
                    "quantity": None,
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text

    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(boq["groups"][0]["items"]) == 1  # satır DURUYOR
    assert Decimal(boq["groups"][0]["items"][0]["quantity"]) == Decimal("120")

    # `BoqItemResponse` şeması `contract_item_id` ALANINI TAŞIMAZ (P4 mockup
    # sadakati) — bağın koptuğu dağılım ucundan doğrulanır: kalem artık hiçbir
    # şantiyeye dağıtılmış görünmez.
    dagitim = yanit.json()
    kalem = next(
        k for g in dagitim["groups"] for k in g["items"] if k["id"] == str(sozlesme_kalemi)
    )
    assert kalem["allocations"] == []
    assert Decimal(kalem["remaining_quantity"]) == Decimal("200")


@pytest.mark.asyncio
async def test_baska_projenin_santiyesine_kota_422(
    client, admin_headers, sozlesmeli_proje, baska_projenin_santiyesi, sozlesme_kalemi
):
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(baska_projenin_santiyesi),
                    "quantity": 10,
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_ayni_gruba_iki_kalem_tek_boq_grubu_acar(
    client, admin_headers, sozlesmeli_proje, santiye, iki_kalem_ayni_grup
):
    kalem_a, kalem_b = iki_kalem_ayni_grup
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {"contract_item_id": str(kalem_a), "site_id": str(santiye), "quantity": 10},
                {"contract_item_id": str(kalem_b), "site_id": str(santiye), "quantity": 20},
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text

    boq = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(boq["groups"]) == 1
    assert len(boq["groups"][0]["items"]) == 2


@pytest.mark.asyncio
async def test_mevcut_ciftte_yalniz_miktar_guncellenir(
    client, admin_headers, dagitimli_proje, santiye, sozlesme_kalemi
):
    """Spec §6.3 madde 3: satır YENİDEN OLUŞTURULMAZ, kimliği korunur."""
    once = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    onceki_id = once["groups"][0]["items"][0]["id"]

    yanit = await client.put(
        f"/projects/{dagitimli_proje}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(sozlesme_kalemi),
                    "site_id": str(santiye),
                    "quantity": 150,
                }
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text

    sonra = (await client.get(f"/sites/{santiye}/boq", headers=admin_headers)).json()
    assert len(sonra["groups"]) == 1
    assert len(sonra["groups"][0]["items"]) == 1
    assert sonra["groups"][0]["items"][0]["id"] == onceki_id
    assert Decimal(sonra["groups"][0]["items"][0]["quantity"]) == Decimal("150")


@pytest.mark.asyncio
async def test_ayni_cift_iki_kez_gonderilirse_422(
    client, admin_headers, sozlesmeli_proje, santiye, sozlesme_kalemi
):
    """Kısmi benzersiz indeks (spec §3.3) `IntegrityError`'a DÜŞMEDEN önce yakalanır."""
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 10},
                {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 20},
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_baska_projenin_kalemi_404(
    client, admin_headers, sozlesmeli_proje, santiye, seeded_db, project_factory
):
    """IDOR: gövdedeki kalem bu projeye ait değilse ayırt edilemez 404."""
    other = await project_factory(code="CL-DW-98", name="Yabancı Sözleşme")
    await _contract(
        seeded_db, other.id, "SZL-2026-089"
    )  # poz grubu FK'si `project_contracts`'a bakar
    grup = EmployerContractGroup(project_id=other.id, name="X", sort_order=0)
    seeded_db.add(grup)
    await seeded_db.flush()
    yabanci = await _employer_item(seeded_db, other.id, grup.id, code="99.999")

    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {"contract_item_id": str(yabanci.id), "site_id": str(santiye), "quantity": 10}
            ]
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_yetkisiz_rol_403(client, site_chief_headers, sozlesmeli_proje):
    yanit = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={"allocations": []},
        headers=site_chief_headers,
    )
    assert yanit.status_code == 403
