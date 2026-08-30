"""PARA-GERCEK — `mark-paid` GERÇEKLEŞMİŞ para ister (İŞVEREN ailesi).

Kapı İKİ ailede de vardır ve bu dosya ikizin ölçüldüğü yerdir. Tek ailede
uygulansaydı `_TRANSITION_SHAPE`i paylaşan iki makine aynı `mark_paid` çifti
için FARKLI davranırdı ve fark hiçbir yerde görünmezdi.

## Yön BURADA TERSTİR ve ölçülür

İşveren hakedişinde para bize GELİR: fatura `outgoing`tur, karşılığında ALINAN
(`received`) bir çek elimize girer ve o çekin "para geçti" durumu `collected`tır
(`paid` DEĞİL — aldığımız çeki biz ödemeyiz). Taşeron ikizinde her şey terstir.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.treasury.models import FinancialInstrumentStatus
from app.modules.treasury.realized import PAYMENT_NOT_REALIZED
from tests._para_gercek import hakedis_neti, parayi_yatir

pytestmark = pytest.mark.asyncio


async def test_G1_ODEMESIZ_isveren_hakedisi_odendi_isaretlenemez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_G1_POZITIF_KONTROL_tahsil_edilmis_hakedis_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı: kapı "her şeyi reddet" hâline gelirse bu test
    kırmızıya döner."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, payment_id, taseron=False)

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"


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
    """🔴 YÖN: işverenden ALINAN çek `collected` olunca para gelmiştir.

    Bu ailede `paid` durumu ANLAMSIZDIR (verilen çeke aittir) ve bir sonraki
    test onun sayılmadığını ayrıca ölçer.
    """
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(
        seeded_db, payment_id, taseron=False, evrak_durumu=FinancialInstrumentStatus.collected
    )

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


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
    net = await hakedis_neti(seeded_db, payment_id, taseron=False)
    yatan = await parayi_yatir(seeded_db, payment_id, taseron=False, fark=Decimal("0.00"))
    assert yatan == net, "kurulum sınırı kurmadı"

    yanit = await client.post(f"/progress-payments/{payment_id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize("uc", ["submit", "approve", "reject", "mark-paid", "unapprove"])
async def test_G4_paid_hicbir_gecisin_KAYNAGI_degildir(
    client: AsyncClient,
    admin_headers: dict[str, str],
    hakedis_fabrikasi,
    uc: str,
) -> None:
    """PARA-GERCEK bir KAPI ekledi, tabloya ÇİFT EKLEMEDİ: `paid` TERMİNAL kalır."""
    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.paid)

    yanit = await client.post(
        f"/progress-payments/{payment_id}/{uc}",
        json={"reason": "gerekçe metni"},
        headers=admin_headers,
    )

    assert yanit.status_code == 409, yanit.text


async def test_kapi_TASERON_odemesini_ISVEREN_hakedisine_saymaz(
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """🔴 KAYNAK KOLONU DOĞRU OKUNUYOR MU: iki ailenin FK'si farklıdır.

    Kolonu karıştıran bir uygulama (taşeron kolonuna bakan işveren kapısı) her
    işveren hakedişini reddederdi; bu test toplamanın kolona GERÇEKTEN bağlı
    olduğunu, sabit sıfır dönmediğini kilitler.
    """
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    payment_id = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    yatan = await parayi_yatir(seeded_db, payment_id, taseron=False)

    kendi = await realized_total_for_source(seeded_db, Invoice.progress_payment_id, payment_id)
    obur_kolon = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, payment_id
    )

    assert kendi == yatan
    assert obur_kolon == Decimal("0")


async def test_kapi_ILGISIZ_bir_hakedisin_parasini_saymaz(
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
) -> None:
    """Başka bir hakedişe yatan para bu hakedişi ödemez (sabit dönüş bekçisi)."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    odenen = await hakedis_fabrikasi(ProgressPaymentStatus.approved)
    await parayi_yatir(seeded_db, odenen, taseron=False)

    toplam = await realized_total_for_source(seeded_db, Invoice.progress_payment_id, uuid.uuid4())
    assert toplam == Decimal("0")
