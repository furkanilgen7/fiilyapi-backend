"""Bordro hesabının TEK KAYNAĞI — saf, yan etkisiz fonksiyonlar (İK-3 T2).

Spec: `docs/superpowers/specs/2026-08-13-ik3-bordro-design.md` (K1/K3, S1-S7).
`personnel/leave.py` ve `inventory/balance.py` kardeşidir: DB'ye DOKUNMAZ,
kapsam kararı VERMEZ (onu `service.py` verir), yalnız bir personelin bir aylık
satırını hesaplar. İkinci bir formül yazılsaydı ekran, Excel ve SGK özeti aynı
kişi için farklı sayı gösterir ve hangisinin doğru olduğu anlaşılamazdı.

## Zincir

    gün (puantaj) → brüt (ücret tipi) → kesinti (oran seti) → net → bölüşüm

Her halka bir öncekine bağlıdır ve **her halka fail-closed'dur**: hesaplanamayan
bir değer `null` kalır, UYDURMA 0 BASILMAZ (S4 · NULL-EŞİK kanonu, WORKFLOW §4).
Uydurma 0, eksik veriyi "ödenecek bir şey yok" gibi gösterirdi — para sınıfı yalan.

## Bu dosyanın taşıdığı bağlanmış kararlar

* **Kesinti = yalnız İŞÇİ payları.** İşveren primleri (`sgk_employer_pct` ·
  `unemployment_employer_pct` · `short_work_pct`) işçinin kesintisi DEĞİL,
  işverenin maliyetidir (spec §7: `toplam_maliyet = brüt + üç işveren kalemi`).
  İkisini karıştırmak neti yanlış hesaplardı.
* **🔴 ŞEF KARARI 1 — `hourly` FAIL-CLOSED.** Puantajda normal çalışma SAATİ
  kolonu yoktur (`timesheet_entries` yalnız `overtime_hours` taşır, o da sadece
  `overtime` kodunda dolu). "Günde 8 saat" gibi bir sabit İCAT ETMEK yasaktır
  (WORKFLOW §3) ve para sınıfı bir uydurma olurdu → satır `uncomputed`.
* **🔴 YÖNETİM KARARI (T4b) — puantaj KAYDI olmayan personel FAIL-CLOSED,
  ÜÇ ÜCRET TİPİNDE DE.** Dönemde personele ait HİÇ `timesheet_entries` kaydı
  yoksa "bu ay hiç çalışmadı" ile "puantajı henüz girilmedi" veritabanında
  AYIRT EDİLEMEZ; ikisi de brüt 0 üretseydi veri eksikliği "ödenecek bir şey
  yok" gibi görünürdü. `monthly` DE dâhildir: "aylık ücretlide gün brütü
  etkilemez" varsayımı, işe hiç başlamamış ya da çıkmış personele sessizce tam
  maaş hesaplamayı meşrulaştırırdı. ⚠️ Bu kural KAYDIN VARLIĞINA bakar, gün
  SAYISINA değil: kaydı olan ama tüm günleri izin/tatil kodlu (`MAN_DAY_CODES`
  dışı) personelde gün 0 GERÇEKTİR — veri girilmiştir, hesap yapılır. Kuralın
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
  ("mesai/ikramiye/avans"). `overtime` kodlu gün `MAN_DAY_CODES` gereği GÜN
  olarak sayılır (`matrix.py`), saati ayrıca paraya çevrilmez — çevrilseydi aynı
  mesai hem gün hem saat olarak iki kez ödenirdi.
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


def employee_deduction_pct(rate: PayrollRate) -> Decimal:
    """İşçiden kesilen toplam yüzde — SGK 70-73'ün toplamı (4a'da %25,759).

    İşveren sütunları KASTEN dışarıdadır (`EMPLOYER_RATE_FIELDS`): onlar
    maliyettir, kesinti değildir (spec §7).
    """
    return sum((getattr(rate, alan) for alan in EMPLOYEE_RATE_FIELDS), Decimal("0"))


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


def deduction_and_net(gross_amount: Decimal, rate: PayrollRate) -> tuple[Decimal, Decimal]:
    """Kesinti ve net — zincirin ORTASI, tek tanım.

    `compute_line` (puantajdan otomatik hesap) ve T3'ün brüt override yolu (K3)
    AYNI fonksiyonu çağırır. Override kendi aritmetiğini yazsaydı elle
    düzeltilmiş satırlar zamanla otomatik satırlardan farklı bir kurala tabi
    olurdu.

    Net BAĞIMSIZ YUVARLANMAZ: kesintinin farkıdır (modül docstring'i, "Kuruş").
    """
    deduction = quantize_money(gross_amount * employee_deduction_pct(rate) / PERCENT_DIVISOR)
    return deduction, gross_amount - deduction


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
) -> ComputedLine:
    """Bir satırın TAM hesabı. Saf: aynı girdiye her zaman aynı çıktı.

    `has_timesheet_records` personelin dönemde HERHANGİ bir puantaj hücresi
    olup olmadığıdır (kod ayrımı YAPILMAZ) ve `man_days`ten AYRI bir olgudur:
    biri verinin VAR olup olmadığını, öteki içindeki adam-gün sayısını söyler.
    Kayıt yoksa satır her ücret tipinde `uncomputed` kalır (YÖNETİM KARARI T4b,
    modül docstring'i) ve **gün de `null`dur** — kaydı olmayan kişinin gün
    sayısı 0 değil BİLİNMEYENDİR; 0 yazmak eksik verinin yerini gizlerdi.

    `man_days` puantajdan gelen `MAN_DAY_CODES` sayısıdır (`matrix.py` kanonu);
    `rate` `(dönemin yılı, personel tipi)` ile seçilmiş oran satırıdır — **yıl
    dönemin yılıdır, bugünün değil** (S2), seçim `service.py`dedir.

    `rate` `None` ise brüt hesaplanabilse bile satır `uncomputed` kalır
    (ŞEF KARARI 2): kesintisi bilinmeyen bir brütten net türetmek, kesintiyi 0
    saymak demektir.
    """
    if not has_timesheet_records:
        return _uncomputed(personnel_source, days=None)

    days = computed_days(personnel_source, man_days)
    gross = compute_gross(wage_type, wage_amount, days)
    if gross is None or rate is None:
        return _uncomputed(personnel_source, days)

    # Net TÜREVDİR — bağımsız yuvarlanmaz; bölüşüm de netten türer (S3).
    deduction, net = deduction_and_net(gross, rate)
    bank, cash = split_payment(net, payment_method)
    return ComputedLine(
        days=days,
        gross_amount=gross,
        deduction_amount=deduction,
        net_amount=net,
        bank_amount=bank,
        cash_amount=cash,
        status=_status(personnel_source, computed=True),
        excluded_reason=_excluded_reason(personnel_source),
    )
