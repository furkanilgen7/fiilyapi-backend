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
    EmployerContractGroup,
    EmployerContractItem,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site
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


async def _onayli_hakedis(
    session, project: Project, *, code: str, unit_price: Decimal, quantity: Decimal
) -> None:
    """O1 (H9 denetimi): `project`'e TEK onaylı hakediş + tek satır kurar —

    `progress_payments/conftest.py::_ozet_ortami`'nin küçültülmüş hâli. Amaç
    yazma korkuluklarını (dağıtım/kota) sınamak DEĞİL, `contracts` liste
    KPI'sinin (`summary.progress_payment_total`) kümülatif brütü SADECE
    görünür projelerden topladığını kanıtlamaktır.
    """
    created_by = (
        await session.execute(select(User).where(User.email == "kisitli@contracts-list.co"))
    ).scalar_one()
    group = EmployerContractGroup(project_id=project.id, name=f"Grup {code}", sort_order=1)
    session.add(group)
    await session.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code=code,
        description="KPI test pozu",
        unit="m³",
        quantity=Decimal("100000"),
        unit_price=unit_price,
        sort_order=1,
    )
    site = Site(project_id=project.id, code=f"SNT-{code}", name=f"Şantiye {code}")
    session.add_all([item, site])
    await session.flush()
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.approved,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        created_by=created_by.id,
    )
    payment.lines = [
        ProgressPaymentLine(
            contract_item_id=item.id,
            site_id=site.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=quantity,
            group_name=group.name,
        )
    ]
    session.add(payment)
    await session.flush()


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
    # P7/H9 (spec §9.6): `progress_payment_total` artık `MetricPlaceholder`
    # sarmalayıcısı DEĞİL düz `Decimal`'dır — C3'te sabitlenen sözleşme bilinçli
    # olarak DEĞİŞTİ (frontend'e kırıcı değişiklik olarak bildirilir, §10/4).
    # Hakedişi olmayan sözleşmede toplam 0'dır (bilinmiyor değil, gerçekten sıfır).
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("0.00")
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
    # Taşeron hakedişi AYRI dilimdir (spec §1.2): P7/H9 sonrası alan düz
    # `Decimal | None` olduğu için burada `None` döner — sahte 0 gösterilmez.
    assert items[0]["progress_pct"] is None


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

    # O1 (H9 denetimi): görünmeyen projede de onaylı bir hakediş olsun — kaçan
    # mutasyon `summary.progress_payment_total`'ı TÜM projeler üzerinden
    # (`cumulative.values()`) toplarsa bu satır sızar ve aşağıdaki iddia
    # kırmızıya döner; `items` iddiası TEK BAŞINA bunu YAKALAMAZ (374 test
    # yeşil kalırken kapsamsız KPI fark edilmeden kalırdı).
    await _onayli_hakedis(
        seeded_db,
        gorunmeyen_proje,
        code="HID-01",
        unit_price=Decimal("100"),
        quantity=Decimal("50"),
    )
    await _onayli_hakedis(
        seeded_db, ornek_proje, code="VIS-01", unit_price=Decimal("10"), quantity=Decimal("20")
    )

    yanit = await client.get("/contracts?type=employer", headers=kisitli_headers)

    assert yanit.status_code == 200
    govde = yanit.json()
    assert all(k["id"] != str(gorunmeyen_proje.id) for k in govde["items"])
    assert any(k["id"] == str(ornek_proje.id) for k in govde["items"])
    # Görünmeyen projenin brütü (5.000,00) KPI şeridine SIZMAMALI: yalnız
    # görünür `ornek_proje`'nin brütü (200,00) toplama girer.
    assert Decimal(govde["summary"]["progress_payment_total"]) == Decimal("200.00")


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
