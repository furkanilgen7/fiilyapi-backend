"""🔴 MU-3E — BORDRO TAHAKKUKUNUN FİŞİ (MU-3 zincirinin SON ailesi).

## 🔴 ŞEMA ÖLÇÜMÜ — görev emrinin premise'i KISMEN ÇÜRÜTÜLDÜ

Emir şöyle diyordu: *"`payroll_lines`ta `deduction_amount` TEK KOLON, SGK işçi
payı / işsizlik / damga ayrışmıyor; işveren primi hiçbir tabloda YOK →
doğru muhasebe fişi bugünkü şemayla YAZILAMAZ, bir migration BEKLENİYOR."*

**Kodda ölçülen durum:**

| Bileşen | Kolonu VAR MI | Türetilebilir Mİ | Kanonik türetim |
|---|---|---|---|
| brüt | ✅ `gross_amount` | — | — |
| gelir vergisi | ✅ **`income_tax_amount`** | — | IK3-GV'de AÇILDI |
| toplam kesinti | ✅ `deduction_amount` | — | — |
| net | ✅ `net_amount` | — | — |
| SGK işçi %14 | ❌ | ✅ | `compute.rate_share(brüt, sgk_employee_pct)` |
| işsizlik işçi %1 | ❌ | ✅ | `compute.rate_share(brüt, unemployment_employee_pct)` |
| damga %0,759 | ❌ | ✅ | kesintinin KALANI (aşağıda) |
| SGK işveren %20,5 | ❌ | ✅ | `compute.rate_share(brüt, sgk_employer_pct)` |
| işsizlik işveren %2 | ❌ | ✅ | `compute.rate_share(brüt, unemployment_employer_pct)` |
| kısa çalışma %1 | ❌ | ✅ | `compute.rate_share(brüt, short_work_pct)` |

👉 **Bileşenler ZATEN HESAPLANIYOR; yalnız SAKLANMIYORLAR.** Dahası, hepsinin
ÜRÜNDE ÇALIŞAN ve CANLIDA BASILAN kanonik bir türetimi var: `payroll/sgk.py`
(SGK bildirim ekranı) tam olarak bu yedi kalemi bu formüllerle üretiyor.

**Bu yüzden bu dilimde KESİNTİ KIRILIMI MIGRATION'I YAZILMADI.** Gerekçe üç
ölçüme dayanır:

1. **İş "hesabı icat etmek" değil.** Emir bunu zaten öngörüyordu ve cevap bu:
   var olan hesabın parçalarını KULLANMAK yeterlidir. Altı yeni kolon açmak,
   `compute.py`nin bugün ürettiği sayıları İKİNCİ KEZ saklamak olurdu — ve
   yeni bir kolon, eskisiyle sessizce çelişebilen İKİNCİ BİR GERÇEK KAYNAKTIR
   (bu deponun tekrar tekrar ölçtüğü kusur).
2. **`sgk.py` K6 dersi tam olarak bunu söylüyor.** Orada ölçülmüş kusur şuydu:
   SGK ekranı gelir vergisini `income_tax_pct × brüt` ile YENİDEN TÜRETİYORDU
   ve dilimli motor gelince bordro ekranıyla AYRIŞTI. Çare kolon açmak değil,
   **aynı kaynaktan okumak** oldu. Fiş de aynı kaynaktan okur; mutabakat
   böylece KURULUŞ GEREĞİ tutar, bir tesadüf olarak değil.
3. **Snapshot sorusunun cevabı MU-3D'de verilmişti:** *"snapshot FİŞİN
   KENDİSİDİR"*. `journal_lines.debit`/`credit` yazıldığı anda DONAR. Oranlar
   sonradan düzeltilse SGK ekranı yeni sayı gösterir ama MİZAN onayın alındığı
   andaki gerçeği gösterir — ve doğru olan budur (MK-2 kanonunun bu aile için
   zaten seçilmiş hâli).

⚠️ `payroll_lines`a `project_id` YOKTUR ve bu dilimde EKLENMEZ (KARAR-4): o
yüzden gider `730`e yazılır, `720`ye değil — direkt/endirekt işçilik ayrımının
DAYANAĞI yoktur. `journal_entries`te de `project_id` yoktur (şema değişmez).

## 🔴 FİŞ NE ZAMAN DOĞAR — `transitions.py`den ÖLÇÜLDÜ

    draft ──approve──▶ pending_approval ──approve──▶ approved ──pay──▶ paid

Mali olarak BAĞLAYICI olan geçiş **BİRDİR**: `pending_approval ──▶ approved`.

* **`compute`** para taşımaz: satırları ÜRETİR ve yeniden koşulabilir. Fişlense
  her yeniden hesap mizanı oynatırdı.
* **`draft → pending_approval`** bir iş akışı adımıdır (`approve_period` TEK
  ADIM ilerletir, S8). Burada henüz onay YOKTUR.
* **`approved`** kilidin düştüğü andır: `LOCKED_PERIOD_STATUSES` bu durumdan
  itibaren `compute`u, satır düzenlemesini ve satır onay değişikliğini KAPATIR.
  Tutarlar bu an DONAR — tahakkuk tam olarak buradadır.

### 🔴 `pay` FİŞ ATMAZ ve bu bir eksiklik DEĞİL, bir ÖLÇÜMDÜR

MU-3C kanonu: *"nakit/gider bacağı GEÇİŞE DEĞİL BELGEYE bağlanır; bir geçiş
para taşımıyorsa ondan fiş çıkmaz."* `pay_period` ÖLÇÜLDÜ:

* **`payments` satırı YAZMAZ.** `payments.invoice_id` **NOT NULL** ve
  `invoices.id`ye FK'dir — bir bordro dönemi o tabloya YAPISAL OLARAK giremez.
* **Banka hesabı ALMAZ.** Ucun gövdesi yoktur; `bank_account_id`, tutar ve
  ödeme günü hiçbir yerde İSTENMEZ. Nakit bacağının üç girdisi de YOKTUR.
* Kendi docstring'i bunu yazıyor: *"Dış sistem entegrasyonu YOKTUR: bu uç bir
  DAMGADIR, EFT talimatı GÖNDERMEZ."*

Yani `pay`den fiş atmak, olmayan bir banka hesabını UYDURMAK olurdu.
⚠️ Bunun bilinen bedeli: `335 Personele Borçlar` defterde AÇIK KALIR.
Kapatılması ödeme ucuna banka hesabı eklemeyi gerektirir — bir ÜRÜN
KARARIDIR, bir kod tercihi değil. Raporun `KAPSAM DIŞI` başlığındadır.

## 🔴 ÇİFT SAYIM — `excluded` (TAŞERON) SATIR FİŞE GİRMEZ

Bu dilimin en büyük riski ve en kolay kaçırılacak kusuru budur.

`summary.py` İKİ AYRI TABAN tanımlar ve fiş **ÖDEME TABANINI** kullanır
(`PAYABLE_LINE_STATUSES`), MALİYET tabanını DEĞİL. Sebep ölçüldü:

* `excluded` satır TAŞERON işçisidir; ücreti bordrodan ÖDENMEZ, taşerona
  **hakediş üzerinden** ödenir (K2, `transitions.py`de yapısal olarak kapalı);
* o hakediş **MU-3D'de ZATEN FİŞLENİYOR** (`subcontractor_progress_payment` →
  `740` gider + `320` cari).

Maliyet tabanı seçilseydi aynı emek İKİ KEZ gider yazılırdı: bir kez `730`e
(bordrodan), bir kez `740`a (hakedişten). Fiş yine DENGELİ olurdu ve mizan
DOĞRU görünürdü — bu yüzden bekçi sonucu değil, DEĞİŞMEMESİ gerekeni ölçer
(`test_mu3e_cift_sayim.py`, MU-3C'nin `..._GIDER_ve_HASILAT_hesaplarina_
DOKUNMAZ` deseninin kardeşi).

🔴 Aynı sebeple SGK tabanı da KULLANILMAZ: `sgk.build_sgk_summary` taşeron
satırını BİLEREK içerir (bildirim bir ödeme değildir). Doğru bir SGK
bildirimi ile doğru bir yevmiye fişi AYNI KÜME ÜZERİNDE TANIMLI DEĞİLDİR.

## BACAKLAR ve DENGENİN YAPISAL OLUŞU

    B 730 Genel Üretim Giderleri              = Σ brüt + Σ işveren üçlüsü
    A 335 Personele Borçlar                   = Σ net
    A 360 Ödenecek Vergi ve Fonlar            = Σ gelir vergisi + Σ damga
    A 361 Ödenecek Sosyal Güvenlik Kesintileri = Σ (işçi ikilisi + işveren üçlüsü)

Denge YAPISALDIR ve bir aritmetik tesadüf değildir:

    net        = brüt − (SGK işçi + işsizlik işçi + gelir vergisi + damga)
    Σ alacak   = net + (gv + damga) + (SGK işçi + işsizlik işçi) + işveren üçlüsü
               = brüt + işveren üçlüsü
               = Σ borç                                                    ∎

🔴 Bu ancak **damga KESİNTİNİN KALANI olarak** türetilirse tutar
(`_stamp_share`, `sgk.py`nin K6 deseniyle BİREBİR aynı formül). Damga
`stamp_tax_pct × brüt` ile yeniden türetilseydi asgari ücret damga
istisnasını GÖREMEZ ve fiş DENGESİZ çıkardı — K1 kapısı 422 verir ve dönem
ONAYLANAMAZDI. Yani bu tercih bir kolaylık değil, bir ZORUNLULUKTUR.

## 🔴 FAIL-CLOSED: bileşeni EKSİK olan dönem FİŞLENMEZ (422)

`income_tax_amount` IK3-GV'den ÖNCE hesaplanmış satırlarda **`NULL`**dur.
Böyle bir satırın neti `335`e girer ama gelir vergisi ve damgası `360`a
GİREMEZ — fiş DENGESİZ olur. `sgk.py` böyle satırı `unknown_tax_count`ta
gösterip prim kalemlerinde TUTAR (ekranın asıl işi primdir); fiş **TUTAMAZ**:
bir yevmiye fişinin yarısı olmaz.

Aynı şey oran seti bulunamayan satır için de geçerlidir (ŞEF KARARI 2).

Eksiği 0 sayıp dengeyi tutturmak, bilinmeyen bir vergiyi "vergi yok" diye
deftere yazmak olurdu — para sınıfı bir yalan (NULL-EŞİK kanonu). Bedeli
bilinerek alınmıştır: böyle bir dönem ONAYLANAMAZ ve kullanıcı önce
`compute`u yeniden koşar.

## KARAR-1 / KARAR-2 / KARAR-3 / KARAR-5 / KARAR-6

* **KARAR-1** — `170`/`350` ÖLÜ; bu ailede hiç geçmez.
* **KARAR-2** — bu aile CARİ hesaba (`320`/`120`) HİÇ DOKUNMAZ: personele
  borç `335`tir, satıcıya borç değil. ⚠️ MU-4 mayını bu aileyi ETKİLEMEZ.
* **KARAR-3** — fiş `posted` doğar (`post_document`).
* **KARAR-5** — geri alma STORNODUR; ama 🔴 **BU AİLEDE TETİKLEYİCİSİ
  YOKTUR** ve bu ölçüldü: `PERIOD_TRANSITIONS` DOĞRUSAL ve TEK YÖNLÜDÜR,
  `approved`tan geri dönen HİÇBİR çift yoktur (`paid` de kaynak değildir).
  Bir `reverse_payroll_period` YAZILMADI: çağıranı olmayan kod bekçisizdir
  ve okuyucuya var olmayan bir geri alma yolu varmış gibi gösterirdi.
* **KARAR-6** — dönem kapısı `post_document`tedir; fiş AYIN SON GÜNÜNE yazılır
  (aşağıda).

## 🔴 `entry_date` — AYIN SON GÜNÜ, `approved_at` DEĞİL

İki sebep:

1. **Muhasebe olarak doğru olan budur.** Bordro tahakkuku AY SONUNDA doğar;
   onayın hangi gün tıklandığı bir iş akışı ayrıntısıdır. Temmuz bordrosu
   Ağustos'ta onaylansa bile gideri TEMMUZ'a aittir.
2. **🔴 YEREL TAKVİM KAÇAĞI böylece YAPISAL OLARAK imkânsızdır.**
   `approved_at` bir `timestamptz`tir ve üzerinde ham `.date()` çağırmak
   (TR = UTC+3) gece 00:00-03:00 arasında basılan damgayı BİR GÜN GERİYE, ay
   sınırında ÖNCEKİ AYIN mizanına, hatta KAPALI bir döneme düşürürdü (MU-3D'de
   gerçek kusur olarak bulundu). `core.month_bounds` saf bir `date` üretir:
   ortada dönüştürülecek bir zaman damgası YOKTUR.

KARAR-6'nın ayağı buradan sarkar: o ayın muhasebe dönemi KAPALIYSA
`post_document` **409** verir ve dönem ONAYLANAMAZ. İstenen budur — kapalı bir
ayın mizanını sessizce oynatan bir onay KARAR-6'yı delerdi.

## KARAR-4 · hesap kodları

Kodlar BU DOSYADA DEĞİL `posting_rules` tablosundadır; aşağıdaki
`PAYROLL_POSTING_RULES` yalnız TOHUMUN kaynağıdır.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PayrollValidationError
from app.modules.accounting.models import JournalSourceType
from app.modules.payroll import compute, summary
from app.modules.payroll.models import PayrollLine, PayrollPeriod, PayrollRate
from app.modules.payroll.service.core import month_bounds
from app.modules.posting import service as posting_service
from app.modules.posting.service import PostingLine, PostingOutcome
from app.modules.site_diary.models import WorkerSource
from app.modules.users.models import User

__all__ = [
    "INCOMPLETE_LINES",
    "PAYROLL_POSTING_RULES",
    "ROLE_PERSONNEL_EXPENSE",
    "ROLE_PERSONNEL_PAYABLE",
    "ROLE_SOCIAL_SECURITY_PAYABLE",
    "ROLE_TAX_PAYABLE",
    "SOURCE_TYPE",
    "PostingTotals",
    "description_for",
    "lines_for",
    "post_payroll_period",
    "postable_lines",
    "totals_for",
]

#: `journal_entries.source_type` üyesi — üye = TABLO (`payroll_periods`).
#: 🔴 MU-3A'da AÇILMIŞTI ve bugüne kadar hiçbir kod onu kullanmadı; bu dosya ilk
#: kullanıcıdır. Dolayısıyla bu dilimde `ALTER TYPE … ADD VALUE` GEREKMEZ ve
#: MU-3D'nin "enum ekleme ile tohum AYRI migration olmak zorundadır" tuzağı
#: buraya hiç UĞRAMAZ: tohum TEK migration'dır.
SOURCE_TYPE = JournalSourceType.payroll_period

# --------------------------------------------------------------------------- #
# BACAK ROLLERİ
#
# 🔴 `expense` DEĞİL `personnel_expense`. Öteki ailelerin `expense` rolü `740`ı
# gösterir; bu aileninki `730`u (KARAR-4). `posting_rules`ın anahtarı
# `(source_type, role_key)` olduğu için teknik bir çakışma OLMAZDI — ama aynı
# adı taşımaları okuyucuya AYNI hesabı gösterdiklerini İMA EDERDİ ve MU-3C'nin
# yazılı kuralı tam tersidir: aynı ad ancak AYNI hesap için kullanılır.
#
# `payable` de DEĞİL `personnel_payable`: `320 Satıcılar` ile `335 Personele
# Borçlar` iki ayrı yükümlülüktür ve ikisi de mizanda "Kısa Vadeli Yabancı
# Kaynaklar" altında toplanır — tek rol adı altında karışsalardı toplam TUTMAYA
# DEVAM EDER, yani kusur GÖRÜNMEZDİ (MU-3C'nin `bank`/`cash` ayrımının aynı
# gerekçesi).
# --------------------------------------------------------------------------- #

ROLE_PERSONNEL_EXPENSE = "personnel_expense"
ROLE_PERSONNEL_PAYABLE = "personnel_payable"
ROLE_TAX_PAYABLE = "tax_payable"
ROLE_SOCIAL_SECURITY_PAYABLE = "social_security_payable"

#: 🔴 TOHUMUN KAYNAĞI — `(role_key, hesap kodu)`. ÇALIŞMA ZAMANI EŞLEMESİ
#: DEĞİLDİR: `post_document` hesabı DAİMA `posting_rules` tablosundan okur.
#: İki katmanın birebir aynı olduğunu bir test AST ile iddia eder (MU-3B deseni).
#:
#: 🔴 `vat_input`/`vat_output` YOKTUR ve olamaz: bordro KDV TAŞIMAZ. Rolleri
#: tanımlı olmadığı için `post_document` onları ÇÖZEMEZ — bordroya KDV yazmak
#: tip/veri düzeyinde imkânsızdır, bir kod nezaketi değil. Gerekçe MU-3D ile
#: aynı: `accounting.vat_return` beyannameyi YALNIZ `invoices`tan türetir ve
#: "beyanname == yevmiye" kimliği kuruş toleransı olmadan iddia edilir.
PAYROLL_POSTING_RULES: tuple[tuple[str, str], ...] = (
    (ROLE_PERSONNEL_EXPENSE, "730"),
    (ROLE_PERSONNEL_PAYABLE, "335"),
    (ROLE_TAX_PAYABLE, "360"),
    (ROLE_SOCIAL_SECURITY_PAYABLE, "361"),
)

#: 422 — bileşeni eksik satır. Metin SAYI taşır (ad değil): bir bordro fişinin
#: hata mesajında personel adı geçseydi, yetkisi olmayan bir okuyucuya ücret
#: bilgisi sızdıran bir kanal açılırdı.
INCOMPLETE_LINES = (
    "Bordro fişi yazılamıyor: tutarları ya da oran seti eksik ödenebilir satır var "
    "(dönemi yeniden hesaplayın)"
)

_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class PostingTotals:
    """Fişin DÖRT bacağının yedi bileşeni. DONMUŞTUR.

    Bacaklar DEĞİL BİLEŞENLER taşınır: `730`un `brüt + işveren üçlüsü` olduğu
    tek yerde (`lines_for`) yazılıdır ve bu yapı, mutabakat testinin bacakları
    KIRILIMLI karşılaştırabilmesini sağlar. Doğrudan dört tutar taşınsaydı bir
    eşleme hatası (`361`e yazılması gerekeni `360`a yazmak) toplamı DEĞİŞTİRMEZ
    ve hiçbir test kırmızıya dönmezdi.
    """

    gross: Decimal
    net: Decimal
    income_tax: Decimal
    stamp_tax: Decimal
    sgk_employee: Decimal
    unemployment_employee: Decimal
    sgk_employer: Decimal
    unemployment_employer: Decimal
    short_work: Decimal

    @property
    def employer_burden(self) -> Decimal:
        """İşverenin brütün ÜSTÜNE eklediği üç kalem (SGK 79-81).

        🔴 `compute.total_employer_cost` KULLANILMAZ ve bu bilinçli bir
        AYRIŞMADIR: o fonksiyon üç YÜZDEYİ toplayıp TEK KEZ yuvarlar
        (`brüt × %23,5`), bu toplam ise üç kalemi AYRI AYRI yuvarlayıp toplar
        (`sgk.py` ile aynı). İkisi bir kuruş ayrışabilir ve fiş, `361`e AYRI
        AYRI yazılan kalemlerle DENGEDE olmak zorundadır — dolayısıyla burada
        kalemlerin toplamı KULLANILMAK ZORUNDADIR.

        ⚠️ Bu, `summary.total_employer_cost` (BY 92 kartı) ile bordro fişinin
        gider bacağının bir kuruş ayrışabileceği anlamına gelir. Ürünün ÖNCEDEN
        VAR OLAN bir tutarsızlığıdır (iki ekran zaten iki formül kullanıyor) ve
        bu dilimde DÜZELTİLMEZ: bir fişleme dilimi bordro aritmetiğini
        değiştirmez. Raporun `KAPSAM DIŞI` başlığındadır.
        """
        return self.sgk_employer + self.unemployment_employer + self.short_work

    @property
    def social_security_payable(self) -> Decimal:
        """`361` — işçi İKİLİSİ + işveren ÜÇLÜSÜ.

        🔴 İşveren payları da BURAYA girer: `361 Ödenecek Sosyal Güvenlik
        Kesintileri` kuruma ödenecek primin TAMAMIDIR, yalnız işçiden kesilen
        kısım değil. İşveren payı `730`a borç yazılıp `361`e alacak
        yazılmasaydı fiş dengesiz kalırdı — işverenin gideri bir yükümlülük
        doğurmadan var olamaz.
        """
        return self.sgk_employee + self.unemployment_employee + self.employer_burden


def postable_lines(lines: list[PayrollLine]) -> list[PayrollLine]:
    """Fişe giren satırlar — ÖDEME tabanı (modül docstring'i, çift sayım).

    🔴 Küme `summary.PAYABLE_LINE_STATUSES`ten İTHAL EDİLİR, buraya elle
    `{pending, approved, paid}` diye YAZILMAZ: iki liste zamanla ayrışır ve
    hazine kartı (`payable.payable_net_totals_by_period`) ile yevmiyedeki
    `335` bakiyesi aynı dönem için farklı para gösterirdi — mutabakat testinin
    tam olarak ölçtüğü kimlik budur.
    """
    return [line for line in lines if line.status in summary.PAYABLE_LINE_STATUSES]


def _stamp_share(line: PayrollLine, rate: PayrollRate) -> Decimal:
    """Damga vergisi = KESİNTİNİN KALANI (`sgk.py` K6 formülüyle BİREBİR).

    🔴 `stamp_tax_pct × brüt` ile TÜRETİLMEZ. `compute` kesintiyi tam olarak
    DÖRT kalemin toplamı olarak kurar (`compute.Deductions.total`), bu yüzden
    fark KURUŞUNA KADAR damgadır **ve asgari ücret damga istisnasını
    KENDİLİĞİNDEN görür** — istisnalı bir satırda orandan türetilen damga
    gerçekte kesilmemiş bir vergiyi deftere yazardı ve fiş DENGESİZ çıkardı.
    """
    return (
        line.deduction_amount
        - compute.rate_share(line.gross_amount, rate.sgk_employee_pct)
        - compute.rate_share(line.gross_amount, rate.unemployment_employee_pct)
        - line.income_tax_amount
    )


def _eksik(line: PayrollLine, rate: PayrollRate | None) -> bool:
    """Satırın fişe girmesini ENGELLEYEN eksiklik var mı (fail-closed).

    Dördü de AYRI AYRI ölçülür ve hiçbiri 0'a çevrilmez: `None`, "hesaplanamadı"
    demektir, "sıfır" değil (NULL-EŞİK kanonu).
    """
    return rate is None or None in (
        line.gross_amount,
        line.net_amount,
        line.deduction_amount,
        line.income_tax_amount,
    )


def totals_for(lines: list[PayrollLine], rates: dict[WorkerSource, PayrollRate]) -> PostingTotals:
    """Ödenebilir satırların YEDİ bileşenini toplar. Eksik varsa **422**.

    🔴 Aritmetik burada YENİDEN YAZILMAZ: her prim kalemi `compute.rate_share`
    üzerinden geçer — brütü oranla çarpıp yuvarlamanın TEK tanımı orasıdır.
    İkinci bir çarpma yazılsaydı aynı kişi için bordro ekranı, SGK ekranı ve
    yevmiye fişi bir kuruş ayrışabilirdi.

    `rates` **DÖNEMİN YILINA** ait aktif orandır (`service.rates_by_source`),
    bugünün yılı değil (S2): geçmiş bir dönemin fişi bu yılın oranıyla
    yazılamaz.
    """
    toplam = dict.fromkeys(
        (
            "gross",
            "net",
            "income_tax",
            "stamp_tax",
            "sgk_employee",
            "unemployment_employee",
            "sgk_employer",
            "unemployment_employer",
            "short_work",
        ),
        _ZERO,
    )
    for line in postable_lines(lines):
        rate = rates.get(line.personnel_source)
        if _eksik(line, rate):
            raise PayrollValidationError(INCOMPLETE_LINES)
        toplam["gross"] += line.gross_amount
        toplam["net"] += line.net_amount
        toplam["income_tax"] += line.income_tax_amount
        toplam["stamp_tax"] += _stamp_share(line, rate)
        for alan, oran_alani in (
            ("sgk_employee", "sgk_employee_pct"),
            ("unemployment_employee", "unemployment_employee_pct"),
            ("sgk_employer", "sgk_employer_pct"),
            ("unemployment_employer", "unemployment_employer_pct"),
            ("short_work", "short_work_pct"),
        ):
            toplam[alan] += compute.rate_share(line.gross_amount, getattr(rate, oran_alani))
    return PostingTotals(**toplam)


def lines_for(totals: PostingTotals) -> list[PostingLine]:
    """DÖRT bacak — sıra SABİTTİR (borç önce, alacak sonra).

    Tutarı SIFIR olan bacak SÜZÜLÜR (`invoicing.posting.lines_for` deseni):
    `ck_journal_lines_single_side` `(0, 0)` bacağını reddeder. Süzgeç burada
    GERÇEKTEN koşar ve bir kolaylık değildir — 2026 tohumunda asgari ücret
    istisnası 9.000₺ brütün gelir vergisinin TAMAMINI karşılar ve damga da
    istisnalıdır, yani `360` bacağı **sıfır olur**. Süzgeç olmasaydı sıradan
    bir bordro dönemi 422 alır ve ONAYLANAMAZDI.
    """
    bacaklar = [
        PostingLine(role_key=ROLE_PERSONNEL_EXPENSE, debit=totals.gross + totals.employer_burden),
        PostingLine(role_key=ROLE_PERSONNEL_PAYABLE, credit=totals.net),
        PostingLine(role_key=ROLE_TAX_PAYABLE, credit=totals.income_tax + totals.stamp_tax),
        PostingLine(role_key=ROLE_SOCIAL_SECURITY_PAYABLE, credit=totals.social_security_payable),
    ]
    return [satir for satir in bacaklar if satir.debit > _ZERO or satir.credit > _ZERO]


def description_for(period: PayrollPeriod) -> str:
    """`07/2026 Bordrosu`.

    🔴 TUTAR metne GİRMEZ (HZ-1 kanonu): metin donmuş bir kopyadır ve fişin
    kendi kolonlarıyla çelişebilirdi. Ay ADI da yazılmaz — bu depoda Türkçe ay
    adlarının TEK KOPYA bir kaynağı YOKTUR (ölçüldü) ve burada bir liste
    açmak, bir gün ikinci bir listeyle ayrışacak bir sabit üretirdi.
    """
    return f"{period.month:02d}/{period.year} Bordrosu"


async def post_payroll_period(
    session: AsyncSession,
    actor: User,
    period: PayrollPeriod,
    lines: list[PayrollLine],
    rates: dict[WorkerSource, PayrollRate],
) -> PostingOutcome | None:
    """Dönemin tahakkukunu fişler. `None` = *"fişlenecek para yok"*.

    🔴 COMMIT ETMEZ: çağıranın (`service.approve_period`) kendi transaction'ında
    koşar. Dönemin durum damgası ile fiş AYNI transaction'da yazılmalıdır, aksi
    hâlde "onaylı ama fişsiz" (ya da tersi) bir bordro doğardı.

    🔴 `None` iki meşru hâli birden taşır: ödenebilir satırı olmayan dönem ve
    tutarların tamamı sıfır olan dönem. İkisi de 422 OLMAMALIDIR — 422
    kullanıcının ONAYINI bloklardı ve satırsız/sıfır bir dönem normal hâldir.
    Bileşeni EKSİK dönem ise 422'dir (`totals_for`) ve o normal hâl DEĞİLDİR.

    🔴 `lines` ve `rates` DIŞARIDAN verilir, burada okunmaz: çağıran onları
    dönem kilidinin (`_lock_period`) ALTINDA ve `FOR UPDATE` ile zaten
    okumuştur. Buradan ikinci bir okuma açılsaydı kilidin dışına düşer ve
    fiş, onaylanan satırlardan BAŞKA bir kümeyi tutarlayabilirdi.
    """
    bacaklar = lines_for(totals_for(lines, rates))
    if len(bacaklar) < 2:
        return None
    # 🔴 AYIN SON GÜNÜ — `approved_at.date()` DEĞİL (modül docstring'i:
    #    yerel takvim kaçağı yapısal olarak imkânsız kılınır).
    _, ay_sonu = month_bounds(period.year, period.month)
    return await posting_service.post_document(
        session,
        actor,
        source_type=SOURCE_TYPE,
        source_id=period.id,
        entry_date=ay_sonu,
        description=description_for(period),
        lines=bacaklar,
    )
