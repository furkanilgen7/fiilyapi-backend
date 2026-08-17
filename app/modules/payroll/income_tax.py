"""Dilimli (artan oranlı) gelir vergisi motoru — SAF, DB'siz (IK3-GV T1).

`compute.py`nin kardeşidir ve ondan AYRI durur: `compute.py` bir satırın tüm
zincirini kurar, burası yalnız GVK m.103'ün artan oranlı tarifesini ve KK-7'nin
asgari ücret istisnasını hesaplar. Ayrı olması zorunludur çünkü tarife
aritmetiği `compute`tan bağımsız olarak, tek tek dilim sınırlarında sınanabilir
olmalıdır (ayrışma noktası kanonu: "para formülü port edilirken değer testi tek
başına yetmez").

## 🔴 Niçin bu modül VAR: vergi eskiden AYRI BİR SAYI DEĞİLDİ

IK3-GV öncesinde `compute.employee_deduction_pct` dört işçi oranını TEK yüzdede
topluyordu (%25,759) ve `deduction_and_net` tek çarpım yapıyordu. Gelir vergisi
hesabın hiçbir yerinde ayrı bir `Decimal` olarak var olmuyordu. Dilimli vergi
brütün sabit bir yüzdesi OLMADIĞI için o yaklaşım yapısal olarak kullanılamaz:
aynı brüt, yılın hangi ayında olduğuna göre farklı vergi üretir.

## Kümülatif matrah — ayın vergisi FARKTIR

Tarife AYA değil, YIL BAŞINDAN İTİBAREN BİRİKEN matraha uygulanır:

    ayın vergisi = T(önceki kümülatif + ayın matrahı) − T(önceki kümülatif)

Bu fark formülü, bir ayın İKİ DİLİME BÖLÜNMESİNİ kendiliğinden doğru yapar
(kümülatif 185.000 iken 10.000 matrah → 5.000×%15 + 5.000×%20). Ay bazlı naif
bir hesap (ayın matrahını tek başına tarifeye sokmak) burada patlardı ve
yıl boyunca sistematik olarak EKSİK vergi üretirdi.

🔴 **T(...) YUVARLANMAZ, FARK yuvarlanır.** İki kümülatif ayrı ayrı
yuvarlansaydı her ay yarım kuruşa kadar bir artık doğar ve yıl sonunda
kümülatif toplam, aylıkların toplamından kayardı. Yuvarlama TEK YERDE ve
ZİNCİRİN SONUNDADIR (`compute.quantize_money` ile aynı kural).

## Asgari ücret istisnası (KK-7) — İNDİRİM DEĞİL, KREDİ

GV GT 319 md.4/2-4/3: istisna tutarı MATRAHTA KALIR (dilim belirlenirken
dikkate alınır) ve hesaplanan vergiden DÜŞÜLÜR; düşülecek tutar o ayın asgari
ücret üzerinden hesaplanacak vergisini AŞAMAZ.

🔴 **İstisna AYLIK SABİT DEĞİLDİR.** Asgari ücretin KENDİ kümülatif matrahı da
dilim atlar: 2026'da Oca-Haz 4.211,33 · **Tem 4.537,75** (190.000 eşiğini o ay
keser) · Ağu-Ara 5.615,10. Sabit bir aylık tutar yazmak Temmuz'da 326,42 TL
fazla vergi kestirirdi. Bu yüzden istisna tablosu SABİTLENMEZ, aynı fark
formülüyle HESAPLANIR (MK-2 kanonu: türev para snapshot'lanır, sabitlenmez).

## Fail-closed

Dilim seti eksik/boş/sırasız/çelişikse **istisna fırlatılır** (`TaxBracketSetError`);
sessizce 0 vergi ÜRETİLMEZ. Çağıran (`compute.py`) bunu satırı `uncomputed`a
düşürerek karşılar (K3'ün karşı-riski: `income_tax_pct IS NULL` sessizce "vergi
yok" diye okunamaz — NULL-EŞİK kanonu, fail-closed).
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

#: Oranlar YÜZDEDİR (`15.000` = %15) — `compute.PERCENT_DIVISOR` ile aynı kural.
PERCENT_DIVISOR = Decimal("100")

ZERO = Decimal("0")

#: Yılın ay sayısı — istisna takviminin üst sınırı.
MONTHS_IN_YEAR = 12


class TaxBracketSetError(ValueError):
    """Dilim seti kullanılamaz: eksik, boş, sırasız ya da kendi içinde çelişik.

    🔴 Ayrı bir sınıftır ki çağıran onu "hesaplanamadı" (fail-closed) olarak
    ele alıp satırı `uncomputed`a düşürebilsin. Genel bir `ValueError`
    yakalansaydı, tarife dışı bir programlama hatası da sessizce "vergi
    hesaplanamadı"ya dönüşürdü.
    """


@dataclass(frozen=True)
class TaxBracket:
    """Tarifenin bir dilimi. DONMUŞTUR.

    `upper_bound is None` **yalnız SON dilimde** olur ve "üstü" demektir
    (2026 ücret tarifesinde 5.300.000 üzeri %40).
    """

    ordinal: int
    upper_bound: Decimal | None
    rate_pct: Decimal


def normalize_brackets(
    brackets: list[TaxBracket] | tuple[TaxBracket, ...],
) -> tuple[TaxBracket, ...]:
    """Dilim setini DOĞRULAR ve `ordinal` sırasına dizer.

    🔴 Doğrulama fail-closed'un kendisidir: bozuk bir set sessizce kullanılsaydı
    (örneğin son dilim eksikken) yüksek kazançlı bir satır ya eksik vergilenir
    ya da hiç vergilenmezdi. Beş kural birden zorlanır:

    1. set BOŞ OLAMAZ;
    2. `ordinal`lar 1..N ARALIKSIZ olmalıdır (eksik bir dilim = tarifede delik);
    3. sonlu `upper_bound`lar KESİN ARTAN olmalıdır (eşit/azalan sınır, aynı
       matrahı iki dilime sokar);
    4. `upper_bound IS NULL` **yalnız SON** dilimde olabilir — ortada bir açık
       uç, sonraki dilimleri ERİŞİLEMEZ kılardı;
    5. SON dilimin sınırı `NULL` OLMALIDIR, yoksa sınırın üstündeki matrah
       hiçbir dilime düşmez ve vergisiz kalırdı.

    Oranın negatif olmaması da denetlenir (negatif oran vergiyi AZALTIRDI).
    """
    if not brackets:
        raise TaxBracketSetError("Gelir vergisi dilim seti BOŞ: vergi hesaplanamaz")

    sirali = tuple(sorted(brackets, key=lambda b: b.ordinal))

    beklenen = tuple(range(1, len(sirali) + 1))
    if tuple(b.ordinal for b in sirali) != beklenen:
        raise TaxBracketSetError(
            "Gelir vergisi dilimlerinin sırası 1..N aralıksız olmalıdır; "
            f"bulunan: {[b.ordinal for b in sirali]}"
        )

    for dilim in sirali:
        if dilim.rate_pct < ZERO:
            raise TaxBracketSetError(f"{dilim.ordinal}. dilimin oranı negatif: {dilim.rate_pct}")

    *ilk_dilimler, son_dilim = sirali
    onceki: Decimal | None = None
    for dilim in ilk_dilimler:
        if dilim.upper_bound is None:
            raise TaxBracketSetError(
                f"{dilim.ordinal}. dilimin üst sınırı YOK ama son dilim değil: "
                "sonraki dilimler erişilemez olurdu"
            )
        if onceki is not None and dilim.upper_bound <= onceki:
            raise TaxBracketSetError(
                f"{dilim.ordinal}. dilimin üst sınırı ({dilim.upper_bound}) bir öncekinden "
                f"({onceki}) büyük değil: aynı matrah iki dilime düşerdi"
            )
        onceki = dilim.upper_bound
    if son_dilim.upper_bound is not None:
        raise TaxBracketSetError(
            f"SON dilimin ({son_dilim.ordinal}) üst sınırı olmamalıdır; "
            f"bulunan: {son_dilim.upper_bound} — üstündeki matrah vergisiz kalırdı"
        )

    return sirali


def tax_for_base(cumulative_base: Decimal, brackets: tuple[TaxBracket, ...]) -> Decimal:
    """Kümülatif matrahın TAM (yuvarlanmamış) vergisi — tarifenin kendisi.

    🔴 **YUVARLAMAZ.** Ayın vergisi iki çağrının FARKIDIR (`monthly_income_tax`)
    ve yuvarlama orada, TEK KEZ yapılır. Burada yuvarlansaydı her ay yarım kuruş
    artık doğar, yıl sonunda kümülatif toplam aylıkların toplamından kayardı.

    Negatif matrah 0 sayılır (eksi vergi ÜRETİLMEZ): matrah eksiye düşmesi
    yapısal olarak imkânsızdır ama burada da fail-closed davranılır.
    """
    dilimler = normalize_brackets(brackets)
    if cumulative_base <= ZERO:
        return ZERO

    vergi = ZERO
    taban = ZERO
    for dilim in dilimler:
        tavan = dilim.upper_bound
        if tavan is None or cumulative_base <= tavan:
            vergi += (cumulative_base - taban) * dilim.rate_pct / PERCENT_DIVISOR
            return vergi
        vergi += (tavan - taban) * dilim.rate_pct / PERCENT_DIVISOR
        taban = tavan
    # `normalize_brackets` son dilimin sınırsız olmasını zorlar → buraya
    # ulaşılamaz. Yine de sessiz 0 dönmek yerine bağırılır.
    raise TaxBracketSetError("Dilim seti kümülatif matrahı kapsamıyor")  # pragma: no cover


def monthly_income_tax(
    prior_cumulative_base: Decimal,
    period_tax_base: Decimal,
    brackets: tuple[TaxBracket, ...],
) -> Decimal:
    """Ayın vergisi = `T(önceki + bu ay) − T(önceki)`, YUVARLANMAMIŞ.

    Yuvarlama çağırana (`compute.py`) bırakılır ki para zincirinin tek bir
    yuvarlama noktası olsun (`compute.quantize_money`).
    """
    return tax_for_base(prior_cumulative_base + period_tax_base, brackets) - tax_for_base(
        prior_cumulative_base, brackets
    )


def minimum_wage_tax_base(
    minimum_wage_gross: Decimal,
    sgk_employee_pct: Decimal,
    unemployment_employee_pct: Decimal,
    quantize: Callable[[Decimal], Decimal],
) -> Decimal:
    """Asgari ücretin AYLIK gelir vergisi matrahı — `brüt − SGK işçi − işsizlik işçi`.

    Kesintiler AYRI AYRI yuvarlanır çünkü gerçek bir asgari ücretlinin bordrosu
    da öyle hesaplanır; tek seferde yuvarlanan bir toplam, istisnayı bir kuruş
    kaydırabilirdi. 2026: 33.030,00 − 4.624,20 − 330,30 = **28.075,50**
    (bu sayı aynı zamanda asgari ücretin NETİDİR, çünkü vergi ve damga tamamen
    istisnaya girer — KK-7'nin tutarlılık kanıtı).

    `quantize` DIŞARIDAN verilir: para yuvarlamasının tek tanımı
    `compute.quantize_money`dir ve bu modül `compute`u import etmez (ters yönde
    bağımlılık zaten var, döngü doğardı).
    """
    sgk = quantize(minimum_wage_gross * sgk_employee_pct / PERCENT_DIVISOR)
    issizlik = quantize(minimum_wage_gross * unemployment_employee_pct / PERCENT_DIVISOR)
    return minimum_wage_gross - sgk - issizlik


def minimum_wage_income_tax_credit(
    month: int,
    minimum_wage_monthly_base: Decimal,
    brackets: tuple[TaxBracket, ...],
) -> Decimal:
    """🔴 KK-7 — o AYIN asgari ücret üzerinden hesaplanacak vergisi (YUVARLANMAMIŞ).

    Asgari ücretlinin KENDİ kümülatif matrahı üzerinden aynı fark formülüyle
    bulunur: `T(ay × taban) − T((ay−1) × taban)`.

    🔴 **Bu yüzden istisna aylık SABİT DEĞİLDİR.** 2026'da asgari ücretin
    kümülatifi Temmuz'da 196.528,50'ye çıkar ve 190.000 eşiğini KESER; o ayın
    istisnası 4.211,33 değil **4.537,75**tir, Ağustos'tan itibaren 5.615,10.
    Sabit bir tablo yazmak (ya da 12'ye bölmek) Temmuz'u yanlış hesaplardı.

    Takvim AYINA bağlıdır, kişinin çalıştığı ay SAYISINA değil: istisna
    asgari ücretlinin yıl içindeki konumunu ölçer ve herkes için aynıdır.
    """
    if not 1 <= month <= MONTHS_IN_YEAR:
        raise TaxBracketSetError(f"Geçersiz ay: {month}")
    return tax_for_base(minimum_wage_monthly_base * month, brackets) - tax_for_base(
        minimum_wage_monthly_base * (month - 1), brackets
    )


def stamp_tax_exemption(minimum_wage_gross: Decimal, stamp_tax_pct: Decimal) -> Decimal:
    """DVK (II) IV/34 — brüt ASGARİ ÜCRETE isabet eden damga vergisi müstesnadır.

    2026: 33.030,00 × %0,759 = **250,70 TL/ay**. Bugünkü düz `stamp_tax_pct`
    bunu HİÇ tanımıyordu; asgari ücretliden 250,70 TL fazla kesiliyordu.
    Yuvarlanmamış döner — istisnanın da düşüldüğü yer zincirin sonudur.
    """
    return minimum_wage_gross * stamp_tax_pct / PERCENT_DIVISOR
