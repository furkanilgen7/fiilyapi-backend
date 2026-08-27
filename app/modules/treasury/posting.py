"""🔴 MU-3C — ÖDEME/TAHSİLAT AİLESİNİN FİŞİ (nakit bacağı).

MU-3B fatura ailesini bağladı: `send` hasılatı, `approve` gideri doğurdu ve
cari hesabı (`120`/`320`) AÇTI. Bu dosya o cariyi **KAPATAN** koddur —
ve KAPATMAKTAN BAŞKA HİÇBİR ŞEY YAPMAZ.

## 🔴 BU DİLİMİN EN BÜYÜK RİSKİ: ÇİFT SAYIM

Faturanın kendisi ZATEN fişlidir. Ödeme de fişlenince aynı paranın iki fişi
olur; doğru muhasebe **cari hesabın kapanmasıdır**, gider/gelirin yeniden
yazılması DEĞİL. Bu yüzden aşağıdaki rol kümesinde `expense`/`revenue` YOKTUR
ve OLAMAZ:

    GİDEN fatura → TAHSİLAT (para GİRER)     GELEN fatura → ÖDEME (para ÇIKAR)
    ─────────────────────────────────────    ─────────────────────────────────
    B 102/100 Banka/Kasa   = amount          B 320 Satıcılar      = amount
    A 120     Alıcılar     = amount          A 102/100 Banka/Kasa = amount

Denge YAPISALDIR: iki bacak da AYNI `payments.amount`tır, yani `Σ borç =
Σ alacak` kuruluş gereği tutar. K1 kapısı (`post_document`) yine de koşar —
burada kurulan bir varsayım, orada ÖLÇÜLEN bir iddiadır.

🔴 Bekçisi `test_mu3c_payment_posting.py::
test_ODEME_FISI_GIDER_ve_HASILAT_hesaplarina_DOKUNMAZ`: ödeme sonrası `740` ve
`600` netleri DEĞİŞMEMELİDİR.

## 🔴 KAYNAK `payments` SATIRIDIR — `mark-collected` GEÇİŞİ DEĞİL

Görev emri nakit bacağını *"faturanın tahsilat geçişine"* bağlamayı öneriyordu.
**KODDAN ÖLÇÜLDÜ, ÜÇ AYRI SEBEPLE İMKÂNSIZ:**

1. **Geçişte PARA YOKTUR.** `InvoiceAction.mark_collected` yalnız `status`
   damgalar (`invoicing/state_service.py`); banka hesabı, tutar ve ödeme günü
   TAŞIMAZ. Nakit bacağının üç girdisi de (`bank_account_id` · `amount` ·
   `paid_on`) yalnızca `payments` satırında vardır.
2. **Tekillik YAPISAL OLARAK engeller.** `uq_journal_entries_source`
   `(source_type, source_id)` üzerinde CANLI fişlerde tekildir ve faturanın
   `invoice`/`invoice.id` damgalı CANLI fişi `send`ten beri VARDIR. Aynı
   damgayla ikinci bir çağrı `post_document`in idempotanlık dalına düşer ve
   `created=False` ile SESSİZCE hiçbir şey yazmazdı.
3. **Geçiş TAHSİLATLARIN ÇOĞUNU KAÇIRIR.** Fatura `collected` damgasını
   çoğunlukla `perform_transition`dan DEĞİL, `payments_service._rederive_status`
   üzerinden alır (K5: `Σ payments >= total`). Geçişe bağlanan bir fiş, ödeme
   yoluyla kapanan hiçbir faturayı fişlemezdi.

Dolayısıyla `InvoiceAction.mark_collected` `invoicing.posting.POSTING_ACTIONS`
DIŞINDA KALIR (MU-3B'nin bıraktığı gibi) ve nakit fişi ödeme satırının kendi
yaşam döngüsüne bağlanır: **yazıldığında fişlenir, silindiğinde STORNO edilir.**

⚠️ Ödemesiz `mark-collected` (kullanıcı ucu doğrudan çağırırsa) `120`yi AÇIK
BIRAKIR. Bu bilinen bir boşluktur ve burada İCAT EDİLMEZ: fişlenecek bir para
yoktur (bkz. madde 1). Raporun `KAPSAM DIŞI` başlığındadır.

## 🔴 ÇEK/SENET DURUM GEÇİŞLERİ FİŞ ATMAZ — ölçülmüş karar

⚠️ **BU BÖLÜM ODM-1'DE (2026-08-27) GEÇERSİZ KILINDI ve TARİHSEL olarak
durur.** Aşağıdaki üç ölçüm o günün kodu için DOĞRUYDU; ODM-1 üçünün de
dayanağını kaldırdı: nakdin tanımı `balance.py`de değişti (bağlı ödeme
`collected`/`paid` değilse nakde GİRMEZ, yani çift sayım yapısal olarak
imkânsız), `101`/`103` `posting_rules`ta AÇILDI ve
`JournalSourceType.financial_instrument` üyesi eklendi. Bölümün son
paragrafı zaten bunun *"bir ÜRÜN KARARI"* olduğunu ve verilmeyi beklediğini
söylüyordu. Fişleme kodu `treasury/instruments/posting.py`dedir.

`instruments/transitions.py` altı geçiş tanımlar
(`portfolio → collected|returned|cancelled` ve `portfolio → paid|returned|
cancelled`). Hiçbiri BURADAN fişlenmez ve gerekçe ÜÇ ÖLÇÜMDÜR:

* **Nakdin TEK tanımı `payments`tır.** `treasury/balance.py` bakiyeyi
  YALNIZCA `Σ payments.amount`tan türetir; portföy o formüle HİÇBİR terim
  katmaz. Bir çek tahsilatı `102`ye fiş atsaydı yevmiyeden türeyen nakit,
  Hazine'nin kendi bakiyesinden SAPARDI — ve bakiye SAKLANMADIĞI için farkı
  HİÇBİR KOLON ele vermezdi (bu dilimin mutabakat testi tam olarak orada
  kırmızıya döner).
* **Bağlı çekte ÇİFT SAYIM kesindir.** `payments.financial_instrument_id`
  ile bir ödemeye bağlı çek tahsil edildiğinde aynı para hem ödeme fişinden
  hem çek fişinden geçerdi. `payments_service` bunu zaten yazılı olarak
  reddediyor: *"Hiçbir para türevine girdi eklenmez… aynı para İKİ KEZ
  sayılırdı"* (FIN-PAY K4).
* **`JournalSourceType`ta ÜYE YOKTUR.** `financial_instruments` bir üye değildir
  ve `ALTER TYPE` ile İCAT EDİLMEZ (`JournalSourceType` docstring'i: *"üye
  ICAT EDILMEZ, fişlendiği dilimde eklenir"*). FIN-1 K5 kararı da aynı yerde
  duruyor: *"Muhasebe fişi YOKTUR… portföy bir ENVANTERDIR"*.

Doğru muhasebe `101 Alınan Çekler` / `103 Verilen Çekler` ara hesaplarını ister
(ikisi de TDHP tohumunda VARDIR) ve ödeme fişinin nakit bacağını da onlara
kaydırmayı gerektirir — bu, `balance.py`nin nakit tanımını değiştirmek demektir
ve bir ÜRÜN KARARIDIR, bir kod tercihi değil. Raporun `KAPSAM DIŞI` başlığında.

🔴 Kümeyi (sayıyı değil) ölçen bekçi: `test_mu3c_posted_set.py`.

## KARAR-2 · CARİ ANA HESAP (`320`/`120`), alt hesap AÇILMAZ

MU-3B ile AYNI kodlar, AYNI gerekçe ve AYNI MU-4 mayını: `320.04` açıldığı an
`320`e bakan kural `validation.leaf_blockers`tan **422** alır. MU-4 o gün
`posting_rules`ın SATIRINI günceller; bu dosya değişmez.

## KARAR-5 · GERİ ALMA = STORNO

`DELETE /payments/{id}` (yalnız `admin`) fişi SİLMEZ ve `draft`a DÖNDÜRMEZ:
`accounting.state_service.perform_transition(..., reverse)` çağrılır, orijinal
`reversed` olur ve ters bacaklı yeni bir fiş doğar. Net TAM SIFIRLANIR —
`balance.POSTING_STATUSES` ikisini de saydığı için (`posted` + `reversed`).

🔴 Storno sonrası AYNI ödeme kimliğiyle yeniden fişleme SERBESTTİR
(`LIVE_SOURCE_WHERE`), ama ödeme satırı silindiği için pratikte doğmaz.

## K7 — HİÇBİR ŞEY CANLI OKUNMAZ

Tutar `payments.amount`tan, tarih `payments.paid_on`dan, yön bağlı faturanın
`direction`'ından okunur. Fatura toplamı ya da `Σ payments` YENİDEN
HESAPLANMAZ: kısmi tahsilat her satırda KENDİ tutarıyla fişlenir ve N ödeme N
fiş üretir — tek bir "kapanış fişi" yazılsaydı ara tahsilatların mali izi
kaybolurdu.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import TreasuryValidationError
from app.modules.accounting import state_service as accounting_state_service
from app.modules.accounting.models import JournalSourceType
from app.modules.accounting.transitions import JournalAction
from app.modules.invoicing.models import Invoice, InvoiceDirection
from app.modules.posting import repository as posting_repository
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.treasury.models import BankAccount, BankAccountType, Payment
from app.modules.users.models import User

__all__ = [
    "PAYMENT_ACCOUNT_TYPE_UNMAPPED",
    "PAYMENT_POSTING_RULES",
    "ROLE_BANK",
    "ROLE_CASH",
    "ROLE_INSTRUMENT_PAYABLE",
    "ROLE_INSTRUMENT_RECEIVABLE",
    "ROLE_PAYABLE",
    "ROLE_RECEIVABLE",
    "SOURCE_TYPE",
    "cash_role_for",
    "description_for",
    "lines_for",
    "post_payment",
    "reverse_payment",
]

#: `journal_entries.source_type` üyesi — üye = TABLO (`payments`). MU-3A'da
#: AÇILMIŞTI ve bugüne kadar hiçbir kod onu kullanmadı; bu dosya ilk kullanıcıdır.
SOURCE_TYPE = JournalSourceType.payment

# --------------------------------------------------------------------------- #
# BACAK ROLLERİ
#
# 🔴 Roller YÖNE göre ayrışır (`receivable` ↔ `payable`) ve nakit tarafı HESAP
# TİPİNE göre ayrışır (`bank` ↔ `cash`). Ortak tek bir `cash` rolü seçilseydi
# `102 Bankalar` ile `100 Kasa` TEK bir kural satırına sığmaz, kasadan yapılan
# her tahsilat bankaya yazılırdı — ve mizanda ikisi de "Hazır Değerler" altında
# göründüğü için TOPLAM tutmaya devam ederdi, yani kusur GÖRÜNMEZDİ.
#
# Adlar `invoicing.posting`in `receivable`/`payable` rolleriyle AYNIDIR ve bu
# ÇAKIŞMA DEĞİLDİR: `posting_rules`ın anahtarı `(source_type, role_key)`dir ve
# `source_type` burada `payment`tır. Aynı adı taşımaları bilinçlidir — ikisi de
# AYNI cari hesabı gösterir (KARAR-2) ve farklı adlandırmak, iki ailenin aynı
# hesabı gösterdiğini okuyucudan gizlerdi.
# --------------------------------------------------------------------------- #

ROLE_BANK = "bank"
ROLE_CASH = "cash"
ROLE_RECEIVABLE = "receivable"
ROLE_PAYABLE = "payable"

# 🔴 ODM-1 — ÇEK/SENET ARA HESAPLARI. Nakit bacağının YERİNE geçerler, YANINA
# DEĞİL: bir ödeme `financial_instrument_id` taşıyorsa parası henüz banka/kasada
# DEĞİLDİR, bir evrakın içindedir. Roller `bank`/`cash` ile AYNI bacakta yarışır
# ve seçimi ödemenin enstrüman bağı yapar (D1: bağ, `method` etiketi DEĞİL).
#
# İki ayrı rol (tek bir `instrument` değil) çünkü `101` AKTİF, `103` ise
# `is_contra=True` PASİFTİR: tek kural satırında birleştirilselerdi verilen bir
# çek `101 Alınan Çekler`e borç yazar, mizanın "Hazır Değerler" toplamı yine
# tutar ve kusur GÖRÜNMEZDİ (`bank`/`cash` ayrımının aynı gerekçesi).
ROLE_INSTRUMENT_RECEIVABLE = "instrument_receivable"
ROLE_INSTRUMENT_PAYABLE = "instrument_payable"

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. ÇALIŞMA ZAMANI EŞLEMESİ
#: DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan okur.
#: Buradaki kodlar yalnızca migration'ın tohumladığı satırların kaynağıdır ve
#: iki katmanın birebir aynı olduğunu bir test AST ile iddia eder (MU-3B deseni).
#:
#: 🔴 **ODM-1 — `101`/`103` ARTIK VARDIR.** Eski yorum *"BİLEREK YOKTUR: bu
#: ürünün nakit tanımı `treasury/balance.py`dir ve çek portföyünü SAYMAZ"*
#: diyordu. O cümle, kendi devamında bunun *"bir ÜRÜN KARARI"* olduğunu da
#: söylüyordu; ODM-1'de karar VERİLDİ ve nakit tanımı DEĞİŞTİ: bağlı bir ödeme
#: nakde ancak enstrüman `collected`/`paid` iken girer (`balance.signed_legs`).
#: Yani `101`/`103`e kayan bacak, yevmiyeyi Hazine bakiyesinden AYIRMAZ —
#: tersine, ikisini AYNI anda doğru tutan tek eşlemedir. Kural satırlarının
#: kendisi ise DEĞİŞMEDİ, yalnız İKİ satır EKLENDİ; eski dördü aynı yerde durur.
#:
#: 🔴 Sıra rol adına göre alfabetiktir ve öyle KALMALIDIR: iki katman eşitliği
#: testi sırayı da kilitler ve satırlar iki ayrı migration'dan tohumlanır.
PAYMENT_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_BANK, "102"),
    (ROLE_CASH, "100"),
    (ROLE_INSTRUMENT_PAYABLE, "103"),
    (ROLE_INSTRUMENT_RECEIVABLE, "101"),
    (ROLE_PAYABLE, "320"),
    (ROLE_RECEIVABLE, "120"),
)

#: 🔴 Hesap TİPİ → nakit bacağının rolü. `.get()` ile okunur ve bilinmeyen tip
#: REDDEDİLİR (fail-closed): `BankAccountType`a bir gün `Kredi`/`POS` eklenirse
#: ham `KeyError` **500** verirdi, sessiz bir varsayılan ise o hesabın parasını
#: YANLIŞ TDHP hesabına yazardı ve mizan yine dengeli görünürdü.
_ROLE_BY_ACCOUNT_TYPE: dict[BankAccountType, str] = {
    BankAccountType.checking: ROLE_BANK,
    BankAccountType.cash: ROLE_CASH,
}

# 422 — eşlenmemiş hesap tipi. Bugün ulaşılamaz (iki tipin ikisi de eşlenmiştir)
# ama korkuluk olarak durur; bekçisi eşlemeden bir üye DÜŞÜREREK ölçer.
PAYMENT_ACCOUNT_TYPE_UNMAPPED = "Banka hesabı tipi için nakit hesabı eşlemesi tanımlı değil"

#: Fişin açıklaması — YÖNE göre. 🔴 TUTAR metne GİRMEZ (HZ-1 kanonu): metin
#: donmuş bir kopyadır ve fişin kendi kolonlarıyla çelişebilirdi.
_DESCRIPTION_PREFIX: dict[InvoiceDirection, str] = {
    InvoiceDirection.outgoing: "Tahsilat",
    InvoiceDirection.incoming: "Ödeme",
}

_ZERO = Decimal("0")


def cash_role_for(account: BankAccount) -> str:
    """Nakit bacağının rolü — hesabın TİPİNDEN. Bilinmeyen tip **422**."""
    role_key = _ROLE_BY_ACCOUNT_TYPE.get(account.account_type)
    if role_key is None:
        raise TreasuryValidationError(PAYMENT_ACCOUNT_TYPE_UNMAPPED)
    return role_key


def description_for(invoice: Invoice, account: BankAccount) -> str:
    """`Tahsilat FIL2026000184 — Ziraat Bank`.

    Hesabın adı `display_name` varsa ondan okunur (Kasa satırında banka adı
    `Merkez Kasa` gibi bir etiketle birlikte anlamsızdır, E9:83) — `messages.
    payment_created` ile AYNI ikili, ama metin ORADAN çağrılmaz: denetim
    günlüğü cümlesi ile yevmiye açıklaması iki AYRI yüzeydir ve biri
    düzeltildiğinde ötekinin sessizce değişmesi istenmez.
    """
    hesap_adi = account.display_name or account.bank_name
    return f"{_DESCRIPTION_PREFIX[invoice.direction]} {invoice.invoice_no} — {hesap_adi}"


def lines_for(payment: Payment, invoice: Invoice, account: BankAccount) -> list[PostingLine]:
    """Ödemenin İKİ bacağı — sıra SABİTTİR (borç önce, alacak sonra).

    🔴 Süzgeç YOKTUR ve gerekmez (`invoicing.posting.lines_for`in aksine):
    `ck_payments_amount_positive` sıfır/negatif tutarı DB'de reddeder, yani
    `(0, 0)` bacağı yapısal olarak doğamaz. Bir süzgeç yazılsaydı hiçbir zaman
    koşmayan bir dal, okuyucuya var olmayan bir hâli varmış gibi gösterirdi.
    """
    nakit = cash_role_for(account)
    if invoice.direction is InvoiceDirection.outgoing:
        # TAHSİLAT: para GİRER, alıcı carisi KAPANIR.
        return [
            PostingLine(role_key=nakit, debit=payment.amount),
            PostingLine(role_key=ROLE_RECEIVABLE, credit=payment.amount),
        ]
    # ÖDEME: satıcı carisi KAPANIR, para ÇIKAR.
    return [
        PostingLine(role_key=ROLE_PAYABLE, debit=payment.amount),
        PostingLine(role_key=nakit, credit=payment.amount),
    ]


async def post_payment(
    session: AsyncSession,
    actor: User,
    payment: Payment,
    invoice: Invoice,
    account: BankAccount,
) -> PostingOutcome:
    """Ödemeyi fişler.

    🔴 COMMIT ETMEZ: çağıranın (`payments_service.create_payment`) kendi
    transaction'ında koşar. Ödeme satırı ile fiş AYNI transaction'da
    yazılmalıdır, aksi hâlde "parası girmiş ama fişsiz" (ya da tersi) bir
    tahsilat doğardı.

    🔴 `None` DÖNMEZ (`invoicing.posting.post_invoice`in aksine): her ödeme
    satırının tutarı DB kısıtı gereği pozitiftir, yani fişlenecek para DAİMA
    vardır ve "yazılacak bir şey yok" hâli YOKTUR.
    """
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=payment.id,
        # 🔴 `paid_on` — kaydın girildiği gün DEĞİL (`created_at`). Para o gün
        # geçmiştir ve nakit akışı serisi (`cash_flow.py`) de bu kolondan süzer;
        # fiş başka bir güne yazılsaydı grafik ile mizan AYRI ayları gösterirdi.
        # KARAR-6'nın ayağı buradan sarkar: geriye dönük bir `paid_on` kapalı
        # dönemde **409** alır ve ödeme HİÇ KAYDEDİLMEZ.
        entry_date=payment.paid_on,
        description=description_for(invoice, account),
        lines=lines_for(payment, invoice, account),
    )


async def reverse_payment(session: AsyncSession, actor: User, payment_id: uuid.UUID) -> bool:
    """🔴 KARAR-5 — ödemenin fişini STORNO eder. `True` = storno YAZILDI.

    Fiş SİLİNMEZ ve `draft`a DÖNDÜRÜLMEZ: `accounting.state_service` çağrılır ve
    orijinal `posted → reversed` olur, ters bacaklı YENİ bir fiş doğar. Net TAM
    sıfırlanır çünkü `balance.POSTING_STATUSES` ikisini de sayar.

    `False` MU-3C ÖNCESİ yazılmış ödemeler içindir: onların fişi hiç doğmadı ve
    silinmeleri bir stornoyu hak etmez. Sessiz bir `pass` yerine bir DÖNÜŞ
    değeri taşınır ki çağıran (ve testi) "storno atlandı" hâlini ölçebilsin.

    🔴 Storno fişi **BUGÜNE** yazılır (`state_service._build_reversal`) ve o ayın
    dönemi kapalıysa **409** alır — ödeme silinemez. İstenen budur: kapalı bir
    ayın mali izini sessizce oynatan bir silme, KARAR-6'yı delerdi.
    """
    entry = await posting_repository.entry_for_source(session, SOURCE_TYPE, payment_id)
    if entry is None:
        return False
    await accounting_state_service.perform_transition(
        session, actor, entry.id, JournalAction.reverse
    )
    return True
