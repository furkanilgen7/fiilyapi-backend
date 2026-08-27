"""🔴 ODM-1 — ÇEK/SENET AİLESİNİN FİŞİ: rol/hesap eşlemesi (T1 kapsamı).

Bu dosya bugün YALNIZ **veri**dir: `source_type` üyesi + `posting_rules`
tohumunun ürün kaynağı. Fişi ÜRETEN kod (`lines_for` · `post_instrument` ·
storno) bir sonraki adımda buraya gelir; şu an yazılsaydı çağıranı olmayan bir
dal doğar ve hiçbir bekçi onu ölçemezdi (*"çağıran kod yoksa kök bekçisizdir"*
kanonu).

## NE DEĞİŞTİ — MU-3C'nin kararı ODM-1'de TERSİNE DÖNDÜ

MU-3C *"çek/senet durum geçişleri fiş ATMAZ"* demişti ve gerekçesini ÜÇ ölçüme
dayandırmıştı: (1) nakdin tek tanımı `Σ payments`tı, (2) bağlı çekte çift sayım
kesindi, (3) `JournalSourceType`ta üye YOKTU. Aynı bölüm son paragrafında
doğrusunun `101`/`103` ara hesapları olduğunu ve bunun **bir ÜRÜN KARARI**
olduğunu da yazıyordu. ODM-1 o kararı verir ve üç dayanağı da kaldırır:

* nakit tanımı `balance.py`de SÜZGEÇ kazanır — bağlı bir ödeme nakde ancak
  enstrüman `collected`/`paid` iken girer;
* dolayısıyla çift sayım **yapısal olarak** imkânsızdır: portföydeki çekin
  ödemesi nakitten DÜŞÜLMÜŞTÜR, tahsil fişi onu geri KOYAR — toplam bir kez
  sayılır, iki kez değil;
* üye `f5a6b7c8d9e0` migration'ıyla açılmıştır.

## ÜYE = TABLO

`source_type = financial_instrument`, `source_id = financial_instruments.id`.
`uq_journal_entries_source` bu çift üzerinde tekildir: bir enstrümanın CANLI
fişi EN FAZLA BİR TANEDİR ve terminalden çıkış olmadığı için ikinci bir geçiş
zaten doğamaz.

## 🔴 DÖRT ROL — ve neden bu dördü

    B 102/100 Banka/Kasa       A 101 Alınan Çekler        (alınan çek TAHSİL)
    B 103 Verilen Çekler (-)   A 102/100 Banka/Kasa       (verilen çek ÖDENDİ)

* `instrument_receivable` (**101**) / `instrument_payable` (**103**) — ödeme
  fişinin nakit bacağının kaydığı ara hesaplar. Burada TERS yönde kapanırlar.
* `bank` (**102**) / `cash` (**100**) — paranın gerçekten indiği yer. İKİ ayrı
  roldür ve `treasury.posting.cash_role_for` ile ÖDEME BAŞINA seçilir: bir
  çeke kasadan ve bankadan ayrı ayrı bağlanmış ödemeler karışıksa tek bir
  nakit rolü hepsini bankaya yazar, mizanda ikisi de "Hazır Değerler" altında
  toplandığı için TOPLAM tutmaya devam eder ve kusur GÖRÜNMEZDİ.

## 🔴 `expense`/`revenue` BU AİLEDE YOKTUR ve OLAMAZ

Gider/hasılat faturanın fişindedir (MU-3B), cari kapanışı ödemenin fişindedir
(MU-3C). Çek tahsili yalnızca paranın YERİNİ değiştirir — sonuç hesaplarına
DOKUNMAZ. Bir sonuç rolü burada tanımlı olsaydı bir bacak ona düşebilir, fiş
yine dengeli kalır ve mizan DOĞRU görünürdü. Fail-closed olan taraf
tanımsızlıktır: `post_document` çözemediği rolde **422** verir ve fişi YARIM
YAZMAZ. Bekçisi `test_mu3c_posting_rules.py` içindedir (MU-3C'nin aynı
iddiasının kardeşi).

## 🔴 `120`/`320` DE YOKTUR

Cari hesap ödeme fişinde ZATEN kapanmıştır. Burada yeniden kapatılsaydı alacak
İKİ KEZ kapanır ve müşteri borcu negatife düşerdi. `returned`/`cancelled`
hâlinde cariyi yeniden AÇAN şey de bu aile değil, ödeme fişinin STORNOSUDUR
(D6 — `treasury.posting.reverse_payment` ÇAĞRILIR, KOPYALANMAZ).

## KARAR-2 · ALT HESAP AÇILMAZ (MU-4 mayını)

`101`/`103` ANA hesaplardır. Alt hesap açıldığı an ana hesaba bakan kural
`validation.leaf_blockers`tan **422** alır; MU-4 o gün `posting_rules`ın
SATIRINI günceller, bu dosya değişmez.
"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalSourceType
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.treasury import posting as treasury_posting
from app.modules.treasury.instruments import derive
from app.modules.treasury.models import (
    BankAccount,
    FinancialInstrument,
    FinancialInstrumentDirection,
    FinancialInstrumentStatus,
    Payment,
)
from app.modules.treasury.posting import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_INSTRUMENT_PAYABLE,
    ROLE_INSTRUMENT_RECEIVABLE,
)
from app.modules.users.models import User

__all__ = [
    "INSTRUMENT_POSTING_RULES",
    "POSTING_STATUSES",
    "REVERSING_STATUSES",
    "SOURCE_TYPE",
    "description_for",
    "lines_for",
    "post_instrument",
]

_ZERO = Decimal("0")

#: `journal_entries.source_type` üyesi — üye = TABLO (`financial_instruments`).
SOURCE_TYPE = JournalSourceType.financial_instrument

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. ÇALIŞMA ZAMANI EŞLEMESİ
#: DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan okur.
#: Buradaki kodlar yalnızca migration'ın tohumladığı satırların kaynağıdır ve
#: iki katmanın birebir aynı olduğunu bir test AST ile iddia eder (MU-3B deseni).
#:
#: 🔴 Rol adları `treasury.posting`ten IMPORT EDİLİR, yeniden YAZILMAZ: iki
#: ailenin `instrument_receivable` rolü AYNI `101` hesabını gösterir ve iki ayrı
#: metin sabiti, birinde yapılan bir yazım düzeltmesini ötekine taşımazdı —
#: `posting_rules`ın anahtarı `(source_type, role_key)` olduğu için sessizce
#: ÇÖZÜLEMEYEN bir rol doğar ve fişleme **422**ye düşerdi.
#:
#: Sıra rol adına göre alfabetiktir (`PAYMENT_POSTING_RULES` deseni).
INSTRUMENT_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_BANK, "102"),
    (ROLE_CASH, "100"),
    (ROLE_INSTRUMENT_PAYABLE, "103"),
    (ROLE_INSTRUMENT_RECEIVABLE, "101"),
)

#: 🔴 D3/D6 — TERMINAL DURUMLARIN İKİ SINIFI. `TERMINAL_STATUSES` (tablodan
#: türetilir) tam olarak bu ikisinin BİRLEŞİMİDİR ve bir bekçi bunu iddia eder:
#: `FinancialInstrumentStatus`a yeni bir terminal üye eklendiğinde test KIRMIZI
#: olur ve o üyenin mali karşılığı (fiş mi, storno mu) VERİLMEK ZORUNDA kalır.
#: Küme farkıyla türetilseydi yeni üye sessizce "storno" sınıfına düşerdi.
#:
#: * **FİŞLEYENLER** — para gerçekten hesaba indi/çıktı: `101`/`103` KAPANIR.
#: * **STORNOLAYANLAR** — karşılıksız/iptal: para HİÇ inmedi, ödeme fişi
#:   TERSİNE ÇEVRİLİR (`treasury.posting.reverse_payment`), cari yeniden AÇILIR
#:   ve `101`/`103` yine boşalır. Burada YENİ bir kaynak damgalı fiş DOĞMAZ.
POSTING_STATUSES: frozenset[FinancialInstrumentStatus] = frozenset(
    {FinancialInstrumentStatus.collected, FinancialInstrumentStatus.paid}
)
REVERSING_STATUSES: frozenset[FinancialInstrumentStatus] = frozenset(
    {FinancialInstrumentStatus.returned, FinancialInstrumentStatus.cancelled}
)

#: Fişin açıklaması — YÖNE göre. 🔴 TUTAR metne GİRMEZ (HZ-1 kanonu).
_DESCRIPTION_PREFIX: dict[FinancialInstrumentDirection, str] = {
    FinancialInstrumentDirection.received: "Çek/senet tahsilatı",
    FinancialInstrumentDirection.issued: "Çek/senet ödemesi",
}


def description_for(instrument: FinancialInstrument) -> str:
    """`Çek/senet tahsilatı 0123456789 — Güneşkent A.Ş.`.

    Seri no + keşideci `messages.financial_instrument_*` ile AYNI ikilidir ama
    metin ORADAN çağrılmaz: denetim günlüğü cümlesi ile yevmiye açıklaması iki
    AYRI yüzeydir (MU-3C `description_for` deseni).
    """
    onek = _DESCRIPTION_PREFIX[instrument.direction]
    return f"{onek} {instrument.serial_no} — {instrument.drawer_name}"


def lines_for(
    instrument: FinancialInstrument,
    odemeler: Sequence[tuple[Payment, BankAccount]],
) -> list[PostingLine] | None:
    """🔴 D3 — bacaklar. Bağlı ödeme YOKSA `None` (fiş YAZILMAZ).

    **TUTAR = Σ BAĞLI ÖDEMELER**, `instrument.amount` DEĞİL. `101`den yalnız
    `101`e GİREN çıkabilir; iki büyüklük mesru olarak ayrışabilir (bağ isteğe
    bağlıdır, kısmi tahsilat mümkündür) ve `instrument.amount`tan yazılsaydı
    ara hesap ya eksik boşalır ya da NEGATİFE düşerdi.

    `None` dalı bir korkuluk DEĞİL, ürünün mesru bir hâlidir: hiçbir ödemeye
    bağlanmamış bir çek de tahsil edilir — o çekin `101`e HİÇ GİRMİŞ parası
    yoktur, dolayısıyla çıkaracak parası da yoktur. Boş bir fiş yazılsaydı
    `post_document` K1'den (satır sayısı) **422** alır ve mesru bir geçiş
    reddedilirdi.

    Nakit bacağı **ÖDEME BAŞINA** üretilir ve rolü `treasury.posting.
    cash_role_for` ile O ÖDEMENİN hesabından seçilir (kopyalanmaz): bir çeke
    kasadan ve bankadan bağlanmış ödemeler karışıksa `100` ile `102` AYRI AYRI
    doğru borçlanır. Karşı bacak (`101`/`103`) TEK satırda toplamdır —
    ödeme başına ayrı yazılsaydı fiş aynı hesaba N satır taşır ve mizan yine
    doğru görünürdü, ama ara hesabın kapanışı okunamaz hâle gelirdi.

    Sıra SABİTTİR: borç bacakları önce, alacak sonra (MU-3C deseni).
    Σborç = Σalacak YAPISAL olarak tutar — iki taraf da AYNI toplamdır.
    """
    if not odemeler:
        return None
    toplam = sum((payment.amount for payment, _ in odemeler), _ZERO)
    nakit = [
        PostingLine(role_key=treasury_posting.cash_role_for(account), debit=payment.amount)
        for payment, account in odemeler
    ]
    if instrument.direction is FinancialInstrumentDirection.received:
        # ALINAN çek TAHSİL EDİLDİ: para hesaba GİRER, `101` KAPANIR.
        return [*nakit, PostingLine(role_key=ROLE_INSTRUMENT_RECEIVABLE, credit=toplam)]
    # VERİLEN çek ÖDENDİ: `103` KAPANIR, para hesaptan ÇIKAR.
    return [
        PostingLine(role_key=ROLE_INSTRUMENT_PAYABLE, debit=toplam),
        *[PostingLine(role_key=satir.role_key, credit=satir.debit) for satir in nakit],
    ]


async def post_instrument(
    session: AsyncSession,
    actor: User,
    instrument: FinancialInstrument,
    odemeler: Sequence[tuple[Payment, BankAccount]],
) -> PostingOutcome | None:
    """Tahsil/ödeme fişini yazar; bağlı ödeme yoksa `None` döner.

    🔴 COMMIT ETMEZ: çağıranın (`instruments.service.change_status`) kendi
    transaction'ında koşar. Durum damgası ile fiş AYNI transaction'da
    yazılmalıdır, aksi hâlde "tahsil edilmiş ama fişsiz" (ya da tersi) bir
    evrak doğardı.

    🔴 **`entry_date` = BUGÜN** (`derive.as_of_today`, TR takvimi) ve bu
    ölçülmüş bir tercihtir:

    * Enstrümanda TAHSİL GÜNÜ kolonu YOKTUR. `due_date` VADEDİR, tahsil günü
      değil — vadesi geçmiş bir çek bugün tahsil edilir ve `due_date`e
      yazılsaydı fiş GEÇMİŞ bir aya düşerdi. MU-3C'nin `paid_on` gerekçesinin
      aynası budur: *"para o gün geçmiştir"* — burada geçtiği gün BUGÜNDÜR.
    * KARAR-6 (geriye dönük fiş yok) böylece kendiliğinden korunur. `due_date`
      seçilseydi kapalı bir ayın vadesi taşıyan her çek `post_document`in dönem
      kapısından **409** alır ve HİÇ tahsil edilemezdi — kullanıcının
      düzeltebileceği bir şey olmadan kalıcı bir tıkanma.
    * Bugünün ayı kapalıysa yine **409** gelir ve geçiş HİÇ yazılmaz; istenen
      budur (kapalı aya mali iz sızmaz).
    """
    lines = lines_for(instrument, odemeler)
    if lines is None:
        return None
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=instrument.id,
        entry_date=derive.as_of_today(),
        description=description_for(instrument),
        lines=lines,
    )
