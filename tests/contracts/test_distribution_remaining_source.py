"""TB4 · B2 — dağıtım "kalan" hesabı TEK KAYNAK (spec §1 B2, plan T2).

P5 devri: aşım kontrolü (`_assert_within_contract_quantity`) ile "kalan"
göstergeleri (dağıtım ekranı + sözleşme kalemi listesi) `remaining` değerini
FARKLI kümeden topluyordu:

* aşım kontrolü — **projenin şantiyelerindeki** BOQ satırları,
  `(contract_item_id, site_id)` çiftinde tekilleştirilmiş,
* göstergeler — kaleme bağlı **TÜM** BOQ satırları, şantiyenin hangi projeye
  ait olduğuna BAKMADAN.

Ayrışmayı üreten veri: sözleşme kalemine bağlı bir BOQ satırı BAŞKA projenin
şantiyesinde duruyorsa (şantiye devri sonrası mümkün) gösterge onu "dağıtılmış"
sayar, aşım kontrolü saymaz. Burada iki yüzeyin AYNI kalanı söylemesi
zorlanır — **otorite aşım kontrolünün kümesidir**.
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site

GRUP_ADI = "A — Demir İşleri"
KALEM_MIKTARI = Decimal("200")
PROJE_ICI_KOTA = Decimal("120")
PROJE_DISI_KOTA = Decimal("80")


async def _boq_satiri(session, site_id, contract_item_id, quantity) -> BoqItem:
    group = BoqGroup(site_id=site_id, name=GRUP_ADI)
    session.add(group)
    await session.flush()
    row = BoqItem(
        site_id=site_id,
        group_id=group.id,
        contract_item_id=contract_item_id,
        code="04.001",
        description="Demir donatı",
        unit="Ton",
        quantity=quantity,
        unit_price=Decimal("21500"),
    )
    session.add(row)
    await session.flush()
    return row


@pytest.fixture
async def capraz_kurulum(seeded_db, project_factory) -> dict[str, uuid.UUID]:
    """Kalemin 120'si projenin A şantiyesinde, 80'i BAŞKA projenin şantiyesinde."""
    project = await project_factory(code="CL-B2-01", name="Kalan Tek Kaynak Projesi")
    seeded_db.add(
        ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-B2",
            amount=Decimal("50000000"),
            advance_pct=Decimal("20"),
        )
    )
    site_a = Site(project_id=project.id, code="SNT-B2A", name="Şantiye A")
    site_b = Site(project_id=project.id, code="SNT-B2B", name="Şantiye B")
    seeded_db.add_all([site_a, site_b])

    yabanci_proje = await project_factory(code="CL-B2-99", name="Devredilmiş Proje")
    yabanci_santiye = Site(project_id=yabanci_proje.id, code="SNT-B2X", name="Yabancı Şantiye")
    seeded_db.add(yabanci_santiye)

    group = EmployerContractGroup(project_id=project.id, name=GRUP_ADI, sort_order=0)
    seeded_db.add(group)
    await seeded_db.flush()

    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="04.001",
        description="Demir donatı",
        unit="Ton",
        quantity=KALEM_MIKTARI,
        unit_price=Decimal("21500"),
        sort_order=0,
    )
    seeded_db.add(item)
    await seeded_db.flush()

    await _boq_satiri(seeded_db, site_a.id, item.id, PROJE_ICI_KOTA)
    await _boq_satiri(seeded_db, yabanci_santiye.id, item.id, PROJE_DISI_KOTA)

    return {
        "project_id": project.id,
        "site_b_id": site_b.id,
        "item_id": item.id,
    }


async def _dagitim_kalani(client, headers, project_id) -> Decimal:
    yanit = await client.get(f"/projects/{project_id}/contract/distribution", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return Decimal(yanit.json()["groups"][0]["items"][0]["remaining_quantity"])


async def _kota_dene(client, headers, project_id, item_id, site_id, quantity):
    return await client.put(
        f"/projects/{project_id}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(item_id),
                    "site_id": str(site_id),
                    "quantity": str(quantity),
                }
            ]
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_gosterge_kalani_asim_kontrolunun_kabul_ettigi_kadardir(
    client, admin_headers, capraz_kurulum
):
    """Gösterge "kalan: R" diyorsa aşım kontrolü R'yi kabul, R+1'i RED etmelidir."""
    proje = capraz_kurulum["project_id"]
    kalan = await _dagitim_kalani(client, admin_headers, proje)

    asan = await _kota_dene(
        client,
        admin_headers,
        proje,
        capraz_kurulum["item_id"],
        capraz_kurulum["site_b_id"],
        kalan + 1,
    )
    assert asan.status_code == 422, asan.text

    tam = await _kota_dene(
        client, admin_headers, proje, capraz_kurulum["item_id"], capraz_kurulum["site_b_id"], kalan
    )
    assert tam.status_code == 200, tam.text


@pytest.mark.asyncio
async def test_asim_kontrolu_otorite_kumeyi_mutlak_degerle_sayar(
    client, admin_headers, capraz_kurulum
):
    """Kapının saydığı "dağıtılmış" = 120 (yalnız projenin şantiyesi) — 81 aşar, 80 sığar."""
    proje = capraz_kurulum["project_id"]
    kalan = KALEM_MIKTARI - PROJE_ICI_KOTA  # 80

    asan = await _kota_dene(
        client,
        admin_headers,
        proje,
        capraz_kurulum["item_id"],
        capraz_kurulum["site_b_id"],
        kalan + 1,
    )
    assert asan.status_code == 422, asan.text

    tam = await _kota_dene(
        client, admin_headers, proje, capraz_kurulum["item_id"], capraz_kurulum["site_b_id"], kalan
    )
    assert tam.status_code == 200, tam.text


@pytest.mark.asyncio
async def test_kalem_listesi_ile_dagitim_ekrani_ayni_kalani_soyler(
    client, admin_headers, capraz_kurulum
):
    proje = capraz_kurulum["project_id"]
    kalemler = await client.get(f"/projects/{proje}/contract/items", headers=admin_headers)
    assert kalemler.status_code == 200, kalemler.text
    liste_kalani = Decimal(kalemler.json()["groups"][0]["items"][0]["remaining_quantity"])

    assert liste_kalani == await _dagitim_kalani(client, admin_headers, proje)


@pytest.mark.asyncio
async def test_kalem_miktari_kapisi_da_ayni_kumeyi_kullanir(client, admin_headers, capraz_kurulum):
    """`ITEM_QUANTITY_BELOW_DISTRIBUTED` kapısı da aynı "dağıtılmış" tanımını kullanır."""
    proje = capraz_kurulum["project_id"]
    dagitilmis = KALEM_MIKTARI - await _dagitim_kalani(client, admin_headers, proje)

    tam = await client.patch(
        f"/contracts/employer/items/{capraz_kurulum['item_id']}",
        json={"quantity": str(dagitilmis)},
        headers=admin_headers,
    )
    assert tam.status_code == 200, tam.text

    altina = await client.patch(
        f"/contracts/employer/items/{capraz_kurulum['item_id']}",
        json={"quantity": str(dagitilmis - 1)},
        headers=admin_headers,
    )
    assert altina.status_code == 422, altina.text
