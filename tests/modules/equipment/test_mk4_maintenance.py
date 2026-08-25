"""MK-4 T2 — bakım penceresi çekirdeği (`maintenance.py`), SAF hesap.

Mockup: `projedesign/Makine - Ekipman Detay.dc.html` 🔧 Bakım Bilgileri
(MD:145-160) + `Sonraki Bakım` KPI'ı (MD:46-48).

🔴 **Mockup SAYILARI burada BİR KEZ kural kanıtı olarak kullanılır** ve bu
bilinçli bir istisnadır: MD'nin bakım kartı kendi içinde ARİTMETİK OLARAK
TUTARLIDIR (14.286 − 14.000 = 286 · 286/500 = %57,2 → `%57` · 14.000 + 500 =
14.500 · 14.500 − 14.286 = 214 sa) ve dördü birden tutuyorsa bu, mockup'ın
örtük iş kuralıdır (`cost.DAILY_HOURS`ın dört ekipmanda doğrulanması emsali).
Geri kalan her beklenti testin KENDİ kurduğu sayıdan türer.
"""

from datetime import date
from decimal import Decimal

from app.modules.equipment import maintenance
from app.modules.equipment.models import EquipmentMaintenancePeriod

_HOURMETER = Decimal("14286")
_LAST = Decimal("14000")


# --- Periyodun saat karşılığı ---


def test_periyot_saatleri_uc_uyede_okunur_monthly_None():
    """🔴 `monthly` bir EKSİKLİK değil bir KAPIdır: aylık bakım yapan makinede
    "kalan saat" diye bir büyüklük YOKTUR; uydurma bir saat karşılığı ekranda
    çubuk doldurmak için olmayan bir kural icat etmek olurdu."""
    assert maintenance.period_hours(EquipmentMaintenancePeriod.hours_250) == 250
    assert maintenance.period_hours(EquipmentMaintenancePeriod.hours_500) == 500
    assert maintenance.period_hours(EquipmentMaintenancePeriod.hours_1000) == 1000
    assert maintenance.period_hours(EquipmentMaintenancePeriod.monthly) is None
    assert maintenance.period_hours(None) is None


def test_periyot_haritasi_dort_uyenin_HEPSINI_kapsar():
    """Enum'a beşinci bir üye eklenirse bu test KIRMIZI olur — sessizce
    `KeyError` fırlatan bir `period_hours` yerine burada durulur."""
    assert set(maintenance.PERIOD_HOURS) == set(EquipmentMaintenancePeriod)


# --- MD:145-160 aritmetiği ---


def test_mockup_bakim_karti_dort_sayisi_birden_tutar():
    """MD:151/153/155/159/160 — 14.000 · 14.500 · 286 · 214 · %57."""
    period = EquipmentMaintenancePeriod.hours_500
    kullanilan = maintenance.used_hours(hourmeter_hours=_HOURMETER, last_service_hourmeter=_LAST)
    sonraki = maintenance.next_service_hourmeter(last_service_hourmeter=_LAST, period=period)
    kalan = maintenance.remaining_hours(next_service_hourmeter=sonraki, hourmeter_hours=_HOURMETER)
    assert kullanilan == Decimal("286")
    assert sonraki == Decimal("14500")
    assert kalan == Decimal("214")
    assert maintenance.usage_pct(used_hours=kullanilan, period=period) == Decimal("57.2")


# --- Fail-closed (K16 deseni) ---


def test_hourmeter_yoksa_hicbir_turev_hesaplanmaz():
    assert maintenance.used_hours(hourmeter_hours=None, last_service_hourmeter=_LAST) is None
    assert (
        maintenance.remaining_hours(next_service_hourmeter=Decimal("14500"), hourmeter_hours=None)
        is None
    )


def test_son_bakim_okumasi_yoksa_pencere_hesaplanmaz():
    assert maintenance.used_hours(hourmeter_hours=_HOURMETER, last_service_hourmeter=None) is None
    assert (
        maintenance.next_service_hourmeter(
            last_service_hourmeter=None, period=EquipmentMaintenancePeriod.hours_500
        )
        is None
    )


def test_monthly_periyotta_sonraki_bakim_ve_yuzde_None():
    """Saat cinsinden pencere olmayan makinede çubuk ÇİZİLMEZ."""
    period = EquipmentMaintenancePeriod.monthly
    assert maintenance.next_service_hourmeter(last_service_hourmeter=_LAST, period=period) is None
    assert maintenance.usage_pct(used_hours=Decimal("286"), period=period) is None


def test_sayac_geri_gitmisse_kullanilan_saat_None():
    """🔴 Tutarsız veri sessizce hesaplanmaz: hourmeter son bakım okumasından
    KÜÇÜKSE (sayaç değişmiş ya da yanlış girilmiş) negatif bir çubuk hatayı
    GİZLERDİ."""
    assert (
        maintenance.used_hours(hourmeter_hours=Decimal("13000"), last_service_hourmeter=_LAST)
        is None
    )


# --- Gecikmiş bakım GERÇEKTİR, kırpılmaz ---


def test_bakimi_gecmis_makinede_kalan_saat_NEGATIF_yuzde_100_ustu():
    """0'a kırpılsaydı gecikmiş bakım ekranda "tam zamanında" görünürdü."""
    period = EquipmentMaintenancePeriod.hours_250
    hourmeter = Decimal("14300")
    sonraki = maintenance.next_service_hourmeter(last_service_hourmeter=_LAST, period=period)
    kalan = maintenance.remaining_hours(next_service_hourmeter=sonraki, hourmeter_hours=hourmeter)
    assert sonraki == Decimal("14250")
    assert kalan == Decimal("-50")
    kullanilan = maintenance.used_hours(hourmeter_hours=hourmeter, last_service_hourmeter=_LAST)
    assert maintenance.usage_pct(used_hours=kullanilan, period=period) == Decimal("120.0")


# --- Günlük tempo ve tahmini tarih ---


def test_gunluk_tempo_takvim_gunune_bolunur_hic_calismamissa_None():
    """Payda TAKVİM GÜNÜdür: hafta sonu duran makinenin gerçek temposu
    çalışılan gün sayısından değil takvimden okunur. Tempo 0 ise `None` —
    0'a bölmek sonsuz, `as_of` basmak "bugün bakım" demek olurdu."""
    assert maintenance.daily_rate(window_hours=Decimal("450"), window_days=90) == Decimal("5")
    assert maintenance.daily_rate(window_hours=Decimal("0"), window_days=90) is None
    assert maintenance.daily_rate(window_hours=Decimal("450"), window_days=0) is None


def test_tahmini_tarih_kalan_saati_tempoya_bolup_YUKARI_yuvarlar():
    """37,3 günü 37'ye indirmek bakımı makine eşiğe VARMADAN önceye koyardı."""
    gun = date(2026, 7, 31)
    tarih = maintenance.estimated_service_date(
        remaining_hours=Decimal("214"), daily_rate=Decimal("5.73"), as_of=gun
    )
    # 214 / 5,73 = 37,34… → 38 gün
    assert tarih == date(2026, 9, 7)


def test_tahmini_tarih_kalan_sifir_ya_da_negatifse_BUGUNDUR():
    """Bakım gelmiştir; geçmişe tarih uydurmak "ne zaman yapılacak"ı sorana
    "ne zaman yapılmalıydı"yı cevaplamak olurdu."""
    gun = date(2026, 7, 31)
    for kalan in (Decimal("0"), Decimal("-50")):
        assert (
            maintenance.estimated_service_date(
                remaining_hours=kalan, daily_rate=Decimal("5.73"), as_of=gun
            )
            == gun
        )


def test_tahmini_tarih_girdilerden_biri_yoksa_None():
    gun = date(2026, 7, 31)
    assert (
        maintenance.estimated_service_date(
            remaining_hours=None, daily_rate=Decimal("5.73"), as_of=gun
        )
        is None
    )
    assert (
        maintenance.estimated_service_date(
            remaining_hours=Decimal("214"), daily_rate=None, as_of=gun
        )
        is None
    )
