"""🔴 KRIT-IADE — **İADE FATURASININ ÖDEMESİ TERS AKAR** (nakit bacağı).

`invoicing/posting.py`nin kardeş kusuru burada da ölçüldü:
`command grep -n "refund\\|document_type" app/modules/treasury/posting.py` →
**EXIT=1**. `lines_for` yalnız `invoice.direction`a bakıyordu, yani giden bir
İADE faturasının GERİ ÖDEMESİ bir TAHSİLAT gibi fişleniyordu: kasaya hiç
girmeyen para `102`ye BORÇ yazılıyor, kapanması gereken `120` bir kez daha
kapatılıyordu. Fiş DENGELİYDİ — mizanı ölçen hiçbir kapı bunu göremezdi.

Ürünün kendi kanonu bunun tersini ZATEN söylüyordu:
`treasury/realized.py::realized_total_for_source` iade ödemesini
`-Payment.amount` ile sayar. İki yüzey AYNI olguya bakıyor ve AYRIŞMIŞTI.

## 🔴 BEKÇİ YÖNÜ ÖLÇER

İddialar hesap NETİ üzerindedir (`102`nin borç neti, `120`nin borç neti). Bir
aynalamayı geri alan mutant dengeyi bozmaz ama bu netlerin işaretini çevirir.

## 🔴 KÜME BEKÇİSİ

`test_NAKIT_BACAGI_KUMESI...` evreni `InvoiceDirection` × `InvoiceDocumentType`
kartezyen çarpımından türetir — üründeki elle yazılmış bir listeden DEĞİL.
`InvoiceDocumentType`a yeni bir üye eklendiğinde, o üyenin para akışına bir
karar verilene kadar KIRMIZI kalır.
"""

import itertools
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import TreasuryValidationError
from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.treasury import payments_service, posting
from app.modules.treasury.models import (
    BankAccount,
    BankAccountType,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    Payment,
    PaymentMethodKind,
)
from app.modules.treasury.schemas import PaymentCreate
from tests.modules.treasury._mu3c import (
    KOD_ALICILAR,
    KOD_ALINAN_CEK,
    KOD_BANKA,
    KOD_SATICILAR,
    KOD_VERILEN_CEK,
    TARIH,
    aktor,
    bacaklar,
    banka_hesabi,
    canli_fis,
    esleme_kur,
    fatura,
    hesap_neti,
)

#: Faturanın ödeme yazılabilir durumu — yöne göre.
_DURUM = {
    InvoiceDirection.outgoing: InvoiceStatus.sent,
    InvoiceDirection.incoming: InvoiceStatus.approved,
}


async def _ode(
    seeded_db: AsyncSession,
    user_factory,
    invoice: Invoice,
    account: BankAccount,
    amount: str,
    *,
    instrument: FinancialInstrument | None = None,
) -> Payment:
    payment, _detay = await payments_service.create_payment(
        seeded_db,
        await aktor(seeded_db, user_factory),
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer if instrument is None else PaymentMethodKind.cheque,
            amount=Decimal(amount),
            paid_on=TARIH,
            financial_instrument_id=None if instrument is None else instrument.id,
        ),
    )
    return payment


async def _cek(
    seeded_db: AsyncSession, direction: FinancialInstrumentDirection, amount: str
) -> FinancialInstrument:
    instrument = FinancialInstrument(
        instrument_kind=FinancialInstrumentKind.cheque,
        direction=direction,
        serial_no="0123456789",
        drawer_name="Güneşkent A.Ş.",
        issue_date=TARIH,
        due_date=TARIH,
        amount=Decimal(amount),
        status=FinancialInstrumentStatus.portfolio,
    )
    seeded_db.add(instrument)
    await seeded_db.flush()
    return instrument


# --------------------------------------------------------------------------- #
# UÇTAN UCA — İADE ÖDEMESİNİN BACAKLARI
# --------------------------------------------------------------------------- #


async def test_GIDEN_IADE_odemesi_PARAYI_CIKARIR(seeded_db: AsyncSession, user_factory):
    """🔴 Satış iadesinin geri ödemesi: `120` BORÇ, `102` ALACAK.

    Kusurlu hâlde tam TERSİ yazılıyordu ve banka hesabı, hiç girmemiş bir
    parayla şişiyordu.
    """
    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db)
    iade = await fatura(
        seeded_db,
        await aktor(seeded_db, user_factory),
        direction=InvoiceDirection.outgoing,
        total="480.00",
        status=_DURUM[InvoiceDirection.outgoing],
        document_type=InvoiceDocumentType.refund,
    )

    payment = await _ode(seeded_db, user_factory, iade, hesap, "480.00")

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert entry is not None, "iade ödemesi FİŞSİZ kaldı"
    assert await bacaklar(seeded_db, entry) == [
        (KOD_ALICILAR, "480.00", "0.00"),
        (KOD_BANKA, "0.00", "480.00"),
    ]
    assert entry.description.startswith("İade ödemesi "), entry.description


async def test_GELEN_IADE_odemesi_PARAYI_GETIRIR(seeded_db: AsyncSession, user_factory):
    """Alış iadesinde para GERİ GELİR: `102` BORÇ, `320` ALACAK."""
    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db)
    iade = await fatura(
        seeded_db,
        await aktor(seeded_db, user_factory),
        direction=InvoiceDirection.incoming,
        total="480.00",
        status=_DURUM[InvoiceDirection.incoming],
        document_type=InvoiceDocumentType.refund,
    )

    payment = await _ode(seeded_db, user_factory, iade, hesap, "480.00")

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_BANKA, "480.00", "0.00"),
        (KOD_SATICILAR, "0.00", "480.00"),
    ]
    assert entry.description.startswith("İade tahsilatı "), entry.description


async def test_SATIS_ve_IADESI_birlikte_CARIYI_ve_NAKDI_dogru_birakir(
    seeded_db: AsyncSession, user_factory
):
    """🔴 KABUL KAPISI — 1.200 tahsil + 480 iade ödemesi → `102` neti **720**.

    Kusurlu hâlde `102` 1.680 (iki giriş) ve `120` −480 gösteriyordu; iki fiş de
    dengeliydi. Bekçi bu yüzden NETİ okur.
    """
    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db)
    creator = await aktor(seeded_db, user_factory)
    satis = await fatura(
        seeded_db,
        creator,
        direction=InvoiceDirection.outgoing,
        total="1200.00",
        status=InvoiceStatus.sent,
    )
    iade = await fatura(
        seeded_db,
        creator,
        direction=InvoiceDirection.outgoing,
        total="480.00",
        status=InvoiceStatus.sent,
        document_type=InvoiceDocumentType.refund,
    )

    await _ode(seeded_db, user_factory, satis, hesap, "1200.00")
    await _ode(seeded_db, user_factory, iade, hesap, "480.00")

    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("720.00")
    # `120`: satış fişi açmadı (bu dosya fatura fişi yazmaz), iki ÖDEME fişi
    # onu −1.200 ve +480 oynattı → net −720.
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("-720.00")


# --------------------------------------------------------------------------- #
# 🔴 KÜME BEKÇİSİ — EVREN ENUM'LARDAN TÜRER
# --------------------------------------------------------------------------- #


def _sahte(direction: InvoiceDirection, document_type: InvoiceDocumentType) -> Invoice:
    """`lines_for`un SAF kararını ölçmek için gereken iki kolon. DB'ye YAZILMAZ."""
    return Invoice(direction=direction, document_type=document_type)


#: 🔴 ELLE yazılan beklenti — `(yön, iade mi) → (nakit tarafı, cari rolü)`.
#: Üründen türetilseydi karar ters çevrildiğinde test onunla birlikte dönerdi.
BEKLENEN_NAKIT: dict[tuple[InvoiceDirection, bool], str] = {
    (InvoiceDirection.outgoing, False): "B",  # tahsilat: para girer
    (InvoiceDirection.outgoing, True): "A",  # satış iadesi: para çıkar
    (InvoiceDirection.incoming, False): "A",  # ödeme: para çıkar
    (InvoiceDirection.incoming, True): "B",  # alış iadesi: para geri gelir
}


def test_NAKIT_BACAGI_KUMESI_iki_enumun_KARTEZYEN_carpimindan_TURETILIR():
    """🔴 Evren iki ENUM'dan türer; yeni bir belge tipi bu kapıyı KIRMIZI yapar.

    İddia bacağın TARAFI üzerindedir, tutarı üzerinde değil: kusurlu fiş
    dengeliydi ve tutarları karşılaştıran bir kapı onu göremiyordu.
    """
    evren = list(itertools.product(InvoiceDirection, InvoiceDocumentType))
    assert len(evren) == len(InvoiceDirection) * len(InvoiceDocumentType)

    hesap = BankAccount(bank_name="Ziraat", account_type=BankAccountType.checking)
    odeme = Payment(amount=Decimal("100.00"), financial_instrument_id=None)

    for direction, document_type in evren:
        invoice = _sahte(direction, document_type)
        satirlar = posting.lines_for(odeme, invoice, hesap)
        nakit = next(s for s in satirlar if s.role_key == posting.ROLE_BANK)
        cari_rol = (
            posting.ROLE_RECEIVABLE
            if direction is InvoiceDirection.outgoing
            else posting.ROLE_PAYABLE
        )
        cari = next(s for s in satirlar if s.role_key == cari_rol)

        beklenen = BEKLENEN_NAKIT[(direction, document_type is InvoiceDocumentType.refund)]
        olculen = "B" if nakit.debit > 0 else "A"
        assert olculen == beklenen, (
            f"{direction.value}/{document_type.value} ödemesinin NAKİT bacağı yanlış tarafta: "
            f"ölçülen={olculen} beklenen={beklenen}"
        )
        # Cari bacağı DAİMA nakdin karşı tarafındadır (iki bacaklı fiş).
        assert (cari.debit > 0) is not (nakit.debit > 0)
        # 🔴 Cari ROLÜ belge tipinden ETKİLENMEZ: iade de aynı cariyi kapatır.
        assert cari.role_key == cari_rol


def test_CEK_ARA_HESABI_KUMESI_de_PARANIN_AKISINDAN_turer():
    """🔴 `101`/`103` seçimi de `document_type`a duyarlı olmalıdır.

    KRIT-IADE öncesi `_INSTRUMENT_ROLE` yalnız `direction`a bakıyordu: giden bir
    iadenin geri verilen çeki `101 Alınan Çekler`e yazılırdı — elde olmayan bir
    çek portföyden düşerdi.
    """
    beklenen = {
        (InvoiceDirection.outgoing, False): posting.ROLE_INSTRUMENT_RECEIVABLE,
        (InvoiceDirection.outgoing, True): posting.ROLE_INSTRUMENT_PAYABLE,
        (InvoiceDirection.incoming, False): posting.ROLE_INSTRUMENT_PAYABLE,
        (InvoiceDirection.incoming, True): posting.ROLE_INSTRUMENT_RECEIVABLE,
    }
    for direction, document_type in itertools.product(InvoiceDirection, InvoiceDocumentType):
        invoice = _sahte(direction, document_type)
        # Bağın VARLIĞI `payment_cash_role`un TEK girdisidir (D1: bağ, `method`
        # etiketi DEĞİL); hangi kimlik olduğu önemsizdir.
        odeme = Payment(amount=Decimal("100.00"), financial_instrument_id=uuid.uuid4())
        assert (
            posting.payment_cash_role(odeme, invoice, None)
            == beklenen[(direction, document_type is InvoiceDocumentType.refund)]
        ), f"{direction.value}/{document_type.value} ara hesabı yanlış"


# --------------------------------------------------------------------------- #
# 🔴 BAĞ KAPISI — FIN-PAY K3 de İADEYİ BİLMELİDİR
# --------------------------------------------------------------------------- #


async def test_GIDEN_IADEYE_VERILEN_cek_baglanir_ALINAN_cek_422(
    seeded_db: AsyncSession, user_factory
):
    """🔴 Giden iadenin parası DIŞARI akar → bağlanacak evrak VERİLEN çektir.

    Kapı `direction`a bakmaya devam etseydi kullanıcıdan ALINAN bir çek
    isterdi; o ödeme `101`e ALACAK yazılır ve elde olmayan bir çek portföyden
    düşerdi. Fail-closed olan taraf 422'dir.
    """
    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db)
    iade = await fatura(
        seeded_db,
        await aktor(seeded_db, user_factory),
        direction=InvoiceDirection.outgoing,
        total="480.00",
        status=InvoiceStatus.sent,
        document_type=InvoiceDocumentType.refund,
    )

    alinan = await _cek(seeded_db, FinancialInstrumentDirection.received, "480.00")
    with pytest.raises(TreasuryValidationError):
        await _ode(seeded_db, user_factory, iade, hesap, "480.00", instrument=alinan)

    verilen = await _cek(seeded_db, FinancialInstrumentDirection.issued, "480.00")
    payment = await _ode(seeded_db, user_factory, iade, hesap, "480.00", instrument=verilen)

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_ALICILAR, "480.00", "0.00"),
        (KOD_VERILEN_CEK, "0.00", "480.00"),
    ]


async def test_NORMAL_faturanin_bag_kapisi_DEGISMEDI(seeded_db: AsyncSession, user_factory):
    """Regresyon: iade OLMAYAN faturada FIN-PAY K3 ve `101` aynen durur.

    Bu iddia olmasaydı, kapıyı iadeye duyarlı yapan değişiklik normal faturayı
    da sessizce oynatabilirdi.
    """
    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db)
    satis = await fatura(
        seeded_db,
        await aktor(seeded_db, user_factory),
        direction=InvoiceDirection.outgoing,
        total="480.00",
        status=InvoiceStatus.sent,
    )

    verilen = await _cek(seeded_db, FinancialInstrumentDirection.issued, "480.00")
    with pytest.raises(TreasuryValidationError):
        await _ode(seeded_db, user_factory, satis, hesap, "480.00", instrument=verilen)

    alinan = await _cek(seeded_db, FinancialInstrumentDirection.received, "480.00")
    payment = await _ode(seeded_db, user_factory, satis, hesap, "480.00", instrument=alinan)

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_ALINAN_CEK, "480.00", "0.00"),
        (KOD_ALICILAR, "0.00", "480.00"),
    ]


# --------------------------------------------------------------------------- #
# 🔴 HAZİNE BAKİYESİ — YEVMİYE İLE MUTABAKAT (ÜÇÜNCÜ KARDEŞ KUSUR)
# --------------------------------------------------------------------------- #


async def test_BAKIYE_ile_YEVMIYE_iade_iceren_kumede_de_TUTAR(
    seeded_db: AsyncSession, user_factory
):
    """🔴 `balance.inflow_condition()` de `document_type` KÖRÜYDÜ.

    Ölçüm: `command grep -n "document_type" app/modules/treasury/balance.py` →
    **EXIT=1**. Giden bir İADE faturasının geri ödemesi banka bakiyesini
    ARTIRIYORDU — kasadan çıkan para girmiş gibi sayılıyordu ve kart tek bir
    sayı bastığı için kusur ekranda GÖRÜNMÜYORDU.

    Bu test, iki taban arasındaki mutabakatı iade İÇEREN bir kümede kurar:

        Hazine bakiyesi (`balance`, `payments`ten türer)
            == `102 Bankalar` neti (yevmiyeden türer)

    İki yamadan YALNIZ BİRİ yapılsaydı (fiş aynalanır, bakiye aynalanmazsa ya
    da tersi) bu iddia KIRMIZI olurdu — tek yönlü bir yamayı yakalayan başka
    kapı yok.
    """
    from app.modules.treasury import balance as balance_module

    await esleme_kur(seeded_db)
    hesap = await banka_hesabi(seeded_db, opening_balance="0.00")
    creator = await aktor(seeded_db, user_factory)
    satis = await fatura(
        seeded_db,
        creator,
        direction=InvoiceDirection.outgoing,
        total="1200.00",
        status=InvoiceStatus.sent,
    )
    iade = await fatura(
        seeded_db,
        creator,
        direction=InvoiceDirection.outgoing,
        total="480.00",
        status=InvoiceStatus.sent,
        document_type=InvoiceDocumentType.refund,
    )
    alis_iadesi = await fatura(
        seeded_db,
        creator,
        direction=InvoiceDirection.incoming,
        total="200.00",
        status=InvoiceStatus.approved,
        document_type=InvoiceDocumentType.refund,
    )

    await _ode(seeded_db, user_factory, satis, hesap, "1200.00")
    await _ode(seeded_db, user_factory, iade, hesap, "480.00")
    await _ode(seeded_db, user_factory, alis_iadesi, hesap, "200.00")

    # Beklenen: +1200 − 480 + 200 = 920.
    bakiyeler = await balance_module.balances_for(seeded_db, [hesap.id])
    assert bakiyeler[hesap.id] == Decimal("920.00"), (
        "Hazine bakiyesi iade ödemesini YANLIŞ yönde saydı"
    )
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("920.00"), (
        "yevmiyedeki `102` neti ile Hazine bakiyesi AYRIŞTI"
    )
