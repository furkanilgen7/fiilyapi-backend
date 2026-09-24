"""Santiye EV ayarlarinin varsayilanlari (K1: sirket varsayilani katmani YOK, sabitler).

Ayar satiri yoksa GET bunlari doner; ilk PUT satiri bunlarla degil GOVDEYLE yazar.
Motor kararlariyla (PF bantlari, tatil gunu) cakisan her deger motorun `policy`
sabitinden OKUNUR — iki kopya bir gun ayrisirdi.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.earned_value.engine.policy import (
    DEFAULT_CUMULATIVE_PF_BANDS,
    DEFAULT_DAILY_PF_BANDS,
    DEFAULT_WEEKLY_HOLIDAYS,
)

#: K5 — hafta basi Pazartesi (0). Mockup'taki Cuma ornek veridir.
WEEK_START_DOW = 0
#: S5 — calisilmayan gunler: Pazar.
WEEKLY_OFF_DAYS: frozenset[int] = DEFAULT_WEEKLY_HOLIDAYS
#: K10 — histogramda gereken kisi = a-s ÷ (is gunu × standart gunluk saat).
STANDARD_DAILY_HOURS = Decimal("9.00")
#: K6 — tolerans 2,0 puan (0 her gunu Ahead/Late yapardi).
TOLERANCE_POINTS = Decimal("2.00")

#: Degerler kolon OLCEGINE sabitlenir (`Numeric(4,2)` · `(5,2)` · `(5,3)`): varsayilan GET
#: ile kayit sonrasi GET ayni metni versin ("9" ≠ "9.00" — ajan B1.3 olcumu).
_BAND = Decimal("0.001")
DAILY_RED_BELOW = DEFAULT_DAILY_PF_BANDS.red_below.quantize(_BAND)
DAILY_GREEN_FROM = DEFAULT_DAILY_PF_BANDS.green_from.quantize(_BAND)
DAILY_HIGH_ABOVE: Decimal = (DEFAULT_DAILY_PF_BANDS.high_above or Decimal("1.05")).quantize(_BAND)
WEEKLY_RED_BELOW = DEFAULT_CUMULATIVE_PF_BANDS.red_below.quantize(_BAND)
WEEKLY_GREEN_FROM = DEFAULT_CUMULATIVE_PF_BANDS.green_from.quantize(_BAND)


def days_to_mask(days: frozenset[int] | set[int]) -> int:
    """Haftanin gunleri kumesi → bit maskesi (bit k = `date.weekday() == k`)."""
    return sum(1 << d for d in days)


def mask_to_days(mask: int) -> frozenset[int]:
    return frozenset(d for d in range(7) if mask & (1 << d))
