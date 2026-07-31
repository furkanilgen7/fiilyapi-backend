"""Task C13 — denetim günlüğü merkezileştirme (spec §8).

Kapsam: okuma uçlarının denetime yazMAMASI (mevcut kural) + C6-C12'nin ürettiği
yazma uçlarının hâlâ tam olarak bir satır yazması + yeni `subcontract_published`
ailesinin (`sites.site_published` deseninin aynısı) taslak→yayın geçişinde
düz güncellemeden AYRI bir metin üretmesi.

Mesaj METİNLERİ burada `audit/messages.py`den DOĞRUDAN çağrılır — string
gömülmez, taşınan fonksiyonların gerçekten kullanıldığı doğrulanır.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.audit import messages
from app.modules.audit.models import AuditLog
from app.modules.contracts.models import (
    EmployerContractGroup,
    EmployerContractItem,
    Subcontractor,
    SubcontractorContract,
)
from app.modules.projects.models import ProjectContract
from app.modules.sites.models import Site

GRUP_ADI = "A — Betonarme İşleri"


async def _audit_sayisi(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(AuditLog))


async def _mevcut_kimlikler(db_session) -> set[uuid.UUID]:
    rows = await db_session.scalars(select(AuditLog.id))
    return set(rows)


async def _yeni_kaydin_metni(db_session, onceki_kimlikler: set[uuid.UUID]) -> str:
    """Yeni yazılan TEK satırı bulur — `occurred_at` GÜVENİLMEZ: aynı testteki

    tüm INSERT'ler tek transaction içindedir ve Postgres `now()` transaction
    başlangıcını döner, dolayısıyla sıralama için KULLANILAMAZ (giriş + yazma
    kayıtları aynı zaman damgasını paylaşır).
    """
    rows = await db_session.scalars(select(AuditLog))
    yeni = [row for row in rows if row.id not in onceki_kimlikler]
    assert len(yeni) == 1, f"tam bir yeni satır beklenirdi, {len(yeni)} bulundu"
    return yeni[0].detail


@pytest.fixture
async def proje(seeded_db, project_factory) -> uuid.UUID:
    project = await project_factory(code="C13-001", name="Denetim Test Projesi")
    return project.id


@pytest.fixture
async def taseron(seeded_db) -> uuid.UUID:
    subcontractor = Subcontractor(name="Akın İnşaat Ltd. Şti.", category="Betonarme")
    seeded_db.add(subcontractor)
    await seeded_db.flush()
    return subcontractor.id


@pytest.fixture
async def _dagitim_kurulumu(seeded_db, project_factory):
    project = await project_factory(code="C13-002", name="Dağılım Denetim Projesi")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-C13-002",
        amount=Decimal("50000000"),
        advance_pct=Decimal("20"),
    )
    seeded_db.add(contract)

    site = Site(project_id=project.id, code="SNT-C13-002", name="Şantiye C13")
    seeded_db.add(site)
    await seeded_db.flush()

    group = EmployerContractGroup(project_id=project.id, name=GRUP_ADI, sort_order=0)
    seeded_db.add(group)
    await seeded_db.flush()

    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="04.001",
        description="Demir donatı",
        unit="Ton",
        quantity=Decimal("200"),
        unit_price=Decimal("21500"),
        sort_order=0,
    )
    seeded_db.add(item)
    await seeded_db.flush()

    return {"project_id": project.id, "site_id": site.id, "item_id": item.id}


@pytest.fixture
async def sozlesmeli_proje(_dagitim_kurulumu) -> uuid.UUID:
    return _dagitim_kurulumu["project_id"]


@pytest.fixture
async def santiye(_dagitim_kurulumu) -> uuid.UUID:
    return _dagitim_kurulumu["site_id"]


@pytest.fixture
async def sozlesme_kalemi(_dagitim_kurulumu) -> uuid.UUID:
    return _dagitim_kurulumu["item_id"]


@pytest.mark.asyncio
async def test_okuma_denetim_yazmaz(client, admin_headers, db_session, sozlesmeli_proje):
    once = await _audit_sayisi(db_session)
    await client.get(f"/projects/{sozlesmeli_proje}/contract", headers=admin_headers)
    assert await _audit_sayisi(db_session) == once


@pytest.mark.asyncio
async def test_dagilim_kaydi_denetime_yazar(
    client, admin_headers, db_session, sozlesmeli_proje, santiye, sozlesme_kalemi
):
    onceki = await _mevcut_kimlikler(db_session)
    resp = await client.put(
        f"/projects/{sozlesmeli_proje}/contract/distribution",
        json={
            "allocations": [
                {"contract_item_id": str(sozlesme_kalemi), "site_id": str(santiye), "quantity": 10}
            ]
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    detail = await _yeni_kaydin_metni(db_session, onceki)
    assert detail == messages.contract_distribution_saved("Dağılım Denetim Projesi", 1)


@pytest.mark.asyncio
async def test_taseron_sozlesmesi_olusturma_denetime_yazar(
    client, admin_headers, db_session, proje, taseron
):
    once = await _audit_sayisi(db_session)
    resp = await client.post(
        f"/projects/{proje}/subcontractor-contracts",
        json={"is_draft": True, "subcontractor_id": str(taseron)},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    assert await _audit_sayisi(db_session) == once + 1


@pytest.mark.asyncio
async def test_taslaktan_yayina_gecis_ayri_metin_yazar(
    client, admin_headers, db_session, seeded_db, proje, taseron, user_factory
):
    """`sites.site_published` deseninin aynısı: `is_draft: true -> false` geçişi

    düz `subcontract_updated`'tan AYRI bir metin üretir (spec §8, brief K3).
    Yayın için zorunlu tüm alanlar doldurulmuş bir taslak kurulur.
    """
    owner = await user_factory(
        email="c13-yayin-sahibi@contracts.co", password="parola1234", role_key="system_admin"
    )
    contract = SubcontractorContract(
        project_id=proje,
        subcontractor_id=taseron,
        is_draft=True,
        created_by=owner.id,
        work_category="Betonarme",
        contract_no="TSZ-C13-YAYIN",
        signature_date=date(2026, 1, 10),
        start_date=date(2026, 1, 15),
        end_date=date(2026, 6, 15),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    # `items` (lazy="selectin") ham ORM ile YAZILDIĞINDA session'ın kimlik
    # haritasında yüklenmemiş kalır — `client`/`db_session` AYNI oturumu
    # paylaştığı için `session.get` bir sonraki istekte veritabanına gitmez,
    # ilişki greenlet DIŞINDA erişilir ve `MissingGreenlet` patlar. Gerçek
    # istek akışında HER istek taze bir oturum aldığından bu yalnız test
    # kurulumuna özgü bir ayrıntı — burada AÇIKÇA yeniden yüklenir.
    await seeded_db.refresh(contract, attribute_names=["items"])
    contract_id = contract.id

    onceki = await _mevcut_kimlikler(db_session)
    resp = await client.patch(
        f"/subcontractor-contracts/{contract_id}",
        json={"is_draft": False},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    detail = await _yeni_kaydin_metni(db_session, onceki)
    assert detail == messages.subcontract_published("Denetim Test Projesi", "TSZ-C13-YAYIN")
    assert detail != messages.subcontract_updated("Denetim Test Projesi", "TSZ-C13-YAYIN")
