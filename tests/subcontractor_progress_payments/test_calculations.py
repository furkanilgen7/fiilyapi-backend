"""T3 — taşeron hakedişi hesap zinciri (spec §3; plan T3).

Hesap `progress_payments.calculations` saf fonksiyonlarının YENİDEN KULLANIMIDIR
(kopya değil) — bu dosya sayısal beklentilerle o zincirin taşeron ucundaki
çıktısını doğrular:

    brüt → KDV → avans mahsubu (kümülatif tavanlı) → teminat kesintisi → net

**ONAYLI SAPMA (geri alınmaz):** mockup tfoot'unda OLMAYAN *teminat kesintisi*
satırı ve *fiyat farkı katsayısı* hesaba dahildir. Liste ekranındaki
"Net = Brüt − KDV" görünümü (L146) mockup HESAP HATASIDIR — burada doğru formül
test edilir. KDV tevkifatı bu dilimde hesaba GİRMEZ (spec §8 S4).
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import SubcontractorContractItem
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


async def _kaydet(client: AsyncClient, headers: dict[str, str], payment_id, satirlar) -> dict:
    yanit = await client.put(
        f"/subcontractor-progress-payments/{payment_id}/lines",
        json={"lines": satirlar},
        headers=headers,
    )
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def _kalemler(contract) -> list[SubcontractorContractItem]:
    return sorted(contract.items, key=lambda item: item.sort_order)


def _d(govde: dict, alan: str) -> Decimal:
    return Decimal(govde["calculation"][alan])


# --- Zincir (spec §3) ---


async def test_hesap_zinciri_brut_kdv_avans_teminat_net(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    """Fiyatlar 21.500 / 1.850 · KDV %20 · avans %10 · teminat %5.

    brüt = 10×21.500 + 5×1.850 = 224.250,00
    KDV  = 44.850,00 · avans = 22.425,00 · teminat = 11.212,50
    net  = 224.250 + 44.850 − 22.425 − 11.212,50 = 235.462,50
    """
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem1, kalem2 = _kalemler(contract)
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [
            {"contract_item_id": str(kalem1.id), "quantity": "10"},
            {"contract_item_id": str(kalem2.id), "quantity": "5"},
        ],
    )
    assert _d(govde, "gross") == Decimal("224250.00")
    assert _d(govde, "vat") == Decimal("44850.00")
    assert _d(govde, "advance_deduction") == Decimal("22425.00")
    assert _d(govde, "retention") == Decimal("11212.50")
    assert _d(govde, "net") == Decimal("235462.50")


async def test_net_brut_eksi_kdv_degildir_mockup_l146_hesap_hatasidir(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10"}],
    )
    assert _d(govde, "net") != _d(govde, "gross") - _d(govde, "vat")
    assert _d(govde, "net") == (
        _d(govde, "gross")
        + _d(govde, "vat")
        - _d(govde, "advance_deduction")
        - _d(govde, "retention")
    )


async def test_teminat_kesintisi_hesaba_dahildir_onayli_sapma(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10"}],
    )
    # brüt 215.000 · teminat %5
    assert _d(govde, "retention") == Decimal("10750.00")


async def test_kdv_tevkifati_hesaba_girmez(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi,
    seeded_db: AsyncSession,
) -> None:
    """Spec §8 S4: `vat_withholding` bayrağı BİLGİDİR, KDV'yi bölmez."""
    contract, _, _ = taseron_sozlesmesi
    contract.vat_withholding = True
    await seeded_db.flush()
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10"}],
    )
    assert _d(govde, "vat") == Decimal("43000.00")  # 215.000 × %20, tevkifatsız


# --- Katsayı + kuruş hassasiyeti (K5 kuralı) ---


async def test_fiyat_farki_katsayisi_hesaba_girer(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10", "coefficient": "1.150"}],
    )
    # düz. b.f. = 21.500 × 1,150 = 24.725,00 → × 10 = 247.250,00
    assert Decimal(govde["lines"][0]["adjusted_unit_price"]) == Decimal("24725.00")
    assert Decimal(govde["lines"][0]["line_total"]) == Decimal("247250.00")
    assert _d(govde, "gross") == Decimal("247250.00")


async def test_kurus_hassasiyeti_korunur(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi_fabrikasi
) -> None:
    """K5: düzeltilmiş birim fiyat ÖNCE kuruşa yuvarlanır, sonra miktarla çarpılıp
    TEKRAR kuruşa yuvarlanır (tam liraya yuvarlama mockup artefaktıdır)."""
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C01", unit_prices=[Decimal("1234.57")])
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "3.5", "coefficient": "1.005"}],
    )
    # 1234,57 × 1,005 = 1240,74285 → 1240,74 · × 3,5 = 4342,59
    assert Decimal(govde["lines"][0]["adjusted_unit_price"]) == Decimal("1240.74")
    assert Decimal(govde["lines"][0]["line_total"]) == Decimal("4342.59")
    assert _d(govde, "gross") == Decimal("4342.59")


# --- Avans mahsubu: kümülatif tavan (spec §3) ---


async def test_avans_tavani_sozlesme_bedelinden_turer(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi_fabrikasi
) -> None:
    """Tavan = sözleşme bedeli × avans% = (200 × 100) × %10 = 2.000,00.

    Katsayılı brüt 30.000 → tavansız kesinti 3.000 > tavan → 2.000'e KIRPILIR.
    """
    contract, _, _ = await taseron_sozlesmesi_fabrikasi("THK-C02", unit_prices=[Decimal("100")])
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "200", "coefficient": "1.500"}],
    )
    assert _d(govde, "gross") == Decimal("30000.00")
    assert _d(govde, "advance_deduction") == Decimal("2000.00")
    assert _d(govde, "retention") == Decimal("1500.00")
    assert _d(govde, "net") == Decimal("32500.00")


async def test_avans_kumulatifi_onceki_hakedisleri_zincirler(
    client: AsyncClient,
    admin_headers: dict[str, str],
    taseron_sozlesmesi_fabrikasi,
    hakedis_fabrikasi,
    admin_kullanicisi,
    seeded_db: AsyncSession,
) -> None:
    """Sözleşme bedeli 40.000 · avans %30 → tavan 12.000.

    Önceki ONAYLI hakediş (kat. 2,0 ile brüt 40.000) tavanın TAMAMINI kurtarır;
    bu hakedişin kalan tavanı 0'dır → avans kesintisi 0 (basit toplam DEĞİL).
    """
    contract, _, _ = await taseron_sozlesmesi_fabrikasi(
        "THK-C03", unit_prices=[Decimal("100"), Decimal("100")]
    )
    contract.advance_pct = Decimal("30")
    await seeded_db.flush()
    kalem1, kalem2 = _kalemler(contract)

    onceki = await hakedis_fabrikasi(
        contract, admin_kullanicisi, sequence_no=1, status=SubcontractorPaymentStatus.approved
    )
    seeded_db.add(
        SubcontractorProgressPaymentLine(
            payment_id=onceki.id,
            contract_item_id=kalem1.id,
            code=kalem1.code,
            description=kalem1.description,
            unit=kalem1.unit,
            contract_unit_price=kalem1.unit_price,
            coefficient=Decimal("2.000"),
            quantity=Decimal("200"),
            sort_order=0,
        )
    )
    await seeded_db.flush()

    hakedis = await _olustur(client, admin_headers, contract.id)
    govde = await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem2.id), "quantity": "200"}],
    )
    assert _d(govde, "gross") == Decimal("20000.00")
    assert _d(govde, "advance_deduction") == Decimal("0.00"), "kalan tavan tükenmiş olmalı"
    # 20.000 + 4.000 KDV (%20) − 0 avans − 1.000 teminat (%5)
    assert _d(govde, "net") == Decimal("23000.00")


# --- Liste satırı (brüt/net) ---


async def test_liste_satiri_brut_ve_net_tasir(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    kalem = _kalemler(contract)[0]
    await _kaydet(
        client,
        admin_headers,
        hakedis["id"],
        [{"contract_item_id": str(kalem.id), "quantity": "10"}],
    )
    liste = await client.get("/subcontractor-progress-payments", headers=admin_headers)
    assert liste.status_code == 200, liste.text
    satir = next(s for s in liste.json()["items"] if s["id"] == hakedis["id"])
    assert Decimal(satir["gross_total"]) == Decimal("215000.00")
    # 215.000 + 43.000 KDV − 21.500 avans − 10.750 teminat
    assert Decimal(satir["net_total"]) == Decimal("225750.00")


async def test_satirsiz_hakedis_sifir_hesap_dondurur(
    client: AsyncClient, admin_headers: dict[str, str], taseron_sozlesmesi
) -> None:
    contract, _, _ = taseron_sozlesmesi
    hakedis = await _olustur(client, admin_headers, contract.id)
    assert _d(hakedis, "gross") == Decimal("0.00")
    assert _d(hakedis, "net") == Decimal("0.00")
