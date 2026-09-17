"""K3 invariantının (`SUM(bölüm tahsisi) <= boq_items.quantity`) ÜÇÜNCÜ yazma kapısı.

`boq/models.py:135-138` invariantın "İKİ yazma kapısı vardır ve ikisi de AYNI
kilidi alır" der: `boq.service.replace_allocations` (tahsis toplamı ARTAR) ve
`boq.service.update_item` (poz kotası DÜŞER). Üçüncü kapı `PUT
/projects/{id}/contract/distribution`tır — `contracts/distribution.py`
`row.quantity = alloc.quantity` ile MEVCUT bir BOQ satırının kotasını düşürür.

Burada ölçülen: dağıtım ucunun da aynı eşiği kullanıp kullanmadığı. Sınır
`update_item` ile BİREBİRDİR (`allocated > quantity` → 409; EŞİTLİK geçerlidir).
"""

import uuid
from decimal import Decimal

import pytest

from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Section, Site

GRUP_ADI = "A — Betonarme İşleri"


@pytest.fixture
async def k3_kurulum(seeded_db, project_factory) -> dict[str, uuid.UUID]:
    """1.200 m³'lük sözleşme kalemi + iki bölümlü tek şantiye."""
    project = await project_factory(code="CL-K3-01", name="K3 Dağıtım Projesi")
    seeded_db.add(
        ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-K3",
            amount=Decimal("50000000"),
            advance_pct=Decimal("20"),
        )
    )
    site = Site(project_id=project.id, code="SNT-K3", name="K3 Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()

    kat_a = Section(site_id=site.id, name="Kat 6-10")
    kat_b = Section(site_id=site.id, name="Kat 11-15")
    seeded_db.add_all([kat_a, kat_b])

    group = EmployerContractGroup(project_id=project.id, name=GRUP_ADI, sort_order=0)
    seeded_db.add(group)
    await seeded_db.flush()

    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="03.001",
        description="Beton",
        unit="m³",
        quantity=Decimal("1200"),
        unit_price=Decimal("1850"),
        sort_order=0,
    )
    seeded_db.add(item)
    await seeded_db.flush()

    return {
        "project_id": project.id,
        "site_id": site.id,
        "kat_a_id": kat_a.id,
        "kat_b_id": kat_b.id,
        "item_id": item.id,
    }


async def _dagit(client, headers, kurulum, quantity):
    return await client.put(
        f"/projects/{kurulum['project_id']}/contract/distribution",
        json={
            "allocations": [
                {
                    "contract_item_id": str(kurulum["item_id"]),
                    "site_id": str(kurulum["site_id"]),
                    "quantity": quantity,
                }
            ]
        },
        headers=headers,
    )


async def _boq_satiri(client, headers, site_id) -> dict:
    yanit = await client.get(f"/sites/{site_id}/boq", headers=headers)
    assert yanit.status_code == 200, yanit.text
    return yanit.json()["groups"][0]["items"][0]


@pytest.fixture
async def yediyuzu_tahsisli(client, admin_headers, k3_kurulum) -> dict:
    """1.200 dağıtılmış, 400 + 300 = 700'ü iki bölüme tahsis edilmiş BOQ satırı."""
    yanit = await _dagit(client, admin_headers, k3_kurulum, 1200)
    assert yanit.status_code == 200, yanit.text

    boq_item = await _boq_satiri(client, admin_headers, k3_kurulum["site_id"])
    tahsis = await client.put(
        f"/boq/items/{boq_item['id']}/allocations",
        json={
            "allocations": [
                {"section_id": str(k3_kurulum["kat_a_id"]), "quantity": "400.000"},
                {"section_id": str(k3_kurulum["kat_b_id"]), "quantity": "300.000"},
            ]
        },
        headers=admin_headers,
    )
    assert tahsis.status_code == 200, tahsis.text
    return {**k3_kurulum, "boq_item_id": boq_item["id"]}


@pytest.mark.asyncio
async def test_dagitim_kotayi_tahsis_toplaminin_altina_cekemez(
    client, admin_headers, yediyuzu_tahsisli
):
    """700'ü bölümlere tahsisliyken dağıtım hücresi 500'e çekilemez (409)."""
    yanit = await _dagit(client, admin_headers, yediyuzu_tahsisli, 500)

    assert yanit.status_code == 409, yanit.text

    satir = await _boq_satiri(client, admin_headers, yediyuzu_tahsisli["site_id"])
    assert Decimal(satir["quantity"]) == Decimal("1200.000")
    assert Decimal(satir["unallocated_quantity"]) >= 0


@pytest.mark.asyncio
async def test_dagitim_kotayi_tahsis_toplamina_esit_cekebilir(
    client, admin_headers, yediyuzu_tahsisli
):
    """Sınır `update_item` ile aynı: `allocated > quantity` reddedilir, EŞİTLİK geçer."""
    yanit = await _dagit(client, admin_headers, yediyuzu_tahsisli, 700)

    assert yanit.status_code == 200, yanit.text

    satir = await _boq_satiri(client, admin_headers, yediyuzu_tahsisli["site_id"])
    assert Decimal(satir["quantity"]) == Decimal("700.000")
    assert Decimal(satir["unallocated_quantity"]) == Decimal("0.000")


@pytest.mark.asyncio
async def test_tahsissiz_satirin_kotasi_serbestce_dusurulebilir(client, admin_headers, k3_kurulum):
    """Bölüm tahsisi YOKSA kapı hiçbir şeyi engellememelidir (yanlış-pozitif bekçisi)."""
    assert (await _dagit(client, admin_headers, k3_kurulum, 1200)).status_code == 200

    yanit = await _dagit(client, admin_headers, k3_kurulum, 300)

    assert yanit.status_code == 200, yanit.text
    satir = await _boq_satiri(client, admin_headers, k3_kurulum["site_id"])
    assert Decimal(satir["quantity"]) == Decimal("300.000")
