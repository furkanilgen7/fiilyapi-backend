"""Durum (Ahead/Late/Normal) ve PF bandi — GOSTERILEN (yuvarlanmis) degerle karar (K18, K27).

Motorun urettigi variance ve PF ham kalir; yalniz bant/durum KARARI ekranda gorunen
degere bakar ki renk ile metin hic celismesin.
"""

from __future__ import annotations

from decimal import Decimal

from .policy import (
    PF_BAND_QUANTUM,
    PF_BAND_ROUNDING,
    STATUS_POINTS_SCALE,
    STATUS_QUANTUM,
    STATUS_ROUNDING,
)
from .types import PfBand, PfBands, Status


def variance_points(variance: Decimal) -> Decimal:
    """K27 GOSTERILEN sapma: round_half_up(variance × 100, 1) puan (durum karari buna bakar)."""
    return (variance * STATUS_POINTS_SCALE).quantize(STATUS_QUANTUM, rounding=STATUS_ROUNDING)


def classify_status(variance: Decimal | None, tolerance_points: Decimal) -> Status | None:
    """v = `variance_points(variance)` · |v| <= tol → Normal · v > tol → Ahead
    · v < −tol → Late (spec §3.5 + K27)."""
    if variance is None:
        return None
    points = variance_points(variance)
    if points > tolerance_points:
        return Status.AHEAD
    if points < -tolerance_points:
        return Status.LATE
    return Status.NORMAL


def pf_band(value: Decimal | None, bands: PfBands) -> PfBand | None:
    """Bant karari 2 ondaliga yuvarlanmis (gosterilen) degerle verilir (K18)."""
    if value is None:
        return None
    value = value.quantize(PF_BAND_QUANTUM, rounding=PF_BAND_ROUNDING)
    if value < bands.red_below:
        return PfBand.RED
    if value < bands.green_from:
        return PfBand.AMBER
    if bands.high_above is not None and value > bands.high_above:
        return PfBand.HIGH
    return PfBand.GREEN
