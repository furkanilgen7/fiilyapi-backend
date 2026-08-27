"""🔴 ODM-1 — ÇEK/SENET FİŞİ: `101`/`103` ara hesabı AÇILIR ve KAPANIR.

MU-3C'de ödemenin nakit bacağı DOĞRUDAN `102`/`100`e yazılıyordu. Çek/senetle
yapılan bir ödemede bu YANLIŞTI: para o gün banka hesabına GİRMEZ, bir evrakın
içindedir. ODM-1 iki fişi zincirler:

    (1) ödeme yazılır          B 101 Alınan Çekler   A 120 Alıcılar
    (2) çek TAHSİL edilir      B 102 Bankalar        A 101 Alınan Çekler

`101` net SIFIRA kapanır ve para `120`den `102`ye AYNI büyüklükle geçer.
Verilen çekte ayna görüntüsü `103` üzerinden koşar.

## 🔴 BU DOSYANIN ASIL KABUL KRİTERİ: K-IKIZ1 (D10)

*"Çek tahsilinde `102` borçlanır"* tek başına HİÇBİR ŞEY bekçilemez: her zaman
`102`ye yazan (yani ODM-1 ÖNCESİ) kod da o testi yeşil geçer. Bu yüzden İKİZİ
zorunludur — **çek PORTFÖYDEYKEN `102`/`100`e HİÇ girilmediği** ayrıca ölçülür.
İkisi bir arada, `lines_for`daki bağ kontrolünü kaldıran mutantı KIRMIZI verir.

## 🔴 TUTAR: Σ BAĞLI ÖDEMELER (D3), `instrument.amount` DEĞİL

Bağ İSTEĞE BAĞLIDIR (FIN-1 K4) ve kısmi tahsilat mümkündür; iki büyüklük mesru
olarak ayrışabilir. `instrument.amount`tan yazılsaydı `101`e giren ile çıkan
farklaşır ve ara hesap HİÇ KAPANMAZDI — mizan yine dengeli görünürdü, çünkü her
fiş tek başına dengelidir. Kusuru yalnız `101` NETİ ele verir.

Testler servisi DOĞRUDAN çağırır, uçtan geçmez (`test_mu3c_payment_posting.py`
deseni): ölçülen şey geçişin MALİ SONUCUDUR ve HTTP katmanı ona bir şey katmaz.
"""

from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.modules.accounting.models import JournalEntryStatus, JournalSourceType
from app.modules.invoicing.models import Invoice, InvoiceDirection, InvoiceStatus
from app.modules.treasury import payments_service
from app.modules.treasury.instruments import posting as instrument_posting
from app.modules.treasury.instruments import service as instruments_service
from app.modules.treasury.instruments import transitions as instrument_transitions
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
    KOD_KASA,
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

#: Fatura yönü ↔ çek yönü — FIN-PAY K3'ün uyumlu çifti (ters çift 422'dir).
_FATURA = {
    FinancialInstrumentDirection.received: (InvoiceDirection.outgoing, InvoiceStatus.sent),
    FinancialInstrumentDirection.issued: (InvoiceDirection.incoming, InvoiceStatus.approved),
}


async def _cek(
    seeded_db,
    *,
    direction: FinancialInstrumentDirection = FinancialInstrumentDirection.received,
    amount: str = "1000.00",
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


async def _bagli_ode(
    seeded_db,
    kullanici,
    invoice: Invoice,
    account: BankAccount,
    amount: str,
    instrument: FinancialInstrument | None,
) -> Payment:
    """Ödemeyi ÜRÜN yolundan yazar — bağ varsa `101`/`103`e düşmesi beklenir."""
    payment, _ = await payments_service.create_payment(
        seeded_db,
        kullanici,
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=PaymentMethodKind.cheque,
            amount=Decimal(amount),
            paid_on=TARIH,
            financial_instrument_id=None if instrument is None else instrument.id,
        ),
    )
    return payment


async def _zincir(
    seeded_db,
    user_factory,
    *,
    direction: FinancialInstrumentDirection = FinancialInstrumentDirection.received,
    tutar: str = "1000.00",
    account: BankAccount | None = None,
):
    """Kurulumun TEK kapısı: eşleme + aktör + hesap + fatura + BAĞLI ödeme."""
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    hesap = account if account is not None else await banka_hesabi(seeded_db)
    yon, durum = _FATURA[direction]
    invoice = await fatura(seeded_db, kullanici, direction=yon, total=tutar, status=durum)
    cek = await _cek(seeded_db, direction=direction, amount=tutar)
    payment = await _bagli_ode(seeded_db, kullanici, invoice, hesap, tutar, cek)
    return kullanici, hesap, invoice, cek, payment


async def _cek_fisi(seeded_db, instrument: FinancialInstrument):
    return await canli_fis(seeded_db, JournalSourceType.financial_instrument, instrument.id)


# --------------------------------------------------------------------------- #
# D1 — ÖDEMENİN nakit bacağı ÇEKTE ARA HESABA kayar
# --------------------------------------------------------------------------- #


async def test_BAGLI_odeme_101e_yazilir_NAKDE_GIRMEZ(seeded_db, user_factory):
    """🔴 D1 — giden fatura + bağlı çek: `B 101 / A 120`. `102` GÖRMEZ."""
    _kullanici, _hesap, _invoice, _cek_kaydi, payment = await _zincir(seeded_db, user_factory)

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_ALINAN_CEK, "1000.00", "0.00"),
        (KOD_ALICILAR, "0.00", "1000.00"),
    ]


async def test_BAGLI_ODEME_gelen_faturada_103e_yazilir(seeded_db, user_factory):
    """🔴 D1'in AYNASI — gelen fatura + verilen çek: `B 320 / A 103`.

    Ayrı bir rol OLMASAYDI (tek bir `instrument` rolü) verilen bir çek
    `101 Alınan Çekler`e yazılır, mizanın "Hazır Değerler" toplamı yine tutar ve
    kusur GÖRÜNMEZDİ — `bank`/`cash` ayrımının aynı gerekçesi.
    """
    _k, _h, _i, _c, payment = await _zincir(
        seeded_db, user_factory, direction=FinancialInstrumentDirection.issued, tutar="700.00"
    )

    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_SATICILAR, "700.00", "0.00"),
        (KOD_VERILEN_CEK, "0.00", "700.00"),
    ]


async def test_BAGSIZ_odeme_ESKISI_GIBI_102ye_yazilir(seeded_db, user_factory):
    """🔴 D1 — TETİKLEYİCİ BAĞDIR, `method` ETİKETİ DEĞİL.

    Gövde `method='cheque'` taşır ama BAĞ YOKTUR: davranış MU-3C'deki gibi
    kalır ve para DOĞRUDAN `102`ye girer. `method`e bağlanan bir kural
    canlıdaki bütün `cheque` satırlarını (hepsi bağsızdır, FIN-1 K4) sessizce
    `101`e kaydırır ve onları oradan çıkaracak hiçbir uç bulunmazdı.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    hesap = await banka_hesabi(seeded_db)
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="400.00",
        status=InvoiceStatus.sent,
    )

    payment = await _bagli_ode(seeded_db, kullanici, invoice, hesap, "400.00", None)

    assert payment.method is PaymentMethodKind.cheque, "kurulum `method` etiketini kaybetti"
    entry = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await bacaklar(seeded_db, entry) == [
        (KOD_BANKA, "400.00", "0.00"),
        (KOD_ALICILAR, "0.00", "400.00"),
    ]


async def test_FIS_ACIKLAMASI_bagli_hali_AYIRT_EDILEBILIR_ve_TUTAR_TASIMAZ(seeded_db, user_factory):
    """Fiş açıklamasından hangi hâl olduğu OKUNABİLMELİDİR; tutar metne GİRMEZ."""
    _k, _h, invoice, _c, bagli = await _zincir(seeded_db, user_factory, tutar="1234.56")
    bagli_fis = await canli_fis(seeded_db, JournalSourceType.payment, bagli.id)

    assert bagli_fis.description != f"Tahsilat {invoice.invoice_no} — Ziraat Bank"
    assert bagli_fis.description.startswith(f"Tahsilat {invoice.invoice_no} — Ziraat Bank")
    # 🔴 HZ-1 kanonu: metin donmuş bir kopyadır, fişin kolonlarıyla çelişebilirdi.
    assert "1234" not in bagli_fis.description


# --------------------------------------------------------------------------- #
# 🔴 D10 — K-IKIZ1: iki yön birlikte ölçülür
# --------------------------------------------------------------------------- #


async def test_IKIZ_A_cek_PORTFOYDEYKEN_102ye_ve_100e_HIC_girilmez(seeded_db, user_factory):
    """🔴 K-IKIZ1'in BİRİNCİ yarısı — ASIL KABUL KRİTERİ.

    `lines_for`daki bağ kontrolü kaldırılırsa (yani çek ödemesi doğrudan `102`ye
    yazılırsa) bu test KIRMIZI olur. İkizi olmadan yazılsaydı, hiç fiş atmayan
    bir kod da yeşil geçerdi — o yüzden pozitif kontrol de burada: `101`
    GERÇEKTEN borçlanmış olmalıdır.
    """
    await _zincir(seeded_db, user_factory)

    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("1000.00"), (
        "POZİTİF KONTROL: ödeme `101`e HİÇ yazılmamış — test bir şey ölçmüyor"
    )
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("0.00"), (
        "ÇEK PORTFÖYDEYKEN `102` borçlandı: para hâlâ evrakın içindedir"
    )
    assert await hesap_neti(seeded_db, KOD_KASA) == Decimal("0.00")


async def test_IKIZ_B_cek_TAHSIL_edilince_102_borclanir_ve_101_KAPANIR(seeded_db, user_factory):
    """🔴 K-IKIZ1'in İKİNCİ yarısı + `101` KAPANIR iddiası.

    Tahsil sonrası:
    * `102` net = ödeme tutarı (para artık GERÇEKTEN bankadadır),
    * `101` net = **SIFIR** (giren kadar çıktı),
    * `120` net = sıfır (cari ödeme fişinde ZATEN kapanmıştı, çek fişi ona
      DOKUNMAZ — dokunsaydı alacak İKİ KEZ kapanır ve negatife düşerdi).
    """
    kullanici, _h, _i, cek, _p = await _zincir(seeded_db, user_factory)

    await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.collected
    )

    entry = await _cek_fisi(seeded_db, cek)
    assert entry is not None, "tahsil geçişi FİŞSİZ kaldı"
    assert entry.status is JournalEntryStatus.posted
    assert await bacaklar(seeded_db, entry) == [
        (KOD_BANKA, "1000.00", "0.00"),
        (KOD_ALINAN_CEK, "0.00", "1000.00"),
    ]
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("1000.00")
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00"), (
        "`101` KAPANMADI — ara hesapta kalıntı kaldı"
    )


async def test_VERILEN_cek_ODENINCE_103_KAPANIR_ve_102_alacaklanir(seeded_db, user_factory):
    """Aynanın öteki yüzü: `B 103 / A 102`; `103` net SIFIR."""
    kullanici, _h, _i, cek, _p = await _zincir(
        seeded_db, user_factory, direction=FinancialInstrumentDirection.issued, tutar="700.00"
    )

    await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.paid
    )

    assert await bacaklar(seeded_db, await _cek_fisi(seeded_db, cek)) == [
        (KOD_VERILEN_CEK, "700.00", "0.00"),
        (KOD_BANKA, "0.00", "700.00"),
    ]
    assert await hesap_neti(seeded_db, KOD_VERILEN_CEK) == Decimal("0.00")
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("-700.00")


# --------------------------------------------------------------------------- #
# D3 — TUTAR = Σ BAĞLI ÖDEMELER
# --------------------------------------------------------------------------- #


async def test_KISMI_TAHSILAT_iki_odeme_TOPLAMI_kadar_fislenir(seeded_db, user_factory):
    """🔴 D3 — bir çeke bağlı İKİ ödeme; tahsil fişi İKİSİNİN TOPLAMI kadardır.

    `instrument.amount` (1000) ile Σ ödemeler (900) BİLEREK ayrıştırıldı: fiş
    `instrument.amount`tan yazılsaydı `101` net **−100** kalır, mizan yine
    dengeli görünür ve kusuru hiçbir kolon farkı ele vermezdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    hesap = await banka_hesabi(seeded_db)
    cek = await _cek(seeded_db, amount="1000.00")
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="900.00",
        status=InvoiceStatus.sent,
    )
    await _bagli_ode(seeded_db, kullanici, invoice, hesap, "400.00", cek)
    await _bagli_ode(seeded_db, kullanici, invoice, hesap, "500.00", cek)

    await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.collected
    )

    # 🔴 Nakit bacaklarının SIRASI `(paid_on, payment.id)`dir — aynı günde
    #    eşitlik bozucu `uuid4`tür, yani YAZIM SIRASI DEĞİLDİR. Sıralanmış
    #    karşılaştırma bunu kabul eder; ölçülen şey KÜME ve TUTARLARDIR.
    assert sorted(await bacaklar(seeded_db, await _cek_fisi(seeded_db, cek))) == sorted(
        [
            (KOD_BANKA, "400.00", "0.00"),
            (KOD_BANKA, "500.00", "0.00"),
            (KOD_ALINAN_CEK, "0.00", "900.00"),
        ]
    )
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00")
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("900.00")


async def test_KARISIK_HESAP_kasa_ve_banka_AYRI_AYRI_borclanir(seeded_db, user_factory):
    """🔴 D3 — nakit bacağı ÖDEME BAŞINA, rolü O ÖDEMENİN hesabından.

    Tek bir nakit rolü seçilseydi kasadan bağlanan ödeme de `102`ye yazılır ve
    mizanda ikisi de "Hazır Değerler" altında toplandığı için TOPLAM tutmaya
    devam ederdi — kusur GÖRÜNMEZDİ (`cash_role_for`ın kendi gerekçesi).
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    banka = await banka_hesabi(seeded_db)
    kasa = await banka_hesabi(seeded_db, account_type=BankAccountType.cash)
    cek = await _cek(seeded_db, amount="300.00")
    invoice = await fatura(
        seeded_db,
        kullanici,
        direction=InvoiceDirection.outgoing,
        total="300.00",
        status=InvoiceStatus.sent,
    )
    await _bagli_ode(seeded_db, kullanici, invoice, banka, "200.00", cek)
    await _bagli_ode(seeded_db, kullanici, invoice, kasa, "100.00", cek)

    await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.collected
    )

    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("200.00")
    assert await hesap_neti(seeded_db, KOD_KASA) == Decimal("100.00")
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00")


async def test_ODEMESIZ_cekin_tahsili_HIC_FIS_YAZMAZ(seeded_db, user_factory):
    """🔴 D3 — `101`e GİRMİŞ para yoksa ÇIKACAK para da yoktur.

    Boş bir fiş yazılsaydı `post_document` K1'in satır sayısı kapısından **422**
    alır ve tümüyle MEŞRU bir geçiş (hiçbir faturaya bağlanmamış bir çekin
    tahsili) reddedilirdi.
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    cek = await _cek(seeded_db)

    _kayit, detay = await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.collected
    )

    assert detay, "geçiş REDDEDİLDİ — ödemesiz tahsil meşru olmalıydı"
    assert await _cek_fisi(seeded_db, cek) is None, "ödemesiz çek FİŞ YAZDI"
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00")


# --------------------------------------------------------------------------- #
# D6 — `returned`/`cancelled` → ÖDEME FİŞİ STORNO
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "hedef",
    [FinancialInstrumentStatus.returned, FinancialInstrumentStatus.cancelled],
)
async def test_KARSILIKSIZ_cekte_odeme_fisi_STORNOLANIR_cari_YENIDEN_ACILIR(
    seeded_db, user_factory, hedef
):
    """🔴 D6 (KARAR-5 emsali) — karşılıksız/iptal çekte cari KAPANMAMIŞ olmalıdır.

    Storno `120 B / 101 A` yazar: ödeme fişinin KAPATTIĞI alacak yeniden
    AÇILIR ve `101` BOŞALIR. Ölçüm ÖNCE/SONRA farkı üzerindedir — faturanın
    KENDİ fişi bu kurulumda yoktur (`fatura()` durumu doğrudan damgalar,
    `send` geçişinden geçmez), yani `120`nin mutlak neti yalnız ödeme
    bacağını taşır: kapanışta **−tutar**, stornodan sonra **0**.

    Ödeme SATIRI SİLİNMEZ — mali iz kalır ve o parayı nakitten dışlayan şey
    `balance`ın süzgecidir (D2).

    🔴 Storno kaynak damgası TAŞIMAZ: enstrümanın CANLI fişi DOĞMAZ.
    """
    kullanici, _h, invoice, cek, payment = await _zincir(seeded_db, user_factory)
    odeme_fisi = await canli_fis(seeded_db, JournalSourceType.payment, payment.id)
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == -invoice.total, (
        "POZİTİF KONTROL: ödeme fişi cariyi HİÇ kapatmamış — test bir şey ölçmüyor"
    )

    await instruments_service.change_status(seeded_db, kullanici, cek.id, hedef)

    await seeded_db.refresh(odeme_fisi)
    assert odeme_fisi.status is JournalEntryStatus.reversed
    assert await canli_fis(seeded_db, JournalSourceType.payment, payment.id) is None
    assert await _cek_fisi(seeded_db, cek) is None, (
        "storno YENİ bir kaynak damgalı fiş DOĞURDU — D6 storno der, fiş demez"
    )
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00"), "`101` BOŞALMADI"
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("0.00"), (
        "alacak yeniden AÇILMADI — karşılıksız çekte müşteri borcu DURUYOR olmalıdır"
    )
    assert await seeded_db.get(Payment, payment.id) is not None, "ödeme SATIRI silindi"


async def test_TERMINAL_KUMESI_fisleyen_ve_stornolayan_diye_TAM_bolunur():
    """🔴 Yeni bir terminal durum eklendiğinde mali karşılığı VERİLMEK ZORUNDA.

    İki küme `TERMINAL_STATUSES`ten (tablodan TÜRETİLİR) küme farkıyla
    hesaplansaydı yeni bir üye sessizce "storno" sınıfına düşer ve hiç kimse
    onun fiş atması gerekip gerekmediğini SORMAZDI.
    """
    assert instrument_posting.POSTING_STATUSES.isdisjoint(instrument_posting.REVERSING_STATUSES)
    assert (
        instrument_posting.POSTING_STATUSES | instrument_posting.REVERSING_STATUSES
    ) == instrument_transitions.TERMINAL_STATUSES


# --------------------------------------------------------------------------- #
# D5 — tahsil edilmiş çeke bağlı ödeme SİLİNEMEZ (409)
# --------------------------------------------------------------------------- #


async def test_TAHSIL_EDILMIS_ceke_bagli_odeme_SILINEMEZ_409(seeded_db, user_factory):
    """🔴 D5 — silme `101`i NEGATİFE düşürür ve `102`de kaynaksız para bırakırdı.

    Storno `120 B / 101 A` yazar; ama tahsil fişi `101`i ZATEN boşaltmıştır.
    İki fiş de tek başına dengelidir, mizan doğru görünür ve kusur hiçbir kolon
    farkıyla ele verilmez.
    """
    kullanici, _h, _i, cek, payment = await _zincir(seeded_db, user_factory)
    await instruments_service.change_status(
        seeded_db, kullanici, cek.id, FinancialInstrumentStatus.collected
    )

    savepoint = await seeded_db.begin_nested()
    with pytest.raises(ConflictError):
        await payments_service.delete_payment(seeded_db, kullanici, payment.id)
    await savepoint.rollback()

    assert await seeded_db.get(Payment, payment.id) is not None
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00")
    assert await hesap_neti(seeded_db, KOD_BANKA) == Decimal("1000.00")


async def test_PORTFOYDEKI_ceke_bagli_odeme_SILINEBILIR_POZITIF_KONTROL(seeded_db, user_factory):
    """🔴 D5'in POZİTİF KONTROLÜ. Onsuz, BAĞLI HER silmeyi reddeden bozuk bir
    kod da yeşil geçerdi — ve `101`de kalıntı bırakan yanlış bir ödeme bir daha
    hiç düzeltilemezdi (`PATCH /payments/{id}` YOKTUR)."""
    kullanici, _h, _i, _cek, payment = await _zincir(seeded_db, user_factory)

    await payments_service.delete_payment(seeded_db, kullanici, payment.id)

    assert await seeded_db.get(Payment, payment.id) is None
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00"), "storno `101`i netlemedi"
    assert await hesap_neti(seeded_db, KOD_ALICILAR) == Decimal("0.00")
