"""MK-4 — `GET /equipment/rental-invoices?equipment_id=…` süzgeci.

Denetim bulgusu: Ekipman Detay ekranının "bu makinenin hakedişleri" bloğu
besleneme­yordu çünkü uçta `equipment_id` süzgeci YOKTU.

🔴 Süzgeç SATIR düzeyindedir: `equipment_id` fatura BAŞLIĞINDA değil
`equipment_rental_invoice_lines`tadır (MK-2 şeması). Bu yüzden `EXISTS`tir,
JOIN DEĞİL — JOIN yazılsaydı aynı ekipmanın iki satırı bulunan fatura listede
İKİ KEZ görünür ve `total` gerçek fatura sayısından fazla çıkardı.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    Equipment,
    EquipmentRatePeriod,
    EquipmentRentalInvoice,
    EquipmentRentalInvoiceLine,
    RentalInvoiceStatus,
    RentalLineKind,
)
from app.modules.procurement.models import PaymentTerms, Supplier

pytestmark = pytest.mark.asyncio


async def _tedarikci(session: AsyncSession) -> Supplier:
    supplier = Supplier(name="Liebherr Türkiye A.Ş.", payment_terms=PaymentTerms.days_30)
    session.add(supplier)
    await session.flush()
    return supplier


async def _fatura(
    session: AsyncSession,
    supplier: Supplier,
    *makineler: Equipment,
    period_month: int,
    cift_satir: bool = False,
) -> EquipmentRentalInvoice:
    invoice = EquipmentRentalInvoice(
        supplier_id=supplier.id,
        invoice_no=f"FT-{uuid.uuid4().hex[:8]}",
        period_year=2026,
        period_month=period_month,
        rate_period=EquipmentRatePeriod.hourly,
        status=RentalInvoiceStatus.approved,
    )
    session.add(invoice)
    await session.flush()
    for makine in makineler:
        turler = (
            (RentalLineKind.rented, RentalLineKind.breakdown)
            if cift_satir
            else (RentalLineKind.rented,)
        )
        for tur in turler:
            session.add(
                EquipmentRentalInvoiceLine(
                    invoice_id=invoice.id,
                    equipment_id=makine.id,
                    line_kind=tur,
                    worked_hours=Decimal("100"),
                    breakdown_hours=Decimal("0"),
                    rate_amount=Decimal("320.00"),
                )
            )
    await session.flush()
    return invoice


async def test_equipment_id_suzgeci_YALNIZ_o_makinenin_hakedislerini_dondurur(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    ekskavator = await ekipman_fabrikasi("Ekskavatör CAT 320", site=gorunen_santiye)
    vincin = await _fatura(seeded_db, tedarikci, vinc, period_month=7)
    await _fatura(seeded_db, tedarikci, ekskavator, period_month=6)

    yanit = await client.get(
        f"/equipment/rental-invoices?equipment_id={vinc.id}", headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert [k["id"] for k in govde["items"]] == [str(vincin.id)]
    assert govde["total"] == 1


async def test_suzgecsiz_liste_HEPSINI_dondurur_suzgec_DARALTIR(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 İki sayacın FARKLI olduğu kurulum: süzgeçsiz `total` 2, süzgeçli 1.
    İkisinin eşit olduğu bir kurulumda yazılan test hiçbir şey kanıtlamazdı."""
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    ekskavator = await ekipman_fabrikasi("Ekskavatör CAT 320", site=gorunen_santiye)
    await _fatura(seeded_db, tedarikci, vinc, period_month=7)
    await _fatura(seeded_db, tedarikci, ekskavator, period_month=6)

    hepsi = await client.get("/equipment/rental-invoices", headers=sef_headers)
    suzulmus = await client.get(
        f"/equipment/rental-invoices?equipment_id={vinc.id}", headers=sef_headers
    )
    assert hepsi.json()["total"] == 2
    assert suzulmus.json()["total"] == 1


async def test_ayni_ekipmanin_IKI_satiri_faturayi_IKI_KEZ_dondurmez(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 `EXISTS` yerine JOIN yazılsaydı bu test KIRMIZI olurdu: fatura iki kez
    listelenir ve `total` 2 çıkardı — sayfalama kanonunun sessiz kaçağı."""
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    fatura = await _fatura(seeded_db, tedarikci, vinc, period_month=7, cift_satir=True)

    yanit = await client.get(
        f"/equipment/rental-invoices?equipment_id={vinc.id}", headers=sef_headers
    )
    assert [k["id"] for k in yanit.json()["items"]] == [str(fatura.id)]
    assert yanit.json()["total"] == 1


async def test_suzgecler_ANDlidir_baska_bir_suzgecle_birlikte_daraltir(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    await _fatura(seeded_db, tedarikci, vinc, period_month=7)
    await _fatura(seeded_db, tedarikci, vinc, period_month=6)

    yanit = await client.get(
        f"/equipment/rental-invoices?equipment_id={vinc.id}&period_month=7",
        headers=sef_headers,
    )
    assert yanit.json()["total"] == 1


async def test_var_olmayan_equipment_id_BOS_LISTE_dondurur_404_DEGIL(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 Bu bir SÜZGEÇtir, varlık referansı değil: 404 döndürseydi süzgeç bir
    KEŞİF ARACINA dönerdi (kullanıcı hangi kimliklerin var olduğunu deneme
    yanılmayla öğrenirdi)."""
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    await _fatura(seeded_db, tedarikci, vinc, period_month=7)

    yanit = await client.get(
        f"/equipment/rental-invoices?equipment_id={uuid.uuid4()}", headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["items"] == []
    assert yanit.json()["total"] == 0


async def test_equipment_id_UUID_olmalidir_422(client, sef_headers):
    yanit = await client.get("/equipment/rental-invoices?equipment_id=abc", headers=sef_headers)
    assert yanit.status_code == 422, yanit.text


async def test_suzgec_KAPSAMI_genisletmez(
    client, sef_headers, seeded_db: AsyncSession, ekipman_fabrikasi, gorunmeyen_santiye
):
    """🔴 Kapsam (K9) HER ZAMAN üsttedir: görünmeyen şantiyeye ait bir hakediş,
    ekipman kimliği bilinse bile listeye GİRMEZ."""
    tedarikci = await _tedarikci(seeded_db)
    vinc = await ekipman_fabrikasi("Gizli Vinç", site=gorunmeyen_santiye)
    fatura = await _fatura(seeded_db, tedarikci, vinc, period_month=7)
    fatura.site_id = gorunmeyen_santiye.id
    await seeded_db.flush()

    yanit = await client.get(
        f"/equipment/rental-invoices?equipment_id={vinc.id}", headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0
