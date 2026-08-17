"""İK-3 T2 — bordro hesap ÇEKİRDEĞİ (`compute.py`) saf fonksiyonları.

Spec: `docs/superpowers/specs/2026-08-13-ik3-bordro-design.md` (K1/K3, S1-S7).
DB YOKTUR: bu dosya yalnız hesabın kendisini sınar (`personnel/leave.py` ve
`inventory/balance.py` emsali — türev TEK KAYNAKTAN, router'dan bağımsız
sınanabilir).

**PARA sınıfı.** Her beklenti ya mockup satırından ya da bağlanmış bir karardan
gelir; hiçbir sayı "makul göründüğü için" yazılmamıştır.
"""

from decimal import Decimal

import pytest

from app.modules.payroll import compute
from app.modules.payroll.models import PayrollLineStatus, PayrollRate
from app.modules.personnel.models import PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource

# SGK 70-73 işçi payları (S1): 14 + 1 + 10 + 0,759 = **%25,759**.
SGK_4A = {
    "sgk_employee_pct": Decimal("14.000"),
    "unemployment_employee_pct": Decimal("1.000"),
    "income_tax_pct": Decimal("10.000"),
    "stamp_tax_pct": Decimal("0.759"),
    "sgk_employer_pct": Decimal("20.500"),
    "unemployment_employer_pct": Decimal("2.000"),
    # 🔑 KK-5 (2026-08-16): "SGK %1 kısa çalışma ödeneği YOK, hesaplanmaz."
    # `f6a7b8c9d0e1` bu oranı canlı veride 1'den 0'a çekti; kaynak sabit
    # `payroll/rate_seed_data.PAYROLL_RATES_2026`tır.
    #
    # 🔴 BU DOSYADAKİ DEĞER LOAD-BEARING DEĞİLDİR — ölçüldü: 1.000 ile de
    # 0.000 ile de 162 test geçer. Buradaki `SGK_4A` üretim tohumunun AYNASI
    # değil, saf `compute.py` fonksiyonlarını sınamak için kurulmuş YEREL bir
    # fikstürdür (dosya docstring'i: "DB YOKTUR"); hiçbir test bu sütunun
    # değerine dayanmaz. Yine de KK-5 ile TUTARLI tutulur: adı üretimdeki
    # seed sabitiyle aynı olduğu için 1 yazsaydı, okuyan "kısa çalışma %1'dir"
    # diye YANLIŞ sonuç çıkarırdı (para sınıfı yanılgı).
    #
    # İşveren sütunlarının kesintiye SIZMADIĞINI sınayan test buranın değerine
    # DEĞİL, kendi şişirdiği 77.000'e bakar (`test_isveren_oranlari_kesintiye_GIRMEZ`),
    # yani bu hizalama hiçbir bekçiyi zayıflatmaz.
    "short_work_pct": Decimal("0.000"),
}
ZERO = dict.fromkeys(SGK_4A, Decimal("0.000"))
# BY 243 "Serbest Makbuz · %20 Stopaj" — SGK payı YOK.
SERBEST = {**ZERO, "income_tax_pct": Decimal("20.000")}

TOPLAM_ISCI_ORANI = Decimal("25.759")


def rate(**oranlar: Decimal) -> PayrollRate:
    """Oturumsuz `PayrollRate` — hesap saf olduğu için DB'ye ihtiyaç yok."""
    return PayrollRate(year=2026, personnel_source=WorkerSource.company, **{**SGK_4A, **oranlar})


def hesapla(**kwargs) -> compute.ComputedLine:
    """Varsayılanı ŞİRKET / GÜNLÜKÇÜ / banka olan çağrı sarmalayıcısı."""
    varsayilan = {
        "personnel_source": WorkerSource.company,
        "wage_type": WageType.daily,
        "wage_amount": Decimal("1800.00"),
        "payment_method": PaymentMethod.bank,
        "man_days": 21,
        "has_timesheet_records": True,
        "rate": rate(),
    }
    return compute.compute_line(**{**varsayilan, **kwargs})


# --- Oran toplamı: işçi tarafı / işveren tarafı ayrımı ----------------------


def test_isci_orani_dort_kalemin_toplamidir():
    """SGK 70-73: 14 + 1 + 10 + 0,759. Damga ÜÇ ONDALIKLI kalmalı (0,76 DEĞİL)."""
    assert compute.employee_deduction_pct(rate()) == TOPLAM_ISCI_ORANI


def test_isveren_oranlari_kesintiye_GIRMEZ():
    """İşveren payları maliyettir, işçinin kesintisi değildir (spec §7).

    İşveren sütunları uçuk değerlere çekilir; kesinti oranı KIMILDAMAMALIDIR.
    Aynı kural mutasyon denetimidir: `employee_deduction_pct` yanlışlıkla yedi
    sütunu toplarsa bu test kırmızıya döner.
    """
    sisirilmis = rate(
        sgk_employer_pct=Decimal("99.000"),
        unemployment_employer_pct=Decimal("88.000"),
        short_work_pct=Decimal("77.000"),
    )

    assert compute.employee_deduction_pct(sisirilmis) == TOPLAM_ISCI_ORANI


def test_yedi_oran_sutunu_iki_kumeye_TAM_bolunur():
    """Yeni bir oran sütunu eklenip hiçbir kümeye yazılmazsa bu test kırılır.

    Sessizce dışarıda kalan bir sütun ya kesintiyi ya işveren maliyetini eksik
    gösterirdi — ikisi de para sınıfı hata (spec §7).
    """
    kumeler = set(compute.EMPLOYEE_RATE_FIELDS) | set(compute.EMPLOYER_RATE_FIELDS)

    assert kumeler == set(SGK_4A)
    assert not set(compute.EMPLOYEE_RATE_FIELDS) & set(compute.EMPLOYER_RATE_FIELDS)


# --- Brüt: ücret tipine göre -----------------------------------------------


def test_gunlukcu_brut_gun_carpimi():
    """`daily` → gün × yevmiye. BY 138 (21 gün) · BY 139 (37.800 brüt)."""
    satir = hesapla(wage_amount=Decimal("1800.00"), man_days=21)

    assert satir.days == 21
    assert satir.gross_amount == Decimal("37800.00")


def test_aylikci_tam_tutar_alir_ama_gun_yine_yazilir():
    """`monthly` → gün SAYISINDAN BAĞIMSIZ tam ay ücreti.

    Gün yine de satıra yazılır: BY 138/158 aylıkçı satırlarında da "Gün" sütunu
    doludur (21 · 23) — gün bir BİLGİDİR, aylıkçıda çarpan değildir.
    """
    satir = hesapla(wage_type=WageType.monthly, wage_amount=Decimal("50600.00"), man_days=23)

    assert satir.days == 23
    assert satir.gross_amount == Decimal("50600.00")


def test_saatlik_ucret_FAIL_CLOSED():
    """🔴 ŞEF KARARI 1 — `hourly` HESAPLANMAZ.

    Puantajda normal çalışma SAATİ kolonu yoktur (`timesheet_entries` yalnız
    `overtime_hours` taşır ve o da sadece `overtime` kodunda doludur). "Günde 8
    saat" gibi bir sabit UYDURMAK para sınıfı bir yalan olurdu (WORKFLOW §3) —
    satır S4 yolunun aynısıyla `uncomputed` kalır, 0 BASILMAZ.
    """
    satir = hesapla(wage_type=WageType.hourly, wage_amount=Decimal("225.00"))

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.net_amount is None
    # `excluded_reason` DEĞİL: satır dışlanmış değil, HESAPLANAMAMIŞTIR.
    assert satir.excluded_reason is None


@pytest.mark.parametrize("eksik", ["wage_amount", "wage_type"])
def test_ucreti_tanimsiz_personel_FAIL_CLOSED(eksik: str):
    """S4 — ücretsiz personelde brüt/net `null`, satır `uncomputed`. 0 BASILMAZ.

    Uydurma 0, eksik veriyi "ödenecek bir şey yok" gibi gösterirdi.
    """
    satir = hesapla(**{eksik: None})

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.deduction_amount is None
    assert satir.net_amount is None
    assert satir.bank_amount is None
    assert satir.cash_amount is None


@pytest.mark.parametrize(
    ("wage_type", "wage_amount"),
    [
        (WageType.daily, Decimal("1800.00")),
        (WageType.hourly, Decimal("225.00")),
        (WageType.monthly, Decimal("50600.00")),
    ],
)
def test_puantaj_KAYDI_OLMAYAN_personel_UC_UCRET_TIPINDE_de_fail_closed(
    wage_type: WageType, wage_amount: Decimal
):
    """🔴 YÖNETİM KARARI (T4b) — dönemde HİÇ puantaj kaydı yoksa satır `uncomputed`.

    "Bu ay hiç çalışmadı" ile "puantajı henüz girilmedi" veritabanında AYIRT
    EDİLEMEZ; ikisi de brüt 0 üretseydi veri eksikliği "ödenecek bir şey yok"
    gibi görünürdü (S4'ün yasakladığı yalan). Ayın 3'ünde bordro hesaplayan
    kullanıcı, puantajı girilmemiş 40 işçiyi 0,00 ile onaya sokabilirdi.

    **`monthly` DE dâhildir:** "aylık ücretlide gün brütü etkilemez" varsayımı
    işe hiç başlamamış ya da çıkmış personele sessizce tam maaş hesaplardı.

    Gün de `null`dur: kaydı olmayan kişinin gün sayısı 0 DEĞİL, BİLİNMEYENDİR.
    """
    satir = hesapla(wage_type=wage_type, wage_amount=wage_amount, has_timesheet_records=False)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.days is None
    assert satir.gross_amount is None
    assert satir.deduction_amount is None
    assert satir.net_amount is None
    assert satir.bank_amount is None
    assert satir.cash_amount is None


def test_kaydi_VAR_ama_adam_gunu_0_ise_hesap_YAPILIR():
    """🔴 Ayrımın öteki yüzü: "kayıt yok" ≠ "kayıt var ama izin/tatil kodlu".

    Puantajı girilmiş ama tüm günleri `MAN_DAY_CODES` dışında kalan personelin
    gün sayısı 0'dır ve bu GERÇEKTİR — veri girilmiştir. Satır hesaplanır.
    Tetikleyici gün SAYISI değil KAYDIN VARLIĞIdır; bu test iki durumun tek
    koşula indirgenmesini (örneğin `man_days == 0` ile kapı kurmayı) engeller.
    """
    gunlukcu = hesapla(man_days=0, has_timesheet_records=True)
    aylikci = hesapla(
        wage_type=WageType.monthly,
        wage_amount=Decimal("50600.00"),
        man_days=0,
        has_timesheet_records=True,
    )

    assert gunlukcu.status is PayrollLineStatus.pending
    assert gunlukcu.days == 0
    assert gunlukcu.gross_amount == Decimal("0.00")
    assert aylikci.status is PayrollLineStatus.pending
    assert aylikci.gross_amount == Decimal("50600.00")


def test_oran_seti_YOKSA_fail_closed():
    """🔴 ŞEF KARARI 2 — `(yıl, tip)` oran satırı yoksa hesap YAPILMAZ.

    `general` tipi personelin oran satırı yoktur (spec §4) ve henüz seti
    girilmemiş bir yıl da aynı durumdadır. Kesintiyi 0 varsaymak "kesinti yok"
    yalanı olurdu (NULL-EŞİK kanonu, WORKFLOW §4) — brüt hesaplanabilse bile
    satır `uncomputed` kalır.
    """
    satir = hesapla(personnel_source=WorkerSource.general, rate=None)

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    assert satir.deduction_amount is None


# --- Dört personel tipi -----------------------------------------------------


def test_sirket_kadrosu_tam_hesap():
    """BY 127 bölümü. 37.800 brüt × %25,759 = 9.736,90 kesinti."""
    satir = hesapla(wage_amount=Decimal("1800.00"), man_days=21)

    assert satir.gross_amount == Decimal("37800.00")
    assert satir.deduction_amount == Decimal("9736.90")
    assert satir.net_amount == Decimal("28063.10")
    assert satir.status is PayrollLineStatus.pending


def test_taseron_satiri_EXCLUDED_ama_tutarlari_HESAPLANIR():
    """K2 — taşeron işçisi görünür ve MALİYETE GİRER, ödeme onayına GİRMEZ.

    Ödemesi hakediş üzerinden taşerona yapılır (TH modülü); satırın `pending`
    olması çift ödeme kapısını açardı. Tutarlar yine hesaplanır (BY 186-189:
    26.400 brüt → 7.064 kesinti gösteriliyor) ve `excluded_reason` DOLDURULUR —
    sessiz atlama yok (WORKFLOW §3).
    """
    satir = hesapla(
        personnel_source=WorkerSource.subcontractor, wage_amount=Decimal("1200.00"), man_days=22
    )

    assert satir.status is PayrollLineStatus.excluded
    assert satir.excluded_reason
    assert satir.gross_amount == Decimal("26400.00")
    assert satir.net_amount is not None


def test_ucretsiz_taseron_de_asla_pending_olmaz():
    """K2 yapısaldır: hesap yapılamasa bile taşeron satırı ödemeye GİRMEZ."""
    satir = hesapla(personnel_source=WorkerSource.subcontractor, wage_amount=None)

    assert satir.status is PayrollLineStatus.excluded
    assert satir.gross_amount is None


@pytest.mark.parametrize("wage_type", list(WageType))
@pytest.mark.parametrize("source", list(WorkerSource))
def test_taseron_hicbir_kombinasyonda_pending_uretmez(source, wage_type):
    """K2 mutasyon süpürmesi: dört tip × üç ücret tipi taranır.

    Yalnız taşeron satırı denetlenir; diğer tipler bu testin kontrol grubudur.
    """
    satir = hesapla(personnel_source=source, wage_type=wage_type)

    if source is WorkerSource.subcontractor:
        assert satir.status is PayrollLineStatus.excluded


def test_serbest_meslek_GUNSUZ_ve_yuzde_yirmi_stopajli():
    """S7 + BY 254-257 BİREBİR: gün "—", 12.500 brüt → 2.500 kesinti → 10.000 net.

    `days` `null`dur çünkü serbest meslekli puantaja girse bile ücreti güne
    bağlı değildir (BY 254 gün hücresi "—").
    """
    satir = hesapla(
        personnel_source=WorkerSource.freelance,
        wage_type=WageType.monthly,
        wage_amount=Decimal("12500.00"),
        man_days=20,
        rate=rate(**SERBEST),
    )

    assert satir.days is None
    assert satir.gross_amount == Decimal("12500.00")
    assert satir.deduction_amount == Decimal("2500.00")
    assert satir.net_amount == Decimal("10000.00")


def test_serbest_meslekte_GUNLUK_ucret_fail_closed():
    """Serbest meslekte gün YOKTUR (S7) → gün çarpanı da yoktur.

    Günlük yevmiyeyi "bir aylık tam tutar" saymak (ör. 1.500 TL'yi aylık gibi
    okumak) para sınıfı bir uydurma olurdu; satır `uncomputed` kalır.
    """
    satir = hesapla(
        personnel_source=WorkerSource.freelance,
        wage_type=WageType.daily,
        rate=rate(**SERBEST),
    )

    assert satir.days is None
    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None


def test_stajyerde_kesinti_SIFIR_ve_net_brute_esit():
    """BY 282-285 BİREBİR: 22 gün · 7.500 brüt · kesinti "—" · 7.500 net.

    Oranların hepsi 0'dır (S2) — bu, "hesaplanamadı"dan FARKLIDIR: oran satırı
    VARDIR ve sıfırdır, o yüzden satır `pending`e girer.
    """
    satir = hesapla(
        personnel_source=WorkerSource.intern,
        wage_type=WageType.monthly,
        wage_amount=Decimal("7500.00"),
        man_days=22,
        rate=rate(**ZERO),
    )

    assert satir.deduction_amount == Decimal("0.00")
    assert satir.net_amount == Decimal("7500.00")
    assert satir.status is PayrollLineStatus.pending


# --- Banka / elden bölüşümü (S3) -------------------------------------------


@pytest.mark.parametrize(
    ("payment_method", "banka_dolu"),
    [
        (PaymentMethod.bank, True),
        (PaymentMethod.cash, False),
        (PaymentMethod.mixed, True),
        (None, True),
    ],
)
def test_varsayilan_bolusum(payment_method, banka_dolu: bool):
    """🔴 ŞEF KARARI 3 — `mixed`/NULL'da varsayılan HEPSİ BANKA.

    BY 143/163/259/287'de banka input'u dolu, elden 0; nakit yalnız taşeron
    satırlarında görünüyor (BY 194/214/234) ve onlar zaten `excluded`. Elden
    nakit varsayılanı üretmek DENETLENMEMİŞ nakit çıkışı önerirdi. Kullanıcı
    bölüşümü T3'teki PATCH ile değiştirir (S3 doğrulamasıyla).
    """
    satir = hesapla(payment_method=payment_method)
    net = satir.net_amount

    assert net is not None
    beklenen = (net, Decimal("0.00")) if banka_dolu else (Decimal("0.00"), net)
    assert (satir.bank_amount, satir.cash_amount) == beklenen


def test_kurus_kaymasi_bolusumu_BOZMAZ():
    """S3 kuruşu kuruşuna: `banka + elden = net`, yuvarlama artığı olmadan.

    Tek sayılı bir brüt × %25,759 kasten seçildi: 12.345,67 × 0,25759 =
    3.180,1211... → yuvarlanır. Kesinti ayrı, net ayrı yuvarlansaydı toplam
    netten bir kuruş kayabilirdi ve T3'te S3 kapısı 422'ye düşerdi.
    """
    satir = hesapla(wage_type=WageType.monthly, wage_amount=Decimal("12345.67"))

    assert satir.gross_amount == Decimal("12345.67")
    assert satir.deduction_amount == Decimal("3180.12")
    # Net TÜREVDİR: brütten kesinti düşülür, bağımsız yuvarlanmaz.
    assert satir.net_amount == Decimal("9165.55")
    assert satir.bank_amount + satir.cash_amount == satir.net_amount


@pytest.mark.parametrize("kurus", [Decimal("0.01") * n for n in range(1, 40)])
def test_her_kurusta_bolusum_nete_esit(kurus: Decimal):
    """Kuruş süpürmesi: 39 farklı artıkta invariant KIRILMAMALI."""
    satir = hesapla(wage_type=WageType.monthly, wage_amount=Decimal("10000") + kurus)

    assert satir.bank_amount + satir.cash_amount == satir.net_amount


# --- Yarım dolu satır üretilmez (yönetim eki #3) ---------------------------


@pytest.mark.parametrize("payment_method", [*list(PaymentMethod), None])
@pytest.mark.parametrize("wage_type", [*list(WageType), None])
@pytest.mark.parametrize("source", list(WorkerSource))
def test_compute_YARIM_DOLU_satir_uretmez(source, wage_type, payment_method):
    """`net` doluysa `banka` ve `elden` de dolu VE toplamları nete eşit olmalı.

    Yarım dolu bir satır T3'teki S3 kapısını sessizce atlatırdı: kapı yalnız
    "gönderilen bölüşüm nete eşit mi" diye bakar, hiç gönderilmemiş bölüşümü
    yakalayamaz. Tarama dört tip × dört ücret durumu × dört ödeme yöntemidir.
    """
    satir = hesapla(personnel_source=source, wage_type=wage_type, payment_method=payment_method)

    if satir.net_amount is None:
        assert satir.bank_amount is None and satir.cash_amount is None
        assert satir.gross_amount is None and satir.deduction_amount is None
        return

    assert satir.bank_amount is not None
    assert satir.cash_amount is not None
    assert satir.bank_amount + satir.cash_amount == satir.net_amount
    assert satir.gross_amount - satir.deduction_amount == satir.net_amount


# --- Yuvarlama TEK YERDE ---------------------------------------------------


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        (Decimal("1.005"), Decimal("1.01")),
        (Decimal("1.004"), Decimal("1.00")),
        (Decimal("2.675"), Decimal("2.68")),
        (Decimal("0.001"), Decimal("0.00")),
    ],
)
def test_yuvarlama_half_up_ve_iki_ondalik(ham: Decimal, beklenen: Decimal):
    """`ROUND_HALF_UP`, iki ondalık — TEK yardımcıda.

    Python'un varsayılanı `ROUND_HALF_EVEN`dir ve 1,005'i 1,00'e indirirdi:
    bordroda her ay bir kuruş kaybı, banka mutabakatında görünen bir fark.
    """
    assert compute.quantize_money(ham) == beklenen
