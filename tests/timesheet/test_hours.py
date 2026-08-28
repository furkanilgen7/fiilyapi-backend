"""`timesheet/hours.py` — FM/normal/adam-gün kuralının SAF birim testleri.

DB'siz ve HTTP'siz: kural bir aritmetiktir ve kırıldığında hata mesajı doğrudan
kuralı göstermelidir. Uçtan geçen ölçüm `test_week.py`dedir; ikisi birbirinin
yerine geçmez (biri kuralı, öteki kuralın YAYINLANDIĞINI bekçiler).
"""

from decimal import Decimal

import pytest

from app.modules.timesheet.hours import (
    NORMAL_DAY_HOURS,
    WEEKLY_NORMAL_HOURS,
    man_days,
    week_totals,
)


def _d(*values) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


# E5 236-313: mockup'ın dört satırı (Ayşe düzeltilmiş Pazar=5 ile).
@pytest.mark.parametrize(
    ("ad", "saatler", "beklenen"),
    [
        ("Mehmet", (9, 11, 9, 9, 9, 6), ("45", "8", "53")),
        ("Ali", (9, 9, 12, 9), ("36", "3", "39")),
        ("Hasan", (9, 9, 9, 10, 9, 8), ("45", "9", "54")),
        ("Ayşe", (9, 9, 9, 4, 9, 7, 5), ("45", "7", "52")),
    ],
)
def test_mockupun_dort_satiri_BIREBIR_uretilir(ad, saatler, beklenen) -> None:
    sonuc = week_totals(_d(*saatler))
    assert tuple(str(x) for x in (sonuc.normal_hours, sonuc.overtime_hours, sonuc.total_hours)) == (
        f"{Decimal(beklenen[0]):.1f}",
        f"{Decimal(beklenen[1]):.1f}",
        f"{Decimal(beklenen[2]):.1f}",
    ), ad


def test_kural_SAF_HAFTALIK_degildir() -> None:
    """🔴 Ali'nin haftası 39 saattir (45'in ALTINDA) ama FM'i 3'tür.

    Saf haftalık kural (`FM = max(0, toplam − 45)`) burada **0** verirdi ve
    mockup'ın E5 268'deki "3"ü ile çelişirdi. Günlük 9'u aşan saat, hafta tavanı
    hiç aşılmasa bile FM'dir.
    """
    assert week_totals(_d(9, 9, 12, 9)).overtime_hours == Decimal("3.0")


def test_kural_SAF_GUNLUK_de_degildir() -> None:
    """🔴 Mehmet'in günlük fazlası yalnız 2 saattir (11−9) ama FM'i 8'dir.

    Saf günlük kural (`FM = Σ max(0, gün−9)`) **2** verirdi ve E5 246'daki "8"
    ile çelişirdi. Günlük tavanın altında kalan saatler de haftalık 45 tavanına
    vurur ve aşan kısım FM olur.
    """
    assert week_totals(_d(9, 11, 9, 9, 9, 6)).overtime_hours == Decimal("8.0")


def test_bos_hafta_sifirdir() -> None:
    sonuc = week_totals([])
    assert (sonuc.normal_hours, sonuc.overtime_hours, sonuc.total_hours) == (
        Decimal("0.0"),
        Decimal("0.0"),
        Decimal("0.0"),
    )


def test_tavanin_TAM_UZERINDE_hafta_FM_uretmez() -> None:
    """45 saatin kendisi normaldir; sınırda `<` yerine `<=` hatası 1 saatlik bir
    FM icat ederdi (İK-2'nin sınır günü dersi)."""
    sonuc = week_totals(_d(9, 9, 9, 9, 9))
    assert sonuc.normal_hours == Decimal("45.0")
    assert sonuc.overtime_hours == Decimal("0.0")


def test_yarim_gun_normale_TAM_katilir() -> None:
    """4 saatlik gün 4 saat normaldir — 9'a tamamlanmaz, 0 da sayılmaz."""
    assert week_totals(_d(4)).normal_hours == Decimal("4.0")


def test_adam_gun_saatin_dokuza_bolumudur() -> None:
    """E5 349-350: `588 ÷ 9 = 65,3` — bir ondalık basamak."""
    assert man_days(Decimal("588")) == Decimal("65.3")
    assert man_days(Decimal("0")) == Decimal("0.0")
    assert man_days(Decimal("9")) == Decimal("1.0")


def test_ekran_sabitleri_mockuptan() -> None:
    """E5 71 başlığı: "Normal gün 9 saat · Haftalık normal 45 saat"."""
    assert NORMAL_DAY_HOURS == Decimal("9")
    assert WEEKLY_NORMAL_HOURS == Decimal("45")
