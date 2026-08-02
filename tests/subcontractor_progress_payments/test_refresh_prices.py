"""T3 — `POST /subcontractor-progress-payments/{id}/refresh-prices` (plan T3).

İşveren `refresh-prices` deseninin taşeron karşılığı: yalnız `draft`ta, bağı
kopmamış satırların snapshot'ı sözleşme KALEMİNDEN, hakedişin yüzde üçlüsü
SÖZLEŞMEDEN bilinçli tazelenir. `coefficient`/`quantity` KULLANICI verisidir,
dokunulmaz.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.subcontractor_progress_payments import guards
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPaymentLine,
)

pytestmark = pytest.mark.asyncio


async def _olustur(client: AsyncClient, headers: dict[str, str], contract_id) -> dict:
    yanit = await client.post(
        f"/subcontractor-contracts/{contract_id}/progress-payments", json={}, headers=headers
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


async def _tazele(client: AsyncClient, headers: dict[str, str], payment_id):
    return await client.post(
        f"/subcontractor-progress-payments/{payment_id}/refresh-prices", headers=headers
    )


def _kalemler(contract):
    return sorted(contract.items, key=lambda item: item.sort_order)


async def test_fiyat_degisince_snapshot_tazelenir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    kalem.unit_price = Decimal("23000")
    kalem.description = "Yeni açıklama"
    await seeded_db.flush()

    yanit = await _tazele(client, admin_headers, hakedis["id"])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["refreshed_count"] == 1

    detay = (
        await client.get(f"/subcontractor-progress-payments/{hakedis['id']}", headers=admin_headers)
    ).json()
    satir = next(s for s in detay["lines"] if s["contract_item_id"] == str(kalem.id))
    assert Decimal(satir["contract_unit_price"]) == Decimal("23000")
    assert satir["description"] == "Yeni açıklama"


async def test_degismemis_satir_sayilmaz(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    yanit = await _tazele(client, admin_headers, hakedis["id"])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["refreshed_count"] == 0


async def test_kullanici_verisine_dokunulmaz(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    await client.put(
        f"/subcontractor-progress-payments/{hakedis['id']}/lines",
        json={
            "lines": [{"contract_item_id": str(kalem.id), "quantity": "12", "coefficient": "1.200"}]
        },
        headers=admin_headers,
    )
    kalem.unit_price = Decimal("23000")
    await seeded_db.flush()
    await _tazele(client, admin_headers, hakedis["id"])

    detay = (
        await client.get(f"/subcontractor-progress-payments/{hakedis['id']}", headers=admin_headers)
    ).json()
    satir = detay["lines"][0]
    assert Decimal(satir["quantity"]) == Decimal("12")
    assert Decimal(satir["coefficient"]) == Decimal("1.200")


async def test_yuzde_ucluse_sozlesmeden_tazelenir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    contract.vat_pct = Decimal("10")
    contract.advance_pct = Decimal("15")
    contract.retainage_pct = Decimal("3")
    await seeded_db.flush()

    await _tazele(client, admin_headers, hakedis["id"])
    detay = (
        await client.get(f"/subcontractor-progress-payments/{hakedis['id']}", headers=admin_headers)
    ).json()
    assert Decimal(detay["vat_pct"]) == Decimal("10")
    assert Decimal(detay["advance_pct"]) == Decimal("15")
    assert Decimal(detay["retainage_pct"]) == Decimal("3")


async def test_bagi_kopmus_satir_atlanir_silinmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    satirlar = (
        (
            await seeded_db.execute(
                select(SubcontractorProgressPaymentLine).where(
                    SubcontractorProgressPaymentLine.payment_id == hakedis["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    satirlar[0].contract_item_id = None
    await seeded_db.flush()

    yanit = await _tazele(client, admin_headers, hakedis["id"])
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["refreshed_count"] == 0

    detay = (
        await client.get(f"/subcontractor-progress-payments/{hakedis['id']}", headers=admin_headers)
    ).json()
    assert len(detay["lines"]) == 2, "bağı kopmuş satır SİLİNMEZ"


async def test_draft_disinda_409(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    admin_kullanicisi,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    payment = await hakedis_fabrikasi(
        contract, admin_kullanicisi, status=SubcontractorPaymentStatus.approved
    )
    yanit = await _tazele(client, admin_headers, payment.id)
    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == guards.INVALID_STATUS_TRANSITION


async def test_gorunmeyen_hakedis_404(
    client: AsyncClient, kisitli_headers: dict[str, str], gorunmeyen_hakedis
) -> None:
    yanit = await _tazele(client, kisitli_headers, gorunmeyen_hakedis)
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == guards.PAYMENT_MISSING


async def test_denetim_kaydi_yazilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    await _tazele(client, admin_headers, hakedis["id"])
    kayitlar = (await seeded_db.execute(select(AuditLog))).scalars().all()
    assert any("fiyatları tazelendi" in kayit.detail for kayit in kayitlar), [
        k.detail for k in kayitlar
    ]
