"""Task C6 — işveren sözleşmesi okuma + grup/kalem yazma uçları (spec §6.2).

Kapsam: `GET /projects/{id}/contract`, `GET /projects/{id}/contract/items`,
`POST /projects/{id}/contract/groups`, `PATCH /contracts/employer/groups/{id}`,
`POST /projects/{id}/contract/items`, `PATCH /contracts/employer/items/{id}`.

Sözleşmenin KENDİ alanları (contract_no, amount, advance_pct...) için yazma ucu
YOKTUR — bu dilim onları AÇMAZ (spec §6.2), `PATCH /projects/{id}` nested
`contract`'ında kalır.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import PriceIndexType, ProjectContract
from app.modules.sites.models import Site


async def _contract(session, project_id, **kwargs) -> ProjectContract:
    defaults = {
        "contract_no": "SZL-2026-010",
        "amount": Decimal("11200000"),
        "advance_pct": Decimal("20"),
    }
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
        "code": "03.001",
        "description": "Beton",
        "unit": "m³",
        "quantity": Decimal("100"),
        "unit_price": Decimal("1850"),
    }
    defaults.update(kwargs)
    item = EmployerContractItem(project_id=project_id, group_id=group_id, **defaults)
    session.add(item)
    await session.flush()
    return item


async def _site(session, project_id, code="SNT-001", name="Ana Şantiye") -> Site:
    site = Site(project_id=project_id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


@pytest.fixture
async def sozlesmeli_proje(seeded_db, project_factory) -> uuid.UUID:
    project = await project_factory(code="CL-EMP-01", name="Sözleşmeli Proje")
    await _contract(seeded_db, project.id)
    return project.id


@pytest.fixture
async def grup(seeded_db, sozlesmeli_proje) -> uuid.UUID:
    group = await _group(seeded_db, sozlesmeli_proje)
    return group.id


@pytest.fixture
async def dagitimli_proje(seeded_db, project_factory) -> uuid.UUID:
    """200 Ton'luk kalem, 200 Ton'u tek şantiyeye tam dağıtılmış (spec §3.3)."""
    project = await project_factory(code="CL-EMP-02", name="Dağıtımlı Proje")
    await _contract(seeded_db, project.id, contract_no="SZL-2026-011")
    return project.id


@pytest.fixture
async def sozlesme_kalemi(seeded_db, dagitimli_proje) -> uuid.UUID:
    group = await _group(seeded_db, dagitimli_proje, name="A — Demir İşleri")
    item = await _item(
        seeded_db,
        dagitimli_proje,
        group.id,
        code="04.001",
        description="Demir donatı",
        unit="Ton",
        quantity=Decimal("200"),
        unit_price=Decimal("30000"),
    )
    site = await _site(seeded_db, dagitimli_proje)
    boq_group = BoqGroup(site_id=site.id, name="A — Demir İşleri")
    seeded_db.add(boq_group)
    await seeded_db.flush()
    seeded_db.add(
        BoqItem(
            site_id=site.id,
            group_id=boq_group.id,
            code="04.001",
            description="Demir donatı",
            unit="Ton",
            quantity=Decimal("200"),
            unit_price=Decimal("30000"),
            contract_item_id=item.id,
        )
    )
    await seeded_db.flush()
    return item.id


@pytest.mark.asyncio
async def test_avans_tutari_ve_kalem_toplami(client, admin_headers, sozlesmeli_proje, seeded_db):
    group = await _group(seeded_db, sozlesmeli_proje)
    await _item(seeded_db, sozlesmeli_proje, group.id)

    yanit = await client.get(f"/projects/{sozlesmeli_proje}/contract", headers=admin_headers)

    assert yanit.status_code == 200
    govde = yanit.json()
    # amount=11_200_000, advance_pct=20 (E14 85)
    assert Decimal(govde["advance_amount"]) == Decimal("2240000")
    assert "items_total" in govde and "items_total_diff" in govde
    assert Decimal(govde["items_total"]) == Decimal("185000.00")
    assert Decimal(govde["items_total_diff"]) == Decimal("11200000") - Decimal("185000.00")


@pytest.mark.asyncio
async def test_endeks_alanlari_yanitta_doner(client, admin_headers, project_factory, seeded_db):
    """T5 (spec §6 ek task): okuma ucu `index_type` + `has_price_escalation` döner.

    Taşeron hakedişi ekranı fiyat farkı katsayısını gösterirken sözleşmenin
    endeks tipini ister; alan additive eklendi, yazma yolu değişmedi.
    """
    project = await project_factory(code="CL-EMP-IDX", name="Endeksli Proje")
    await _contract(
        seeded_db,
        project.id,
        has_price_escalation=True,
        index_type=PriceIndexType.tufe,
        base_index_value=Decimal("2450.123"),
    )

    yanit = await client.get(f"/projects/{project.id}/contract", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["has_price_escalation"] is True
    assert govde["index_type"] == "tufe"


@pytest.mark.asyncio
async def test_fiyat_farksiz_sozlesmede_endeks_null(
    client, admin_headers, project_factory, seeded_db
):
    """`has_price_escalation=false` sözleşmede `index_type` NULL döner."""
    project = await project_factory(code="CL-EMP-IDX0", name="Endekssiz Proje")
    await _contract(seeded_db, project.id, has_price_escalation=False)

    yanit = await client.get(f"/projects/{project.id}/contract", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["has_price_escalation"] is False
    assert govde["index_type"] is None


@pytest.mark.asyncio
async def test_sozlesmesiz_proje_404(client, admin_headers, project_factory, seeded_db):
    proje = await project_factory(code="CL-EMP-99", name="Sözleşmesiz Proje")

    yanit = await client.get(f"/projects/{proje.id}/contract", headers=admin_headers)

    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_ayni_poz_kodu_409(client, admin_headers, sozlesmeli_proje, grup):
    govde = {
        "group_id": str(grup),
        "code": "03.001",
        "description": "Beton",
        "unit": "m³",
        "quantity": 100,
        "unit_price": 1850,
    }
    ilk = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/items", json=govde, headers=admin_headers
    )
    assert ilk.status_code == 201, ilk.text
    ikinci = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/items", json=govde, headers=admin_headers
    )
    assert ikinci.status_code == 409


@pytest.mark.asyncio
async def test_gorunmeyen_proje_ile_olmayan_proje_ayni_yanit(
    client, kisitli_headers, gorunmeyen_proje
):
    gercek = await client.get(f"/projects/{gorunmeyen_proje.id}/contract", headers=kisitli_headers)
    sahte = await client.get(f"/projects/{uuid.uuid4()}/contract", headers=kisitli_headers)
    assert gercek.status_code == sahte.status_code == 404
    assert gercek.json() == sahte.json()


@pytest.mark.asyncio
async def test_miktar_dagitilmis_toplamin_altina_inemez(
    client, admin_headers, dagitimli_proje, sozlesme_kalemi
):
    """200 Ton'un 200'ü dağıtılmışken miktar 150'ye indirilemez."""
    yanit = await client.patch(
        f"/contracts/employer/items/{sozlesme_kalemi}",
        json={"quantity": 150},
        headers=admin_headers,
    )
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_miktar_dagitilmis_toplamin_ustune_cikarilabilir(
    client, admin_headers, dagitimli_proje, sozlesme_kalemi
):
    yanit = await client.patch(
        f"/contracts/employer/items/{sozlesme_kalemi}",
        json={"quantity": 250},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert Decimal(yanit.json()["quantity"]) == Decimal("250.000")


@pytest.mark.asyncio
async def test_kalem_listesi_dagitilmis_ve_kalan_miktari_dondurur(
    client, admin_headers, dagitimli_proje, sozlesme_kalemi
):
    yanit = await client.get(f"/projects/{dagitimli_proje}/contract/items", headers=admin_headers)

    assert yanit.status_code == 200
    govde = yanit.json()
    assert len(govde["groups"]) == 1
    item = govde["groups"][0]["items"][0]
    assert item["id"] == str(sozlesme_kalemi)
    assert Decimal(item["distributed_quantity"]) == Decimal("200")
    assert Decimal(item["remaining_quantity"]) == Decimal("0")


@pytest.mark.asyncio
async def test_grup_olusturma_ve_guncelleme(client, admin_headers, sozlesmeli_proje):
    olustur = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/groups",
        json={"name": "B — Kalıp İşleri", "sort_order": 1},
        headers=admin_headers,
    )
    assert olustur.status_code == 201, olustur.text
    group_id = olustur.json()["id"]

    guncelle = await client.patch(
        f"/contracts/employer/groups/{group_id}",
        json={"name": "B — Kalıp İşleri (güncel)"},
        headers=admin_headers,
    )
    assert guncelle.status_code == 200, guncelle.text
    assert guncelle.json()["name"] == "B — Kalıp İşleri (güncel)"


@pytest.mark.asyncio
async def test_sozlesmesiz_projede_grup_olusturulamaz(client, admin_headers, project_factory):
    proje = await project_factory(code="CL-EMP-98", name="Sözleşmesiz Proje 2")

    yanit = await client.post(
        f"/projects/{proje.id}/contract/groups",
        json={"name": "A — Grup"},
        headers=admin_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_yetkisiz_rol_403(client, site_chief_headers, sozlesmeli_proje):
    yanit = await client.get(f"/projects/{sozlesmeli_proje}/contract", headers=site_chief_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_gorunmeyen_projeye_grup_id_ile_dolayli_erisim_404(
    client, kisitli_headers, gorunmeyen_proje, seeded_db
):
    """`grup` görünmeyen bir projeye ait olsa da (dolaylı kimlikle) 404 döner."""
    await _contract(seeded_db, gorunmeyen_proje.id, contract_no="SZL-HIDDEN")
    group = await _group(seeded_db, gorunmeyen_proje.id)

    yanit = await client.patch(
        f"/contracts/employer/groups/{group.id}",
        json={"name": "Değişti"},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_gorunmeyen_projeye_kalem_id_ile_dolayli_erisim_404(
    client, kisitli_headers, gorunmeyen_proje, seeded_db
):
    """C6'dan devredildi (dal geneli son inceleme): grup PATCH'inin dolaylı-

    kimlik IDOR testi vardı, kalem PATCH'inin yoktu — kod yolu
    (`service._visible_item`) zaten doğru, burada yalnız regresyon güvencesi
    ekleniyor.
    """
    await _contract(seeded_db, gorunmeyen_proje.id, contract_no="SZL-HIDDEN-ITEM")
    group = await _group(seeded_db, gorunmeyen_proje.id)
    item = await _item(seeded_db, gorunmeyen_proje.id, group.id)

    yanit = await client.patch(
        f"/contracts/employer/items/{item.id}",
        json={"description": "Değişti"},
        headers=kisitli_headers,
    )
    assert yanit.status_code == 404


@pytest.mark.asyncio
async def test_grup_baska_projeye_ait_kalem_eklenemez(
    client, admin_headers, sozlesmeli_proje, project_factory, seeded_db
):
    diger_proje = await project_factory(code="CL-EMP-97", name="Diğer Proje")
    await _contract(seeded_db, diger_proje.id, contract_no="SZL-OTHER")
    diger_grup = await _group(seeded_db, diger_proje.id)

    yanit = await client.post(
        f"/projects/{sozlesmeli_proje}/contract/items",
        json={
            "group_id": str(diger_grup.id),
            "code": "05.001",
            "description": "Yanlış grup",
            "unit": "m³",
            "quantity": 10,
            "unit_price": 100,
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 422
