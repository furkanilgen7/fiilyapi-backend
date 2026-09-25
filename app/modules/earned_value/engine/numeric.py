"""Sayi kurallari (spec §3.6): sifira bolme → None; yuvarlama motorda YOK.

Motor butun hesabi `ENGINE_CONTEXT` icinde yapar: sonuc cagiranin global decimal
baglamina bagli olmaz. Toplama/carpma girdiler kadar kesindir; yalniz BOLME 28 anlamli
haneye iner (IEEE 754R ROUND_HALF_EVEN) — bu sunum yuvarlamasi degil bolme hassasiyetidir.
Iki istisna: prorata payi (`PRORATA_QUANTUM`) ve yayma gun payi (`SPREAD_QUANTUM`) —
toplanan/saklanan ara degerler oldugu icin sabit kuantuma iner (Σ pay = kaynak esitligi
TOPLAMADAN ve DB'ye yazildiktan SONRA da kesin kalsin diye).
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

#: Yayma gun payinin sabit kuantumu (a-s). Gerekce: yaprak × gun egrisi DB'de
#: `Numeric(24, 8)` kolonuna (donmus baseline snapshot'i, K8) BIREBIR yazilir: 1e-6
#: kuantumlu paylar ve kuantum-alti ARTIK (butce − kuantuma inmis butce; butce = qty × oran,
#: <= 7 ondalik) kolonun 8 ondaligina kayipsiz sigar → okunan egri motorun urettigiyle ayni,
#: Σ pay == butce DB'den sonra da tutar. Paylastirma Hamilton (en buyuk kalan,
#: `policy.largest_remainder`): eksik kuantumlar en buyuk kesirli gunlere, artik EN BUYUK
#: paya verilir (`spread.spread_leaf`).
#: 1e-6 a-s ≈ 3,6 ms: sunumda hicbir basamagi degistirmez.
SPREAD_QUANTUM = Decimal("0.000001")


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    return a - b
