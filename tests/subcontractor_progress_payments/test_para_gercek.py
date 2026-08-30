"""PARA-GERCEK — `mark-paid` GERÇEKLEŞMİŞ para ister (taşeron ailesi).

Kullanıcının kuralı birebir: *"Nakit olarak görmeden veya çekin vadesi gelip de
tahsil edilmeden 'ödendi' gözükmemesi gerekiyor."* Canlıda ÜÇ taşeron hakedişi
arkalarında tek kuruş ödeme olmadan `paid` damgası taşıyordu.

## Her iddianın İKİ YARISI vardır

🔴 Her kapı testi ÇİFTTİR: reddedilen hâlin yanında mutlaka *geçen* hâl de
vardır. Yalnız reddi ölçen bir test, kapı "her şeyi reddet" hâline geldiğinde de
YEŞİL kalırdı — yani "kural işliyor"u değil "hiçbir şey olmuyor"u kanıtlardı.

🔴 Ve bu dosyanın EN ÖNEMLİ testi `test_KESINTILI_hakedis_UCTAN_UCA_odenebilir`
dir: ilk turda kapı, kesinti taşıyan hiçbir hakediş için GEÇİLEMİYORDU (eşik
hakediş netiydi, ödemenin tavanı ise fatura `total`i) ve bunu HİÇBİR bekçi
görmedi, çünkü yardımcı faturayı elle kurup iki sayıyı zorla eşitliyordu.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import InvoiceDocumentType, InvoiceStatus
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)
from app.modules.treasury.models import FinancialInstrumentStatus, PaymentMethodKind
from app.modules.treasury.realized import PAYMENT_NOT_REALIZED, SOURCE_NOT_INVOICED
from app.modules.users.models import User
from tests._para_gercek import fatura_kes, hakedis_bruttu, odeme_yaz, parayi_yatir
from tests.subcontractor_progress_payments.test_transitions import _satirli_hakedis

pytestmark = pytest.mark.asyncio

_UC = "/subcontractor-progress-payments"


async def _onayli_hakedis(
    seeded_db: AsyncSession, hakedis_fabrikasi, contract, admin_kullanicisi: User
) -> SubcontractorProgressPayment:
    return await _satirli_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        status=SubcontractorPaymentStatus.approved,
    )


# --------------------------------------------------------------------------- #
# 🔴 BULGU 1 — KESINTILI hakedis ULASILABILIR olmali (asil regresyon)
# --------------------------------------------------------------------------- #


async def test_KESINTILI_hakedis_UCTAN_UCA_odenebilir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 DENETİM BULGUSU 1'İN BEKÇİSİ — kapı kullanıcıyı KİLİTLEMİYOR.

    Fixture kesintilidir (avans %10 · teminat %5 · KDV %20) ve iki formül
    YAPISAL olarak ayrışır:

        hakediş neti : KDV **brüt** üzerinden      → 245.175,00
        fatura total : KDV **tax_base** üzerinden  → 238.170,00

    Ödeme yalnız faturaya yazılabilir ve tavanı `total`dir. Eşik hakediş neti
    olsaydı bu test ASLA geçemezdi. Üç GERÇEK uçla kurulur, hiçbir yardımcı
    aradaki hesabı kısa devre yapmaz.
    """
    from app.modules.accounting.models import JournalSourceType
    from app.modules.treasury.posting import PAYMENT_POSTING_RULES
    from tests._hakedis_esleme import esleme_kur

    await esleme_kur(seeded_db, JournalSourceType.payment, PAYMENT_POSTING_RULES)

    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    brut = await hakedis_bruttu(seeded_db, payment.id, taseron=True)

    # Kesintiler GERÇEKTEN dolu — aksi hâlde test kusuru yeniden üretemezdi.
    assert payment.advance_pct > 0 and payment.retainage_pct > 0 and payment.vat_pct > 0

    erken = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert erken.status_code == 409, erken.text
    assert erken.json()["detail"] == SOURCE_NOT_INVOICED

    fatura = await client.post(
        "/invoices",
        json={
            "direction": "incoming",
            "invoice_no": f"TS{uuid.uuid4().hex[:10].upper()}",
            "document_type": "einvoice",
            "issue_date": "2026-02-01",
            "party_name": "Taşeron A.Ş.",
            "subcontractor_progress_payment_id": str(payment.id),
            "advance_rate": str(payment.advance_pct),
            "retention_rate": str(payment.retainage_pct),
            "lines": [
                {
                    "description": "Hakediş bedeli",
                    "quantity": "1",
                    "unit": "adet",
                    "unit_price": str(brut),
                    "vat_rate": str(payment.vat_pct),
                }
            ],
        },
        headers=admin_headers,
    )
    assert fatura.status_code in (200, 201), fatura.text
    total = Decimal(str(fatura.json()["total"]))
    assert total > 0

    # Faturasi var ama parasi yok -> HALA kapali, ama ARTIK BASKA bir metinle.
    faturali = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert faturali.status_code == 409, faturali.text
    assert faturali.json()["detail"] == PAYMENT_NOT_REALIZED

    hesap = await client.post(
        "/bank-accounts",
        json={"bank_name": "Uçtan Uca Bank", "account_type": "checking", "iban": None},
        headers=admin_headers,
    )
    assert hesap.status_code in (200, 201), hesap.text

    odeme = await client.post(
        f"/invoices/{fatura.json()['id']}/payments",
        json={
            "bank_account_id": hesap.json()["id"],
            "method": "transfer",
            "amount": str(total),
            "paid_on": "2026-02-05",
        },
        headers=admin_headers,
    )
    assert odeme.status_code in (200, 201), odeme.text

    sonuc = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert sonuc.status_code == 200, sonuc.text
    assert sonuc.json()["status"] == "paid"


async def test_BULGU2_yardimci_faturayi_URUNUN_PARA_MOTORUNDAN_gecirir(
    seeded_db: AsyncSession,
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 DENETİM BULGUSU 2'NİN BEKÇİSİ — yardımcı, ölçtüğü yolu KURMASIN.

    İlk hâlinde `fatura_kes` para kolonlarını elle dolduruyor ve tüm oranları
    SIFIRLIYORDU (`subtotal = tax_base = total = tutar`). O yüzden kapının
    karşılaştırdığı iki sayı testte zorla eşitleniyordu ve bulgu 1
    (kesintili hakediş kilitleniyor) DÖRT KAPIDAN DA yeşil geçti.

    Bu test üç şeyi birden çakar:

      1. faturanın kesinti kolonları GERÇEKTEN dolu (oranlar düşmemiş),
      2. `total` ürünün motorunun (`invoicing.amounts.compute`) verdiği sayı,
      3. 🔴 ve o sayı hakediş NETİNDEN FARKLI — iki formülün KDV matrahı
         gerçekten ayrışıyor. Bu üçüncüsü bulgu 1'in sayısal özüdür: eşik net
         olsaydı fark kadar bir tutar ASLA ödenemezdi.
    """
    from app.modules.invoicing import amounts as invoice_amounts
    from app.modules.progress_payments import calculations

    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    assert payment.advance_pct > 0 and payment.retainage_pct > 0 and payment.vat_pct > 0

    fatura = await fatura_kes(seeded_db, payment.id, taseron=True)
    brut = await hakedis_bruttu(seeded_db, payment.id, taseron=True)

    # 1 — kesintiler faturaya TASINDI
    assert fatura.advance_amount > 0
    assert fatura.retention_amount > 0
    assert fatura.vat_amount > 0

    # 2 — total URUNUN motorundan
    beklenen = invoice_amounts.compute(
        [
            invoice_amounts.LineInput(
                quantity=Decimal("1"), unit_price=brut, vat_rate=payment.vat_pct
            )
        ],
        advance_rate=payment.advance_pct,
        retention_rate=payment.retainage_pct,
        withholding_rate=None,
    )
    assert fatura.total == beklenen.total
    assert fatura.tax_base == beklenen.tax_base

    # 3 — iki formul GERCEKTEN ayrisiyor (bulgu 1'in sayisal ozu)
    hakedis_net = calculations.net_amount(
        brut,
        calculations.vat_amount(brut, payment.vat_pct),
        calculations.retention_amount(brut, payment.advance_pct),
        calculations.retention_amount(brut, payment.retainage_pct),
    )
    assert hakedis_net > fatura.total, (
        "Kesintili hakediste net ile fatura total'i AYRISMALI; ayrismiyorsa "
        "bulgu 1'i ureten kosul yok demektir ve bu dosya onu olcmuyordur."
    )


# --------------------------------------------------------------------------- #
# G1 — odemesiz hakedis `paid` OLAMAZ (+ pozitif kontrol)
# --------------------------------------------------------------------------- #


async def test_G1_FATURASIZ_hakedis_odendi_isaretlenemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Canlıdaki kusurun ta kendisi: arkasında hiçbir şey olmayan hakediş."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == SOURCE_NOT_INVOICED
    await seeded_db.refresh(payment)
    assert payment.status is SubcontractorPaymentStatus.approved
    assert payment.paid_at is None


async def test_G1_ODEMESIZ_faturali_hakedis_de_isaretlenemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Faturanın VARLIĞI yetmez; iki engelin metinleri de AYRIDIR."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await fatura_kes(seeded_db, payment.id, taseron=True)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_G1_POZITIF_KONTROL_yeterli_gerceklesmis_odeme_GECER(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı — kapı HER ŞEYİ reddetmiyor."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"


# --------------------------------------------------------------------------- #
# G2 — cek TEK BASINA yetmez
# --------------------------------------------------------------------------- #


async def test_G2_PORTFOYDEKI_cek_TEK_BASINA_yetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Kuralın İKİNCİ yarısı: *"çekin vadesi gelip de tahsil edilmeden"*."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(
        seeded_db, payment.id, taseron=True, evrak_durumu=FinancialInstrumentStatus.portfolio
    )

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


async def test_G2_POZITIF_KONTROL_cek_ODENINCE_gecer(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 YÖN BURADA ÖLÇÜLÜR: taşerona biz öderiz → VERİLEN çek → `paid`
    (`collected` DEĞİL; verilen çek tahsil edilmez)."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(
        seeded_db, payment.id, taseron=True, evrak_durumu=FinancialInstrumentStatus.paid
    )

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


@pytest.mark.parametrize(
    "durum", [FinancialInstrumentStatus.returned, FinancialInstrumentStatus.cancelled]
)
async def test_G2_KARSILIKSIZ_ya_da_IPTAL_cek_para_SAYILMAZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    durum: FinancialInstrumentStatus,
) -> None:
    """Beyaz liste fail-closed: terminal olmak para geçtiği anlamına GELMEZ."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, evrak_durumu=durum)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


# --------------------------------------------------------------------------- #
# 🔴 BULGU 5 — BAGSIZ cek/senet odemesi fail-closed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", [PaymentMethodKind.cheque, PaymentMethodKind.promissory_note])
async def test_BULGU5_BAGSIZ_cek_odemesi_hakedisi_ODETMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    method: PaymentMethodKind,
) -> None:
    """🔴 DENETİM BULGUSU 5.

    Kullanıcı `method='cheque'` yazıp `financial_instrument_id` GÖNDERMEZSE
    (form zorunlu tutmuyor) banka bakiyesi tanımı bunu KOŞULSUZ nakit sayar
    (ODM-1 D1) ve hakediş o an `paid` olurdu — kullanıcının kuralının birebir
    yasakladığı hâl. Kapı bakiyeninkinden DAR bir tanım kullanır ve bağsız
    kıymetli evrak ödemesini SAYMAZ.

    Banka bakiyesinin tanımına DOKUNULMADI: bu iki ayrı sorudur.
    """
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, method=method)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


@pytest.mark.parametrize("method", [PaymentMethodKind.transfer, PaymentMethodKind.cash])
async def test_BULGU5_POZITIF_KONTROL_bagsiz_HAVALE_ve_NAKIT_sayilir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    method: PaymentMethodKind,
) -> None:
    """🔴 Daraltma YALNIZ kıymetli evrak etiketlerini kapsar.

    Bu yarı olmadan bulgu 5'in düzeltmesi, "bağsız her ödemeyi reddet" hâline
    dönüşür ve kullanıcı havaleyle ödediği hakedişi de kapatamazdı.
    """
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, method=method)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


# --------------------------------------------------------------------------- #
# G3 — kismi odeme yetmez; SINIR (tam esit) gecer
# --------------------------------------------------------------------------- #


async def test_G3_KISMI_odeme_yetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Faturanın bir KURUŞ altı bile yetmez."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    yatan = await parayi_yatir(seeded_db, payment.id, taseron=True, fark=Decimal("-0.01"))
    assert yatan > 0, "kurulum anlamsız: kısmi ödeme sıfır olamaz"

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


async def test_G3_SINIR_tam_esit_tutar_GECER(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 SINIR: `<` yerine `<=` yazan mutant YALNIZ burada görünür."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, fark=Decimal("0.00"))

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


# --------------------------------------------------------------------------- #
# G4 — `paid` HALA TERMINAL
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("uc", ["submit", "approve", "reject", "mark-paid", "unapprove"])
async def test_G4_paid_hicbir_gecisin_KAYNAGI_degildir(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
    uc: str,
) -> None:
    """PARA-GERCEK bir KAPI ekledi, tabloya ÇİFT EKLEMEDİ."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _satirli_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        status=SubcontractorPaymentStatus.paid,
    )

    yanit = await client.post(
        f"{_UC}/{payment.id}/{uc}", json={"reason": "gerekçe metni"}, headers=admin_headers
    )

    assert yanit.status_code == 409, yanit.text


# --------------------------------------------------------------------------- #
# 🔴 BULGU 6 — IADE faturasinin odemesi CIKARILIR
# --------------------------------------------------------------------------- #


async def test_BULGU6_IADE_odemesi_gerceklesen_tutari_DUSURUR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 DENETİM BULGUSU 6.

    Asıl fatura tam tahsil edildi, sonra bir kısmı İADE faturasıyla geri döndü.
    İlk uygulama iade ödemesini tamamen ATLIYORDU ve kapı geçiyordu — kasada o
    para artık yokken. Aynı PR'ın ODM-2 mantığı bunun tersini söyler.
    """
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True)

    # Buraya kadar GECER — karsit kanit.
    on_kontrol = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert on_kontrol.status_code == 200, on_kontrol.text

    # Ayni kurulumu ikinci bir hakedis icin kurup bu kez IADE ekle.
    ikinci = await _satirli_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.approved,
    )
    await parayi_yatir(seeded_db, ikinci.id, taseron=True)
    brut = await hakedis_bruttu(seeded_db, ikinci.id, taseron=True)
    iade = await fatura_kes(
        seeded_db,
        ikinci.id,
        taseron=True,
        brut=brut / 2,
        document_type=InvoiceDocumentType.refund,
    )
    await odeme_yaz(seeded_db, iade, taseron=True, tutar=iade.total)

    yanit = await client.post(f"{_UC}/{ikinci.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED


# --------------------------------------------------------------------------- #
# Toplamanin KAPSAMI
# --------------------------------------------------------------------------- #


async def test_G6_bir_odeme_IKI_hakedise_birden_sayilamaz(
    seeded_db: AsyncSession,
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 ÇİFT SAYIM YAPISAL OLARAK İMKÂNSIZDIR — kilitle değil ŞEMAYLA."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    contract, _, _ = taseron_sozlesmesi
    birinci = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    ikinci = await _satirli_hakedis(
        seeded_db,
        hakedis_fabrikasi,
        contract,
        admin_kullanicisi,
        sequence_no=2,
        status=SubcontractorPaymentStatus.approved,
    )
    yatan = await parayi_yatir(seeded_db, birinci.id, taseron=True)

    birinci_toplam = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, birinci.id
    )
    ikinci_toplam = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, ikinci.id
    )

    assert birinci_toplam == yatan
    assert ikinci_toplam == Decimal("0")


async def test_FATURA_pending_iken_de_odeme_SAYILIR(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 Kapı faturanın DURUMUNA bakmaz, PARANIN hareketine bakar.

    Gelen fatura sisteme `pending` girer. Kapıya bir `approved` şartı da
    eklenseydi, parayı gerçekten ödemiş ama faturayı henüz onaylamamış kullanıcı
    hakedişi kapatamazdı.
    """
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, status=InvoiceStatus.pending)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


async def test_kapi_hakedisin_KENDI_odemesine_bakar(
    seeded_db: AsyncSession,
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Kaynağa bağlanmamış bir faturanın parası hakedişe SAYILMAZ."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    bagimsiz = await fatura_kes(seeded_db, payment.id, taseron=True, kaynaga_bagla=False)
    await odeme_yaz(seeded_db, bagimsiz, taseron=True, tutar=bagimsiz.total)

    toplam = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, payment.id
    )
    assert toplam == Decimal("0")


async def test_kapi_KAPSAM_disindaki_hakedisin_varligini_SIZDIRMAZ(
    client: AsyncClient,
    kisitli_headers: dict[str, str],
    gorunmeyen_hakedis,
) -> None:
    """Kapsam süzgeci kapıdan ÖNCE koşar: görünmeyen kayıt 404/403'tür."""
    yanit = await client.post(f"{_UC}/{gorunmeyen_hakedis}/mark-paid", headers=kisitli_headers)
    assert yanit.status_code in (403, 404), yanit.text
