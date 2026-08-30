"""PARA-GERCEK — `mark-paid` GERÇEKLEŞMİŞ para ister (İŞVEREN ailesi).

Kapı İKİ ailede de vardır ve bu dosya ikizin ölçüldüğü yerdir. Tek ailede
uygulansaydı `_TRANSITION_SHAPE`i paylaşan iki makine aynı `mark_paid` çifti
için FARKLI davranırdı ve fark hiçbir yerde görünmezdi.

## Yön BURADA TERSTİR ve ölçülür

İşveren hakedişinde para bize GELİR: fatura `outgoing`tur, karşılığında ALINAN
(`received`) bir çek elimize girer ve o çekin "para geçti" durumu `collected`tır
(`paid` DEĞİL — aldığımız çeki biz ödemeyiz).
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.treasury.models import FinancialInstrumentStatus, PaymentMethodKind
from app.modules.treasury.realized import PAYMENT_NOT_REALIZED, SOURCE_NOT_INVOICED
from tests._para_gercek import parayi_yatir

pytestmark = pytest.mark.asyncio


async def test_G1_FATURASIZ_isveren_hakedisi_odendi_isaretlenemez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == SOURCE_NOT_INVOICED


async def test_G1_POZITIF_KONTROL_tahsil_edilmis_hakedis_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı: kapı "her şeyi reddet" hâline gelirse kırmızı."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, payment_id, taseron=False)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"


async def test_KESINTILI_isveren_hakedisi_de_odenebilir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 DENETİM BULGUSU 1'in bu ailedeki bekçisi.

    Fatura, hakedişin KENDİ oranlarıyla ürünün para motorundan geçirilir
    (`invoicing.amounts.compute`). Kesintiler doluysa `total`, hakediş netinden
    KÜÇÜKTÜR; eşik net olsaydı bu hakediş asla kapanamazdı.
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    from app.modules.progress_payments.models import ProgressPayment

    hakedis = await seeded_db.get(ProgressPayment, payment_id)
    assert hakedis is not None
    hakedis.advance_pct = Decimal("10.00")
    hakedis.retainage_pct = Decimal("5.00")
    hakedis.vat_pct = Decimal("20.00")
    await seeded_db.flush()

    await parayi_yatir(seeded_db, payment_id, taseron=False)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


async def test_G2_PORTFOYDEKI_cek_TEK_BASINA_yetmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(
        seeded_db, payment_id, taseron=False, evrak_durumu=FinancialInstrumentStatus.portfolio
    )

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


async def test_G2_POZITIF_KONTROL_cek_TAHSIL_edilince_gecer(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 YÖN: işverenden ALINAN çek `collected` olunca para gelmiştir."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(
        seeded_db, payment_id, taseron=False, evrak_durumu=FinancialInstrumentStatus.collected
    )

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


async def test_BULGU5_BAGSIZ_cek_odemesi_hakedisi_ODETMEZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Bağsız kıymetli evrak ödemesi bu ailede de fail-closed'dır."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, payment_id, taseron=False, method=PaymentMethodKind.cheque)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_G3_KISMI_odeme_yetmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, payment_id, taseron=False, fark=Decimal("-0.01"))

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


async def test_G3_SINIR_tam_esit_tutar_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Sınır değeri: `<` yerine `<=` yazan mutant YALNIZ burada görünür."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, payment_id, taseron=False, fark=Decimal("0.00"))

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize("uc", ["submit", "approve", "reject", "mark-paid", "unapprove"])
async def test_G4_paid_hicbir_gecisin_KAYNAGI_degildir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    hakedis_fabrikasi,
    uc: str,
) -> None:
    """PARA-GERCEK bir KAPI ekledi, tabloya ÇİFT EKLEMEDİ: `paid` TERMİNAL."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.paid)

    yanit = await client.post(
        f"/progress-payments/{payment_id}/{uc}",
        json={"reason": "gerekçe metni"},
        headers=admin_headers,
    )

    assert yanit.status_code == 409, yanit.text


async def test_kapi_TASERON_kolonunu_ISVEREN_hakedisiyle_karistirmaz(
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 İki ailenin FK'si farklıdır; toplama kolona GERÇEKTEN bağlıdır."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    yatan = await parayi_yatir(seeded_db, payment_id, taseron=False)

    kendi = await realized_total_for_source(seeded_db, Invoice.progress_payment_id, payment_id)
    obur = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, payment_id
    )

    assert kendi == yatan
    assert obur == Decimal("0")


async def test_kapi_ILGISIZ_bir_hakedisin_parasini_saymaz(
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Sabit dönüş bekçisi: başka bir hakedişe yatan para bu hakedişi ödemez."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    odenen = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, odenen, taseron=False)

    toplam = await realized_total_for_source(seeded_db, Invoice.progress_payment_id, uuid.uuid4())
    assert toplam == Decimal("0")
