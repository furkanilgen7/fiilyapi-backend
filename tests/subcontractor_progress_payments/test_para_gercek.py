"""PARA-GERCEK — `mark-paid` artık GERÇEKLEŞMİŞ para ister (taşeron ailesi).

Kullanıcının kuralı birebir: *"Nakit olarak görmeden veya çekin vadesi gelip de
tahsil edilmeden 'ödendi' gözükmemesi gerekiyor."* Canlıda ÜÇ taşeron hakedişi
arkalarında tek kuruş ödeme olmadan `paid` damgası taşıyordu.

## Her iddianın İKİ YARISI vardır

🔴 Bu dosyadaki her kapı testi ÇİFTTİR: *reddedilen* hâlin yanında mutlaka
*geçen* hâl de vardır. Yalnız reddi ölçen bir test, kapı "her şeyi reddet"
hâline geldiğinde de YEŞİL kalırdı — yani "kural işliyor"u değil "hiçbir şey
olmuyor"u kanıtlardı.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import InvoiceDocumentType, InvoiceStatus
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
)
from app.modules.treasury.models import FinancialInstrumentStatus
from app.modules.treasury.realized import PAYMENT_NOT_REALIZED
from app.modules.users.models import User
from tests._para_gercek import fatura_kes, hakedis_neti, odeme_yaz, parayi_yatir
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
# G1 — ödemesiz hakediş `paid` OLAMAZ (+ pozitif kontrol)
# --------------------------------------------------------------------------- #


async def test_G1_ODEMESIZ_hakedis_odendi_isaretlenemez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Canlıdaki kusurun ta kendisi: arkasında hiçbir para hareketi olmayan
    onaylı hakediş tek tıkla `paid` olabiliyordu."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text
    assert yanit.json()["detail"] == PAYMENT_NOT_REALIZED
    await seeded_db.refresh(payment)
    assert payment.status is SubcontractorPaymentStatus.approved
    assert payment.paid_at is None


async def test_G1_POZITIF_KONTROL_yeterli_gerceklesmis_odeme_GECER(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 İddianın ikinci yarısı — bu olmadan G1, kapının HER ŞEYİ reddettiği
    (yani ekranın tamamen kilitlendiği) hâlde de yeşil kalırdı."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["status"] == "paid"
    assert yanit.json()["paid_at"] is not None


# --------------------------------------------------------------------------- #
# G2 — çek TEK BAŞINA yetmez; tahsil/ödeme damgası gerekir
# --------------------------------------------------------------------------- #


async def test_G2_PORTFOYDEKI_cek_TEK_BASINA_yetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Kuralın İKİNCİ yarısı: *"çekin vadesi gelip de tahsil edilmeden"*.

    Ödeme kaydı VARDIR ve tutarı tamdır — ama bağlı çek hâlâ `portfolio`dadır,
    yani para henüz hareket etmemiştir. Ödeme satırının varlığına bakan bir
    kapı burada YANILIRDI.
    """
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
    """🔴 YÖN BURADA ÖLÇÜLÜR: taşerona biz öderiz, yani evrak VERİLEN çektir ve
    onun "para geçti" durumu `paid`tir (`collected` DEĞİL — verilen çek tahsil
    edilmez). Yönü ters çeviren bir uygulama bu testi geçemez."""
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
    """Beyaz liste fail-closed'dır: terminal olmak para geçtiği anlamına GELMEZ."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True, evrak_durumu=durum)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


# --------------------------------------------------------------------------- #
# G3 — kısmi ödeme yetmez; SINIR (tam eşit) geçer
# --------------------------------------------------------------------------- #


async def test_G3_KISMI_odeme_yetmez(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Netin bir KURUŞ altı bile yetmez — eşiği tamamen kaldıran ya da
    `>= net` yerine `> 0` bakan bir uygulama burada kırmızıya döner."""
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
    """🔴 SINIR DEĞERİ AYRICA ölçülür: karşılaştırmayı `<`ten `<=`ye çeviren
    mutant (yani tam ödenmiş hakedişi de reddeden hâl) YALNIZ bu testte görünür.
    G1'in pozitif kontrolü netin ÜSTÜNDE kalsaydı bu mutant hayatta kalırdı."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    net = await hakedis_neti(seeded_db, payment.id, taseron=True)
    yatan = await parayi_yatir(seeded_db, payment.id, taseron=True, fark=Decimal("0.00"))
    assert yatan == net, "kurulum sınırı kurmadı"

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


# --------------------------------------------------------------------------- #
# G4 — `paid` HÂLÂ TERMİNAL (kapı İLERİ yönde, ters geçiş AÇILMADI)
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
    """🔴 PARA-GERCEK bir KAPI ekledi, tabloya ÇİFT EKLEMEDİ.

    Ödenmiş hakedişin geri dönüşü yoktur (K7) ve bu dilim o kanonu DELMEDİ.
    Tabloya `paid → approved` ekleyen bir mutant burada kırmızıya döner.
    """
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
# Toplamanın KAPSAMI — hangi para sayılır, hangisi sayılmaz
# --------------------------------------------------------------------------- #


async def test_IADE_faturasinin_odemesi_hakedisi_ODETMEZ(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """İade faturası aynı kaynağa bağlanabilir (kısmi UNIQUE indeks onu dışlar)
    ama parası TERS yöne akar. Sayılsaydı bir iade tahsilatı, taşerona hiç
    ödenmemiş bir borcu "ödenmiş" gösterirdi."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    net = await hakedis_neti(seeded_db, payment.id, taseron=True)
    iade = await fatura_kes(
        seeded_db,
        payment.id,
        taseron=True,
        tutar=net,
        document_type=InvoiceDocumentType.refund,
    )
    await odeme_yaz(seeded_db, payment.id, taseron=True, tutar=net, fatura=iade)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 409, yanit.text


async def test_G6_bir_odeme_IKI_hakedise_birden_sayilamaz(
    seeded_db: AsyncSession,
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 ÇİFT SAYIM YAPISAL OLARAK İMKÂNSIZDIR — kilitle değil ŞEMAYLA.

    Bir ödeme tek faturanındır (`payments.invoice_id` NOT NULL), bir faturada
    en fazla BİR kaynak kolonu dolabilir (`ck_invoices_single_source`) ve bir
    kaynağa en fazla BİR asıl fatura bağlanabilir (`SOURCE_UNIQUE_INDEXES`).
    Bu test o zincirin ucundaki gözlemi kilitler: aynı para ikinci hakedişte
    GÖRÜNMEZ.
    """
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


# --------------------------------------------------------------------------- #
# ÜRÜN YOLU — kullanıcının GERÇEKTEN izleyeceği adımlar, GERÇEK uçlarla
# --------------------------------------------------------------------------- #


async def test_UCTAN_UCA_gercek_uclarla_hakedis_odenebiliyor(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """🔴 KAPI KULLANICIYI KİLİTLEMİYOR — üç GERÇEK uçla kanıtlanır.

    Yardımcıların (`tests/_para_gercek.py`) ORM düzeyinde kurduğu zincirin
    ürünün KENDİ uçlarıyla da kurulabildiğini gösterir. Bu test olmadan kapı
    "teoride doğru ama pratikte ulaşılamaz" olabilirdi ve bunu hiçbir bekçi
    yakalamazdı:

        1. `POST /invoices`                    — hakedişe bağlı GELEN fatura
        2. `POST /invoices/{id}/payments`      — ödeme kaydı (para hareketi)
        3. `POST …/mark-paid`                  — artık GEÇER
    """
    from app.modules.accounting.models import JournalSourceType
    from app.modules.treasury.posting import PAYMENT_POSTING_RULES
    from tests._hakedis_esleme import esleme_kur

    # 🔴 Ödeme ucu yevmiye fişi yazar ve hesap eşlemesi ARANIR. Canlıda bu
    #    satırları migration tohumlar; test kümesi migration KOŞMAZ, bu yüzden
    #    ÜRÜN demetinden kurulur (elle yazılsaydı demet bozulunca test yeşil kalırdı).
    await esleme_kur(seeded_db, JournalSourceType.payment, PAYMENT_POSTING_RULES)

    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    net = await hakedis_neti(seeded_db, payment.id, taseron=True)

    # Kapı, para yatmadan ÖNCE gerçekten kapalıdır.
    erken = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert erken.status_code == 409, erken.text

    fatura = await client.post(
        "/invoices",
        json={
            "direction": "incoming",
            "invoice_no": f"TS{uuid.uuid4().hex[:10].upper()}",
            "document_type": "einvoice",
            "issue_date": "2026-02-01",
            "party_name": "Taşeron A.Ş.",
            "subcontractor_progress_payment_id": str(payment.id),
            "lines": [
                {
                    "description": "Hakediş bedeli",
                    "quantity": "1",
                    "unit": "adet",
                    "unit_price": str(net),
                    "vat_rate": "0",
                }
            ],
        },
        headers=admin_headers,
    )
    assert fatura.status_code in (200, 201), fatura.text
    fatura_id = fatura.json()["id"]
    assert Decimal(str(fatura.json()["total"])) == net

    hesap = await client.post(
        "/bank-accounts",
        json={"bank_name": "Uçtan Uca Bank", "account_type": "checking", "iban": None},
        headers=admin_headers,
    )
    assert hesap.status_code in (200, 201), hesap.text

    odeme = await client.post(
        f"/invoices/{fatura_id}/payments",
        json={
            "bank_account_id": hesap.json()["id"],
            "method": "transfer",
            "amount": str(net),
            "paid_on": "2026-02-05",
        },
        headers=admin_headers,
    )
    assert odeme.status_code in (200, 201), odeme.text

    sonuc = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)
    assert sonuc.status_code == 200, sonuc.text
    assert sonuc.json()["status"] == "paid"


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
    hakedişi kapatamazdı — kullanıcının kuralı ödemeyle ilgilidir, evrak
    onayıyla değil.
    """
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    net = await hakedis_neti(seeded_db, payment.id, taseron=True)
    fatura = await fatura_kes(
        seeded_db, payment.id, taseron=True, tutar=net, status=InvoiceStatus.pending
    )
    await odeme_yaz(seeded_db, payment.id, taseron=True, tutar=net, fatura=fatura)

    yanit = await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    assert yanit.status_code == 200, yanit.text


async def test_kapi_KAPSAM_disindaki_hakedisin_varligini_SIZDIRMAZ(
    client: AsyncClient,
    kisitli_headers: dict[str, str],
    gorunmeyen_hakedis,
) -> None:
    """Kapsam süzgeci kapıdan ÖNCE koşar: görünmeyen kayıt 404'tür, 409 değil —
    yoksa 409 metni o hakedişin VAR OLDUĞUNU ve ödenmediğini sızdırırdı."""
    yanit = await client.post(f"{_UC}/{gorunmeyen_hakedis}/mark-paid", headers=kisitli_headers)
    assert yanit.status_code in (403, 404), yanit.text


async def test_kapi_hakedisin_KENDI_odemesine_bakar(
    seeded_db: AsyncSession,
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Faturasız/bağsız bir ödeme (başka bir faturanın parası) hakedişe SAYILMAZ."""
    from app.modules.invoicing.models import Invoice
    from app.modules.treasury.realized import realized_total_for_source

    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    # Hiçbir kaynağa bağlanmamış bir faturaya ödeme yaz.
    bagimsiz = await fatura_kes(seeded_db, payment.id, taseron=True, tutar=Decimal("100.00"))
    bagimsiz.subcontractor_progress_payment_id = None
    await seeded_db.flush()
    await odeme_yaz(seeded_db, payment.id, taseron=True, tutar=Decimal("100.00"), fatura=bagimsiz)

    toplam = await realized_total_for_source(
        seeded_db, Invoice.subcontractor_progress_payment_id, payment.id
    )
    assert toplam == Decimal("0")


async def test_hakedis_ODENDIKTEN_sonra_kayit_hala_gorunur(
    client: AsyncClient,
    seeded_db: AsyncSession,
    admin_headers: dict[str, str],
    admin_kullanicisi: User,
    taseron_sozlesmesi,
    hakedis_fabrikasi,
) -> None:
    """Damga düştükten sonra kaydın kendisi bozulmaz (regresyon emniyeti)."""
    contract, _, _ = taseron_sozlesmesi
    payment = await _onayli_hakedis(seeded_db, hakedis_fabrikasi, contract, admin_kullanicisi)
    await parayi_yatir(seeded_db, payment.id, taseron=True)
    await client.post(f"{_UC}/{payment.id}/mark-paid", headers=admin_headers)

    taze = (
        await seeded_db.execute(
            select(SubcontractorProgressPayment).where(
                SubcontractorProgressPayment.id == payment.id
            )
        )
    ).scalar_one()
    assert taze.status is SubcontractorPaymentStatus.paid
    assert taze.paid_at is not None
