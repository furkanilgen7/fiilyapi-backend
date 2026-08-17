"""IK3-GV T1+T2 — dilimli tarife + asgari ücret istisnası, SAF motorun kendisi.

DB YOKTUR (`test_payroll_compute.py` kardeşi): yalnız `income_tax.py` ve
`compute.employee_deductions` sınanır.

## 🔴 NİÇİN DEĞER TESTİ TEK BAŞINA YETMEZ

Kanon: *"para formülü port edilirken değer testi tek başına yetmez — AYRIŞMA
NOKTASI aranır."* Bir tarifeyi doğru bir tek noktada hesaplayan yanlış bir
uygulama yazmak kolaydır. Bu dosya bu yüzden formülün YANLIŞ uygulamalarından
AYRIŞTIĞI noktaları arar:

* **dört dilim sınırı × üç nokta** (tam eşik / −1 kuruş / +1 kuruş) — sınır
  `<` mi `<=` mi sorusunu 12 noktada çakar;
* **bir ay İKİ dilime bölünür** — kümülatif fark formülünün doğruluğunu
  kanıtlar; ay-bazlı naif hesap burada patlar;
* **bir ay ÜÇ dilim atlar** — tek adımlı bir uygulama burada patlar;
* **Temmuz** — asgari ücretin KENDİ kümülatifi 190.000'i keser; istisna
  4.211,33 DEĞİL 4.537,75'tir. Bu tek test *"istisna aylık sabittir"*
  varsayımını ÖLDÜRÜR;
* **istisna MATRAHTA KALIR** — kredi mi indirim mi sorusunu, dilim atlayan bir
  kümülatifte ayrıştırır (indirim olsaydı vergi 0 çıkardı, kredi olduğu için
  1.153,78);
* **bozuk dilim seti** — sessiz 0 YOK, istisna fırlar (K3 fail-closed).
"""

from decimal import Decimal

import pytest

from app.modules.payroll import compute, income_tax
from app.modules.payroll.models import PayrollLineStatus, PayrollRate
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
)
from app.modules.personnel.models import PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource

from .test_payroll_compute import BRACKETS, SGK_4A, tax_context

KURUS = Decimal("0.01")

#: KK-7'nin türev tablosu — SABİTLENMEZ, hesaplanır. Buradaki sayılar
#: BEKLENTİDİR (kullanıcı kararında birebir yazılıdır), tohum DEĞİLDİR.
ISTISNA_OCAK_HAZIRAN = Decimal("4211.33")
ISTISNA_TEMMUZ = Decimal("4537.75")
ISTISNA_AGUSTOS_ARALIK = Decimal("5615.10")

#: Asgari ücretin aylık gelir vergisi matrahı = NETİ (vergi + damga tamamen
#: istisnaya girdiği için ikisi eşittir — KK-7'nin tutarlılık kanıtı).
ASGARI_MATRAH = Decimal("28075.50")


def sirket_orani(**degisiklik) -> PayrollRate:
    return PayrollRate(year=2026, personnel_source=WorkerSource.company, **{**SGK_4A, **degisiklik})


# --------------------------------------------------------------------------- #
# KK-6 tarifesinin kümülatif kırılma noktaları
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("esik", "esikteki_vergi", "sonraki_oran"),
    [
        (Decimal("190000"), Decimal("28500"), Decimal("0.20")),
        (Decimal("400000"), Decimal("70500"), Decimal("0.27")),
        (Decimal("1500000"), Decimal("367500"), Decimal("0.35")),
        (Decimal("5300000"), Decimal("1697500"), Decimal("0.40")),
    ],
)
def test_dilim_sinirlari_UC_NOKTADA(esik, esikteki_vergi, sonraki_oran):
    """🔴 Dört sınır × üç nokta = **12 ayrışma noktası** (KK-6).

    * **tam eşikte** kümülatif vergi, kullanıcı kararındaki formülün sabit
      terimine EŞİTTİR (28.500 / 70.500 / 367.500 / 1.697.500);
    * **−1 kuruşta** o eşiğin ALTINDAKİ oran uygulanır;
    * **+1 kuruşta** SONRAKİ dilimin oranı uygulanır.

    Sınır `<` yerine `<=` (ya da tersi) yazılsaydı bu üçlünün ikisi kırılırdı.
    """
    onceki_oran = (esikteki_vergi - income_tax.tax_for_base(esik - KURUS, BRACKETS)) / KURUS

    assert income_tax.tax_for_base(esik, BRACKETS) == esikteki_vergi
    # Eşiğin bir kuruş altı: eşikteki vergiden ESKİ oran kadar eksik.
    assert income_tax.tax_for_base(esik - KURUS, BRACKETS) == esikteki_vergi - KURUS * onceki_oran
    # Eşiğin bir kuruş üstü: eşikteki vergiye YENİ oran kadar eklenir.
    assert income_tax.tax_for_base(esik + KURUS, BRACKETS) == esikteki_vergi + KURUS * sonraki_oran


def test_ilk_dilim_dogrudan_carpimdir():
    """1. dilim: `m × 0,15` — sabit terimi YOKTUR."""
    assert income_tax.tax_for_base(Decimal("100000"), BRACKETS) == Decimal("15000")


def test_son_dilim_SINIRSIZDIR():
    """5. dilim "üstü"dür: 10.000.000 matrah da vergilenir, kapsam dışı KALMAZ.

    `upper_bound IS NULL` son dilimde olmasaydı bu matrah hiçbir dilime düşmez
    ve SESSİZCE vergisiz kalırdı.
    """
    beklenen = Decimal("1697500") + Decimal("4700000") * Decimal("0.40")
    assert income_tax.tax_for_base(Decimal("10000000"), BRACKETS) == beklenen


def test_bir_ay_IKI_dilime_BOLUNUR():
    """🔴 Ayrışma noktası: kümülatif 185.000 iken 10.000 matrah.

    5.000 × %15 + 5.000 × %20 = **1.750**. Ay-bazlı naif bir hesap (ayın
    matrahını tek başına tarifeye sokmak) 10.000 × %15 = 1.500 üretir ve
    aradaki 250 TL yıl boyunca birikirdi.
    """
    vergi = income_tax.monthly_income_tax(Decimal("185000"), Decimal("10000"), BRACKETS)

    assert vergi == Decimal("1750")
    assert vergi != Decimal("10000") * Decimal("0.15")


def test_bir_ay_UC_DILIM_ATLAR():
    """Kümülatif 380.000 iken +1.200.000 → üç sınır birden geçilir.

    20.000×%20 + 1.100.000×%27 + 80.000×%35 = 4.000 + 297.000 + 28.000 =
    **329.000**. Tek adımda ilerleyen bir uygulama burada patlar.
    """
    assert income_tax.monthly_income_tax(
        Decimal("380000"), Decimal("1200000"), BRACKETS
    ) == Decimal("329000")


def test_sifir_ve_negatif_matrah_vergi_URETMEZ():
    assert income_tax.tax_for_base(Decimal("0"), BRACKETS) == Decimal("0")
    assert income_tax.tax_for_base(Decimal("-1"), BRACKETS) == Decimal("0")


# --------------------------------------------------------------------------- #
# 🔴 Bozuk dilim seti — SESSİZ 0 YOK (K3 fail-closed)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("adi", "dilimler"),
    [
        ("bos", ()),
        (
            "ordinal_bosluklu",
            (
                income_tax.TaxBracket(1, Decimal("190000"), Decimal("15")),
                income_tax.TaxBracket(3, None, Decimal("20")),
            ),
        ),
        (
            "sinir_azalan",
            (
                income_tax.TaxBracket(1, Decimal("190000"), Decimal("15")),
                income_tax.TaxBracket(2, Decimal("100000"), Decimal("20")),
                income_tax.TaxBracket(3, None, Decimal("27")),
            ),
        ),
        (
            "sinir_esit",
            (
                income_tax.TaxBracket(1, Decimal("190000"), Decimal("15")),
                income_tax.TaxBracket(2, Decimal("190000"), Decimal("20")),
                income_tax.TaxBracket(3, None, Decimal("27")),
            ),
        ),
        (
            "ortada_acik_uc",
            (
                income_tax.TaxBracket(1, None, Decimal("15")),
                income_tax.TaxBracket(2, Decimal("400000"), Decimal("20")),
            ),
        ),
        (
            "son_dilim_SINIRLI",
            (
                income_tax.TaxBracket(1, Decimal("190000"), Decimal("15")),
                income_tax.TaxBracket(2, Decimal("400000"), Decimal("20")),
            ),
        ),
        (
            "negatif_oran",
            (
                income_tax.TaxBracket(1, Decimal("190000"), Decimal("-15")),
                income_tax.TaxBracket(2, None, Decimal("20")),
            ),
        ),
    ],
)
def test_BOZUK_dilim_seti_ISTISNA_firlatir(adi, dilimler):
    """🔴 Sessiz 0 YASAK: bozuk set `TaxBracketSetError` fırlatır.

    Her biri gerçek bir yalan üretirdi: `son_dilim_SINIRLI`de 400.000 üstü
    matrah **vergisiz** kalırdı; `ortada_acik_uc`ta sonraki dilimler
    ERİŞİLEMEZ olurdu; `negatif_oran` vergiyi AZALTIRDI.
    """
    with pytest.raises(income_tax.TaxBracketSetError):
        income_tax.tax_for_base(Decimal("500000"), dilimler)


def test_dilimler_ORDINAL_sirasina_dizilir():
    """Set karışık sırada gelse de sonuç DEĞİŞMEZ — sıra `ordinal`dendir.

    DB'den `ORDER BY` olmadan okunan bir set, satır sırasına göre farklı vergi
    üretseydi aynı kişi iki koşuda iki farklı sayı görürdü.
    """
    karisik = tuple(reversed(BRACKETS))
    assert income_tax.tax_for_base(Decimal("500000"), karisik) == income_tax.tax_for_base(
        Decimal("500000"), BRACKETS
    )


# --------------------------------------------------------------------------- #
# KK-7 — asgari ücret istisnası (KREDİ, indirim DEĞİL)
# --------------------------------------------------------------------------- #


def test_asgari_ucretin_matrahi_NETINE_ESITTIR():
    """33.030,00 − %14 SGK (4.624,20) − %1 işsizlik (330,30) = **28.075,50**.

    🔴 Bu sayı aynı zamanda 2026 NET asgari ücretidir (Komisyon Kararı 2025/1)
    ve tesadüf değildir: gelir vergisi ile damga TAMAMEN istisnaya girdiği için
    matrah = net olur. Net ayrıca SABİTLENSEYDİ ikinci bir gerçek kaynak doğar
    ve oran değişince sessizce çelişirdi.
    """
    assert (
        income_tax.minimum_wage_tax_base(
            MINIMUM_WAGE_GROSS_2026,
            SGK_4A["sgk_employee_pct"],
            SGK_4A["unemployment_employee_pct"],
            compute.quantize_money,
        )
        == ASGARI_MATRAH
    )


@pytest.mark.parametrize(
    ("ay", "beklenen"),
    [
        (1, ISTISNA_OCAK_HAZIRAN),
        (2, ISTISNA_OCAK_HAZIRAN),
        (6, ISTISNA_OCAK_HAZIRAN),
        # 🔴 TEMMUZ — asgari ücretin KENDİ kümülatifi (196.528,50) 190.000
        #    eşiğini KESER. Bu tek satır "istisna aylık sabittir" varsayımını
        #    öldürür: 4.211,33 DEĞİL 4.537,75.
        (7, ISTISNA_TEMMUZ),
        (8, ISTISNA_AGUSTOS_ARALIK),
        (9, ISTISNA_AGUSTOS_ARALIK),
        (12, ISTISNA_AGUSTOS_ARALIK),
    ],
)
def test_istisna_AYLIK_SABIT_DEGILDIR(ay, beklenen):
    """KK-7 — Oca-Haz 4.211,33 · **Tem 4.537,75** · Ağu-Ara 5.615,10.

    Tablo SABİTLENMEZ, HESAPLANIR (MK-2 kanonu: türev para snapshot'lanır,
    sabitlenmez): brüt asgari ücret ya da SGK oranı değişince kendiliğinden
    doğru kalır. Yıllık vergiyi 12'ye bölen bir uygulama Temmuz'da 326,42 TL
    hata yapardı.
    """
    kredi = income_tax.minimum_wage_income_tax_credit(ay, ASGARI_MATRAH, BRACKETS)
    assert compute.quantize_money(kredi) == beklenen


def test_istisnanin_yillik_toplami_asgari_ucretin_yillik_vergisidir():
    """12 ayın istisnası, asgari ücretin YILLIK kümülatif vergisine eşittir.

    Aylıklar bağımsız hesaplansaydı (ör. yıllık vergiyi 12'ye bölerek) bu
    invariant tutar ama Temmuz yanlış çıkardı; tersine, aylıklar yuvarlanıp
    toplansaydı yıl sonunda kuruş kayardı. İkisi birden kontrol edilir.
    """
    aylik_toplam = sum(
        income_tax.minimum_wage_income_tax_credit(ay, ASGARI_MATRAH, BRACKETS)
        for ay in range(1, 13)
    )
    assert aylik_toplam == income_tax.tax_for_base(ASGARI_MATRAH * 12, BRACKETS)


def test_damga_istisnasi_brut_asgari_ucrete_isabet_eder():
    """DVK (II) IV/34 — 33.030,00 × %0,759 = **250,70 TL/ay**.

    Bugüne kadar düz `stamp_tax_pct` bunu HİÇ tanımıyordu: asgari ücretliden
    her ay 250,70 TL fazla kesiliyordu.
    """
    istisna = income_tax.stamp_tax_exemption(MINIMUM_WAGE_GROSS_2026, SGK_4A["stamp_tax_pct"])
    assert compute.quantize_money(istisna) == Decimal("250.70")


@pytest.mark.parametrize("ay", [0, 13, -1])
def test_gecersiz_ay_ISTISNA_firlatir(ay):
    """Ay 1-12 dışındaysa sessizce hesaplanmaz — takvim uydurulmaz."""
    with pytest.raises(income_tax.TaxBracketSetError):
        income_tax.minimum_wage_income_tax_credit(ay, ASGARI_MATRAH, BRACKETS)


# --------------------------------------------------------------------------- #
# Zincirin tamamı: `compute.employee_deductions`
# --------------------------------------------------------------------------- #


def _kesinti(gross: str, **baglam) -> compute.Deductions:
    sonuc = compute.employee_deductions(Decimal(gross), sirket_orani(), tax_context(**baglam))
    assert sonuc is not None
    return sonuc


def test_TAM_ASGARI_UCRETLIDE_gelir_vergisi_ve_damga_SIFIR_net_28075_50():
    """🔴 KK-7'nin bütünlük kanıtı: tam asgari ücretlide GV = 0, damga = 0.

    33.030,00 brüt · Ocak: kesinti YALNIZ SGK (4.624,20) + işsizlik (330,30);
    net **28.075,50** — Komisyon Kararı 2025/1'in ilan ettiği net asgari ücret.
    Motorun bağımsız bir dış sayıyla örtüşmesi, tarifenin de istisnanın da
    doğru olduğunu birlikte kanıtlar.
    """
    kesinti = _kesinti(str(MINIMUM_WAGE_GROSS_2026))

    assert kesinti.income_tax == Decimal("0.00")
    assert kesinti.stamp_tax == Decimal("0.00")
    assert kesinti.tax_base == ASGARI_MATRAH
    assert kesinti.total == Decimal("4954.50")
    assert MINIMUM_WAGE_GROSS_2026 - kesinti.total == Decimal("28075.50")


def test_asgari_ucretin_BIR_KURUS_ALTINDA_negatif_vergi_URETILMEZ():
    """🔴 İstisna hesaplanan vergiyi AŞAMAZ — taban 0 (KK-7 adım 4).

    33.029,99 brütte hesaplanan vergi (4.211,3235) istisnadan (4.211,325)
    KÜÇÜKTÜR. Taban olmasaydı −0,0015 çıkar, `quantize` onu −0,00'a çevirir ve
    `ck_payroll_lines_income_tax_positive` sınırında ya da negatif bir "vergi
    iadesi" olarak görünürdü.
    """
    kesinti = _kesinti("33029.99")

    assert kesinti.income_tax == Decimal("0.00")
    assert kesinti.stamp_tax == Decimal("0.00")


def test_ISTISNA_MATRAHTA_KALIR_indirim_DEGIL_KREDIDIR():
    """🔴🔴 Kredi mi indirim mi — AYRIŞMA NOKTASI (KK-7).

    Kümülatif 185.000 iken tam asgari ücretli bir ay (matrah 28.075,50):

    * **KREDİ (doğru):** 213.075,50 kümülatifin vergisi 33.115,10; önceki
      27.750 → ayın vergisi 5.365,10; istisna 4.211,325 düşülür → **1.153,78**.
    * **İNDİRİM (yanlış):** matrahtan 28.075,50 düşülseydi ay matrahı 0 olur,
      vergi **0,00** çıkardı.

    Fark 1.153,78 TL'dir ve yüksek kümülatifte her ay tekrarlanırdı. Bu test
    tam olarak bu iki uygulamayı ayırır — düşük kümülatifte ikisi de aynı sayıyı
    üretir ve ayrım GÖRÜNMEZ.
    """
    kesinti = _kesinti(str(MINIMUM_WAGE_GROSS_2026), prior_cumulative_base=Decimal("185000.00"))

    assert kesinti.cumulative_tax_base == Decimal("213075.50")
    assert kesinti.income_tax == Decimal("1153.78")


def test_YUKSEK_KAZANCTA_fazla_MARJINAL_oranla_vergilenir():
    """🔴 İstisna matrahta kaldığı için fazla, %15'ten YENİDEN BAŞLAMAZ.

    300.000,00 brüt · Ocak: matrah 255.000,00 → 190.000×%15 + 65.000×%20 =
    41.500,00; istisna 4.211,325 → **37.288,68**.

    Matrahtan istisna düşülseydi kalan 226.924,50 olur, ikinci dilime daha AZ
    girer ve vergi 39.884,90 çıkardı — 2.596 TL'lik sistematik bir fark.
    """
    kesinti = _kesinti("300000.00")

    assert kesinti.tax_base == Decimal("255000.00")
    assert kesinti.income_tax == Decimal("37288.68")


def test_AYNI_BRUT_yilin_farkli_ayinda_FARKLI_vergi_uretir():
    """🔴 Dilimli verginin tanımı: brütün sabit bir yüzdesi DEĞİLDİR.

    Aynı 100.000 TL brüt, kümülatifi 0 olan bir ayda ve kümülatifi 500.000 olan
    bir ayda farklı vergilenir. "Tek toplam yüzde" yaklaşımının niçin yapısal
    olarak kullanılamaz olduğunun doğrudan kanıtı.
    """
    ocak = _kesinti("100000.00")
    kasim = _kesinti("100000.00", month=11, prior_cumulative_base=Decimal("500000.00"))

    assert ocak.income_tax != kasim.income_tax
    assert kasim.income_tax > ocak.income_tax


# --------------------------------------------------------------------------- #
# 🔴 K3 fail-closed — VARSAYILAN YOL
# --------------------------------------------------------------------------- #


def _satir(**baglam) -> compute.ComputedLine:
    return compute.compute_line(
        personnel_source=WorkerSource.company,
        wage_type=WageType.monthly,
        wage_amount=Decimal("50000.00"),
        payment_method=PaymentMethod.bank,
        man_days=21,
        has_timesheet_records=True,
        rate=sirket_orani(),
        tax=tax_context(**baglam),
    )


@pytest.mark.parametrize("eksik", ["brackets", "minimum_wage_gross"])
def test_TARIFESI_OLMAYAN_YIL_satiri_UNCOMPUTED_yapar_SIFIR_YAZMAZ(eksik):
    """🔴🔴 **VARSAYILAN YOL** — 2027'de tarife/asgari ücret satırı YOKTUR.

    `income_tax_pct IS NULL` sessizce *"vergi yok"* diye OKUNAMAZ (NULL-EŞİK
    kanonu, SA dilimi). Testsiz kalsaydı 2027'nin ilk bordrosu HERKESİ vergisiz
    hesaplar ve kimse fark etmezdi — para sınıfı, sessiz, geriye dönük yalan.

    Satır `uncomputed` olur ve **beş para alanı da `null` kalır**; 0 BASILMAZ.
    """
    satir = _satir(**{eksik: None})

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.net_amount is None
    assert satir.income_tax_amount is None
    assert satir.tax_base_amount is None
    assert satir.cumulative_tax_base is None


def test_BOZUK_dilim_seti_de_satiri_UNCOMPUTED_yapar():
    """Set VAR ama kullanılamaz (son dilim sınırlı) → yine fail-closed.

    "Dilim seti yok" ile "dilim seti bozuk" AYRI kusurlardır ve ikisi de sessiz
    0 üretmemelidir; ikincisi ilkinin testiyle kapanmaz.
    """
    bozuk = (
        income_tax.TaxBracket(1, Decimal("190000"), Decimal("15")),
        income_tax.TaxBracket(2, Decimal("400000"), Decimal("20")),
    )
    satir = _satir(brackets=bozuk)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.income_tax_amount is None


def test_DUZ_ORAN_rejimi_tarifeden_BAGIMSIZDIR():
    """`freelance` (%20) ve `intern` (0) dilim seti OLMADAN da hesaplanır.

    K3'ün öteki yüzü: `income_tax_pct` DOLU ise rejim düz orandır ve tarifeye
    hiç bakılmaz. `intern`in `0`ı bir VERİDİR ("kesinti yok" kararı) ve `NULL`
    ile aynı şey değildir — biri hesaplanır, öteki fail-closed'dur.
    """
    serbest = compute.employee_deductions(
        Decimal("12500.00"),
        PayrollRate(
            year=2026,
            personnel_source=WorkerSource.freelance,
            **{**dict.fromkeys(SGK_4A, Decimal("0.000")), "income_tax_pct": Decimal("20.000")},
        ),
        tax_context(brackets=None, minimum_wage_gross=None),
    )
    stajyer = compute.employee_deductions(
        Decimal("7500.00"),
        PayrollRate(
            year=2026,
            personnel_source=WorkerSource.intern,
            **dict.fromkeys(SGK_4A, Decimal("0.000")),
        ),
        tax_context(brackets=None, minimum_wage_gross=None),
    )

    assert serbest is not None and serbest.income_tax == Decimal("2500.00")
    assert serbest.total == Decimal("2500.00")
    assert stajyer is not None and stajyer.total == Decimal("0.00")


def test_DUZ_ORANDA_asgari_ucret_istisnasi_UYGULANMAZ():
    """İstisna ÜCRET gelirine aittir (GV GT 319), serbest meslek stopajına değil.

    12.500 TL serbest meslek makbuzunda %20 stopaj TAM kesilir; istisna
    uygulansaydı stopaj 0'a düşer ve GVK m.94 ihlal edilirdi.
    """
    serbest = compute.employee_deductions(
        Decimal("12500.00"),
        PayrollRate(
            year=2026,
            personnel_source=WorkerSource.freelance,
            **{**dict.fromkeys(SGK_4A, Decimal("0.000")), "income_tax_pct": Decimal("20.000")},
        ),
        tax_context(),
    )
    assert serbest is not None
    assert serbest.income_tax == Decimal("2500.00")


def test_ISCI_PAYLARI_BRUTU_ASARSA_fail_closed():
    """Eksi matrah üretecek bozuk oran seti → **`None`**, negatif matrah YOK.

    `ck_payroll_lines_tax_base_positive` sınırına çarpsaydı kullanıcı hatası
    500 gibi görünürdü.
    """
    assert (
        compute.employee_deductions(
            Decimal("1000.00"),
            sirket_orani(
                sgk_employee_pct=Decimal("90.000"), unemployment_employee_pct=Decimal("20.000")
            ),
            tax_context(),
        )
        is None
    )
