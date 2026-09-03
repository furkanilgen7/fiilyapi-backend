"""🔴 FAT-HAK — TAŞERON ailesinde fatura ↔ hakediş TUTAR kapısı (uçtan uca).

İşveren ikizinin aynası, ama kapının BİRİNCİ katmanı BAŞKA BİR YERDEDİR ve bu
fark ÖLÇÜLDÜ:

    giden fatura (işveren)   `draft` doğar → silinebilir, kalemleri
                             düzeltilebilir → kapı `send` geçişindedir
    gelen fatura (taşeron)   `pending` doğar → SİLİNEMEZ (`DELETABLE_STATUS`
                             yalnız `draft`), kalemleri DEĞİŞTİRİLEMEZ
                             (`LINES_EDITABLE_STATUS` yalnız `draft` ve gelen
                             tarafta `draft` HİÇ YOKTUR), tutarı
                             PATCH'lenemez (`INCOMING_PATCHABLE_FIELDS` yalnız
                             not/vade/ödeme şekli)
                             → kayıt DOĞDUĞU AN kalıcıdır → kapı `POST`tadır

Kapı `approve`a bırakılsaydı yanlış tutarlı gelen fatura ÇOKTAN DOĞMUŞ olur ve
`uq_invoices_subcontractor_progress_payment` kısmi UNIQUE indeksi yüzünden
hakedişin fatura slotunu SONSUZA DEK işgal ederdi: doğrusu bir daha hiç
bağlanamaz, hakediş bir daha hiç ödenemezdi. Bu, geri dönüşü OLMAYAN tek hâldir
ve yalnız `POST` kapısı onu önler.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import Invoice, InvoiceStatus
from app.modules.invoicing.validation import source_amount_mismatch
from app.modules.subcontractor_progress_payments.models import SubcontractorPaymentStatus
from app.modules.treasury.realized import BINDING_INVOICE_INVALID, PAYMENT_NOT_REALIZED
from app.modules.users.models import User
from tests._para_gercek import fatura_kes, hakedis_bruttu, odeme_yaz
from tests.subcontractor_progress_payments.test_transitions import _satirli_hakedis

pytestmark = pytest.mark.asyncio

_HAKEDIS = "/subcontractor-progress-payments"
_FATURA = "/invoices"

_TUTAR_409_BASI = "Hakediş ödendi işaretlenemez: hakedişe bağlı faturanın ara toplamı"

#: `POST /invoices` gövdesinin kalem şablonu (`test_invoicing_api._KALEM` ikizi).
_KALEM = {
    "description": "Kaba İnşaat İmalatı",
    "unit": "m³",
    "quantity": "1.000",
    "unit_price": "1000.00",
    "vat_rate": "20.00",
}


async def _onayli_hakedis(seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi):
    """`taseron_sozlesmesi` ÜÇLÜ döner (`sözleşme, proje, şantiye`) — ilk eleman
    alınır; ikizi `test_para_gercek.py`de de böyle açılır."""
    contract, _, _ = taseron_sozlesmesi
    return await _satirli_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        status=SubcontractorPaymentStatus.approved,
    )


def _gelen_govde(payment_id: uuid.UUID, birim_fiyat: Decimal) -> dict:
    """Taşeronun bize kestiği GELEN fatura — tek kalem, birim fiyat testin eli."""
    return {
        "direction": "incoming",
        "document_type": "einvoice",
        "invoice_no": f"TSR{uuid.uuid4().hex[:10].upper()}",
        "issue_date": "2026-07-18",
        "party_name": "Yıldız Taşeronluk Ltd. Şti.",
        "party_tax_number": "1234567890",
        "subcontractor_progress_payment_id": str(payment_id),
        "lines": [dict(_KALEM) | {"quantity": "1.000", "unit_price": str(birim_fiyat)}],
    }


# --------------------------------------------------------------------------- #
# KATMAN 1 — `POST /invoices` (422). Geri dönüşü olmayan hâlin TEK bekçisi.
# --------------------------------------------------------------------------- #


async def test_FH5_POST_TUTARSIZ_gelen_fatura_HIC_DOGMAZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
) -> None:
    """🔴 Kayıt DOĞMAZ — ve doğmaması ŞARTTIR: doğsaydı silinemez, düzeltilemez
    ve hakedişin fatura slotunu kalıcı olarak işgal ederdi."""
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)
    assert brut > Decimal("1.00"), "kurulum: brüt 1 ₺'den büyük olmalı"

    yanit = await client.post(
        _FATURA, headers=admin_headers, json=_gelen_govde(hakedis.id, Decimal("1.00"))
    )

    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["detail"] == source_amount_mismatch(Decimal("1.00"), brut), yanit.text
    # 🔴 Asıl iddia: ORTADA KAYIT YOK. Yalnız durum kodunu iddia eden bir test,
    #    422 döndürdükten SONRA yine de satırı yazan bir uçta yeşil kalırdı.
    kalan = (
        await seeded_db.execute(
            Invoice.__table__.select().where(
                Invoice.subcontractor_progress_payment_id == hakedis.id
            )
        )
    ).all()
    assert kalan == [], "422 verildi ama fatura satırı yine de yazıldı"


async def test_FH5_POZITIF_KONTROL_POST_dogru_tutarda_fatura_DOGAR(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
) -> None:
    """🔴 Karşıt kanıt: aynı gövde, YALNIZ tutar doğru → 201.

    Bu satır olmasaydı, her gövdeye 422 veren bozuk bir uç da yukarıdaki testi
    yeşil geçirirdi (K-IKIZ1).
    """
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)

    yanit = await client.post(_FATURA, headers=admin_headers, json=_gelen_govde(hakedis.id, brut))

    assert yanit.status_code == 201, yanit.text
    assert Decimal(yanit.json()["subtotal"]) == brut
    assert yanit.json()["status"] == InvoiceStatus.pending.value


async def test_FH6_POST_KAYNAKSIZ_gelen_fatura_ETKILENMEZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Kapsam bekçisi: hakedişe bağlı OLMAYAN gelen fatura kuralı görmez.

    Kural her faturaya bir brüt uydurur hâle gelirse (ör. `None` yerine
    `Decimal(0)`) ürünün ÇOĞUNLUĞU olan kaynaksız faturalar kesilemez olurdu.
    """
    govde = _gelen_govde(uuid.uuid4(), Decimal("1.00"))
    govde.pop("subcontractor_progress_payment_id")

    yanit = await client.post(_FATURA, headers=admin_headers, json=govde)

    assert yanit.status_code == 201, yanit.text


# --------------------------------------------------------------------------- #
# KATMAN 2 — `mark-paid` (409). Doğmuş kayıtların ve eski verinin bekçisi.
# --------------------------------------------------------------------------- #


async def test_FH7_BIR_TL_lik_fatura_taseron_hakedisini_ODETEMEZ(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
) -> None:
    """🔴 422 katmanı bu kaydı GÖRMEDİ (fatura doğrudan DB'ye kuruldu) — tıpkı
    kural doğmadan ÖNCE yazılmış CANLI kayıtlar gibi. Para kapısı fail-closed
    olduğu için onları da tutar."""
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)
    fatura = await fatura_kes(seeded_db, hakedis.id, taseron=True, brut=Decimal("1.00"))
    assert fatura.total > 0, "kurulum: `total > 0` şartı BU testte elenmiş olmalı"
    await odeme_yaz(seeded_db, fatura, taseron=True, tutar=fatura.total)

    yanit = await client.post(f"{_HAKEDIS}/{hakedis.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    detay = yanit.json()["detail"]
    assert detay.startswith(_TUTAR_409_BASI), detay
    assert detay != BINDING_INVOICE_INVALID
    assert detay != PAYMENT_NOT_REALIZED
    assert "1.00" in detay and str(brut) in detay


async def test_FH7_POZITIF_KONTROL_dogru_tutarli_fatura_hakedisi_ODER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
) -> None:
    """İddianın ikinci yarısı — kapı "her şeyi reddet" olursa KIRMIZI."""
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)
    fatura = await fatura_kes(seeded_db, hakedis.id, taseron=True, brut=brut)
    await odeme_yaz(seeded_db, fatura, taseron=True, tutar=fatura.total)

    yanit = await client.post(f"{_HAKEDIS}/{hakedis.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"


@pytest.mark.parametrize(
    "sapma", [Decimal("0.01"), Decimal("-0.01")], ids=["arti_bir_kurus", "eksi_bir_kurus"]
)
async def test_FH8_SINIR_bir_kurusluk_sapma_GECER(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
    sapma: Decimal,
) -> None:
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)
    fatura = await fatura_kes(seeded_db, hakedis.id, taseron=True, brut=brut + sapma)
    await odeme_yaz(seeded_db, fatura, taseron=True, tutar=fatura.total)

    yanit = await client.post(f"{_HAKEDIS}/{hakedis.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize(
    "sapma", [Decimal("0.02"), Decimal("-0.02")], ids=["arti_iki_kurus", "eksi_iki_kurus"]
)
async def test_FH8_SINIR_iki_kurusluk_sapma_REDDEDILIR(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_db: AsyncSession,
    hakedis_fabrikasi,
    taseron_sozlesmesi,
    admin_kullanicisi: User,
    sapma: Decimal,
) -> None:
    hakedis = await _onayli_hakedis(
        seeded_db, hakedis_fabrikasi, taseron_sozlesmesi, admin_kullanicisi
    )
    brut = await hakedis_bruttu(seeded_db, hakedis.id, taseron=True)
    fatura = await fatura_kes(seeded_db, hakedis.id, taseron=True, brut=brut + sapma)
    await odeme_yaz(seeded_db, fatura, taseron=True, tutar=fatura.total)

    yanit = await client.post(f"{_HAKEDIS}/{hakedis.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"].startswith(_TUTAR_409_BASI), yanit.text
