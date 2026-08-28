"""`timesheet/hours.py` — FM/normal/adam-gün kuralının SAF birim testleri.

DB'siz ve HTTP'siz: kural bir aritmetiktir ve kırıldığında hata mesajı doğrudan
kuralı göstermelidir. Uçtan geçen ölçüm `test_week.py`dedir; ikisi birbirinin
yerine geçmez (biri kuralı, öteki kuralın YAYINLANDIĞINI bekçiler).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.timesheet.hours import (
    NORMAL_DAY_HOURS,
    WEEKLY_NORMAL_HOURS,
    man_days,
    period_totals,
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


# --------------------------------------------------------------------------- #
# 🔴 PUAN-SAAT-3 — `period_totals`: 45 tavani HAFTALIKTIR, aylik DEGILDIR
# --------------------------------------------------------------------------- #


def _temmuz(*gunler) -> list[tuple[date, Decimal]]:
    return [(date(2026, 7, gun), Decimal(str(saat))) for gun, saat in gunler]


def test_haftalik_tavan_AY_TOPLAMINA_uygulanmaz() -> None:
    """🔴🔴 Bu testin bekçilediği hata bir PARA FELAKETİDİR.

    Temmuz 2026'da dört tam hafta × 5 gün × 9 saat = 180 saat, FM **0**.
    45 tavanı ay toplamına tek seferde uygulansaydı normal 45, FM **135**
    çıkardı; 200 TL/saat bir kişide brüt 36.000 yerine
    `200 × (45 + 135 × 1,5) = 49.500` olurdu — kişi başına **13.500 TL** fazla
    ödeme.

    Günler ISO haftalarına dağıtılır: 1-3 Tem (27. hafta), 6-10 (28.),
    13-17 (29.), 20-24 (30.), 27-29 (31.).
    """
    gunler = [(gun, 9) for gun in (1, 2, 3, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17)]
    gunler += [(gun, 9) for gun in (20, 21, 22, 23, 24, 27, 28, 29)]
    sonuc = period_totals(_temmuz(*gunler))

    assert sonuc.total_hours == Decimal("189.0")
    assert sonuc.overtime_hours == Decimal("0.0")
    assert sonuc.normal_hours == Decimal("189.0")


def test_her_hafta_KENDI_tavanina_vurur() -> None:
    """İki AYRI hafta, ikisi de 48 saat → her birinde 3 saat FM (toplam 6).

    Haftalar birleştirilseydi 96 saatin 51'i FM olurdu (45 tavanı bir kez
    uygulanır) — 45 saatlik bir fark.
    """
    # 28. hafta (6-10 Tem) ve 29. hafta (13-17 Tem): beşer gün, dördü 9 biri 12.
    gunler = [(6, 9), (7, 9), (8, 9), (9, 9), (10, 12)]
    gunler += [(13, 9), (14, 9), (15, 9), (16, 9), (17, 12)]
    sonuc = period_totals(_temmuz(*gunler))

    assert sonuc.total_hours == Decimal("96.0")
    assert sonuc.normal_hours == Decimal("90.0")
    assert sonuc.overtime_hours == Decimal("6.0")


def test_haftalar_YIL_ve_HAFTA_ciftiyle_ayrilir() -> None:
    """🔴 ISO hafta NUMARASI tek başına yetmez: yıl da anahtarın parçasıdır.

    2026'nın 1. haftası (29 Ara 2025 - 4 Oca 2026) ile 2027'nin 1. haftası
    (4-10 Oca 2027) aynı numarayı taşır. Yalnız numaraya bakılsaydı iki AYRI
    yılın haftası tek havuzda toplanır, 45 tavanı bir kez uygulanır ve FM
    olmayan saatler FM'e düşerdi.

    Burada iki hafta da 45 saattir → FM 0 beklenir; birleşselerdi 90 saatin
    45'i FM olurdu.
    """
    # 2026-W01 = 29 Ara 2025 - 4 Oca 2026 · 2027-W01 = 4-10 Oca 2027.
    hafta_2026 = [(date(2025, 12, gun), Decimal("9")) for gun in (29, 30, 31)]
    hafta_2026 += [(date(2026, 1, gun), Decimal("9")) for gun in (1, 2)]
    hafta_2027 = [(date(2027, 1, gun), Decimal("9")) for gun in (4, 5, 6, 7, 8)]
    assert {d.isocalendar()[1] for d, _ in hafta_2026 + hafta_2027} == {1}
    sonuc = period_totals(hafta_2026 + hafta_2027)

    assert sonuc.total_hours == Decimal("90.0")
    assert sonuc.overtime_hours == Decimal("0.0")


def test_bos_donem_UC_SIFIR_dondurur() -> None:
    """Hücresi olmayan dönem `None` değil ÜÇ SIFIRDIR — "kaydı var ama hepsi
    kodlu" hâlinin taşıyıcısı budur (`compute_line` `None`u ayrı ele alır)."""
    sonuc = period_totals([])

    assert sonuc == (Decimal("0.0"), Decimal("0.0"), Decimal("0.0"))
