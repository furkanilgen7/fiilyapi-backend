"""MU-3C — ÖDEME/TAHSİLAT FİŞLENİR + 🔴 **ÇİFT SAYIM BEKÇİSİ**.

Testler `payments_service.create_payment` / `delete_payment`i DOĞRUDAN çağırır,
uçtan geçmez: ölçülen şey ödemenin MALİ SONUCUDUR ve HTTP katmanı ona hiçbir şey
katmaz — uçtan geçilseydi kırmızı, yetki/kapsam kurulumunu da gösterir ve
kuralın kendisini bulanıklaştırırdı (`test_hz1_payments_api.py` o zinciri zaten
ölçüyor).

## 🔴 BU DOSYANIN EN AĞIR İDDİASI: ÇİFT SAYIM YOK

Fatura ZATEN fişlidir (MU-3B). Ödeme fişi cariyi (`120`/`320`) KAPATIR ve
gider/hasılata (`740`/`600`) **DOKUNMAZ**. Dokunsaydı aynı para iki kez gider
yazılır ve mizan yine DENGELİ görünürdü — kusur hiçbir kolon farkıyla
görünmezdi. Bekçi `test_ODEME_FISI_GIDER_ve_HASILAT_hesaplarina_DOKUNMAZ`
gider/hasılat netlerini ödemeden ÖNCE ve SONRA ölçer.

## 🔴 "GERİ ALINIR" İDDİASI SAVEPOINT İLE ÖLÇÜLÜR

`create_payment` fişi AYNI transaction'da yazar; 422/409 hâlinde ödemenin de
geri alınması bir TRANSACTION olgusudur, oturum olgusu değil. Bu yüzden hata
dalları `begin_nested()` (gerçek bir SQL SAVEPOINT) içinde koşar ve geri alma
DB'de ölçülür. Çıplak bir sayım, `flush` edilmiş ödemeyi AYNI transaction'da
görür ve iddia hiç koşmamış olurdu.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import AccountingValidationError, ConflictError, TreasuryValidationError
from app.modules.accounting.models import (
    JournalEntry,
    JournalEntryStatus,
    JournalSourceType,
)
from app.modules.invoicing import state_service as invoicing_state_service
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceStatus
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.treasury import payments_service, posting
from app.modules.treasury.models import BankAccountType, Payment, PaymentMethodKind
from app.modules.treasury.schemas import PaymentCreate
from tests.modules.treasury._mu3c import (
    KOD_ALICILAR,
    KOD_BANKA,
    KOD_GIDER,
    KOD_KASA,
    KOD_SATICILAR,
    KOD_SATIS,
    TARIH,
    aktor,
    bacaklar,
    banka_hesabi,
    canli_fis,
    esleme_kur,
    fatura,
    hesap_neti,
)


async def _ode(
    seeded_db,
    user_factory,
    invoice: Invoice,
    account,
    amount: str,
    *,
    paid_on: date = TARIH,
) -> Payment:
    payment, _detay = await payments_service.create_payment(
        seeded_db,
        await aktor(seeded_db, user_factory),
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=PaymentMethodKind.transfer,
            amount=Decimal(amount),
            paid_on=paid_on,
        ),
    )
    return payment


async def _odeme_fisi(seeded_db, payment: Payment):
    return await canli_fis(seeded_db, JournalSourceType.payment, payment.id)


async def _fis_sayisi(seeded_db) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(JournalEntry))


async def _odeme_sayisi(seeded_db) -> int:
    return await seeded_db.scalar(select(func.count()).select_from(Payment))


# --------------------------------------------------------------------------- #
# BACAKLAR — cari KAPANIR, nakit HAREKET EDER
# --------------------------------------------------------------------------- #


async def test_TAHSILAT_bankaya_GIRER_ve_ALICI_carisini_KAPATIR(seeded_db, user_factory):
    """🔴 Giden fatura + tahsilat: `B 102 / A 120`. `600`e DOKUNULMAZ."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1200.00",
        status=InvoiceStatus.sent,
    )

    payment = await _ode(seeded_db, user_factory, invoice, account, "1200.00")

    entry = await _odeme_fisi(seeded_db, payment)
    assert entry is not None, "ödeme FİŞSİZ kaldı"
    assert entry.status is JournalEntryStatus.posted  # KARAR-3
    assert entry.entry_date == TARIH  # `paid_on`, `created_at` DEĞİL
    assert await bacaklar(seeded_db, entry) == [
        (KOD_BANKA, "1200.00", "0.00"),
        (KOD_ALICILAR, "0.00", "1200.00"),
    ]


async def test_ODEME_bankadan_CIKAR_ve_SATICI_carisini_KAPATIR(seeded_db, user_factory):
    """🔴 Gelen fatura + ödeme: `B 320 / A 102`. `740`a DOKUNULMAZ."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.incoming,
        total="500.00",
        status=InvoiceStatus.approved,
    )

    payment = await _ode(seeded_db, user_factory, invoice, account, "500.00")

    entry = await _odeme_fisi(seeded_db, payment)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_SATICILAR, "500.00", "0.00"),
        (KOD_BANKA, "0.00", "500.00"),
    ]


async def test_KASA_hesabi_100e_duser_BANKA_102ye(seeded_db, user_factory):
    """🔴 Nakit bacağının rolü HESABIN TİPİNDEN gelir.

    Tek bir nakit rolü seçilseydi kasadan yapılan her tahsilat `102`ye yazılırdı
    ve ikisi de mizanda "Hazır Değerler" altında toplandığı için TOPLAM tutmaya
    devam ederdi — yani kusur GÖRÜNMEZDİ.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    kasa = await banka_hesabi(seeded_db, account_type=BankAccountType.cash)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="300.00",
        status=InvoiceStatus.sent,
    )

    payment = await _ode(seeded_db, user_factory, invoice, kasa, "300.00")

    assert await bacaklar(seeded_db, await _odeme_fisi(seeded_db, payment)) == [
        (KOD_KASA, "300.00", "0.00"),
        (KOD_ALICILAR, "0.00", "300.00"),
    ]


async def test_KISMI_TAHSILAT_her_satir_KENDI_fisini_uretir(seeded_db, user_factory):
    """K5 — kısmi tahsilat SATIRDIR; N ödeme N fiş üretir.

    Tek bir "kapanış fişi" yazılsaydı ara tahsilatların mali izi kaybolur ve
    `120` faturanın kapandığı güne kadar TAM açık görünürdü.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )

    ilk = await _ode(seeded_db, user_factory, invoice, account, "400.00")
    ikinci = await _ode(seeded_db, user_factory, invoice, account, "600.00")

    assert await _odeme_fisi(seeded_db, ilk) is not None
    assert await _odeme_fisi(seeded_db, ikinci) is not None
    assert await _fis_sayisi(seeded_db) == 2
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("1000.00")
    # Fatura `collected` damgasını `_rederive_status`tan aldı — o damga FİŞ ATMAZ.
    assert invoice.status is InvoiceStatus.collected


# --------------------------------------------------------------------------- #
# 🔴 ÇİFT SAYIM BEKÇİSİ
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("yon", "durum", "gecis", "izlenen_kod"),
    [
        (InvoiceDirection.incoming, InvoiceStatus.pending, InvoiceAction.approve, KOD_GIDER),
        (InvoiceDirection.outgoing, InvoiceStatus.draft, InvoiceAction.send, KOD_SATIS),
    ],
)
async def test_ODEME_FISI_GIDER_ve_HASILAT_hesaplarina_DOKUNMAZ(
    seeded_db,
    user_factory,
    yon,
    durum,
    gecis,
    izlenen_kod,
):
    """🔴 BU DİLİMİN KABUL KAPISI — ödeme sonrası gider/hasılat DEĞİŞMEZ.

    Ödeme `740`/`600`e dokunsaydı aynı para İKİ KEZ gider (ya da hasılat)
    yazılırdı ve fiş yine dengeli olduğu için mizan DOĞRU görünürdü. Bekçi
    sonucun kendisini değil, DEĞİŞMEMESİ gerekeni ölçer.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(seeded_db, kullanici, direction=yon, total="1000.00", status=durum)
    await invoicing_state_service.perform_transition(seeded_db, kullanici, invoice.id, gecis)

    once = await hesap_neti(seeded_db, izlenen_kod)
    assert once != 0, "kurulum FİŞSİZ kaldı — bekçi hiçbir şeyi ölçmüyor olurdu"

    await _ode(seeded_db, user_factory, invoice, account, "1000.00")

    sonra = await hesap_neti(seeded_db, izlenen_kod)
    assert sonra == once, (
        f"ÇİFT SAYIM: ödeme fişi `{izlenen_kod}` hesabını oynattı "
        f"({once} → {sonra}); ödeme yalnız CARİYİ kapatmalıdır"
    )
    # Cari GERÇEKTEN kapandı: fatura + ödeme birlikte netlenir.
    cari = KOD_SATICILAR if yon is InvoiceDirection.incoming else KOD_ALICILAR
    assert await hesap_neti(seeded_db, cari) == Decimal("0.00")


async def test_MARK_COLLECTED_gecisi_NAKIT_fisi_URETMEZ(seeded_db, user_factory):
    """🔴 Tahsilat damgası bir GEÇİŞTİR, para hareketi DEĞİL.

    Geçişten fiş atılsaydı hem tekillik yüzünden sessizce hiçbir şey yazılmaz
    (fatura zaten fişli), hem de ödeme yoluyla kapanan faturalar hiç
    fişlenmezdi — gerekçe `treasury/posting.py` modül docstring'inde ÜÇ ölçümle.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.draft,
    )
    await invoicing_state_service.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.send
    )

    await invoicing_state_service.perform_transition(
        seeded_db, kullanici, invoice.id, InvoiceAction.mark_collected
    )

    assert (
        await seeded_db.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.source_type == JournalSourceType.payment)
        )
        == 0
    )
    assert await _fis_sayisi(seeded_db) == 1


# --------------------------------------------------------------------------- #
# KARAR-5 — GERİ ALMA = STORNO
# --------------------------------------------------------------------------- #


async def test_ODEME_SILININCE_STORNO_yazilir_ve_net_TAM_sifirlanir(seeded_db, user_factory):
    """🔴 KARAR-5 — `posted` fiş SİLİNMEZ, `draft`a DÖNMEZ; storno netler."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )
    payment = await _ode(seeded_db, user_factory, invoice, account, "1000.00")
    orijinal = await _odeme_fisi(seeded_db, payment)

    await payments_service.delete_payment(seeded_db, kullanici, payment.id)

    await seeded_db.refresh(orijinal)
    assert orijinal.status is JournalEntryStatus.reversed
    assert await _fis_sayisi(seeded_db) == 2, "storno YENİ bir fiştir (bayrak değil)"
    # 🔴 `posted` + `reversed` birlikte sayılır: net TAM sıfırdır.
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("0.00")
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("0.00")
    # Belgenin CANLI fişi kalmadı.
    assert await canli_fis(seeded_db, JournalSourceType.payment, payment.id) is None


async def test_FISI_OLMAYAN_odeme_silinebilir_STORNO_YAZILMAZ(seeded_db, user_factory):
    """MU-3C ÖNCESİ yazılmış ödemelerin fişi hiç doğmadı; silinmeleri serbesttir.

    `reverse_payment` `False` döner ve hiçbir şey yazılmaz. Kör bir `raise`
    olsaydı canlıdaki mevcut ödemelerin HİÇBİRİ silinemezdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )
    # MU-3C öncesi kaydın taklidi: ödeme satırı fişleme YOLUNDAN GEÇMEDEN yazılır.
    payment = Payment(
        invoice_id=invoice.id,
        bank_account_id=account.id,
        method=PaymentMethodKind.transfer,
        amount=Decimal("1000.00"),
        paid_on=TARIH,
        created_by_id=kullanici.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()

    assert await posting.reverse_payment(seeded_db, kullanici, payment.id) is False

    await payments_service.delete_payment(seeded_db, kullanici, payment.id)
    assert await _fis_sayisi(seeded_db) == 0
    assert await _odeme_sayisi(seeded_db) == 0


# --------------------------------------------------------------------------- #
# FAIL-CLOSED DALLARI — hepsi SAVEPOINT içinde ölçülür
# --------------------------------------------------------------------------- #


async def test_ESLEME_YOKSA_422_ve_ODEME_de_GERI_ALINIR(seeded_db, user_factory):
    """🔴 `esleme_kur` BİLEREK ÇAĞRILMADI — `payment` ailesinin kuralı YOK.

    Fişleme ödemenin İÇİNDEDİR: 422 atarsa ödeme satırı da geri alınır ve
    "parası girmiş ama fişsiz" bir tahsilat DOĞMAZ.
    """
    kullanici = await aktor(seeded_db, user_factory)
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )

    savepoint = await seeded_db.begin_nested()
    with pytest.raises(AccountingValidationError):
        await _ode(seeded_db, user_factory, invoice, account, "1000.00")
    await savepoint.rollback()

    assert await _fis_sayisi(seeded_db) == 0
    assert await _odeme_sayisi(seeded_db) == 0, "fişsiz kalan ödeme satırı GERİ ALINMADI"


async def test_KAPALI_doneme_odeme_409_KARAR6(seeded_db, user_factory):
    """🔴 KARAR-6 — GERİYE DÖNÜK FİŞ YOK. Fiş `paid_on`a yazılır.

    Dönem satırı ÜRÜN yoluyla kapatılır (`periods_service`in kendi UPSERT'ü
    devreye girsin diye ORM ile kurulur); kapalı ay `post_document`in dönem
    kapısında 409 verir ve ödeme HİÇ KAYDEDİLMEZ.
    """
    from datetime import UTC, datetime

    from app.modules.accounting.models import AccountingPeriod, AccountingPeriodStatus

    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    seeded_db.add(
        AccountingPeriod(
            year=2026,
            month=6,
            status=AccountingPeriodStatus.closed,
            closed_at=datetime(2026, 7, 1, tzinfo=UTC),
            closed_by_id=kullanici.id,
        )
    )
    await seeded_db.flush()
    account = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="1000.00",
        status=InvoiceStatus.sent,
    )

    savepoint = await seeded_db.begin_nested()
    with pytest.raises(ConflictError):
        await _ode(seeded_db, user_factory, invoice, account, "1000.00", paid_on=date(2026, 6, 30))
    await savepoint.rollback()

    assert await _fis_sayisi(seeded_db) == 0
    assert await _odeme_sayisi(seeded_db) == 0


async def test_ESLENMEMIS_hesap_tipi_422_FAIL_CLOSED(seeded_db, user_factory, monkeypatch):
    """🔴 `BankAccountType`a eşlenmemiş bir üye eklenirse ödeme REDDEDİLİR.

    Bugün ulaşılamaz bir daldır (iki tipin ikisi de eşlidir) ve tam olarak bu
    yüzden mutasyonla ölçülür: eşlemeden bir üye DÜŞÜRÜLÜR. `KeyError` ham
    **500** verirdi; sessiz bir varsayılan ise kasadaki parayı `102`ye yazar ve
    mizan yine dengeli görünürdü.
    """
    await esleme_kur(seeded_db)
    monkeypatch.delitem(posting._ROLE_BY_ACCOUNT_TYPE, BankAccountType.cash)
    kullanici = await aktor(seeded_db, user_factory)
    kasa = await banka_hesabi(seeded_db, account_type=BankAccountType.cash)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="100.00",
        status=InvoiceStatus.sent,
    )

    savepoint = await seeded_db.begin_nested()
    with pytest.raises(TreasuryValidationError):
        await _ode(seeded_db, user_factory, invoice, kasa, "100.00")
    await savepoint.rollback()

    assert await _fis_sayisi(seeded_db) == 0
    assert await _odeme_sayisi(seeded_db) == 0
