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

from app.modules.payroll import compute, income_tax
from app.modules.payroll.models import PayrollLineStatus, PayrollRate
from app.modules.payroll.tax_bracket_seed_data import (
    MINIMUM_WAGE_GROSS_2026,
    TAX_BRACKETS_2026_WAGE,
)
from app.modules.personnel.models import PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource
from app.modules.timesheet import hours as hours_rules


def gunler(tam_gun: int, fm: str = "0") -> hours_rules.WeekHours:
    """`tam_gun` adet TAM (9 saatlik) gün + istenirse fazla mesai saati.

    🔴 PUAN-SAAT-3: `compute_line` artık gün SAYISI değil SAAT TÜREVİ alır.
    Yardımcı, eski `man_days=N` çağrılarının BİREBİR karşılığını üretir
    (`N × 9` normal saat) — böylece bu dosyadaki mockup tutarları (BY 143
    37.800 = 21 × 1.800) DEĞİŞMEDEN geçerli kalır ve tip değişimi eski
    beklentileri sessizce gevşetmez.
    """
    normal = Decimal(tam_gun) * hours_rules.NORMAL_DAY_HOURS
    fazla = Decimal(fm)
    return hours_rules.WeekHours(
        normal_hours=normal, overtime_hours=fazla, total_hours=normal + fazla
    )

#: 2026 ÜCRET tarifesi — `tax_bracket_seed_data`dan gelir, elle KOPYALANMAZ.
BRACKETS = tuple(
    income_tax.TaxBracket(ordinal=o, upper_bound=u, rate_pct=r)
    for o, u, r in TAX_BRACKETS_2026_WAGE
)


#: Varsayılan vergi bağlamı: yılın İLK ayı, devir yok. Ayrışma noktaları
#: (Temmuz istisnası, kümülatif taşma, dilim sınırları) kendi testlerinde
#: bağlamı AÇIKÇA değiştirir.
def tax_context(**degisiklikler) -> compute.TaxContext:
    varsayilan = {
        "month": 1,
        "prior_cumulative_base": Decimal("0.00"),
        "brackets": BRACKETS,
        "minimum_wage_gross": MINIMUM_WAGE_GROSS_2026,
    }
    return compute.TaxContext(**{**varsayilan, **degisiklikler})


# SGK 70-73 işçi payları (S1). 🔴 IK3-GV: `income_tax_pct` artık **`None`**dır ve
# bu "vergi yok" DEMEK DEĞİLDİR — `payroll_tax_brackets` üzerinden DİLİMLİ motor
# demektir (K3). Dört kalemi tek yüzdede toplayan eski %25,759 sabiti KALKTI:
# dilimli vergi brütün sabit bir yüzdesi değildir, aynı brüt yılın hangi ayında
# olduğuna göre farklı vergi üretir.
SGK_4A = {
    "sgk_employee_pct": Decimal("14.000"),
    "unemployment_employee_pct": Decimal("1.000"),
    "income_tax_pct": None,
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
        "work_hours": gunler(21),
        "has_timesheet_records": True,
        "rate": rate(),
        "overtime_multiplier": Decimal("1.500"),
        "tax": tax_context(),
    }
    return compute.compute_line(**{**varsayilan, **kwargs})


# --- Oran toplamı: işçi tarafı / işveren tarafı ayrımı ----------------------


def test_dilimli_rejimde_toplam_isci_orani_TANIMSIZDIR():
    """🔴 IK3-GV — `income_tax_pct IS NULL` iken "toplam yüzde" YOKTUR.

    `employee_deduction_pct` bu durumda **`None`** döner, 0 DEĞİL: 0 dönmek
    "kesinti yok" yalanı olurdu (NULL-EŞİK kanonu) ve dilimli vergiyi hesabın
    dışına düşürürdü. Eski %25,759 sabiti tam olarak bu yüzden kaldırıldı.
    """
    assert compute.employee_deduction_pct(rate()) is None


def test_duz_oranli_rejimde_isci_orani_dort_kalemin_toplamidir():
    """Düz oran rejiminde (serbest meslek) toplam yine tanımlıdır: 0+0+20+0."""
    assert compute.employee_deduction_pct(rate(**SERBEST)) == Decimal("20.000")


def test_isveren_oranlari_kesintiye_GIRMEZ():
    """İşveren payları maliyettir, işçinin kesintisi değildir (spec §7).

    İşveren sütunları uçuk değerlere çekilir; kesinti KIMILDAMAMALIDIR.
    Mutasyon denetimidir: kesinti yanlışlıkla yedi sütunu toplarsa kırmızıya
    döner. 🔴 IK3-GV ile oran TOPLAMI üzerinden değil, hesaplanan KESİNTİ
    üzerinden ölçülür — dilimli rejimde "toplam yüzde" diye bir sayı yoktur.
    """
    sisirilmis = hesapla(
        rate=rate(
            sgk_employer_pct=Decimal("99.000"),
            unemployment_employer_pct=Decimal("88.000"),
            short_work_pct=Decimal("77.000"),
        )
    )
    normal = hesapla()

    assert sisirilmis.deduction_amount == normal.deduction_amount
    assert sisirilmis.net_amount == normal.net_amount


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
    satir = hesapla(wage_amount=Decimal("1800.00"), work_hours=gunler(21))

    assert satir.days == 21
    assert satir.gross_amount == Decimal("37800.00")


def test_aylikci_tam_tutar_alir_ama_gun_yine_yazilir():
    """`monthly` → gün SAYISINDAN BAĞIMSIZ tam ay ücreti.

    Gün yine de satıra yazılır: BY 138/158 aylıkçı satırlarında da "Gün" sütunu
    doludur (21 · 23) — gün bir BİLGİDİR, aylıkçıda çarpan değildir.
    """
    satir = hesapla(wage_type=WageType.monthly, wage_amount=Decimal("50600.00"), work_hours=gunler(23))

    assert satir.days == 23
    assert satir.gross_amount == Decimal("50600.00")


def test_saatlik_ucret_ARTIK_HESAPLANIR_ve_FM_yuzde_50_zamlidir():
    """🔴 PUAN-SAAT-3 — ŞEF KARARI 1 KAPANDI, `hourly` yolu AÇILDI.

    Mockup E5 356-358 birebir: *"Bu Hafta Normal … × saatlik ücret"* +
    *"Bu Hafta FM … × saatlik ücret × 1,5"*.

    Sayı mockup'ın KENDİ haftasından kurulur (E5 236-245, Mehmet Yılmaz):
    normal **45**, FM **8**. Saatlik ücret 225 ile:

        45 × 225           = 10.125,00
         8 × 225 × 1,5     =  2.700,00
        ------------------------------
                             12.825,00

    🔑 FM'in AYRI çarpanla girdiği bu testte kanıtlanır: FM saati normal saatle
    aynı fiyattan ödenseydi brüt 11.925 olurdu (900 TL eksik).
    """
    satir = hesapla(
        wage_type=WageType.hourly,
        wage_amount=Decimal("225.00"),
        work_hours=hours_rules.WeekHours(
            normal_hours=Decimal("45.0"),
            overtime_hours=Decimal("8.0"),
            total_hours=Decimal("53.0"),
        ),
    )

    assert satir.status is PayrollLineStatus.pending
    assert satir.gross_amount == Decimal("12825.00")
    # Adam-gün TÜREVDİR ve FM saatini de içerir: 53 ÷ 9 = 5,9 (E5 349-350).
    assert satir.days == Decimal("5.9")


def test_YEVMIYELIDE_saatlik_ucret_YEVMIYENIN_DOKUZDA_BIRIDIR():
    """🔴 Mockup E5 359 birebir: *"Saatlik ücret = günlük ücret ÷ 9"*.

    Aynı hafta (normal 45 · FM 8), yevmiye 2.025 = 225 × 9 ile kurulunca
    saatlik ücretli satırla **BİREBİR AYNI** brütü vermelidir. İki ücret tipi
    için iki ayrı formül yazılsaydı bu eşitlik bozulurdu ve aynı çalışma iki
    farklı para ederdi.

    🔑 Bölme YUVARLANMAZ: `2025 ÷ 9 = 225` tamdır, ama `1200 ÷ 9 = 133,333…`
    için kuruşa yuvarlama 45 saatlik haftada 15 kuruş kaybettirirdi
    (`test_yevmiye_dokuza_TAM_bolunmediginde_kurus_kaybi_YOK`).
    """
    ortak = {
        "work_hours": hours_rules.WeekHours(
            normal_hours=Decimal("45.0"),
            overtime_hours=Decimal("8.0"),
            total_hours=Decimal("53.0"),
        )
    }
    saatlik = hesapla(wage_type=WageType.hourly, wage_amount=Decimal("225.00"), **ortak)
    yevmiyeli = hesapla(wage_type=WageType.daily, wage_amount=Decimal("2025.00"), **ortak)

    assert yevmiyeli.gross_amount == saatlik.gross_amount == Decimal("12825.00")


def test_yevmiye_dokuza_TAM_bolunmediginde_kurus_kaybi_YOK():
    """🔴 Saatlik ücret ARA DEĞERDİR ve yuvarlanmaz (`hourly_rate`).

    1.200 TL yevmiye → 133,333… TL/saat. Kuruşa yuvarlansaydı (133,33) 45
    saatlik hafta 5.999,85 ederdi; oysa aynı hafta beş tam yevmiyedir: 6.000.
    Fark haftada 15 kuruş, kişi başına yılda ~7,80 TL — para sınıfı sızıntı.
    """
    satir = hesapla(
        wage_amount=Decimal("1200.00"),
        work_hours=hours_rules.WeekHours(
            normal_hours=Decimal("45.0"),
            overtime_hours=Decimal("0.0"),
            total_hours=Decimal("45.0"),
        ),
    )

    assert satir.gross_amount == Decimal("6000.00")


def test_FM_carpani_BILINMIYORSA_satir_FAIL_CLOSED():
    """🔴 K1 + NULL-EŞİK — FM çarpanı VERİDİR, 1,5 VARSAYILMAZ.

    `payroll_overtime_rates`te o yılın satırı yoksa çarpan `None` gelir. FM
    saati OLAN satır `uncomputed` kalır ve **0 ya da 1,5 uydurulmaz**; brüt
    `null` durur (S4).
    """
    satir = hesapla(
        overtime_multiplier=None,
        work_hours=hours_rules.WeekHours(
            normal_hours=Decimal("45.0"),
            overtime_hours=Decimal("8.0"),
            total_hours=Decimal("53.0"),
        ),
    )

    assert satir.status is PayrollLineStatus.uncomputed
    assert satir.gross_amount is None
    # Gün yine YAZILIR: puantajdan OKUNAN bir olgudur (`_uncomputed`).
    assert satir.days == Decimal("5.9")


def test_FM_YOKSA_carpanin_bilinmemesi_satiri_DUSURMEZ():
    """🔴 IK3-RATE-FIX kanonu — bir korkuluk, koruduğu şeyden büyük hasar
    üretemez.

    FM saati 0 olan bir dönemde çarpan hesaba HİÇ GİRMEZ; onun eksikliği
    yüzünden satırı `uncomputed`a düşürmek, ilgisiz bir eksik yüzünden ödemeyi
    durdurmak olurdu.
    """
    satir = hesapla(overtime_multiplier=None, work_hours=gunler(21))

    assert satir.status is PayrollLineStatus.pending
    assert satir.gross_amount == Decimal("37800.00")


def test_YARIM_GUN_TAM_GUN_SAYILMAZ():
    """🔴🔴 PUAN-SAAT-3'ün ASIL BORCU: 4 saatlik gün TAM GÜN değildir.

    Eski `payroll` "saati olan hücre" SAYIYORDU: 4 saatlik bir gün de 1 gündü
    ve yevmiyeli personele **tam yevmiye** ödenirdi. Mockup E5 305 tam olarak
    bu hücreyi çiziyor (Ayşe Demir, Perşembe `value="4"`).

    20 tam gün + 1 yarım gün (4 saat) = 184 saat:

        eski sayım : 21 gün × 1.800 = 37.800,00
        yeni türev : 184 ÷ 9 = 20,4 adam-gün · brüt = 200 × 184 = 36.800,00
        ------------------------------------------------------------------
        FAZLA ÖDEME (kişi başına, tek yarım günde)      = 1.000,00 TL
    """
    satir = hesapla(
        work_hours=hours_rules.WeekHours(
            normal_hours=Decimal("184.0"),
            overtime_hours=Decimal("0.0"),
            total_hours=Decimal("184.0"),
        )
    )

    assert satir.days == Decimal("20.4")
    assert satir.gross_amount == Decimal("36800.00")


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
    gunlukcu = hesapla(work_hours=gunler(0), has_timesheet_records=True)
    aylikci = hesapla(
        wage_type=WageType.monthly,
        wage_amount=Decimal("50600.00"),
        work_hours=gunler(0),
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
    """BY 127 bölümü — 🔴 IK3-GV sonrası DÖRT KALEM, tek yüzde DEĞİL.

    37.800,00 brüt · OCAK (kümülatif 0):
      SGK işçi   %14      → 5.292,00
      işsizlik   %1       →   378,00
      matrah = 37.800 − 5.670 = **32.130,00** (istisna matrahta KALIR)
      gelir vergisi: 32.130 × %15 = 4.819,50 − istisna 4.211,325 = **608,18**
      damga: 37.800 × %0,759 = 286,902 − istisna 250,6977 = **36,20**
      kesinti = 6.314,38 · net = 31.485,62

    Eski sayı (9.736,90 = 37.800 × %25,759) MEVZUATA DAYANMIYORDU: içindeki
    düz %10 gelir vergisi mockup etiketinden (SGK 72) gelmişti ve GVK m.103'ün
    hiçbir dilimine karşılık gelmiyordu.
    """
    satir = hesapla(wage_amount=Decimal("1800.00"), work_hours=gunler(21))

    assert satir.gross_amount == Decimal("37800.00")
    assert satir.tax_base_amount == Decimal("32130.00")
    assert satir.cumulative_tax_base == Decimal("32130.00")
    assert satir.income_tax_amount == Decimal("608.18")
    assert satir.deduction_amount == Decimal("6314.38")
    assert satir.net_amount == Decimal("31485.62")
    assert satir.status is PayrollLineStatus.pending


def test_taseron_satiri_EXCLUDED_ama_tutarlari_HESAPLANIR():
    """K2 — taşeron işçisi görünür ve MALİYETE GİRER, ödeme onayına GİRMEZ.

    Ödemesi hakediş üzerinden taşerona yapılır (TH modülü); satırın `pending`
    olması çift ödeme kapısını açardı. Tutarlar yine hesaplanır (BY 186-189:
    26.400 brüt → 7.064 kesinti gösteriliyor) ve `excluded_reason` DOLDURULUR —
    sessiz atlama yok (WORKFLOW §3).
    """
    satir = hesapla(
        personnel_source=WorkerSource.subcontractor, wage_amount=Decimal("1200.00"), work_hours=gunler(22)
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
        work_hours=gunler(20),
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
        work_hours=gunler(22),
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

    Tek sayılı bir brüt kasten seçildi (12.345,67): SGK %14 → 1.728,3938 ve
    işsizlik %1 → 123,4567 ikisi de yuvarlanır. Kesinti dört kalemin toplamıdır
    (IK3-GV) ve net onun FARKIDIR; net bağımsız yuvarlansaydı `banka + elden`
    netten bir kuruş kayar, T3'te S3 kapısı 422'ye düşerdi.

    Gelir vergisi ve damga **0,00**dır: 12.345,67 brüt, 2026 asgari ücretinin
    (33.030,00) ALTINDADIR → KK-7 istisnası ikisini de tamamen karşılar.
    """
    satir = hesapla(wage_type=WageType.monthly, wage_amount=Decimal("12345.67"))

    assert satir.gross_amount == Decimal("12345.67")
    assert satir.income_tax_amount == Decimal("0.00")
    assert satir.deduction_amount == Decimal("1851.85")  # 1.728,39 + 123,46
    # Net TÜREVDİR: brütten kesinti düşülür, bağımsız yuvarlanmaz.
    assert satir.net_amount == Decimal("10493.82")
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
