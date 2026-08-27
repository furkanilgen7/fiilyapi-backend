"""ODM-1 D2 — NAKDİN TANIMI: portföydeki çek nakit DEĞİLDİR.

    ödeme nakde girer  ⟺  financial_instrument_id IS NULL
                          VEYA bağlı enstrüman status ∈ {collected, paid}

NEDEN BU TESTLER: bakiye SAKLANMADIĞI için hiçbir kolon onu doğrulamaz. Bir
çekle yapılan tahsilatta ödeme satırı ÇEKİN ALINDIĞI GÜN girilir (cari o an
kapanır) ama para bankaya çek TAHSİL EDİLİNCE girer. Süzgeç olmasaydı kart,
henüz tahsil edilmemiş çekleri nakit gibi gösterir ve kullanıcı elinde olmayan
parayı harcanabilir sanırdı.

Ölçülen beş kusur sınıfı:

1. **K-IKIZ1 (kritik).** "Tahsil edilince girer" testi TEK BAŞINA yazılsaydı,
   süzgeci hiç uygulamayan (yani HER ZAMAN sayan) bozuk kod da yeşil geçerdi.
   Bu yüzden portföy hâli ve tahsil hâli AYRI AYRI, ikisi de iddia edilir.
2. **TERMİNAL OLUMSUZ DURUMLAR.** `returned` (karşılıksız) / `cancelled` bir
   çeke bağlı ödeme bakiyeye HİÇBİR ZAMAN girmez — beyaz liste değil de
   "portfolio hariç hepsi" yazan bir uygulama bu testte kırmızı verir.
3. **OUTER JOIN.** Enstrüman bağı NULLABLE'dır ve canlıdaki ödemelerin ezici
   çoğunluğu bağsızdır. `join_instrument` INNER olsaydı o satırların HEPSİ
   sorgudan düşer ve nakit sessizce SIFIRLANIRDI.
4. **D1 — TETİKLEYİCİ BAĞDIR, `method` ETİKETİ DEĞİL.** `method='cheque'` ama
   bağsız ödeme NAKİTTİR. Bu, tasarımın en tartışmalı kararıdır (gerekçesi
   `balance.cash_realized_condition` docstring'inde); bekçisiz kalsaydı biri
   yarın süzgeci `method`e bağlar ve canlı bakiyeler SESSİZCE değişirdi.
5. **İKİ YÜZEY PARİTESİ.** Bakiye kartı (`balance`) ile nakit akışı grafiği
   (`cash_flow`) AYNI çek için AYNI nakdi göstermelidir. İki yerde iki ayrı
   yazım olsaydı kullanıcı aynı ekranda iki farklı gerçek okurdu; parite tek
   testte, AYNI veri üzerinde ölçülür.

Durum geçişleri burada `instruments.service.change_status` ile DEĞİL, kolona
doğrudan yazılarak kurulur: bu dosya nakdin TANIMINI ölçer, geçiş kapısını
değil (o `test_fin1_transitions.py`nin işidir) — servis üzerinden gidilseydi
kırmızı, tanımı değil geçiş kurallarını gösterebilirdi.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoicing.models import (
    Invoice,
    InvoiceDirection,
    InvoiceDocumentType,
    InvoiceStatus,
)
from app.modules.treasury import balance, cash_flow
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
from tests._iban import tr_iban

pytestmark = pytest.mark.asyncio

TARIH = date(2026, 6, 15)
YIL, AY = TARIH.year, TARIH.month
TUTAR = Decimal("50000.00")
SIFIR = Decimal("0.00")


@pytest.fixture
async def kullanici_id(seeded_db: AsyncSession, user_factory) -> uuid.UUID:
    user = await user_factory(email="odm1@fiil.co", password="parola1234", role_key="system_admin")
    return user.id


@pytest.fixture
def hesap_fabrikasi(seeded_db: AsyncSession):
    sayac = {"n": 0}

    async def _create(opening_balance: str = "0.00") -> BankAccount:
        sayac["n"] += 1
        account = BankAccount(
            bank_name=f"ODM Bank {sayac['n']}",
            account_type=BankAccountType.checking,
            iban=tr_iban(400 + sayac["n"]),
            opening_balance=Decimal(opening_balance),
        )
        seeded_db.add(account)
        await seeded_db.flush()
        return account

    return _create


@pytest.fixture
def cek_fabrikasi(seeded_db: AsyncSession):
    sayac = {"n": 0}

    async def _create(
        direction: FinancialInstrumentDirection = FinancialInstrumentDirection.received,
        status: FinancialInstrumentStatus = FinancialInstrumentStatus.portfolio,
        amount: Decimal = TUTAR,
    ) -> FinancialInstrument:
        sayac["n"] += 1
        cek = FinancialInstrument(
            instrument_kind=FinancialInstrumentKind.cheque,
            direction=direction,
            serial_no=f"ODM{sayac['n']:07d}",
            drawer_name="Güneşkent A.Ş.",
            issue_date=TARIH,
            due_date=date(2026, 9, 15),
            amount=amount,
            status=status,
        )
        seeded_db.add(cek)
        await seeded_db.flush()
        return cek

    return _create


@pytest.fixture
def odeme_fabrikasi(seeded_db: AsyncSession, kullanici_id: uuid.UUID):
    """Fatura + ona bağlı ödeme; enstrüman bağı ve `method` İSTEĞE BAĞLI.

    Fatura `total`i bilinçli yüksektir: bu dosya aşırı tahsilat denetimini
    değil, YALNIZ nakdin tanımını ölçer.
    """
    sayac = {"n": 0}

    async def _create(
        account: BankAccount,
        amount: Decimal = TUTAR,
        direction: InvoiceDirection = InvoiceDirection.outgoing,
        instrument: FinancialInstrument | None = None,
        method: PaymentMethodKind = PaymentMethodKind.transfer,
        paid_on: date = TARIH,
    ) -> Payment:
        sayac["n"] += 1
        invoice = Invoice(
            direction=direction,
            invoice_no=f"ODM{sayac['n']:09d}",
            document_type=InvoiceDocumentType.einvoice,
            status=InvoiceStatus.sent,
            issue_date=date(2026, 6, 1),
            party_name="Test Karşı Taraf",
            subtotal=Decimal("1000000.00"),
            advance_amount=SIFIR,
            retention_amount=SIFIR,
            tax_base=Decimal("1000000.00"),
            vat_amount=SIFIR,
            withholding_amount=SIFIR,
            total=Decimal("1000000.00"),
            created_by_id=kullanici_id,
        )
        seeded_db.add(invoice)
        await seeded_db.flush()
        payment = Payment(
            invoice_id=invoice.id,
            bank_account_id=account.id,
            method=method,
            amount=amount,
            paid_on=paid_on,
            financial_instrument_id=None if instrument is None else instrument.id,
            created_by_id=kullanici_id,
        )
        seeded_db.add(payment)
        await seeded_db.flush()
        return payment

    return _create


async def _bakiye(session: AsyncSession, hesap: BankAccount) -> Decimal:
    return (await balance.balances_for(session, [hesap.id]))[hesap.id]


# --- 1. K-IKIZ1: portföydeyken HİÇ, tahsil edilince TAM ---------------------


async def test_PORTFOYDEKI_ceke_bagli_odeme_bakiyeye_HIC_GIRMEZ(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 K-IKIZ1'in birinci yarısı — süzgecin VARLIĞINI kanıtlayan taraf.

    Bu test olmasaydı, `cash_realized_condition`ı hiç uygulamayan (her ödemeyi
    sayan) bir uygulama ikiz testinin ötekini geçer ve kusur canlıya çıkardı.
    """
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    cek = await cek_fabrikasi(status=FinancialInstrumentStatus.portfolio)
    await odeme_fabrikasi(hesap, instrument=cek)

    assert await _bakiye(seeded_db, hesap) == Decimal("1000.00")


async def test_TAHSIL_EDILEN_ceke_bagli_odeme_bakiyeye_GIRER(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 K-IKIZ1'in ikinci yarısı — süzgecin ÇOK GENİŞ olmadığını kanıtlar.

    Yalnız portföy testi yazılsaydı, çeke bağlı HER ödemeyi sonsuza dek nakit
    saymayan (yani parayı hiç göstermeyen) bozuk kod da yeşil geçerdi.
    """
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    cek = await cek_fabrikasi(status=FinancialInstrumentStatus.portfolio)
    await odeme_fabrikasi(hesap, instrument=cek)

    cek.status = FinancialInstrumentStatus.collected
    await seeded_db.flush()

    assert await _bakiye(seeded_db, hesap) == Decimal("1000.00") + TUTAR


async def test_ODENEN_verilen_ceke_bagli_odeme_bakiyeden_DUSER(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """`paid` damgası ÇIKIŞ yönünde de nakdi serbest bırakır.

    Yalnız `collected` sınanıp `paid` atlansaydı, beyaz listeden `paid`i
    düşüren bir uygulama yeşil kalır ve verilen çekler ödendikleri hâlde
    bakiyeden hiç düşmezdi (bakiye kalıcı olarak ŞİŞİK görünürdü).
    """
    hesap = await hesap_fabrikasi(opening_balance="80000.00")
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.issued)
    await odeme_fabrikasi(hesap, direction=InvoiceDirection.incoming, instrument=cek)

    assert await _bakiye(seeded_db, hesap) == Decimal("80000.00")

    cek.status = FinancialInstrumentStatus.paid
    await seeded_db.flush()

    assert await _bakiye(seeded_db, hesap) == Decimal("80000.00") - TUTAR


# --- 2. Terminal olumsuz durumlar ------------------------------------------


@pytest.mark.parametrize(
    "durum",
    [FinancialInstrumentStatus.returned, FinancialInstrumentStatus.cancelled],
)
async def test_KARSILIKSIZ_VE_IPTAL_cek_bakiyeye_HICBIR_ZAMAN_girmez(
    seeded_db: AsyncSession,
    hesap_fabrikasi,
    cek_fabrikasi,
    odeme_fabrikasi,
    durum: FinancialInstrumentStatus,
) -> None:
    """Beyaz liste bekçisi: "portfolio hariç hepsi nakit" YAZILAMAZ.

    `returned`/`cancelled` bir çekin parası hiç gelmemiştir; bunları nakit
    sayan bir uygulama karşılıksız çeki tahsil edilmiş gibi gösterirdi.
    """
    hesap = await hesap_fabrikasi(opening_balance="1000.00")
    cek = await cek_fabrikasi(status=durum)
    await odeme_fabrikasi(hesap, instrument=cek)

    assert await _bakiye(seeded_db, hesap) == Decimal("1000.00")


# --- 3. OUTER JOIN bekçisi --------------------------------------------------


async def test_BAGSIZ_odeme_nakittir_OUTER_JOIN_BEKCISI(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 `join_instrument` INNER yapılırsa BU test kırmızı verir.

    Bağsız ödemeler enstrüman tablosunda karşılık BULMAZ; INNER join onları
    komple düşürür ve bakiye açılış bakiyesine çöker. Testte bağlı bir ödeme de
    vardır: bağsızları toptan atan bir uygulamanın "hiç join yok" gibi
    davranarak kaçmasını engeller.
    """
    hesap = await hesap_fabrikasi(opening_balance="500.00")
    await odeme_fabrikasi(hesap, amount=Decimal("300.00"))
    await odeme_fabrikasi(hesap, amount=Decimal("200.00"), direction=InvoiceDirection.incoming)
    cek = await cek_fabrikasi(status=FinancialInstrumentStatus.collected)
    await odeme_fabrikasi(hesap, amount=Decimal("100.00"), instrument=cek)

    assert await _bakiye(seeded_db, hesap) == Decimal("700.00")


async def test_bagsiz_odemeler_TEK_BASINA_bakiyeyi_kurar(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """Enstrüman tablosu TAMAMEN BOŞKEN de bakiye doğrudur.

    INNER join mutasyonunun en saf hâli: hiç enstrüman yoksa INNER'da sorgu
    SIFIR satır döner ve bakiye sessizce açılış bakiyesine düşer.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    await odeme_fabrikasi(hesap, amount=Decimal("1234.56"))

    assert await _bakiye(seeded_db, hesap) == Decimal("1234.56")


# --- 4. D1: tetikleyici BAĞDIR, `method` etiketi DEĞİL ----------------------


async def test_D1_method_cheque_ama_BAGSIZ_odeme_NAKITTIR(
    seeded_db: AsyncSession, hesap_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 ODM-1 D1'in bekçisi — tasarımın en tartışmalı kararı.

    `method='cheque'` bir ETİKETTİR (FIN-1 K4); bir enstrüman VARLIĞI ima
    ETMEZ. Süzgeç `method`e bağlansaydı bu paranın bir "tahsil olayı"
    olmadığı için bakiyeye BİR DAHA hiç giremeyeceği (kalıcı kayıp) ve
    canlıdaki mevcut `cheque` satırlarının hepsi bağsız olduğu için canlı
    bakiyelerin SESSİZCE değişeceği ölçülmüştür.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    await odeme_fabrikasi(hesap, method=PaymentMethodKind.cheque)

    assert await _bakiye(seeded_db, hesap) == TUTAR


async def test_D1_method_transfer_ama_PORTFOYDEKI_ceke_BAGLI_odeme_nakit_DEGILDIR(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """D1'in aynadaki yarısı: karar `method`i hem YETERLİ hem GEREKLİ olmaktan çıkarır.

    Yalnız yukarıdaki test yazılsaydı, süzgeci `method != cheque` diye kuran
    bir uygulama yeşil geçerdi.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    cek = await cek_fabrikasi()
    await odeme_fabrikasi(hesap, instrument=cek, method=PaymentMethodKind.transfer)

    assert await _bakiye(seeded_db, hesap) == SIFIR


# --- 5. İKİ YÜZEY PARİTESİ --------------------------------------------------


async def test_IKI_YUZEY_PARITESI_bakiye_ile_nakit_akisi_AYNI_nakdi_basar(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """🔴 Kart (`balance`) ile grafik (`cash_flow`) AYNI veri üzerinde karşılaştırılır.

    İki yüzey nakdi AYRI AYRI yazsaydı, portföydeki bir çek birinde sayılıp
    ötekinde sayılmayabilirdi — ikisi de "bir sayı" bastığı için kullanıcı
    hangisinin doğru olduğunu ANLAYAMAZDI. Parite ÜÇ anda ölçülür: bağsız
    ödemeden sonra, çek PORTFÖYDEYKEN ve çek `collected` olduktan SONRA.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    await odeme_fabrikasi(hesap, amount=Decimal("300.00"))

    akis = await cash_flow.build_cash_flow(seeded_db, year=YIL, month=AY)
    assert await _bakiye(seeded_db, hesap) == akis.inflow_total - akis.outflow_total
    assert akis.inflow_total == Decimal("300.00")

    cek = await cek_fabrikasi()
    await odeme_fabrikasi(hesap, amount=TUTAR, instrument=cek)

    akis = await cash_flow.build_cash_flow(seeded_db, year=YIL, month=AY)
    assert await _bakiye(seeded_db, hesap) == akis.inflow_total - akis.outflow_total
    assert akis.inflow_total == Decimal("300.00"), "portföydeki çek GRAFİĞE de girmemeli"

    cek.status = FinancialInstrumentStatus.collected
    await seeded_db.flush()

    akis = await cash_flow.build_cash_flow(seeded_db, year=YIL, month=AY)
    assert await _bakiye(seeded_db, hesap) == akis.inflow_total - akis.outflow_total
    assert akis.inflow_total == Decimal("300.00") + TUTAR


async def test_IKI_YUZEY_PARITESI_CIKIS_bacaginda_da_tutar(
    seeded_db: AsyncSession, hesap_fabrikasi, cek_fabrikasi, odeme_fabrikasi
) -> None:
    """Süzgeç ÇIKIŞ bacağına da uygulanmalı.

    `_nakit` sarmalı yalnız giriş bacağına konsaydı, verilen bir portföy çeki
    grafikte ÇIKIŞ olarak görünür ama bakiyeden düşmezdi; parite bunu yakalar.
    """
    hesap = await hesap_fabrikasi(opening_balance="0.00")
    cek = await cek_fabrikasi(direction=FinancialInstrumentDirection.issued)
    await odeme_fabrikasi(hesap, direction=InvoiceDirection.incoming, instrument=cek)

    akis = await cash_flow.build_cash_flow(seeded_db, year=YIL, month=AY)
    assert akis.outflow_total == SIFIR, "portföydeki verilen çek ÇIKIŞ sayılmamalı"
    assert await _bakiye(seeded_db, hesap) == akis.inflow_total - akis.outflow_total

    cek.status = FinancialInstrumentStatus.paid
    await seeded_db.flush()

    akis = await cash_flow.build_cash_flow(seeded_db, year=YIL, month=AY)
    assert akis.outflow_total == TUTAR
    assert await _bakiye(seeded_db, hesap) == akis.inflow_total - akis.outflow_total
