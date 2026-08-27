"""🔴 ODM-1 D9 — **MUTABAKAT**: yevmiyeden türeyen nakit ↔ Hazine'nin bakiyesi.

## Niçin bu dosya ODM-1'in ASIL kabul kriteridir

MU-3C bu kimliği zaten kurmuştu (`test_mu3c_reconciliation.py`) ama o gün nakit
TEK bir şeydi: `Σ payments`. ODM-1 nakdin TANIMINI değiştirdi — bağlı bir ödeme
nakde ancak enstrüman `collected`/`paid` iken girer (D2) — ve aynı anda ödemenin
nakit bacağını `101`/`103`e kaydırdı (D1). Yani **aynı büyüklüğün iki kaynağı
YENİDEN ayrışabilir hâle geldi**, üstelik bu kez bir de ZAMAN ekseni var: para
`101`de bekler, sonra `102`ye geçer.

    Σ(journal_lines net borç; kod ∈ {100, 102}; entry.status ∈ POSTING_STATUSES)
      ==  Σ(bank_accounts bakiyesi) − Σ(opening_balance)

🔴 **Kanon (MU-3B): aynı büyüklüğün iki kaynağı varsa, ayrıştıklarını HİÇBİR
KOLON FARKI ele vermez — çünkü bakiye SAKLANMAZ.** Her fiş tek başına
dengelidir, mizan doğru görünür, ekranlar sayı basar; fark ancak elle bir
sayımda ortaya çıkar.

## 🔴 EVREN BAĞIMSIZ KAYNAKTAN (sahte-yeşilin 8. hâli)

İki taraf AYNI fonksiyondan gelirse test kendi kendini doğrular:

* **SOL** — `_mu3c.hesap_neti`, `journal_lines` üzerinde HAM SQL
  (`Σ borç − Σ alacak`, `balance.posting_filter()` ile `posted` **+**
  `reversed`). Ürünün Hazine tarafını HİÇ okumaz.
* **SAĞ** — `treasury.balance.balances_for()`, yani ürünün nakit formülünün
  KENDİSİ. Test kendi `Σ payments`ini yazsaydı ölçtüğü şey ürünün nakit tanımı
  değil TESTİN aritmetiği olurdu.

`opening_balance` ÇIKARILIR: açılış bakiyesinin yevmiyede karşılığı YOKTUR (bu
ürün açılış fişi kesmez) ve bırakılsaydı mutabakat sabit bir farkla düşer, o
farkı "beklenen" sayan bir tolerans gerçek bir kaymayı da yutardı.

## ALTI AN — hepsinde EŞİT

| # | An | Beklenen |
|---|---|---|
| 1 | nakit (`100`) + havale (`102`) ödemeleri | nakit ARTAR, iki taraf eşit |
| 2 | çek ödemesi **PORTFÖYDE** | 🔴 nakit HİÇ değişmez (para `101`de) |
| 3 | çek `collected` | nakit İKİ tarafta da AYNI kadar artar |
| 4 | çek `returned` (storno) | nakit HİÇ artmamış olur |
| 5 | verilen çek `issued` → **portföyde** | nakit HİÇ azalmaz (para `103`te) |
| 6 | verilen çek `paid` | nakit İKİ tarafta da AYNI kadar azalır |

🔴 An 2 ve 5 bu dosyanın ASIL anlarıdır: yalnız "tahsil sonrası tutuyor mu"
ölçülseydi, ÇİFT SAYAN bir kod (para hem `101`de hem `102`de) 2. anda yakalanmaz
ve 3. anda toplam yine tutardı.

## `103` KONTRA HESABI — ölçülür, karıştırılmaz

`103 Verilen Çekler ve Ödeme Emirleri (-)` tohumda `liability` + `is_contra=True`
(`chart_seed_data.py`). Mutabakatın nakit tarafı hesap KODUNA göre süzülür
(`100`/`102`), yani `103` oraya YAPISAL OLARAK karışamaz. Bu bir varsayım değil,
ölçülen bir iddiadır (`test_103_KONTRA_hesabi_nakit_toplamina_KARISMAZ`): kod
süzgeci bir gün tipe (`asset`/`liability`) çevrilseydi `103` sessizce nakit
toplamına girer ve verilen her çek nakdi eksiye çekerdi.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.modules.accounting.models import ChartAccount, ChartAccountType
from app.modules.invoicing.models import InvoiceDirection, InvoiceStatus
from app.modules.treasury import balance, payments_service
from app.modules.treasury.instruments import service as instruments_service
from app.modules.treasury.models import (
    BankAccount,
    BankAccountType,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentKind,
    FinancialInstrumentStatus,
    PaymentMethodKind,
)
from app.modules.treasury.schemas import PaymentCreate
from tests.modules.treasury._mu3c import (
    KOD_ALINAN_CEK,
    KOD_BANKA,
    KOD_KASA,
    KOD_VERILEN_CEK,
    TARIH,
    aktor,
    banka_hesabi,
    esleme_kur,
    fatura,
    hesap_neti,
)

#: Fatura yönü ↔ çek yönü (FIN-PAY K3'ün uyumlu çifti) + o yönde meşru durum.
_FATURA = {
    FinancialInstrumentDirection.received: (InvoiceDirection.outgoing, InvoiceStatus.sent),
    FinancialInstrumentDirection.issued: (InvoiceDirection.incoming, InvoiceStatus.approved),
}


class _Sahne:
    """Kurulumun taşıyıcısı — iki hesap, bir aktör, açılış toplamı."""

    def __init__(self, kullanici, banka: BankAccount, kasa: BankAccount) -> None:
        self.kullanici = kullanici
        self.banka = banka
        self.kasa = kasa
        self.hesaplar = (banka, kasa)


async def _sahne_kur(seeded_db, user_factory) -> _Sahne:
    await esleme_kur(seeded_db)
    kullanici = await aktor(seeded_db, user_factory)
    banka = await banka_hesabi(
        seeded_db, account_type=BankAccountType.checking, opening_balance="10000.00"
    )
    kasa = await banka_hesabi(
        seeded_db, account_type=BankAccountType.cash, opening_balance="250.00"
    )
    return _Sahne(kullanici, banka, kasa)


async def _cek(
    seeded_db,
    *,
    direction: FinancialInstrumentDirection,
    amount: str,
) -> FinancialInstrument:
    """Seri no BENZERSİZDİR: aynı sahnede birden çok çek yaşar ve karışmamalıdır."""
    instrument = FinancialInstrument(
        instrument_kind=FinancialInstrumentKind.cheque,
        direction=direction,
        serial_no=uuid.uuid4().hex[:10].upper(),
        drawer_name="Güneşkent A.Ş.",
        issue_date=TARIH,
        due_date=TARIH,
        amount=Decimal(amount),
        status=FinancialInstrumentStatus.portfolio,
    )
    seeded_db.add(instrument)
    await seeded_db.flush()
    return instrument


async def _ode(
    seeded_db,
    sahne: _Sahne,
    *,
    account: BankAccount,
    direction: InvoiceDirection,
    tutar: str,
    instrument: FinancialInstrument | None = None,
    method: PaymentMethodKind = PaymentMethodKind.transfer,
):
    """Fatura + ödeme, ÜRÜN yolundan (`create_payment`).

    ORM ile yazılsaydı fişleme hiç koşmaz ve mutabakat "sıfır ↔ sıfır" diye
    tutardı — sahte-yeşilin en ucuz hâli.
    """
    durum = InvoiceStatus.sent if direction is InvoiceDirection.outgoing else InvoiceStatus.approved
    invoice = await fatura(
        seeded_db, sahne.kullanici, direction=direction, total=tutar, status=durum
    )
    payment, _ = await payments_service.create_payment(
        seeded_db,
        sahne.kullanici,
        invoice.id,
        PaymentCreate(
            bank_account_id=account.id,
            method=method,
            amount=Decimal(tutar),
            paid_on=TARIH,
            financial_instrument_id=None if instrument is None else instrument.id,
        ),
    )
    return invoice, payment


async def _hazine_nakdi(seeded_db, sahne: _Sahne) -> Decimal:
    """SAĞ TARAF — Hazine'nin KENDİ bakiyesi eksi açılış.

    Ürünün nakit formülünden (`balance.balances_for`) okunur; kırılım tip
    bazında değil TOPLAMDIR çünkü bu dosyanın ölçtüğü şey zaman eksenidir —
    tip kırılımı `test_mu3c_reconciliation.py`de zaten ölçülüdür.
    """
    bakiyeler = await balance.balances_for(seeded_db, [h.id for h in sahne.hesaplar])
    return sum(
        (bakiyeler[h.id] - h.opening_balance for h in sahne.hesaplar),
        Decimal("0"),
    )


async def _yevmiye_nakdi(seeded_db) -> Decimal:
    """SOL TARAF — `journal_lines`tan HAM net, YALNIZ `100` + `102`.

    🔴 `101`/`103` BİLİNÇLİ OLARAK dışarıdadır: onlar nakit DEĞİL, yoldaki
    paranın ara hesaplarıdır. İçeri alınsalardı portföydeki çek de "nakit"
    sayılır ve D2'nin bütün süzgeci anlamsızlaşırdı — üstelik mutabakat yine
    TUTARDI (iki taraf da aynı yanlışı yapardı), yani kusuru hiçbir şey ele
    vermezdi.
    """
    return await hesap_neti(seeded_db, KOD_BANKA) + await hesap_neti(seeded_db, KOD_KASA)


async def _mutabakat(seeded_db, sahne: _Sahne, an: str) -> Decimal:
    """İKİ tarafı ölçer, EŞİT olduklarını iddia eder ve ortak değeri döner.

    Dönüş değeri anlar ARASI farkın ölçülmesini sağlar: "eşit" tek başına
    yetmez, nakdin DOĞRU ANDA değiştiği de ölçülmelidir.
    """
    hazine = await _hazine_nakdi(seeded_db, sahne)
    yevmiye = await _yevmiye_nakdi(seeded_db)
    assert hazine == yevmiye, (
        f"🔴 MUTABAKAT AYRIŞTI ({an}): Hazine {hazine} ↔ yevmiye {yevmiye}. "
        "Aynı büyüklüğün iki kaynağı sessizce ayrıştı; bakiye saklanmadığı için "
        "hiçbir kolon farkı bunu ele vermez."
    )
    return hazine


async def test_D9_MUTABAKAT_alti_anda_da_BIREBIR_tutar(seeded_db, user_factory):
    """🔴 BU DİLİMİN KABUL KAPISI — kuruş toleransı YOK.

    Tolerans girseydi her turda bir kuruş kaçak meşrulaşır ve fark yıl sonunda
    gözle görünür hâle gelirdi (HZ-1 K6 kanonu).
    """
    sahne = await _sahne_kur(seeded_db, user_factory)

    # --- AN 0: hiç para yok, iki taraf da sıfır (taban) -------------------- #
    assert await _mutabakat(seeded_db, sahne, "AN 0 — boş sahne") == Decimal("0.00")

    # --- AN 1: BAĞSIZ nakit + havale ödemeleri ----------------------------- #
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=InvoiceDirection.outgoing,
        tutar="1200.00",
    )
    await _ode(
        seeded_db,
        sahne,
        account=sahne.kasa,
        direction=InvoiceDirection.outgoing,
        tutar="750.50",
        method=PaymentMethodKind.cash,
    )
    an1 = await _mutabakat(seeded_db, sahne, "AN 1 — nakit + havale")
    assert an1 == Decimal("1950.50"), f"kurulum yanlış: bağsız ödemeler nakde girmedi ({an1})"

    # --- AN 2: 🔴 ÇEK ÖDEMESİ PORTFÖYDEYKEN -------------------------------- #
    #     Para `101`dedir: nakit İKİ tarafta da DEĞİŞMEMELİDİR.
    alinan = await _cek(seeded_db, direction=FinancialInstrumentDirection.received, amount="800.00")
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=_FATURA[FinancialInstrumentDirection.received][0],
        tutar="800.00",
        instrument=alinan,
        method=PaymentMethodKind.cheque,
    )
    an2 = await _mutabakat(seeded_db, sahne, "AN 2 — çek PORTFÖYDE")
    assert an2 == an1, (
        f"portföydeki çek nakde GİRDİ ({an1} → {an2}) — para `101`de olmalıydı; "
        "D2 süzgeci ya da `101` kaydırması çalışmıyor"
    )
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("800.00"), (
        "`101` açılmadı: ödemenin nakit bacağı ara hesaba KAYMAMIŞ"
    )

    # --- AN 3: çek TAHSİL EDİLDİ ------------------------------------------ #
    await instruments_service.change_status(
        seeded_db, sahne.kullanici, alinan.id, FinancialInstrumentStatus.collected
    )
    an3 = await _mutabakat(seeded_db, sahne, "AN 3 — çek TAHSİL EDİLDİ")
    assert an3 == an2 + Decimal("800.00"), f"tahsil edilen çek nakde TAM girmedi ({an2} → {an3})"
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00"), (
        "🔴 `101` KALINTISI: ara hesap kapanmadı"
    )

    # --- AN 4: KARŞILIKSIZ çek (storno) ------------------------------------ #
    karsiliksiz = await _cek(
        seeded_db, direction=FinancialInstrumentDirection.received, amount="400.00"
    )
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=_FATURA[FinancialInstrumentDirection.received][0],
        tutar="400.00",
        instrument=karsiliksiz,
        method=PaymentMethodKind.cheque,
    )
    await instruments_service.change_status(
        seeded_db, sahne.kullanici, karsiliksiz.id, FinancialInstrumentStatus.returned
    )
    an4 = await _mutabakat(seeded_db, sahne, "AN 4 — çek KARŞILIKSIZ (storno)")
    assert an4 == an3, f"karşılıksız çek nakde girdi ({an3} → {an4}) — para HİÇ inmemişti"
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("0.00"), (
        "storno sonrası `101` boşalmadı"
    )

    # --- AN 5: VERİLEN çek PORTFÖYDE (para `103`te) ------------------------ #
    verilen = await _cek(seeded_db, direction=FinancialInstrumentDirection.issued, amount="600.00")
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=_FATURA[FinancialInstrumentDirection.issued][0],
        tutar="600.00",
        instrument=verilen,
        method=PaymentMethodKind.cheque,
    )
    an5 = await _mutabakat(seeded_db, sahne, "AN 5 — VERİLEN çek portföyde")
    assert an5 == an4, (
        f"verilen çek daha ödenmeden nakitten DÜŞTÜ ({an4} → {an5}) — para `103`te olmalıydı"
    )
    assert await hesap_neti(seeded_db, KOD_VERILEN_CEK) == Decimal("-600.00"), (
        "`103` açılmadı: verilen çekin nakit bacağı ara hesaba KAYMAMIŞ"
    )

    # --- AN 6: VERİLEN çek ÖDENDİ ------------------------------------------ #
    await instruments_service.change_status(
        seeded_db, sahne.kullanici, verilen.id, FinancialInstrumentStatus.paid
    )
    an6 = await _mutabakat(seeded_db, sahne, "AN 6 — VERİLEN çek ÖDENDİ")
    assert an6 == an5 - Decimal("600.00"), f"ödenen çek nakitten TAM düşmedi ({an5} → {an6})"
    assert await hesap_neti(seeded_db, KOD_VERILEN_CEK) == Decimal("0.00"), (
        "🔴 `103` KALINTISI: ara hesap kapanmadı"
    )

    # 🔴 Küme GERÇEKTEN para taşıdı ve gerçekten HAREKET ETTİ: sabit bir sayı
    #    üzerinde altı kez "eşit" demek hiçbir şey ölçmezdi.
    assert len({an1, an2, an3, an5, an6}) >= 3


async def test_103_KONTRA_hesabi_nakit_toplamina_KARISMAZ(seeded_db, user_factory):
    """🔴 `103` `liability` + `is_contra` — ve nakit süzgeci KODA göredir.

    Ölçülen üç şey:

    1. tohumdaki tip/kontra bayrağı gerçekten böyledir (kurulum iddiası değil,
       ÜRÜN tohumundan gelen kayıt okunur);
    2. `103`ün ham neti NEGATİFTİR (alacak bakiyeli) — yani bir `asset` gibi
       toplanırsa nakdi AŞAĞI çeker;
    3. buna rağmen mutabakatın nakit tarafı DEĞİŞMEZ, çünkü süzgeç `100`/`102`
       KODLARINA bakar. Süzgeç bir gün hesap TİPİNE (`asset`) çevrilseydi `103`
       (`liability`) yine dışarıda kalırdı ama `101` (`asset`) İÇERİ girer ve
       portföydeki her çek nakit sayılırdı — bu testin ikinci yarısı tam olarak
       o kaymayı ölçer.
    """
    sahne = await _sahne_kur(seeded_db, user_factory)
    verilen = await _cek(seeded_db, direction=FinancialInstrumentDirection.issued, amount="600.00")
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=_FATURA[FinancialInstrumentDirection.issued][0],
        tutar="600.00",
        instrument=verilen,
        method=PaymentMethodKind.cheque,
    )

    # (1) Tohumun kimliği — hesap planı kaydından okunur.
    kayit = (
        await seeded_db.execute(select(ChartAccount).where(ChartAccount.code == KOD_VERILEN_CEK))
    ).scalar_one()
    assert kayit.account_type is ChartAccountType.liability, kayit.account_type
    assert kayit.is_contra is True, "103 kontra bayrağını kaybetti"

    # (2) Ham net ALACAK bakiyelidir.
    net_103 = await hesap_neti(seeded_db, KOD_VERILEN_CEK)
    assert net_103 == Decimal("-600.00"), net_103

    # (3) Nakit toplamı ondan ETKİLENMEZ ve iki taraf yine birebir tutar.
    nakit = await _mutabakat(seeded_db, sahne, "verilen çek portföyde")
    assert nakit == Decimal("0.00"), (
        f"verilen çek portföydeyken nakit {nakit} — `103` nakit toplamına KARIŞTI "
        "(süzgeç koda değil tipe bakıyor olabilir)"
    )
    # `101` de nakit DEĞİLDİR: aynı süzgecin öteki yarısı.
    alinan = await _cek(seeded_db, direction=FinancialInstrumentDirection.received, amount="900.00")
    await _ode(
        seeded_db,
        sahne,
        account=sahne.banka,
        direction=_FATURA[FinancialInstrumentDirection.received][0],
        tutar="900.00",
        instrument=alinan,
        method=PaymentMethodKind.cheque,
    )
    assert await hesap_neti(seeded_db, KOD_ALINAN_CEK) == Decimal("900.00")
    assert await _mutabakat(seeded_db, sahne, "alınan çek portföyde") == Decimal("0.00")
