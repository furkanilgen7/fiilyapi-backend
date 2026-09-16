"""🔴 MK-2 K2/K9 — `reload`un KAPSAM DIŞI satırlara dokunmaması.

Kapsam (`_visible_project_ids`) bir OKUMA süzgecidir. Kira faturasının satır
kümesi ise `invoice_id`ye göre KAPSAMSIZ okunur ve detay ucu zaten tüm satırları
basar; yani dar kapsamlı kullanıcı o satırları GÖRÜR. Kapsamın tek fiilî etkisi
`_build_lines`in SİLME dalıydı: dar kapsamlı bir `reload` görmediği projenin
satırlarını — ve onlara girilmiş `invoiced_hours`/`rate_amount` emeğini —
sessizce siliyordu. Bir okuma süzgeci YAZMA etkisi doğuramaz.

Mevcut `reload` bekçilerinin hepsi `admin_headers` kullanır; `system_admin`in
`projects` izni `_A` olduğu için kapsam dalı HİÇ KOŞMAZ.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import EquipmentOwnership, EquipmentRentalInvoiceLine
from app.modules.sites.models import Site

from ._mk2_rental_invoice import (
    _BEDEL,
    _detay,
    _fatura_kur,
    _kayit,
    _satir,
    _tedarikci,
)

pytestmark = pytest.mark.asyncio


async def _satirlar(session: AsyncSession, invoice_id: str) -> list[EquipmentRentalInvoiceLine]:
    return list(
        (
            await session.execute(
                select(EquipmentRentalInvoiceLine).where(
                    EquipmentRentalInvoiceLine.invoice_id == uuid.UUID(invoice_id)
                )
            )
        )
        .scalars()
        .all()
    )


async def test_dar_kapsamli_kullanicinin_reloadu_gormedigi_projenin_satirini_SILMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    sef_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
    gorunmeyen_santiye: Site,
) -> None:
    """🔴 `site_id=None` ("Tüm Projeler") fatura + dar kapsamlı `reload`.

    Şef faturayı LİSTEDE ve DETAYDA görür (`invoice_scope`in `site_id IS NULL`
    dalı); tazelediğinde göremediği projenin satırı ve üzerine girilmiş fatura
    saati OLDUĞU GİBİ kalmalıdır.
    """
    supplier = await _tedarikci(seeded_db, "CAT Türkiye A.Ş.")
    gorunen_makine = await ekipman_fabrikasi(
        "Ekskavatör EX-01",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    gorunmeyen_makine = await ekipman_fabrikasi(
        "Ekskavatör EX-02",
        site=gorunmeyen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    await _kayit(seeded_db, gorunen_makine, hours="100", ilk_gun=1, site=gorunen_santiye)
    await _kayit(seeded_db, gorunmeyen_makine, hours="60", ilk_gun=1, site=gorunmeyen_santiye)

    fatura = await _fatura_kur(client, admin_headers, supplier)
    detay = await _detay(client, admin_headers, fatura["id"])
    assert len(detay["lines"]) == 2, detay["lines"]

    # Muhasebe firmanın faturasına bakıp GÖRÜNMEYEN projenin satırına saat girer.
    disaridaki = _satir(detay, "rented", gorunmeyen_makine.id)
    resp = await client.patch(
        f"/equipment/rental-invoice-lines/{disaridaki['id']}",
        json={"invoiced_hours": "66.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    # Şef "tazele" der — kötü niyet gerekmez.
    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=sef_headers
    )
    assert resp.status_code == 200, resp.text

    kalanlar = await _satirlar(seeded_db, fatura["id"])
    assert len(kalanlar) == 2, [
        (str(s.equipment_id), s.line_kind, str(s.site_id)) for s in kalanlar
    ]
    korunan = next(s for s in kalanlar if s.equipment_id == gorunmeyen_makine.id)
    await seeded_db.refresh(korunan)
    assert korunan.invoiced_hours == Decimal("66.00")
    assert korunan.worked_hours == Decimal("60.00")


async def test_genis_kapsamli_reload_dayanagi_kalmayan_satiri_YINE_SILER(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    ekipman_fabrikasi,
    gorunen_santiye: Site,
) -> None:
    """Silme kuralı (dayanağı kalmayan satır SİLİNİR) kapsam İÇİNDE sürer.

    Onarım silmeyi kaldırmaz, YALNIZ kapsam dışı satırı muaf tutar; bu test o
    muafiyetin silme kuralını topyekûn öldürmediğini bekçiler.
    """
    supplier = await _tedarikci(seeded_db, "Liebherr Türkiye A.Ş.")
    makine = await ekipman_fabrikasi(
        "Tower Crane TC-48",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.rented,
        supplier_id=supplier.id,
        rate_amount=_BEDEL,
    )
    kayitlar = await _kayit(seeded_db, makine, hours="40", ilk_gun=1, site=gorunen_santiye)
    fatura = await _fatura_kur(client, admin_headers, supplier)
    assert len(await _satirlar(seeded_db, fatura["id"])) == 1

    for kayit in kayitlar:
        await seeded_db.delete(kayit)
    await seeded_db.flush()

    resp = await client.post(
        f"/equipment/rental-invoices/{fatura['id']}/reload", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert await _satirlar(seeded_db, fatura["id"]) == []
