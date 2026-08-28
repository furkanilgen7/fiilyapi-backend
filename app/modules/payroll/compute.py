"""Bordro hesabının TEK KAYNAĞI — saf, yan etkisiz fonksiyonlar (İK-3 T2).

Spec: `docs/superpowers/specs/2026-08-13-ik3-bordro-design.md` (K1/K3, S1-S7).
`personnel/leave.py` ve `inventory/balance.py` kardeşidir: DB'ye DOKUNMAZ,
kapsam kararı VERMEZ (onu `service.py` verir), yalnız bir personelin bir aylık
satırını hesaplar. İkinci bir formül yazılsaydı ekran, Excel ve SGK özeti aynı
kişi için farklı sayı gösterir ve hangisinin doğru olduğu anlaşılamazdı.

## Zincir

    gün (puantaj) → brüt (ücret tipi) → kesinti (oran seti + TARİFE) → net → bölüşüm

🔴 **IK3-GV (2026-08-17) zinciri AYRIŞTIRDI.** Önceden dört işçi oranı tek
yüzdede toplanıp (%25,759) tek çarpım yapılıyordu ve **gelir vergisi hesabın
hiçbir yerinde ayrı bir `Decimal` olarak var olmuyordu.** GVK m.103 artan
oranlıdır ve KÜMÜLATİF matraha göre işler; dilimli vergi brütün sabit bir
yüzdesi olmadığı için "tek toplam yüzde" yaklaşımı YAPISAL OLARAK kullanılamaz
hâle geldi. Kesinti artık dört ayrı kalemdir (`Deductions`) ve gelir vergisi
`income_tax.py`den, satırın YIL-İÇİ konumuyla (`TaxContext`) birlikte gelir.

Her halka bir öncekine bağlıdır ve **her halka fail-closed'dur**: hesaplanamayan
bir değer `null` kalır, UYDURMA 0 BASILMAZ (S4 · NULL-EŞİK kanonu, WORKFLOW §4).
Uydurma 0, eksik veriyi "ödenecek bir şey yok" gibi gösterirdi — para sınıfı yalan.

## Bu dosyanın taşıdığı bağlanmış kararlar

* **Kesinti = yalnız İŞÇİ payları.** İşveren primleri (`sgk_employer_pct` ·
  `unemployment_employer_pct` · `short_work_pct`) işçinin kesintisi DEĞİL,
  işverenin maliyetidir (spec §7: `toplam_maliyet = brüt + üç işveren kalemi`).
  İkisini karıştırmak neti yanlış hesaplardı.
* **🔴 ŞEF KARARI 1 — `hourly` FAIL-CLOSED (⚠️ ARTIK GEÇİCİ).** Kararın
  dayanağı "puantajda çalışma SAATİ yoktur" idi; **PUAN-SAAT bu dayanağı
  kaldırdı** — `timesheet_entries.hours` artık günlük çalışma saatidir. Yol
  yine de bu dilimde AÇILMADI: saatlik ücret yolu FM'in %50 zammını
  (mockup E5 358 "× saatlik ücret × 1,5") ve haftalık 45 tavanını bordroya
  taşımayı gerektirir, bu ise PUAN-SAAT-2'nin işidir. O gelene kadar sabit
  İCAT ETMEK yasaktır (WORKFLOW §3) → satır `uncomputed`.
* **🔴 YÖNETİM KARARI (T4b) — puantaj KAYDI olmayan personel FAIL-CLOSED,
  ÜÇ ÜCRET TİPİNDE DE.** Dönemde personele ait HİÇ `timesheet_entries` kaydı
  yoksa "bu ay hiç çalışmadı" ile "puantajı henüz girilmedi" veritabanında
  AYIRT EDİLEMEZ; ikisi de brüt 0 üretseydi veri eksikliği "ödenecek bir şey
  yok" gibi görünürdü. `monthly` DE dâhildir: "aylık ücretlide gün brütü
  etkilemez" varsayımı, işe hiç başlamamış ya da çıkmış personele sessizce tam
  maaş hesaplamayı meşrulaştırırdı. ⚠️ Bu kural KAYDIN VARLIĞINA bakar, gün
  SAYISINA değil: kaydı olan ama tüm günleri izin/tatil KODLU (saatsiz)
  personelde gün 0 GERÇEKTİR — veri girilmiştir, hesap yapılır. Kuralın
  çıkışı K3 override'ıdır (`uncomputed → pending`), yoksa bordro kilitlenirdi.
* **🔴 ŞEF KARARI 2 — oran seti yoksa FAIL-CLOSED.** `(yıl, tip)` için satır
  yoksa (`general` tipi personel; ya da seti henüz girilmemiş bir yıl) kesintiyi
  0 varsaymak "kesinti yok" yalanı olurdu → satır `uncomputed`.
* **🔴 ŞEF KARARI 3 — varsayılan bölüşüm HEPSİ BANKA** (`mixed`/NULL dahil).
  BY 143/163/259/287'de banka input'u dolu, elden 0; nakit yalnız taşeron
  satırlarında (BY 194/214/234) ve onlar zaten `excluded`. Elden nakit
  varsayılanı üretmek DENETLENMEMİŞ nakit çıkışı önerirdi.
* **🔴 ŞEF KARARI 4 — mesai brüte OTOMATİK EKLENMEZ.** BY 110-118 tablo
  başlığında mesai sütunu YOKTUR ve K3 mesaiyi açıkça override yoluna bağlar
  ("mesai/ikramiye/avans"). Fazla mesaili gün `worked_day_clause` gereği GÜN
  olarak sayılır (`matrix.py`), saati ayrıca paraya çevrilmez — çevrilseydi aynı
  mesai hem gün hem saat olarak iki kez ödenirdi. PUAN-SAAT sonrası FM bir kolon
  değil TÜREVDİR; bordroya taşınması PUAN-SAAT-2'nin işidir.
* **K2 — taşeron satırı YAPISAL olarak ödemeye giremez.** Durum HER ZAMAN
  `excluded`tır (hesap yapılabilse de yapılamasa da); tutarlar yine hesaplanır
  çünkü satır görünür ve MALİYETE girer (BY 186-189). Ödemesi hakediş üzerinden
  taşerona yapılır — çift ödeme yapısal olarak imkânsızdır.

## Kuruş

Yuvarlama TEK YERDEDİR (`quantize_money`, `ROUND_HALF_UP`, iki ondalık) ve
zincirin sırası ANLAMLIDIR: brüt ve kesinti yuvarlanır, **net onların FARKIDIR**,
bölüşüm de **netten** türer. Net bağımsız yuvarlansaydı ya da bölüşüm brütten
hesaplansaydı `banka + elden` netten bir kuruş kayar ve T3'teki S3 kapısı
422'ye düşerdi.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.payroll import income_tax as income_tax_engine
from app.modules.payroll.models import PayrollLineStatus, PayrollRate
from app.modules.personnel.models import PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource

#: Kuruş adımı — `Numeric(12,2)` ile aynı ölçek (models.py `MONEY_SCALE`).
MONEY_QUANTUM = Decimal("0.01")

#: Oranlar YÜZDEDİR (`14.000` = %14), katsayı değil.
PERCENT_DIVISOR = Decimal("100")

ZERO_MONEY = Decimal("0.00")

#: Kesintiye giren İŞÇİ payları (SGK 70-73).
EMPLOYEE_RATE_FIELDS = (
    "sgk_employee_pct",
    "unemployment_employee_pct",
    "income_tax_pct",
    "stamp_tax_pct",
)

#: İŞVEREN payları (SGK 79-81) — kesintiye GİRMEZ, `toplam_maliyet`e girer
#: (spec §7). Burada durur ki T3/T5 ayrımı yeniden KARAR VERMESİN ve yeni bir
#: oran sütunu eklendiğinde hangi tarafa yazılacağı tek yerde görünsün.
EMPLOYER_RATE_FIELDS = (
    "sgk_employer_pct",
    "unemployment_employer_pct",
    "short_work_pct",
)

#: K2 — sessiz atlama yoktur (WORKFLOW §3): satırın niçin ödemeye girmediği yazılır.
SUBCONTRACTOR_EXCLUDED_REASON = (
    "Taşeron işçisi: ödemesi taşeron hakedişi üzerinden yapılır, bordrodan ödenmez"
)


def quantize_money(value: Decimal) -> Decimal:
    """Para yuvarlamasının TEK tanımı: iki ondalık, `ROUND_HALF_UP`.

    Python'un `Decimal` varsayılanı `ROUND_HALF_EVEN`dir ve 1,005'i 1,00'e
    indirirdi — bordroda her ay sistematik bir kuruş kaybı, banka mutabakatında
    görünen bir fark. Her para çıktısı BU fonksiyondan geçer; ikinci bir
    `.quantize(...)` çağrısı koda serpilirse iki yuvarlama kuralı doğar.
    """
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def employee_deduction_pct(rate: PayrollRate) -> Decimal | None:
    """İşçiden kesilen toplam yüzde — SGK 70-73'ün toplamı.

    🔴 **IK3-GV: BU FONKSİYON ARTIK NETİ HESAPLAMAZ.** Dilimli vergi brütün
    sabit bir yüzdesi DEĞİLDİR (aynı brüt, yılın hangi ayında olduğuna göre
    farklı vergi üretir) — "tek toplam yüzde" yaklaşımı yapısal olarak
    kullanılamaz hâle geldi ve zincir `employee_deductions`ta AYRIŞTIRILDI.
    Burası yalnız oran setinin KENDİSİNİ tarif eden bir görünüm olarak kalır
    (şema doğrulaması, oran ekranı) ve dilimli rejimde **`None`** döner:
    "toplam yüzde" o rejimde TANIMSIZDIR ve 0 dönmek "kesinti yok" yalanı
    olurdu (NULL-EŞİK kanonu).

    İşveren sütunları KASTEN dışarıdadır (`EMPLOYER_RATE_FIELDS`): onlar
    maliyettir, kesinti değildir (spec §7).
    """
    degerler = [getattr(rate, alan) for alan in EMPLOYEE_RATE_FIELDS]
    if any(deger is None for deger in degerler):
        return None
    return sum(degerler, Decimal("0"))


def employer_burden_pct(rate: PayrollRate) -> Decimal:
    """İşverenin brüt üzerine EKLEDİĞİ toplam yüzde — SGK 79-81 (4a'da %23,5).

    `employee_deduction_pct`in aynadaki eşi ve ondan KESİN olarak ayrıdır:
    biri işçinin cebinden çıkanı, öteki işverenin cebinden çıkanı ölçer. İkisi
    tek fonksiyonda toplansaydı net de maliyet de yanlış çıkardı.
    """
    return sum((getattr(rate, alan) for alan in EMPLOYER_RATE_FIELDS), Decimal("0"))


def total_employer_cost(gross_amount: Decimal | None, rate: PayrollRate | None) -> Decimal | None:
    """İşverene toplam maliyet — **`brüt + ÜÇ işveren kalemi`** (spec §7).

    🔴 Bu formülün TEK KAYNAĞI burasıdır: BY 90-92'nin 4. kartı da, BG 49'un
    "Toplam Maliyet" sütunu da bu fonksiyondan geçer. İki yere kopyalansaydı
    biri güncellenip öteki unutulduğunda aynı dönem iki ekranda iki maliyet
    gösterirdi.

    ⚠️ **Etiket mockup'tan, HESAP spec'ten.** BY 92 "SGK işveren payı dahil"
    yazar ama işveren tarafı SGK 78-86'da ÜÇ kalemdir (SGK işveren %20,5 ·
    işsizlik işveren %2 · kısa çalışma %1). Yalnız SGK payını toplamak işveren
    maliyetini sistematik olarak EKSİK gösterirdi — para sınıfı hata. Mockup
    toplamları (BG 892.000) bu eksik tabana dayanır ve **test beklentisi
    DEĞİLDİR** (S1: açık oran kazanır).

    Fail-closed: brüt ya da oran seti yoksa **`None`** — 0 dönmek, maliyeti
    bilinmiyorken "maliyet yok" demek olurdu (WORKFLOW §4 NULL-EŞİK kanonu).
    """
    if gross_amount is None or rate is None:
        return None
    return gross_amount + quantize_money(gross_amount * employer_burden_pct(rate) / PERCENT_DIVISOR)


def rate_share(gross_amount: Decimal | None, rate_pct: Decimal | None) -> Decimal | None:
    """Tek bir oran sütununun brütteki karşılığı (BG 47 "SGK İşveren" sütunu).

    `total_employer_cost`in bir parçası DEĞİL, onun YANINDAKİ ayrı bir
    görünümdür: BG hem SGK işveren payını hem toplam maliyeti ayrı sütunlarda
    basar. İkisi tek fonksiyondan üretilseydi sütunlardan biri ötekinin
    yuvarlamasını miras alırdı.
    """
    if gross_amount is None or rate_pct is None:
        return None
    return quantize_money(gross_amount * rate_pct / PERCENT_DIVISOR)


@dataclass(frozen=True)
class TaxContext:
    """Dilimli vergi için satırın YIL-İÇİ konumu — `compute_line`ın vergi girdisi.

    Saflığın sınırıdır: `compute.py` DB'ye dokunmaz, bu yüzden "önceki
    kümülatif", "o yılın tarifesi" ve "o yılın asgari ücreti" DIŞARIDAN verilir
    (`service.compute_period` toplu okumalarından ya da tek satır için
    `service._tax_context_for_line`ten). Hesap DB'ye kendi gitseydi tarife
    aritmetiği router'dan ve veritabanından bağımsız sınanamazdı.

    `brackets`/`minimum_wage_gross` **`None` olabilir** ve bu bir eksiklik değil
    bir OLGUDUR: o yıl için tarife ya da asgari ücret satırı yoktur. Dilimli
    rejimde bu, satırı `uncomputed`a düşürür (K3 fail-closed).
    """

    #: Dönemin AYI (1-12) — istisna takviminin girdisi (KK-7).
    month: int
    #: Yıl başından ÖNCEKİ aya kadar biriken matrah (devir dâhil, K7).
    prior_cumulative_base: Decimal
    brackets: tuple[income_tax_engine.TaxBracket, ...] | None
    minimum_wage_gross: Decimal | None


@dataclass(frozen=True)
class Deductions:
    """İşçi kesintisinin DÖRT kalemi + vergi snapshot'ı. DONMUŞTUR.

    🔴 **IK3-GV'nin yapısal değişimi burada.** Önceden dört oran tek yüzdede
    toplanıp (%25,759) tek çarpım yapılıyordu; gelir vergisi hesabın hiçbir
    yerinde ayrı bir `Decimal` olarak VAR OLMUYORDU. Dilimli vergi bunu
    imkânsız kıldı — kalemler artık AYRI AYRI hesaplanır ve ayrı ayrı yuvarlanır.

    ⚠️ Kuruş sonucu: dört kalemin ayrı yuvarlanması, tek seferde yuvarlanmış
    toplamdan bir kuruş ayrışabilir. Bu KASITLIDIR ve `sgk.py`nin zaten
    uyguladığı kuralla hizalanır ("kullanıcı bu ekranda dört kalemi gözüyle
    toplar"): artık `deduction_amount` da dört kalemin TOPLAMIDIR, yani bordro
    ekranı ile SGK ekranı kuruşuna kadar mutabıktır (K6).
    """

    sgk_employee: Decimal
    unemployment_employee: Decimal
    income_tax: Decimal
    stamp_tax: Decimal
    #: KK-7 adım 1: `brüt − SGK işçi − işsizlik işçi`. İstisna tutarı bu
    #: matrahta KALIR (indirim değil KREDİdir) ve dilim belirlenirken sayılır.
    tax_base: Decimal
    #: Bu ay DAHİL biriken matrah — satıra SNAPSHOT olarak yazılır (K1).
    cumulative_tax_base: Decimal

    @property
    def total(self) -> Decimal:
        return self.sgk_employee + self.unemployment_employee + self.income_tax + self.stamp_tax


def employee_deductions(
    gross_amount: Decimal, rate: PayrollRate, tax: TaxContext
) -> Deductions | None:
    """Dört kesinti kalemi + vergi snapshot'ı — hesaplanamıyorsa **`None`**.

    ## İki rejim, tek karar noktası (K3)

    * `rate.income_tax_pct` **dolu** → DÜZ ORAN (`freelance` %20 · `intern` 0).
      Asgari ücret istisnası UYGULANMAZ: istisna ÜCRET gelirine aittir
      (GV GT 319), serbest meslek stopajına değil.
    * `rate.income_tax_pct` **`NULL`** → DİLİMLİ MOTOR (`company`,
      `subcontractor`) + asgari ücret istisnası (gelir **ve** damga).

    🔴 **`NULL` sessizce "vergi yok" demek DEĞİLDİR.** Tarife ya da asgari ücret
    satırı yoksa (ör. 2027) **`None`** döner ve çağıran satırı `uncomputed`a
    düşürür — **0 vergi ASLA yazılmaz**. Bu, K3'ün karşı-riskinin bekçisidir ve
    VARSAYILAN YOLDUR: testsiz kalsaydı "vergi yok" yalanı üretirdi.

    ## Asgari ücret istisnası KREDİdir, indirim değil (KK-7)

    1. matrah = `brüt − SGK − işsizlik` (istisna MATRAHTA KALIR);
    2. kümülatife eklenir → tarifeden o ayın vergisi;
    3. AYRICA asgari ücretin KENDİ kümülatifinden o ayın vergisi;
    4. `ödenecek = (2) − (3)`, **taban 0** — negatif vergi ÜRETİLMEZ.

    (3) aylık SABİT DEĞİLDİR: 2026'da Temmuz'da asgari ücretin kümülatifi
    190.000'i keser ve istisna 4.211,33 değil **4.537,75** olur.

    Damga vergisinde de aynı mantık: brüt asgari ücrete isabet eden kısım
    müstesnadır (DVK (II) IV/34 — 2026'da 250,70 TL/ay), taban 0.
    """
    sgk = quantize_money(gross_amount * rate.sgk_employee_pct / PERCENT_DIVISOR)
    issizlik = quantize_money(gross_amount * rate.unemployment_employee_pct / PERCENT_DIVISOR)
    tax_base = gross_amount - sgk - issizlik
    if tax_base < ZERO_MONEY:
        # Oran seti bozuk (işçi payları brütü aşıyor). Fail-closed: eksi matrah
        # `ck_payroll_lines_tax_base_positive`e çarpar ve kullanıcı hatası 500
        # gibi görünürdü.
        return None
    cumulative = tax.prior_cumulative_base + tax_base

    if rate.income_tax_pct is not None:
        return Deductions(
            sgk_employee=sgk,
            unemployment_employee=issizlik,
            income_tax=quantize_money(gross_amount * rate.income_tax_pct / PERCENT_DIVISOR),
            stamp_tax=quantize_money(gross_amount * rate.stamp_tax_pct / PERCENT_DIVISOR),
            tax_base=tax_base,
            cumulative_tax_base=cumulative,
        )

    if tax.brackets is None or tax.minimum_wage_gross is None:
        return None
    try:
        ham_vergi = income_tax_engine.monthly_income_tax(
            tax.prior_cumulative_base, tax_base, tax.brackets
        )
        asgari_matrah = income_tax_engine.minimum_wage_tax_base(
            tax.minimum_wage_gross,
            rate.sgk_employee_pct,
            rate.unemployment_employee_pct,
            quantize_money,
        )
        kredi = income_tax_engine.minimum_wage_income_tax_credit(
            tax.month, asgari_matrah, tax.brackets
        )
    except income_tax_engine.TaxBracketSetError:
        # Bozuk/eksik/sırasız dilim seti — sessiz 0 YOK (K3 fail-closed).
        return None

    ham_damga = gross_amount * rate.stamp_tax_pct / PERCENT_DIVISOR
    damga_istisnasi = income_tax_engine.stamp_tax_exemption(
        tax.minimum_wage_gross, rate.stamp_tax_pct
    )
    return Deductions(
        sgk_employee=sgk,
        unemployment_employee=issizlik,
        # Taban 0: istisna hesaplanan vergiyi AŞAMAZ, negatif vergi üretilmez.
        income_tax=quantize_money(max(ZERO_MONEY, ham_vergi - kredi)),
        stamp_tax=quantize_money(max(ZERO_MONEY, ham_damga - damga_istisnasi)),
        tax_base=tax_base,
        cumulative_tax_base=cumulative,
    )


def deduction_and_net(
    gross_amount: Decimal, rate: PayrollRate, tax: TaxContext
) -> tuple[Deductions, Decimal] | None:
    """Kesinti kalemleri ve net — zincirin ORTASI, tek tanım.

    `compute_line` (puantajdan otomatik hesap) ve T3'ün brüt override yolu (K3)
    AYNI fonksiyonu çağırır — 🔴 **İKİ çağıran vardır** (`service.compute_line`
    ve `service._apply_gross_override`) ve ikisi de aynı `TaxContext`i kurar.
    Override kendi aritmetiğini yazsaydı elle düzeltilmiş satırlar zamanla
    otomatik satırlardan farklı bir vergiye tabi olurdu.

    Net BAĞIMSIZ YUVARLANMAZ: kesintinin farkıdır (modül docstring'i, "Kuruş").
    Hesaplanamıyorsa **`None`** — 0 kesinti üretmek "vergi yok" yalanı olurdu.
    """
    kesintiler = employee_deductions(gross_amount, rate, tax)
    if kesintiler is None:
        return None
    return kesintiler, gross_amount - kesintiler.total


def computed_days(personnel_source: WorkerSource, man_days: int) -> int | None:
    """Satıra yazılacak gün — serbest meslekte **`None`** (S7, BY 254 "—").

    Serbest meslekli puantaja girmiş olsa bile ücreti güne bağlı değildir; gün
    yazmak, olmayan bir çarpanı varmış gibi gösterirdi. Diğer tiplerde gün
    puantajdan gelir ve AYLIKÇIDA DA yazılır (BY 138/158) — orada bir BİLGİDİR,
    çarpan değildir.
    """
    if personnel_source is WorkerSource.freelance:
        return None
    return man_days


def compute_gross(
    wage_type: WageType | None, wage_amount: Decimal | None, days: int | None
) -> Decimal | None:
    """Brüt ücret — hesaplanamıyorsa **`None`** (asla 0).

    * `monthly` → tam ay tutarı (gün çarpanı YOK);
    * `daily`   → `gün × yevmiye`, gün yoksa hesaplanamaz;
    * `hourly`  → HER ZAMAN `None` (ŞEF KARARI 1: saat verisi yok, sabit uydurulmaz).
    """
    if wage_type is None or wage_amount is None:
        return None
    if wage_type is WageType.monthly:
        return quantize_money(wage_amount)
    if wage_type is WageType.daily:
        if days is None:
            return None
        return quantize_money(wage_amount * days)
    return None


def split_payment(
    net_amount: Decimal | None, payment_method: PaymentMethod | None
) -> tuple[Decimal | None, Decimal | None]:
    """Varsayılan banka/elden bölüşümü — `(banka, elden)`.

    Toplamı NETE EŞİTTİR (S3) çünkü biri neti alır, diğeri 0'dır: netten
    bağımsız iki hesap yapılsaydı yuvarlama artığı invariantı bozardı.
    Net `None` ise ikisi de `None` — yarım dolu satır ÜRETİLMEZ, çünkü yarım
    dolu satır T3'teki S3 kapısını sessizce atlatırdı.
    """
    if net_amount is None:
        return None, None
    if payment_method is PaymentMethod.cash:
        return ZERO_MONEY, net_amount
    # `bank` · `mixed` · NULL → hepsi banka (ŞEF KARARI 3).
    return net_amount, ZERO_MONEY


@dataclass(frozen=True)
class ComputedLine:
    """Bir personelin bir dönemlik hesap sonucu — DONMUŞTUR.

    Servis bu değerleri `PayrollLine` satırına YAZAR; hesap ile yazma ayrıdır ki
    hesap router'dan ve DB'den bağımsız sınanabilsin.
    """

    days: int | None
    gross_amount: Decimal | None
    deduction_amount: Decimal | None
    net_amount: Decimal | None
    bank_amount: Decimal | None
    cash_amount: Decimal | None
    #: IK3-GV K1 vergi SNAPSHOT'ı — üçü BİRLİKTE dolar ya da BİRLİKTE `null`dur.
    #: Ayrı ayrı dolabilseydi "matrahı var ama vergisi yok" gibi kendi içinde
    #: çelişik bir satır DB'ye yazılabilirdi.
    tax_base_amount: Decimal | None
    cumulative_tax_base: Decimal | None
    income_tax_amount: Decimal | None
    status: PayrollLineStatus
    excluded_reason: str | None


def _status(personnel_source: WorkerSource, *, computed: bool) -> PayrollLineStatus:
    """Satır durumu. **Taşeron her koşulda `excluded`** (K2).

    Öncelik taşerondadır: hesap yapılamamış bir taşeron satırını `uncomputed`
    işaretlemek de güvenlidir (ikisi de ödemeye girmez) ama K2 YAPISAL bir
    kuraldır — tek bir yerde, tek bir koşulla zorlanması, sonraki bir dilimin
    "hesaplanabilir hâle gelince `pending` yapalım" yoluna sapmasını engeller.
    Satırın niçin ödenmediği `excluded_reason`da YAZILIDIR; para sütunları
    hesaplanabildiği kadar dolar (satır maliyete girer).
    """
    if personnel_source is WorkerSource.subcontractor:
        return PayrollLineStatus.excluded
    return PayrollLineStatus.pending if computed else PayrollLineStatus.uncomputed


def _uncomputed(personnel_source: WorkerSource, days: int | None) -> ComputedLine:
    """Fail-closed satır: gün DIŞINDA her para alanı `null`.

    Gün yine yazılır — puantajdan OKUNAN bir olgudur ve ücret tanımsız diye
    kaybolması, eksik verinin nerede olduğunu gizlerdi.
    """
    return ComputedLine(
        days=days,
        gross_amount=None,
        deduction_amount=None,
        net_amount=None,
        bank_amount=None,
        cash_amount=None,
        tax_base_amount=None,
        cumulative_tax_base=None,
        income_tax_amount=None,
        status=_status(personnel_source, computed=False),
        excluded_reason=_excluded_reason(personnel_source),
    )


def _excluded_reason(personnel_source: WorkerSource) -> str | None:
    if personnel_source is WorkerSource.subcontractor:
        return SUBCONTRACTOR_EXCLUDED_REASON
    return None


def compute_line(
    *,
    personnel_source: WorkerSource,
    wage_type: WageType | None,
    wage_amount: Decimal | None,
    payment_method: PaymentMethod | None,
    man_days: int,
    has_timesheet_records: bool,
    rate: PayrollRate | None,
    tax: TaxContext,
) -> ComputedLine:
    """Bir satırın TAM hesabı. Saf: aynı girdiye her zaman aynı çıktı.

    `has_timesheet_records` personelin dönemde HERHANGİ bir puantaj hücresi
    olup olmadığıdır (kod ayrımı YAPILMAZ) ve `man_days`ten AYRI bir olgudur:
    biri verinin VAR olup olmadığını, öteki içindeki adam-gün sayısını söyler.
    Kayıt yoksa satır her ücret tipinde `uncomputed` kalır (YÖNETİM KARARI T4b,
    modül docstring'i) ve **gün de `null`dur** — kaydı olmayan kişinin gün
    sayısı 0 değil BİLİNMEYENDİR; 0 yazmak eksik verinin yerini gizlerdi.

    `man_days` puantajdan gelen "saati olan gün" sayısıdır
    (`matrix.worked_day_clause` kanonu);
    `rate` `(dönemin yılı, personel tipi)` ile seçilmiş oran satırıdır — **yıl
    dönemin yılıdır, bugünün değil** (S2), seçim `service.py`dedir.

    `rate` `None` ise brüt hesaplanabilse bile satır `uncomputed` kalır
    (ŞEF KARARI 2): kesintisi bilinmeyen bir brütten net türetmek, kesintiyi 0
    saymak demektir.

    🔴 **IK3-GV — AYNI KAPI VERGİ İÇİN DE AÇIKTIR (K3).** `tax` bağlamı satırın
    yıl-içi konumunu taşır; dilimli rejimde tarife ya da asgari ücret satırı
    yoksa (ör. 2027) satır yine `uncomputed` kalır ve **0 vergi YAZILMAZ**.
    """
    if not has_timesheet_records:
        return _uncomputed(personnel_source, days=None)

    days = computed_days(personnel_source, man_days)
    gross = compute_gross(wage_type, wage_amount, days)
    if gross is None or rate is None:
        return _uncomputed(personnel_source, days)

    # Net TÜREVDİR — bağımsız yuvarlanmaz; bölüşüm de netten türer (S3).
    sonuc = deduction_and_net(gross, rate, tax)
    if sonuc is None:
        # K3 fail-closed: vergi rejimi tanımlı ama HESAPLANAMIYOR.
        return _uncomputed(personnel_source, days)
    kesintiler, net = sonuc
    bank, cash = split_payment(net, payment_method)
    return ComputedLine(
        days=days,
        gross_amount=gross,
        deduction_amount=kesintiler.total,
        net_amount=net,
        bank_amount=bank,
        cash_amount=cash,
        tax_base_amount=kesintiler.tax_base,
        cumulative_tax_base=kesintiler.cumulative_tax_base,
        income_tax_amount=kesintiler.income_tax,
        status=_status(personnel_source, computed=True),
        excluded_reason=_excluded_reason(personnel_source),
    )
