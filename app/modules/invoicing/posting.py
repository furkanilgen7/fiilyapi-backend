"""🔴 MU-3B — FATURA AİLESİNİN FİŞİ (gelen + giden).

MU-3A `post_document()`i açtı ama **hiçbir belge ailesini bağlamadı**; bu dosya
bağlayan İLK koddur. MU-3B'den önce muhasebe modülü canlıydı ve KENDİ KENDİNE
DOLMUYORDU: mizan yalnız elle girilen fişlerden oluşuyordu.

## 🔴 FİŞ NE ZAMAN DOĞAR — KODDAN ÖLÇÜLDÜ, VARSAYILMADI

`transitions.py`nin iki matrisi geçişlerin TEK kaynağıdır:

    Giden:  draft ──send──▶ sent ──mark-collected──▶ collected
    Gelen:  pending ──approve──▶ approved
               └────dispute────▶ disputed

Mali olarak BAĞLAYICI olan geçiş her yönde BİRDİR ve `POSTING_ACTIONS` tam
olarak onları taşır:

* **`send`** — fatura KESİLDİ; hasılat ve hesaplanan KDV o an doğar.
* **`approve`** — gelen fatura KABUL EDİLDİ; gider ve indirilecek KDV o an doğar.

Ötekiler bilinçli olarak DIŞARIDADIR:

* **`mark-collected`** bir TAHSİLATTIR, bir fatura olayı değil — nakit bacağı
  (`102`/`100`) Hazine diliminindir (MU-3C). Buradan fiş atılsaydı aynı fatura
  İKİ KEZ hasılat yazardı.
* **`dispute`** bir REDDİR: itiraz altındaki faturanın indirim hakkı belirsizdir
  ve `vat_return` de onu SAYMAZ (`INCOMING_STATUSES` yalnız `approved`).

🔴 Bu küme `vat_return`ün saydığı durum kümesiyle BİREBİR ÖRTÜŞÜR ve örtüşmek
ZORUNDADIR (İŞ 3 mutabakatı): `sent`+`collected` giden tarafta, `approved` gelen
tarafta. `collected` faturanın `sent`ten geçmiş olması demektir, yani fişi
ZATEN kesilmiştir — ikinci bir fiş DOĞMAZ.

## 🔴 KARAR-1 · NORMAL TİCARİ REJİM

Yıllara yaygın rejim (`170`/`350`) SEÇİLMEDİ. Kodlar bu dosyada DEĞİL
`posting_rules` tablosundadır (MU-3A'nın kurduğu desen); aşağıdaki
`INVOICE_POSTING_RULES` yalnız TOHUMUN kaynağıdır ve MU-4 kararı
değiştirdiğinde bir SATIR GÜNCELLEMESİYLE değişir, kod değişmez.

## 🔴 KARAR-2 · CARİ ANA HESAP (`320`/`120`), alt hesap AÇILMAZ

`Ekran 8` mockup'ı `120.01`/`320.04`/`102.01` çizer; bu **kullanıcı tarafından
ONAYLANMIŞ mockup sapmasıdır**, geri alınmaz. ⚠️ MU-4 mayını CANLIDIR: `320.04`
açıldığı an `320`e bakan kural `validation.leaf_blockers`tan **422** alır. Buna
DAYANIKLI yazmak MU-4'ün işidir; istenen, sessizce çift sayan bir mizan yerine
gürültülü bir durmadır.

## Bacak şeması — üç para büyüklüğü, İKİ yön

    GİDEN (satış)                         GELEN (alış)
    ────────────────────────────────      ────────────────────────────────
    B 120 Alıcılar        = total         B 740 Gider          = tax_base
    B 136 Diğer Alacak    = tevkifat      B 191 İnd. KDV       = vat_amount
    A 600 Yurt İçi Satış  = tax_base      A 320 Satıcılar      = total
    A 391 Hesaplanan KDV  = vat_amount    A 360 Öd. Vergi/Fon  = tevkifat

Denge `amounts.py`nin 7. adımından ÇIKAR ve bir tesadüf değildir:
`total = tax_base + vat_amount − withholding_amount`, dolayısıyla her iki yönde
de `Σ borç = Σ alacak` KURULUŞ GEREĞİ tutar. K1 kapısı (`post_document`) yine de
koşar ve koşmalıdır — burada kurulan bir varsayım, orada ÖLÇÜLEN bir iddiadır.

🔴 **KDV bacağı TAM `vat_amount`tır, `vat_amount − tevkifat` DEĞİL.** Tevkifat
AYRI bir bacağa (`136`/`360`) düşer. Gerekçe İŞ 3'ün mutabakatıdır: `vat_return`
hesaplanan/indirilecek KDV'yi TAM tutar üzerinden türetir ve `withholding_rate`i
hiç görmez. Tevkifat KDV bacağından düşülseydi tevkifatlı her faturada beyanname
ile yevmiye SESSİZCE ayrışır ve farkı hiçbir kolon ele vermezdi.

🔴 **HASILAT/GİDER `tax_base`tir, `subtotal` DEĞİL.** Bu ürünün para modelinde
avans ve teminat KDV MATRAHINI düşürür (`amounts.py` 4. adım) ve `tax_base`
kolonu beyannamenin matrahının TA KENDİSİDİR (`vat_return` docstring'i). Hasılat
`subtotal`den yazılsaydı fiş `advance + retention` kadar dengesiz kalır ve
bugün var olmayan iki bacağa (avans mahsubu · teminat) ihtiyaç duyardı —
onların belge dünyasındaki karşılığı henüz YOKTUR ve İCAT EDİLMEZ.

## 🔴 TUTARI SIFIR OLAN BACAK YAZILMAZ

`ck_journal_lines_single_side` `(0, 0)` satırını REDDEDER: bir bacak ya borç ya
alacak tarafında POZİTİF olmalıdır. Tevkifatsız fatura (`withholding_rate` NULL,
yani "işaretlenmemiş") normal hâldir ve o bacak hiç doğmaz; KDV'siz (istisna)
fatura da öyle. Süzgeç bu yüzden GENELDİR, tevkifata özel değil.

İki bacaktan azı kalırsa (yalnız bedelsiz kalemlerden oluşan, toplamı sıfır bir
fatura) **fiş HİÇ AÇILMAZ** ve `post_invoice` `None` döner: yazılacak bir para
yoktur ve `0 = 0` dengeli görünen boş bir fiş K1'in ikinci engelinden
(`MIN_LINES_REQUIRED`) 422 alır — o 422 kullanıcının `send`ini bloklardı.

## 🔴 K7 — HİÇBİR ŞEY CANLI OKUNMAZ

Tutarlar faturanın DONMUŞ kolonlarından alınır; `amounts.compute` bu dosyadan
ÇAĞRILMAZ (`state_service.py`nin K7 kuralı). Yeniden hesaplansaydı kaynak
kaydı (hakediş / kira / sipariş) sonradan değişen bir fatura, kesildiği andakinden
BAŞKA bir fiş üretirdi.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import JournalSourceType
from app.modules.invoicing.models import Invoice, InvoiceDirection, is_refund
from app.modules.invoicing.transitions import InvoiceAction
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.users.models import User

__all__ = [
    "INVOICE_POSTING_RULES",
    "POSTING_ACTIONS",
    "SOURCE_TYPE",
    "description_for",
    "lines_for",
    "post_invoice",
]

#: `journal_entries.source_type` üyesi — üye = TABLO (`invoices`). İki YÖN AYNI
#: üyeyi paylaşır çünkü ikisi de AYNI tablonun satırıdır; ayrımı `role_key`
#: taşır (aşağıya bakınız).
SOURCE_TYPE = JournalSourceType.invoice

#: 🔴 Mali olarak BAĞLAYICI geçişler — gerekçe modül docstring'inde.
POSTING_ACTIONS: frozenset[InvoiceAction] = frozenset({InvoiceAction.send, InvoiceAction.approve})

# --------------------------------------------------------------------------- #
# BACAK ROLLERİ
#
# 🔴 Roller YÖNE GÖRE AYRIŞIR ve ayrışmak ZORUNDADIR: `posting_rules`ın anahtarı
# `(source_type, role_key)`dir ve iki yön AYNI `source_type`ı paylaşır. Ortak bir
# `counterparty` rolü seçilseydi giden faturanın `120`si ile gelen faturanın
# `320`si TEK bir kural satırına sığmaz, biri ötekini ezerdi.
# --------------------------------------------------------------------------- #

ROLE_RECEIVABLE = "receivable"
ROLE_REVENUE = "revenue"
ROLE_VAT_OUTPUT = "vat_output"
ROLE_WITHHOLDING_RECEIVABLE = "withholding_receivable"

ROLE_EXPENSE = "expense"
ROLE_PAYABLE = "payable"
ROLE_VAT_INPUT = "vat_input"
ROLE_WITHHOLDING_PAYABLE = "withholding_payable"

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. Bu demet bir ÇALIŞMA ZAMANI
#: EŞLEMESİ DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan
#: okur. Buradaki kodlar yalnızca migration'ın tohumladığı satırların kaynağıdır
#: ve iki katmanın birebir aynı olduğunu bir test iddia eder (MU-SEED T5 deseni).
#:
#: KARAR-1 (`740`/`600`, `170`/`350` DEĞİL) ve KARAR-2 (`320`/`120`, alt hesap
#: AÇILMAZ) tam olarak BU SATIRLARDA yaşar.
INVOICE_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_EXPENSE, "740"),
    (ROLE_PAYABLE, "320"),
    (ROLE_RECEIVABLE, "120"),
    (ROLE_REVENUE, "600"),
    (ROLE_VAT_INPUT, "191"),
    (ROLE_VAT_OUTPUT, "391"),
    (ROLE_WITHHOLDING_PAYABLE, "360"),
    (ROLE_WITHHOLDING_RECEIVABLE, "136"),
)

#: Fişin açıklaması — YÖNE göre. Tutar metne GİRMEZ (HZ-1 kanonu): metin
#: donmuş bir kopyadır ve fişin kendi kolonlarıyla çelişebilirdi.
_DESCRIPTION_PREFIX: dict[InvoiceDirection, str] = {
    InvoiceDirection.outgoing: "Satış faturası",
    InvoiceDirection.incoming: "Alış faturası",
}

#: 🔴 KRIT-IADE — İADE faturasının fiş açıklaması. Yön eki AYNI kalır (belge
#: hâlâ o yönün belgesidir) ama metin İADE olduğunu SÖYLER: iade fişi asıl
#: faturanın TERSİ bacakları taşır ve mizanda `600`ü BORÇLANDIRAN bir satır
#: "Satış faturası" diye okunsaydı, defteri okuyan bir kusur arardı.
_REFUND_DESCRIPTION_PREFIX: dict[InvoiceDirection, str] = {
    InvoiceDirection.outgoing: "Satış iade faturası",
    InvoiceDirection.incoming: "Alış iade faturası",
}

_ZERO = Decimal("0")


def description_for(invoice: Invoice) -> str:
    """`Satış faturası FIL2026000184 — Güneşkent İnşaat A.Ş.`

    Taraf adı faturanın SNAPSHOT'undan (`party_name`) okunur, cari kartından
    DEĞİL (K7): kart sonradan düzeltilse bile fişin metni faturayı anlatmalıdır.
    """
    onek = (_REFUND_DESCRIPTION_PREFIX if is_refund(invoice) else _DESCRIPTION_PREFIX)[
        invoice.direction
    ]
    return f"{onek} {invoice.invoice_no} — {invoice.party_name}"


def _outgoing_lines(invoice: Invoice) -> list[PostingLine]:
    return [
        PostingLine(role_key=ROLE_RECEIVABLE, debit=invoice.total),
        PostingLine(role_key=ROLE_WITHHOLDING_RECEIVABLE, debit=invoice.withholding_amount),
        PostingLine(role_key=ROLE_REVENUE, credit=invoice.tax_base),
        PostingLine(role_key=ROLE_VAT_OUTPUT, credit=invoice.vat_amount),
    ]


def _incoming_lines(invoice: Invoice) -> list[PostingLine]:
    return [
        PostingLine(role_key=ROLE_EXPENSE, debit=invoice.tax_base),
        PostingLine(role_key=ROLE_VAT_INPUT, debit=invoice.vat_amount),
        PostingLine(role_key=ROLE_PAYABLE, credit=invoice.total),
        PostingLine(role_key=ROLE_WITHHOLDING_PAYABLE, credit=invoice.withholding_amount),
    ]


_BUILDERS = {
    InvoiceDirection.outgoing: _outgoing_lines,
    InvoiceDirection.incoming: _incoming_lines,
}


def _aynalanmis(satir: PostingLine) -> PostingLine:
    """Bacağın TARAFINI çevirir; TUTARINI değil.

    `role_key` DEĞİŞMEZ ve değişmemelidir: iade, satışın hesabını (`600`)
    BORÇLANDIRAN bir kayıttır — başka bir hesaba (ör. `610 Satıştan İadeler`)
    yazan bir uygulama `posting_rules`a YENİ SATIRLAR ve dolayısıyla bir
    migration isterdi; üstelik `vat_return`/mizan mutabakatı `600`ün netine
    baktığı için iki taban SESSİZCE ayrışırdı.
    """
    return PostingLine(role_key=satir.role_key, debit=satir.credit, credit=satir.debit)


def lines_for(invoice: Invoice) -> list[PostingLine]:
    """Faturanın bacakları — TUTARI SIFIR OLANLAR SÜZÜLÜR (modül docstring'i).

    Sıra SABİTTİR ve `sort_order`a birebir düşer: borç bacakları önce, alacak
    bacakları sonra. Sıra rastgele olsaydı aynı fatura iki koşuda farklı
    dizilmiş bir defter satırı üretirdi.

    ## 🔴 KRIT-IADE — İADE FATURASI AYNI YÖNÜN **TERSİNİ** YAZAR

    KRIT-IADE öncesi bu fonksiyon YALNIZ `direction`a dallanıyordu: bir iade
    faturası, aynı yöndeki normal bir faturayla BİREBİR AYNI fişi üretiyordu.
    Yani hasılatı/gideri ve cariyi AZALTMASI gereken belge onları ARTIRIYORDU
    ve fiş dengeli olduğu için mizan hiçbir şey görmüyordu (§4.6 damga vergisi
    kusurunun kardeşi: **dengeli bir fiş yanlış yönde de olabilir**).

    ### Neden AYNALAMA, neden STORNO DEĞİL

    `progress_payments/transitions.py`deki storno deseni (`posting.reverse_*`)
    buraya UYMAZ ve uyamaz, üç ölçülmüş sebeple:

    1. **Storno bir BELGENİN KENDİ fişini ters çevirir** — kaynağı
       `(source_type, source_id)` damgasıdır. İade AYRI bir belgedir ve kendi
       `invoices.id`sini taşır (`_source_id`); asıl faturanın damgasıyla
       çağrılsaydı `post_document`in idempotanlık dalına düşer, `created=False`
       döner ve HİÇBİR ŞEY yazmazdı.
    2. **İade KISMİ olabilir.** Storno orijinalin TAMAMINI nötrler; 1.000'lik
       satışın 400'lük iadesi bir stornoyla ifade EDİLEMEZ.
    3. **Ürün bu kararı ZATEN vermiştir**: `source_posting.py` *"Kesilmiş bir
       faturanın düzeltilmesi bu üründe İADE FATURASIDIR ve o ayrı bir
       belgedir; **kendi fişini kendisi yazar**"* der.

    ### Neden EKSİ TUTAR DEĞİL

    `ck_invoice_lines_quantity_positive` miktarı POZİTİF tutar: iade faturası
    eksi tutar TAŞIYAMAZ, yani ters yönü tutarın işareti DEĞİL yalnızca bacağın
    TARAFI ifade edebilir. Ayrıca `ck_journal_lines_single_side` eksi bacağı
    zaten reddederdi.

    Aynı kanonun Hazine'deki kardeşi `realized.realized_total_for_source`tır:
    orası da iadenin parasını `-Payment.amount` ile TERS yönde sayar.
    """
    satirlar = _BUILDERS[invoice.direction](invoice)
    if is_refund(invoice):
        # 🔴 Aynalama SIRAYI da bozar (borç bacakları alacak olur). Sıra
        # yeniden kurulur ki "borç önce" değişmezi İADEDE de tutsun; bozuk
        # bırakılsaydı `sort_order` bir belge tipinde başka türlü dizilir ve
        # defter okuyucusu aynı fişi iki farklı düzende görürdü.
        satirlar = sorted((_aynalanmis(satir) for satir in satirlar), key=_alacak_mi)
    return [satir for satir in satirlar if _doludur(satir)]


def _alacak_mi(satir: PostingLine) -> bool:
    """`sorted` anahtarı — `False` (borç) `True`dan (alacak) ÖNCE gelir.

    `sorted` KARARLIDIR: aynı taraftaki bacakların kendi aralarındaki sırası
    korunur, yani cari bacağı tevkifat bacağından önce kalır.
    """
    return satir.credit > _ZERO


def _doludur(satir: PostingLine) -> bool:
    """`(0, 0)` bacağı `ck_journal_lines_single_side`ı ihlal eder."""
    return satir.debit > _ZERO or satir.credit > _ZERO


async def post_invoice(
    session: AsyncSession, actor: User, invoice: Invoice
) -> PostingOutcome | None:
    """Faturayı fişler. `None` = *"fişlenecek para yok"* (toplamı sıfır fatura).

    🔴 COMMIT ETMEZ: çağıranın (`state_service.perform_transition`) kendi
    transaction'ında koşar. Faturanın durum damgası ile fiş AYNI transaction'da
    yazılmalıdır, aksi hâlde "gönderilmiş ama fişsiz" (ya da tersi) bir fatura
    doğardı.
    """
    lines: Sequence[PostingLine] = lines_for(invoice)
    if len(lines) < 2:
        return None

    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=_source_id(invoice),
        # 🔴 `issue_date` — geçişin koştuğu gün DEĞİL. Beyanname penceresi de
        # (`vat_return.month_bounds`) bu kolondan geçer; fiş başka bir güne
        # yazılsaydı aynı fatura iki AYRI ayın mizanı ile beyanına düşerdi.
        # KARAR-6'nın ayağı buradan sarkar: geçmiş aya kesilen bir fatura
        # kapalı dönemde 409 alır ve `send`/`approve` HİÇ GERÇEKLEŞMEZ.
        entry_date=invoice.issue_date,
        description=description_for(invoice),
        lines=lines,
    )


def _source_id(invoice: Invoice) -> uuid.UUID:
    """Damga faturanın KENDİ kimliğidir — kaynak kaydının (hakediş/sipariş) DEĞİL.

    Üye = TABLO (`JournalSourceType` docstring'i): `source_type='invoice'` ise
    `source_id` `invoices.id`dir. Kaynak kaydının kimliği yazılsaydı aynı
    hakedişten kesilen ikinci bir fatura tekillik kısıtına çarpar ve HİÇ
    fişlenemezdi.
    """
    return invoice.id
