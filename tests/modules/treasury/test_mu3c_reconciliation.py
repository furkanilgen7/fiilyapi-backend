"""🔴 MU-3C — **NAKİT MUTABAKATI**: Hazine bakiyesi ↔ yevmiyeden türeyen nakit.

## Neden bu dosya bu dilimin KABUL KAPISIDIR

MU-3C'den önce nakdin TEK kaynağı vardı: `treasury/balance.py` bakiyeyi
`opening_balance + Σ payments`ten türetiyordu. MU-3C `102`/`100`e fiş atmaya
başlayınca aynı büyüklüğün **İKİ kaynağı** oldu.

🔴 **Kanon (MU-3B'de ölçüldü): aynı büyüklüğün iki kaynağı varsa, ayrıştıklarını
HİÇBİR KOLON FARKI ele vermez — çünkü bakiye SAKLANMAZ.** İki taraf sessizce
ayrışır ve fark ancak yıl sonunda, elle bir sayımda görünür. Mutabakat testi bu
yüzden bir nezaket değil, kabul kapısıdır.

## Mutabakat KİMLİĞİ

    Σ (hesabın Hazine bakiyesi − opening_balance)  ==  Σ borç − Σ alacak  (102/100)
    ────────────────────────────────────────────       ─────────────────────────────
    `treasury/balance.py` (payments)                    `journal_lines` (fişler)

`opening_balance` ÇIKARILIR ve çıkarılmak ZORUNDADIR: açılış bakiyesinin
yevmiyede bir karşılığı YOKTUR (bu ürün açılış fişi kesmez) ve bırakılsaydı
mutabakat açılış tutarı kadar SABİT bir farkla düşerdi — o farkı "beklenen"
sayan bir tolerans, gerçek bir kaymayı da yutardı.

Kırılım HESAP TİPİ BAZINDADIR (`checking → 102`, `cash → 100`), yalnız toplamda
değil: yalnız toplam ölçülseydi kasa parasını bankaya yazan bir eşleme hatası
YEŞİL kalırdı (`100 + 102` toplamı yine tutardı).

## 🔴 STORNO'NUN ÖLÇÜLMÜŞ SINIRI — aylık pencere

Kümülatif kimlik storno altında da TAMDIR (`balance.POSTING_STATUSES` `posted`
**+** `reversed` sayar, net sıfırlanır ve ödeme satırı da silinmiştir).

AYLIK pencere böyle DEĞİLDİR ve bu ölçülmüştür: storno fişi **BUGÜNE** yazılır
(`state_service._build_reversal`, K6), orijinal ise ödemenin ayındadır. Yani
temmuzda alınıp ağustosta silinen bir tahsilat, `/treasury/cash-flow`un
temmuzundan TAMAMEN düşer ama yevmiyenin temmuzunda ORİJİNAL fişiyle durur.
Bu, `cash_flow.py`nin zaten yazılı olan *"iki uç FARKLI SAYI basar ve bu bir
kusur DEĞİLDİR"* ayrımının bir hâlidir; aylık mutabakat bu yüzden SİLİNMEMİŞ
küme üzerinde ölçülür ve silme kümülatif tarafta ölçülür.
"""

from datetime import date
from decimal import Decimal

from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.treasury import balance, cash_flow, payments_service
from app.modules.treasury.models import BankAccount, BankAccountType, PaymentMethodKind
from app.modules.treasury.schemas import PaymentCreate
from tests.modules.treasury._mu3c import (
    KOD_BANKA,
    KOD_KASA,
    TARIH,
    aktor,
    banka_hesabi,
    esleme_kur,
    fatura,
    hesap_neti,
)

#: 🔴 Kümenin GENİŞLİĞİ iddianın parçasıdır. TEK bir ödemeyle ölçülseydi yön
#: ayrımı (giriş/çıkış), hesap tipi ayrımı (banka/kasa), kısmi tahsilat ve
#: kuruşlu tutarların hiçbiri koşmazdı.
#:
#: `(hesap anahtarı, fatura yönü, fatura toplamı, ödeme tutarları)`
MUTABAKAT_KUMESI = (
    ("banka", InvoiceDirection.outgoing, "1200.00", ("1200.00",)),
    ("banka", InvoiceDirection.outgoing, "999.99", ("400.00", "599.99")),  # kısmi
    ("banka", InvoiceDirection.incoming, "3333.33", ("3333.33",)),  # ÇIKIŞ
    ("banka", InvoiceDirection.incoming, "0.01", ("0.01",)),  # kuruş
    ("kasa", InvoiceDirection.outgoing, "750.50", ("750.50",)),
    ("kasa", InvoiceDirection.incoming, "125.25", ("100.00",)),  # kısmi ÇIKIŞ
    # SAYILMAYAN: ödemesi hiç olmayan fatura iki tarafa da girmemeli.
    ("banka", InvoiceDirection.outgoing, "5000.00", ()),
)

_DURUM = {
    InvoiceDirection.outgoing: InvoiceStatus.sent,
    InvoiceDirection.incoming: InvoiceStatus.approved,
}


async def _kumeyi_kur(seeded_db, user_factory, *, paid_on: date = TARIH):
    """Kümeyi ÜRÜN yolundan (`create_payment`) kurar — ORM ile DEĞİL.

    ORM ile yazılsaydı fişleme hiç koşmaz ve mutabakat "sıfır ↔ sıfır" diye
    tutardı (sahte-yeşilin en ucuz hâli).
    """
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    hesaplar = {
        "banka": await banka_hesabi(
            seeded_db, account_type=BankAccountType.checking, opening_balance="10000.00"
        ),
        "kasa": await banka_hesabi(
            seeded_db, account_type=BankAccountType.cash, opening_balance="250.00"
        ),
    }
    odemeler = []
    for hesap_anahtari, yon, toplam, tutarlar in MUTABAKAT_KUMESI:
        account = hesaplar[hesap_anahtari]
        invoice = await fatura(
            seeded_db, kullanici, direction=yon, total=toplam, status=_DURUM[yon]
        )
        for tutar in tutarlar:
            payment, _ = await payments_service.create_payment(
                seeded_db,
                kullanici,
                invoice.id,
                PaymentCreate(
                    bank_account_id=account.id,
                    method=PaymentMethodKind.transfer,
                    amount=Decimal(tutar),
                    paid_on=paid_on,
                ),
            )
            odemeler.append(payment)
    return kullanici, hesaplar, odemeler


async def _hazine_hareketi(seeded_db, hesaplar: dict[str, BankAccount]) -> dict[str, Decimal]:
    """Hazine tarafının NAKİT HAREKETİ = bakiye − açılış (hesap tipi bazında).

    Bakiye ÜRÜN formülünden (`balance.balances_for`) okunur; test kendi
    `Σ payments`ini yazsaydı ölçtüğü şey ürünün nakit tanımı değil TESTİN
    aritmetiği olurdu.
    """
    bakiyeler = await balance.balances_for(seeded_db, [h.id for h in hesaplar.values()])
    return {
        anahtar: bakiyeler[hesap.id] - hesap.opening_balance for anahtar, hesap in hesaplar.items()
    }


async def test_NAKIT_MUTABAKATI_hazine_bakiyesi_ile_yevmiye_BIREBIR_tutar(
    seeded_db,
    user_factory,
):
    """🔴 BU DİLİMİN KABUL KAPISI — birebir, kuruş toleransı YOK.

    Tolerans girseydi her turda bir kuruş kaçak meşrulaşır ve fark yıl sonunda
    gözle görünür hâle gelirdi (HZ-1 K6 kanonu).
    """
    _kullanici, hesaplar, _odemeler = await _kumeyi_kur(seeded_db, user_factory)

    hazine = await _hazine_hareketi(seeded_db, hesaplar)
    yevmiye = {
        "banka": await hesap_neti(seeded_db, KOD_BANKA),
        "kasa": await hesap_neti(seeded_db, KOD_KASA),
    }

    assert hazine["banka"] == yevmiye["banka"], (
        f"BANKA ayrıştı: Hazine {hazine['banka']} ↔ yevmiye {yevmiye['banka']}"
    )
    assert hazine["kasa"] == yevmiye["kasa"], (
        f"KASA ayrıştı: Hazine {hazine['kasa']} ↔ yevmiye {yevmiye['kasa']}"
    )
    # 🔴 Küme GERÇEKTEN para taşıyor: sıfır ↔ sıfır da "tutar"dı.
    assert hazine["banka"] != 0
    assert hazine["kasa"] != 0
    # 🔴 İki tip AYRI sayılar: eşit olsalardı tip kırılımı hiçbir şey ölçmezdi.
    assert hazine["banka"] != hazine["kasa"]


async def test_NAKIT_AKISI_toplamlari_da_yevmiyeyle_TUTAR(seeded_db, user_factory):
    """İkinci Hazine yüzeyi: `/treasury/cash-flow`un iki toplamı.

    `giriş − çıkış` aynı ayın yevmiye nakit netine EŞİT olmalıdır — bakiye ile
    aynı ödemeleri güne ve yöne ayıran bir dökümdür, üçüncü bir para tanımı
    DEĞİL. Ayrı bir formül olduğu için ayrıca ölçülür: `balance.py` tutup
    `cash_flow.py` tutmayabilirdi (ikisi de `inflow_condition`ı okur ama
    toplama biçimleri farklıdır).
    """
    await _kumeyi_kur(seeded_db, user_factory)

    seri = await cash_flow.build_cash_flow(seeded_db, year=TARIH.year, month=TARIH.month)
    yevmiye_nakit = await hesap_neti(seeded_db, KOD_BANKA) + await hesap_neti(seeded_db, KOD_KASA)

    assert seri.inflow_total - seri.outflow_total == yevmiye_nakit, (
        f"NAKİT AKIŞI ayrıştı: giriş {seri.inflow_total} − çıkış {seri.outflow_total} "
        f"↔ yevmiye {yevmiye_nakit}"
    )
    assert seri.inflow_total > 0
    assert seri.outflow_total > 0


async def test_ODEME_SILINDIGINDE_kumulatif_mutabakat_KORUNUR(seeded_db, user_factory):
    """🔴 STORNO altında da birebir: ödeme satırı düşer, fiş NÖTRLENİR.

    Storno sayılmasaydı (çıplak `status == posted`) yevmiye tarafı orijinal
    kadar YÜKSEK kalır ve fark Hazine'de hiçbir kolonda görünmezdi.
    """
    kullanici, hesaplar, odemeler = await _kumeyi_kur(seeded_db, user_factory)
    once = await _hazine_hareketi(seeded_db, hesaplar)

    silinen = odemeler[0]
    tutar = silinen.amount
    await payments_service.delete_payment(seeded_db, kullanici, silinen.id)

    sonra = await _hazine_hareketi(seeded_db, hesaplar)
    assert sonra["banka"] == once["banka"] - tutar, "kurulum yanlış: silinen ödeme BANKA girişiydi"
    assert sonra["banka"] == await hesap_neti(seeded_db, KOD_BANKA), (
        "STORNO SONRASI AYRIŞTI: Hazine ödemeyi düşürdü, yevmiye netlenmedi"
    )
    assert sonra["kasa"] == await hesap_neti(seeded_db, KOD_KASA)
