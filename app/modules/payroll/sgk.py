"""SGK prim özeti — SGK mockup'ının **55-95** aralığı (İK-3 T5).

`summary.py`nin kardeşidir: saf, yan etkisiz, DB'siz. Satır listesi ve oran
sözlüğü alır, SGK bildirim ekranının sayılarını üretir. **Aritmetik burada
YENİDEN YAZILMAZ:** her kalem `compute.rate_share` üzerinden geçer — brütü
oranla çarpıp yuvarlamanın TEK tanımı orasıdır (T2). İkinci bir çarpma yazılsaydı
aynı kişi için bordro ekranı ile SGK ekranı bir kuruş ayrışabilirdi.

## 🔴🔴 MOCKUP TUTARLARI TEST BEKLENTİSİ DEĞİLDİR (spec S1)

SGK mockup'ı kendi aritmetiğine UYMUYOR. Matrah 743.200 üzerinden işçi tarafı
birebir tutuyor (SGK 69-73: 104.048 · 7.432 · 74.320 · 5.641 · toplam 191.441)
ama **işveren tarafı tutmuyor**: aynı matrahtan %20,5 → 152.356 · %2 → 14.864 ·
%1 → 7.432 = **174.652** çıkarken SGK 82 **148.800** yazıyor. KPI'lar da uymuyor
(SGK 57 → 253.048, oranlardan 256.404 · SGK 91 → 275.344, oranlardan 278.700).

Spec S1'in bağladığı kural: **açıkça yazılı ORAN kazanır, tutarlar temsilîdir.**
Bu modülün ürettiği işveren sayıları mockup'takinden BÜYÜKTÜR ve bu DOĞRUDUR;
mockup toplamına "uyduran" bir düzeltme, işveren primini sistematik olarak eksik
gösterirdi (para sınıfı hata, spec §7 ile aynı gerekçe).

## 🔴 TABAN KARARI: taşeron satırı MATRAHA GİRER

SGK bildirimi bir ÖDEME değil bir BİLDİRİMDİR. K2 taşeronu **ödemeden** çıkarır
(`excluded`; ödemesi hakediş üzerinden yapılır) ama bildirimden çıkarmaz:

* SGK 112-113 bildirilecek çalışanlar listesinde **Mehmet Yılmaz** (22 gün,
  matrah 26.400) ve **Ali Kaya** (20 gün, 22.000) satırlarını gösterir; ikisi de
  BY 194/214'teki TAŞERON satırlarının aynısıdır (aynı ad, aynı gün, aynı brüt);
* SGK 55'in "48"i BY tfoot 298'in 48'idir (12 + **29 taşeron** + 5 + 2).

Yani SGK tabanı `summary.py`nin **MALİYET** tabanıyla aynıdır, ÖDEME tabanıyla
değil. T3'te iki tabanın ayrı tutulmuş olması tam olarak bunu mümkün kılar.

## Fail-closed iki dışlama (sessiz atlama YOK, WORKFLOW §3)

* **`uncomputed` satır** (S4): brütü `null`dur, 0 sayılmaz, matraha girmez ve
  `uncomputed_count`ta GÖRÜNÜR.
* **Oran seti olmayan satır**: brütü bilinir ama primi BİLİNMEZ. Matraha
  konsaydı tablo kendi içinde çelişirdi (matrah var, prim yok); primi 0
  sayılsaydı SGK'ya eksik bildirim olurdu. Satır tabandan düşer ve
  `unknown_rate_count`ta görünür.

## 🔴🔴 K6 — İKİ KATMAN MUTABAKATI (IK3-GV'nin en değerli parçası)

**Ölçülmüş kusur:** bu modül `income_tax_total`u **`income_tax_pct × brüt`** ile
YENİDEN TÜRETİYORDU. Dilimli motor gelip satıra doğru vergiyi yazsa bile SGK
ekranı düz yüzdeyi basmaya devam ederdi → bordro ekranı ile SGK ekranı **aynı
kişi için iki farklı vergi** gösterirdi.

🔴 **Ve bugünkü test bunu YAKALAYAMIYORDU:** `test_payroll_sgk.py`nin işçi payı
testi yalnız SGK ekranının **kendi içinde** toplanabilirliğini iddia ediyordu →
düz oranla kendi kendisiyle tutarlı kalır ve **YEŞİL kalırdı**. Bu, *"iki katman
birbirini maskeler — alt katmanın KENDİ bekçisi olur"* kanonunun canlı,
ölçülmüş örneğidir.

**Düzeltme:** gelir vergisi ve damga artık ORANDAN TÜRETİLMEZ, **satırın
kendisinden** okunur:

* `income_tax_total` ← `SUM(payroll_lines.income_tax_amount)`;
* `stamp_tax_total` ← satırın `deduction_amount`ından öteki üç kalem düşülerek
  (böylece asgari ücret damga istisnasını KENDİLİĞİNDEN görür — ayrı bir kolon
  açmadan, çünkü `compute` kesintiyi tam olarak bu dört kalemin toplamı olarak
  kurar);
* SGK/işsizlik/işveren kalemleri ORANDAN türemeye devam eder — onlar brütün
  sabit bir yüzdesidir ve satırda ayrı ayrı saklanmazlar.

### 🔴 Vergisi BİLİNMEYEN satır: taban DIŞLANMAZ, sayaçta görünür

IK3-GV öncesinde hesaplanmış satırların `income_tax_amount`ı `NULL`dur (kolon
o gün yoktu). Böyle bir satırı SGK tabanından TAMAMEN düşürmek cazip ama
YANLIŞTIR: SGK ekranının birincil işi PRİM bildirimidir ve prim, gelir
vergisinden bağımsız olarak brütten türetilebilir. Satırı düşürmek, ilgisiz bir
eksik yüzünden ekranın asıl sayısını yok ederdi — *"bir korkuluk, koruduğu
şeyden büyük hasar üretemez"* (IK3-RATE-FIX kanonu). Bu yüzden satır matrahta
ve prim kalemlerinde KALIR, yalnız vergi/damga kalemlerine GİRMEZ ve
`unknown_tax_count`ta GÖRÜNÜR (sessiz atlama yok).

## Kuruş

Prim kalemleri AYRI AYRI yuvarlanır (`rate_share`) ve toplamları kalemlerin
TOPLAMIDIR — ekranda basılan dört kalem kendi toplamına eşittir. IK3-GV ile
satırdaki `deduction_amount` da tam olarak bu dört kalemin toplamı hâline geldi
(`compute.Deductions.total`), yani bordro ekranı ile SGK ekranı artık kuruşuna
kadar mutabıktır — eskiden tek seferde yuvarlanmış toplam yüzde yüzünden bir
kuruş ayrışabiliyordu.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.modules.payroll import compute
from app.modules.payroll.models import PayrollLine, PayrollLineStatus, PayrollRate
from app.modules.site_diary.models import WorkerSource

ZERO_MONEY = Decimal("0.00")


@dataclass(frozen=True)
class SgkSummary:
    """SGK 55-95'in TAMAMI. DONMUŞTUR.

    SGK **96-118** (çalışan listesi, "SGK No" + 4a/4b rozeti) KASTEN YOKTUR:
    spec §5 bu ucu 55-95'e bağlar ve `sgk_no` diye bir kolon İK-1'de yoktur —
    uydurulmaz (WORKFLOW §3).
    """

    #: --- KPI dörtlüsü (SGK 55-58) ---
    declared_personnel_count: int
    sgk_base_total: Decimal
    sgk_premium_total: Decimal
    unemployment_total: Decimal
    #: --- işçi payları (SGK 69-73) ---
    sgk_employee_total: Decimal
    unemployment_employee_total: Decimal
    income_tax_total: Decimal
    stamp_tax_total: Decimal
    employee_deduction_total: Decimal
    #: --- işveren payları (SGK 79-82) ---
    sgk_employer_total: Decimal
    unemployment_employer_total: Decimal
    short_work_total: Decimal
    employer_burden_total: Decimal
    #: --- SGK'ya ödenecek (SGK 86-91) ---
    sgk_payable_total: Decimal
    #: --- görünür sayaçlar: sessiz atlama yok ---
    uncomputed_count: int
    unknown_rate_count: int
    #: 🔴 K6 — brütü BİLİNEN ama `income_tax_amount`ı `NULL` olan satır sayısı
    #: (IK3-GV öncesinde hesaplanmış satırlar). Satır matrahta ve prim
    #: kalemlerinde KALIR; yalnız gelir vergisi ve damga toplamlarına GİRMEZ.
    unknown_tax_count: int


#: 🔴 ORANDAN türetilen kalemler — **gelir vergisi ve damga BURADA YOKTUR** (K6).
#: Bunlar brütün sabit bir yüzdesidir ve satırda ayrı ayrı saklanmazlar. Gelir
#: vergisi dilimli olduğu için orandan türetilemez; damga da asgari ücret
#: istisnasını görmek zorundadır. İkisi de SATIRDAN okunur.
_RATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("sgk_employee_pct", "sgk_employee_total"),
    ("unemployment_employee_pct", "unemployment_employee_total"),
    ("sgk_employer_pct", "sgk_employer_total"),
    ("unemployment_employer_pct", "unemployment_employer_total"),
    ("short_work_pct", "short_work_total"),
)

#: SATIRDAN okunan kalemler (K6). Ayrı bir demet olarak durur ki yeni bir kalem
#: eklendiğinde hangi katmandan geleceği aranmasın.
_LINE_FIELDS: tuple[str, ...] = ("income_tax_total", "stamp_tax_total")

#: İşçi kesintisinin dört kalemi — SGK 69-73 sırasıyla.
_EMPLOYEE_TOTAL_FIELDS: tuple[str, ...] = (
    "sgk_employee_total",
    "unemployment_employee_total",
    "income_tax_total",
    "stamp_tax_total",
)

#: İşveren yükünün üç kalemi — SGK 79-82.
_EMPLOYER_TOTAL_FIELDS: tuple[str, ...] = (
    "sgk_employer_total",
    "unemployment_employer_total",
    "short_work_total",
)

#: 🔴 SGK 89 etiketi AÇIKÇA sayar: **"İşçi + İşveren SGK + İşsizlik"**. Gelir
#: vergisi ve damga bu toplama GİRMEZ (vergi dairesine gider, SGK'ya değil) ve
#: kısa çalışma da etikette SAYILMAZ. Etikette olmayanı toplama koymak, SGK'ya
#: ödenecek tutarı fazla gösterirdi; ikisi de yanıtta AYRI AYRI döner, hiçbiri
#: gizlenmez — kullanıcı isterse kendi toplamını kurabilir.
_PAYABLE_FIELDS: tuple[str, ...] = (
    "sgk_employee_total",
    "unemployment_employee_total",
    "sgk_employer_total",
    "unemployment_employer_total",
)


def build_sgk_summary(
    lines: list[PayrollLine], rates: dict[WorkerSource, PayrollRate]
) -> SgkSummary:
    """Dönemin satırlarından SGK 55-95'i üretir.

    `rates` **DÖNEMİN YILINA** ait aktif orandır (`service.rates_by_source`),
    bugünün yılı değil (S2): geçmiş bir bildirimin primi bu yılın oranıyla
    yeniden yazılamaz.
    """
    toplamlar = dict.fromkeys((*(alan for _, alan in _RATE_FIELDS), *_LINE_FIELDS), ZERO_MONEY)
    matrah = ZERO_MONEY
    bildirilen = uncomputed_count = unknown_rate_count = unknown_tax_count = 0

    for line in lines:
        if line.status is PayrollLineStatus.uncomputed:
            uncomputed_count += 1
        if line.gross_amount is None:
            # S4 fail-closed: brütü bilinmeyen satır 0 SAYILMAZ, matraha girmez.
            continue
        rate = rates.get(line.personnel_source)
        if rate is None:
            unknown_rate_count += 1
            continue

        # Taşeron (`excluded`) satır BURADA DIŞLANMAZ — bildirim ödeme değildir
        # (modül docstring'i: SGK 112-113 + SGK 55 = BY tfoot 48).
        matrah += line.gross_amount
        bildirilen += 1
        for oran_alani, toplam_alani in _RATE_FIELDS:
            toplamlar[toplam_alani] += compute.rate_share(
                line.gross_amount, getattr(rate, oran_alani)
            )

        # 🔴 K6 — vergi ve damga SATIRDAN gelir, orandan TÜRETİLMEZ.
        if line.income_tax_amount is None or line.deduction_amount is None:
            # IK3-GV öncesi satır: vergisi BİLİNMİYOR. Matrahta ve prim
            # kalemlerinde KALIR (prim brütten türer), yalnız vergi/damga
            # toplamlarına girmez ve sayaçta GÖRÜNÜR.
            unknown_tax_count += 1
            continue
        toplamlar["income_tax_total"] += line.income_tax_amount
        # Damga = kesintinin geri kalanı. `compute` kesintiyi tam olarak bu dört
        # kalemin toplamı olarak kurar (`compute.Deductions.total`), bu yüzden
        # fark KURUŞUNA KADAR damgadır ve asgari ücret istisnasını görür.
        toplamlar["stamp_tax_total"] += (
            line.deduction_amount
            - compute.rate_share(line.gross_amount, rate.sgk_employee_pct)
            - compute.rate_share(line.gross_amount, rate.unemployment_employee_pct)
            - line.income_tax_amount
        )

    isci_kesinti = sum((toplamlar[alan] for alan in _EMPLOYEE_TOTAL_FIELDS), ZERO_MONEY)
    isveren_yuku = sum((toplamlar[alan] for alan in _EMPLOYER_TOTAL_FIELDS), ZERO_MONEY)
    return SgkSummary(
        declared_personnel_count=bildirilen,
        sgk_base_total=matrah,
        # SGK 57 etiketi "İşçi + İşveren": YALNIZ SGK payları (işsizlik SGK 58'de
        # AYRI bir karttır, iki kart aynı tutarı iki kez saymamalıdır).
        sgk_premium_total=toplamlar["sgk_employee_total"] + toplamlar["sgk_employer_total"],
        unemployment_total=(
            toplamlar["unemployment_employee_total"] + toplamlar["unemployment_employer_total"]
        ),
        employee_deduction_total=isci_kesinti,
        # 🔴 SGK 82 — ÜÇ kalemin TAMAMI (spec §7). Mockup 148.800 yazar, oranlar
        # 174.652 der; S1 gereği ORAN kazanır ve bizim sayımız BÜYÜKTÜR.
        employer_burden_total=isveren_yuku,
        sgk_payable_total=sum((toplamlar[alan] for alan in _PAYABLE_FIELDS), ZERO_MONEY),
        uncomputed_count=uncomputed_count,
        unknown_rate_count=unknown_rate_count,
        unknown_tax_count=unknown_tax_count,
        **toplamlar,
    )
