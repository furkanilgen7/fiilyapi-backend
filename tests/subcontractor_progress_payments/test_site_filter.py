"""TB2/T2 — hakediş listesi + `summary` için `site_id` süzgeci (spec §1 U2).

Hakediş tablosunda `site_id` KOLONU YOKTUR: şantiye bağı SÖZLEŞMEDEN gelir
(`subcontractor_contracts.site_id`), süzgeç de o join üzerinden kurulur.

Üç davranış birlikte ölçülür:
1. Süzgeç verilince yalnız O şantiyenin sözleşmesinin hakedişleri gelir.
2. `site_id=NULL` (proje geneli) sözleşmenin hakedişleri süzgeçli sorguda GELMEZ
   (SD S5 tek-anlamlılık kararı).
3. Süzgeç kapsamı GENİŞLETMEZ: görünmeyen projenin şantiye kimliği verilse bile
   `visible_projects` süzgeci kazanır (IDOR).

Geriye uyum, parametresiz çağrının eski kümeyi verdiğini gösteren testle ayrıca
çivilenir (mevcut `test_crud.py`/`test_summary.py` testleri DEĞİŞTİRİLMEDEN yeşil
kalır).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

LISTE_UC = "/subcontractor-progress-payments"
OZET_UC = "/subcontractor-progress-payments/summary"


def _kalemler(contract: SubcontractorContract) -> list[SubcontractorContractItem]:
    return sorted(contract.items, key=lambda item: item.sort_order)


async def _hakedis(
    session: AsyncSession,
    hakedis_fabrikasi,
    contract: SubcontractorContract,
    creator: User,
    *,
    sequence_no: int,
    status: SubcontractorPaymentStatus,
    miktar: Decimal,
    kalem_index: int = 0,
) -> SubcontractorProgressPayment:
    """Tek satırlı hakediş — brüt KPI'ların ölçülebilmesi için satır ŞARTTIR."""
    payment = await hakedis_fabrikasi(
        contract,
        creator,
        sequence_no=sequence_no,
        status=status,
        period_year=2026,
        period_month=7,
    )
    item = _kalemler(contract)[kalem_index]
    session.add(
        SubcontractorProgressPaymentLine(
            payment_id=payment.id,
            contract_item_id=item.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=miktar,
            sort_order=0,
        )
    )
    await session.flush()
    return payment


@pytest.fixture
async def santiye_verisi(
    seeded_db: AsyncSession,
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    admin_kullanicisi: User,
) -> dict:
    """TEK projede iki sözleşme: biri şantiyeli, biri proje geneli (`site_id IS NULL`).

    Kalem birim fiyatları fixture'dan gelir: kalem#1 = 21.500, kalem#2 = 1.850.

    | Sözleşme        | Hakediş                       | Brüt      |
    |-----------------|-------------------------------|-----------|
    | A (şantiyeli)   | `pending_approval` 5×1.850    |   9.250   |
    | A (şantiyeli)   | `paid` 2×21.500               |  43.000   |
    | B (proje geneli)| `approved` 10×21.500          | 215.000   |
    """
    santiyeli, proje, site = await taseron_sozlesmesi_fabrikasi(
        "THK-F01", subcontractor_name="Şantiye Taşeronu"
    )
    proje_geneli, _, _ = await taseron_sozlesmesi_fabrikasi(
        "THK-F02",
        project=proje,
        subcontractor_name="Proje Geneli Taşeron",
        with_site=False,
    )
    assert proje_geneli.site_id is None

    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        santiyeli,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.pending_approval,
        miktar=Decimal("5"),
        kalem_index=1,
    )
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        santiyeli,
        admin_kullanicisi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.paid,
        miktar=Decimal("2"),
    )
    await _hakedis(
        seeded_db,
        hakedis_fabrikasi,
        proje_geneli,
        admin_kullanicisi,
        sequence_no=1,
        status=SubcontractorPaymentStatus.approved,
        miktar=Decimal("10"),
    )
    return {"proje": proje, "site": site, "santiyeli": santiyeli, "proje_geneli": proje_geneli}


# --- 1. Liste ucu ---


async def test_site_id_filtresi_yalniz_o_santiyenin_hakedislerini_getirir(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 2
    assert {item["contract_id"] for item in govde["items"]} == {str(santiye_verisi["santiyeli"].id)}


async def test_site_id_filtresi_proje_geneli_sozlesmenin_hakedisini_getirmez(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """`site_id IS NULL` sözleşmenin hakedişi şantiye süzgeciyle GELMEZ (spec §1 U2)."""
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    contract_ids = {item["contract_id"] for item in yanit.json()["items"]}
    assert str(santiye_verisi["proje_geneli"].id) not in contract_ids


async def test_parametresiz_liste_eski_davranisi_korur(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Geriye uyum: süzgeç verilmezse proje geneli sözleşmenin hakedişi de gelir."""
    yanit = await client.get(LISTE_UC, headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 3
    assert {item["contract_id"] for item in govde["items"]} == {
        str(santiye_verisi["santiyeli"].id),
        str(santiye_verisi["proje_geneli"].id),
    }


# --- 2. Özet (KPI) ucu ---


async def test_ozet_site_id_filtresi_dort_kpiyi_daraltir(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """Dört KPI da SÜZÜLMÜŞ kümeden hesaplanır — proje geneli sözleşme dışarıda."""
    yanit = await client.get(
        OZET_UC,
        params={
            "site_id": str(santiye_verisi["site"].id),
            "period_year": 2026,
            "period_month": 7,
        },
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("52250.00")  # 9.250 + 43.000
    assert Decimal(govde["pending_gross"]) == Decimal("9250.00")
    assert Decimal(govde["paid_period_gross"]) == Decimal("43000.00")
    assert govde["active_subcontractor_count"] == 1


async def test_ozet_parametresiz_eski_davranisi_korur(
    client: AsyncClient, admin_headers: dict[str, str], santiye_verisi: dict
) -> None:
    yanit = await client.get(
        OZET_UC, params={"period_year": 2026, "period_month": 7}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("267250.00")  # +215.000
    assert govde["active_subcontractor_count"] == 2


# --- 3. IDOR: süzgeç kapsamı GENİŞLETMEZ ---


async def test_gorunmeyen_projenin_santiyesi_liste_getirmez(
    client: AsyncClient, kisitli_headers: dict[str, str], santiye_verisi: dict
) -> None:
    """`kisitli_headers` kullanıcısı yalnız `kisitli_proje`'yi görür; başka projenin
    şantiye kimliği verilse bile hakediş GELMEZ."""
    yanit = await client.get(
        LISTE_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=kisitli_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0
    assert yanit.json()["items"] == []


async def test_gorunmeyen_projenin_santiyesi_ozeti_sifirdir(
    client: AsyncClient, kisitli_headers: dict[str, str], santiye_verisi: dict
) -> None:
    yanit = await client.get(
        OZET_UC, params={"site_id": str(santiye_verisi["site"].id)}, headers=kisitli_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert Decimal(govde["total_gross"]) == Decimal("0.00")
    assert govde["active_subcontractor_count"] == 0
