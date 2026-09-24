"""Sayi kurallari (spec §3.6): sifira bolme → None; yuvarlama motorda YOK.

Motor butun hesabi `ENGINE_CONTEXT` icinde yapar: sonuc cagiranin global decimal
baglamina bagli olmaz. Toplama/carpma girdiler kadar kesindir; yalniz BOLME 28 anlamli
haneye iner (IEEE 754R ROUND_HALF_EVEN) — bu sunum yuvarlamasi degil bolme hassasiyetidir.
Tek istisna prorata payi: toplanan bir ara deger oldugu icin `PRORATA_QUANTUM`a iner
(Σ pay = kaynak esitligi TOPLAMADAN SONRA da kesin kalsin diye).
"""

from __future__ import annotations

from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)

ENGINE_CONTEXT = Context(
    prec=28, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow]
)

ZERO = Decimal(0)

#: Prorata payinin sabit kuantumu (saat). Gerekce: `accumulate.prorata_parts`.
PRORATA_QUANTUM = Decimal("1e-12")


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    return a - b
