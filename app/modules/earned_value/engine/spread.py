"""Yaprak butcesinin gunlere YAYILMASI (PLANLAMA-SPEC §2.5, §3.9 B1-1; K9: yaprak duzeyi).

    u_t = (t − s) / max(1, e − s)            takvim gunu, t ∈ [s, e]   (policy.spread_position)
    w_t = W_dagilim(u_t)  is gunu            (policy.DISTRIBUTION_WEIGHTS)
    w_t = 0               tatil              (policy.NON_WORKING_DAY_WEIGHT)
    pay_t = butce × w_t / Σ w

Paylar `SPREAD_QUANTUM`a (1e-6 a-s) EN BUYUK KALAN yontemiyle iner
(`policy.largest_remainder`): her gun >= 0 ve Σ pay == butce TAM. Sabit kuantum dersi
`accumulate.prorata_parts` ile ayni: ham 28 haneli paylar toplandikca yeniden yuvarlanir
ve mutabakat `==` tutmaz.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, localcontext

from .numeric import ENGINE_CONTEXT, SPREAD_QUANTUM, ZERO
from .policy import (
    DISTRIBUTION_WEIGHTS,
    NON_WORKING_DAY_WEIGHT,
    largest_remainder,
    spread_position,
)
from .types import Distribution


class NoWorkingDayError(ValueError):
    """Yaprak penceresinde hic is gunu yok (Σw = 0): cagiran "is gunsuz yaprak" uyarir."""


def _weights(
    start: date, end: date, distribution: Distribution, is_working_day: Callable[[date], bool]
) -> list[tuple[date, Decimal]]:
    fn = DISTRIBUTION_WEIGHTS[distribution]
    out: list[tuple[date, Decimal]] = []
    for offset in range((end - start).days + 1):
        t = start + timedelta(days=offset)
        w = fn(spread_position(t, start, end)) if is_working_day(t) else NON_WORKING_DAY_WEIGHT
        if w != 0:
            out.append((t, w))
    return out


def spread_leaf(
    budget: Decimal,
    start: date,
    end: date,
    distribution: Distribution,
    is_working_day: Callable[[date], bool],
) -> dict[date, Decimal]:
    """Yaprak butcesini [start, end] gunlerine yayar; sifir agirlikli gun sozluge girmez.

    start > end ya da butce < 0 → ValueError · pencerede is gunu yok → `NoWorkingDayError`
    (butce 0 olsa da: pencere hatasi butceden bagimsizdir) · butce 0 → bos sozluk.
    """
    if not isinstance(budget, Decimal):
        raise TypeError(f"spread_leaf: budget Decimal olmali, {type(budget).__name__} geldi")
    if not budget.is_finite():
        raise ValueError(f"spread_leaf: budget sonlu olmali: {budget}")
    if budget < 0:
        raise ValueError(f"spread_leaf: budget negatif olamaz: {budget}")
    if not isinstance(distribution, Distribution):
        raise TypeError(f"distribution Distribution olmali: {distribution!r}")
    if start > end:
        raise ValueError(f"Yayma penceresi ters: start {start} > end {end}")
    with localcontext(ENGINE_CONTEXT):
        weights = _weights(start, end, distribution, is_working_day)
        if not weights:
            raise NoWorkingDayError(f"Pencerede is gunu yok: {start} – {end}")
        if budget == 0:
            return {}
        total = sum((w for _, w in weights), ZERO)
        raw = [budget * w / total for _, w in weights]
        shares = largest_remainder(raw, budget, SPREAD_QUANTUM)
        return {t: share for (t, _), share in zip(weights, shares, strict=True)}
