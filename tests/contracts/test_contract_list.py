"""Task C5 — birleşik sözleşme listesi ucu (spec §6.1).

`GET /contracts?type=employer|subcontractor` — iki katmanlı koruma:
`contracts` izni (_VIEW) yetkiyi, `projects.service.visible_projects`
kapsamı belirler. Görünmeyen projenin sözleşmesi listede ÇIKMAMALI.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.timezone import today
from app.modules.contracts.models import (
    ContractStatus,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)
from app.modules.projects.models import ProjectContract
from app.modules.users.models import User


async def _employer_contract(session, project, **kwargs) -> ProjectContract:
    contract = ProjectContract(project_id=project.id, **kwargs)
    session.add(contract)
    await session.flush()
    return contract


async def _subcontractor(session, name: str = "ABC İnşaat Taş.") -> Subcontractor:
    sub = Subcontractor(name=name)
    session.add(sub)
    await session.flush()
    return sub


async def _admin_user_id(session) -> uuid.UUID:
    user = (
        await session.execute(select(User).where(User.email == "admin@contracts-list.co"))
    ).scalar_one()
    return user.id


async def _subcontractor_contract(
    session, project, subcontractor, **kwargs
) -> SubcontractorContract:
    created_by = await _admin_user_id(session)
    contract = SubcontractorContract(
        project_id=project.id,
        subcontractor_id=subcontractor.id,
        subcontractor_name=subcontractor.name,
        created_by=created_by,
        **kwargs,
    )
    session.add(contract)
    await session.flush()
    return contract


@pytest.mark.asyncio
async def test_isveren_listesi_ozet_dondurur(client, admin_headers, ornek_proje, seeded_db):
    await _employer_contract(
        seeded_db,
        ornek_proje,
        contract_no="SZL-2026-001",
        amount=Decimal("1000000.00"),
        status=ContractStatus.active,
    )

    yanit = await client.get("/contracts?type=employer", headers=admin_headers)

    assert yanit.status_code == 200
    govde = yanit.json()
    assert set(govde["summary"]) >= {
        "total_amount",
        "active_count",
        "progress_payment_total",
        "expiring_this_month_count",
    }
    # `progress_payment_total` P7'nin işi (spec §2.2): MetricPlaceholder
    # sarmalayıcısı `available=False`/`value=None` ile döner — literal JSON
    # `null` DEĞİL, C3'te sabitlenmiş sözleşme budur.
    assert govde["summary"]["progress_payment_total"]["available"] is False
    assert govde["summary"]["progress_payment_total"]["value"] is None
    assert govde["summary"]["active_count"] == 1
    assert len(govde["items"]) == 1
    item = govde["items"][0]
    assert item["title"] == ornek_proje.name
    assert item["contract_no"] == "SZL-2026-001"
    assert item["amount"] == "1000000.00"


@pytest.mark.asyncio
async def test_isveren_sozlesmesi_olmayan_proje_listede_yok(
    client, admin_headers, ornek_proje, seeded_db, project_factory
):
    """İşveren "sözleşme kaydı" = project_contracts satırı olan proje (spec §6.1)."""
    await project_factory(code="CL-099", name="Sözleşmesiz Proje")

    yanit = await client.get("/contracts?type=employer", headers=admin_headers)

    assert yanit.status_code == 200
    isimler = {item["title"] for item in yanit.json()["items"]}
    assert "Sözleşmesiz Proje" not in isimler


@pytest.mark.asyncio
async def test_taseron_bedeli_turevdir_ve_fiyatsiz_satir_katkisiz(
    client, admin_headers, ornek_proje, seeded_db
):
    sub = await _subcontractor(seeded_db)
    contract = await _subcontractor_contract(
        seeded_db, ornek_proje, sub, contract_no="TSD-01", status=ContractStatus.active
    )
    seeded_db.add_all(
        [
            SubcontractorContractItem(
                contract_id=contract.id,
                code="01.001",
                description="Kazı",
                unit="m3",
                quantity=Decimal("100"),
                unit_price=Decimal("50.00"),
            ),
            SubcontractorContractItem(
                contract_id=contract.id,
                code="01.002",
                description="Dolgu",
                unit="m3",
                quantity=Decimal("10"),
                unit_price=None,
            ),
        ]
    )
    await seeded_db.flush()

    yanit = await client.get("/contracts?type=subcontractor", headers=admin_headers)

    assert yanit.status_code == 200
    items = yanit.json()["items"]
    assert len(items) == 1
    # Σ(quantity × unit_price) = 100*50 = 5000.00; unit_price IS NULL satır 0 katkı.
    assert items[0]["amount"] == "5000.00"
    assert items[0]["progress_pct"]["available"] is False


@pytest.mark.asyncio
async def test_expiring_this_month_count_bu_ay_biten_aktif_sozlesmeleri_sayar(
    client, admin_headers, ornek_proje, seeded_db
):
    bu_ay_bitis = today().replace(day=28)
    await _employer_contract(
        seeded_db,
        ornek_proje,
        contract_no="SZL-EXP-1",
        amount=Decimal("100.00"),
        status=ContractStatus.active,
    )
    # projects.end_date bu ay olmalı — proje tarihini de güncelliyoruz.
    ornek_proje.end_date = bu_ay_bitis
    await seeded_db.flush()

    yanit = await client.get("/contracts?type=employer", headers=admin_headers)

    assert yanit.status_code == 200
    assert yanit.json()["summary"]["expiring_this_month_count"] == 1


@pytest.mark.asyncio
async def test_tip_zorunlu(client, admin_headers):
    yanit = await client.get("/contracts", headers=admin_headers)
    assert yanit.status_code == 422


@pytest.mark.asyncio
async def test_yetkisiz_rol_403(client, site_chief_headers):
    yanit = await client.get("/contracts?type=employer", headers=site_chief_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_gorunmeyen_proje_listede_yok(
    client, kisitli_headers, gorunmeyen_proje, ornek_proje, seeded_db
):
    await _employer_contract(
        seeded_db,
        gorunmeyen_proje,
        contract_no="SZL-HIDDEN",
        amount=Decimal("1.00"),
        status=ContractStatus.active,
    )
    await _employer_contract(
        seeded_db,
        ornek_proje,
        contract_no="SZL-VISIBLE",
        amount=Decimal("1.00"),
        status=ContractStatus.active,
    )

    yanit = await client.get("/contracts?type=employer", headers=kisitli_headers)

    assert yanit.status_code == 200
    govde = yanit.json()
    assert all(k["id"] != str(gorunmeyen_proje.id) for k in govde["items"])
    assert any(k["id"] == str(ornek_proje.id) for k in govde["items"])


@pytest.mark.asyncio
async def test_q_sozlesme_no_ve_karsi_taraf_adinda_arar(
    client, admin_headers, ornek_proje, seeded_db
):
    await _employer_contract(
        seeded_db,
        ornek_proje,
        contract_no="SZL-ARANAN-999",
        amount=Decimal("1.00"),
        status=ContractStatus.active,
    )

    yanit = await client.get("/contracts?type=employer&q=aranan", headers=admin_headers)

    assert yanit.status_code == 200
    assert len(yanit.json()["items"]) == 1
