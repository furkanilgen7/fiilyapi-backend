"""Hareketleri rapor gunu d icin dugum "noktalarina" biriktirir (spec §3.2, §3.3).

Nokta = bir dugumun KENDI degeri (alt agac toplami DEGIL):
* yaprak: miktar, kazanilmis (qty × yapragin KENDI orani), butce;
* herhangi bir dugum: uzerine INEN saat (direct'te M'nin kendisi; prorata'da yapraklar;
  miktarsiz gunde M'de unallocated).

Alt agac toplamlari (`rollup`) ve KPI satirlari (`summary`) bu noktalardan turer —
"baslik = Σ yaprak" tek bir toplama yolundan gecer.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from .calendar import ProjectCalendar
from .numeric import PRORATA_QUANTUM, ZERO
from .policy import prorata_by_earned
from .tree import Tree
from .types import AllocationRule, HoursEntry, QtyEntry


class Triple:
    """Gun / kumulatif / hafta toplamlarini dugum dizini basina tutar."""

    __slots__ = ("day", "cum", "week")

    def __init__(self, size: int) -> None:
        self.day = [ZERO] * size
        self.cum = [ZERO] * size
        self.week = [ZERO] * size


@dataclass(slots=True)
class Points:
    qty: Triple
    earned: Triple
    spent: Triple
    unallocated: Triple
    source_hours_day: Decimal
    source_hours_cum: Decimal
    unrated_entries: tuple[QtyEntry, ...]


def _add(t: Triple, i: int, value: Decimal, is_day: bool, in_week: bool) -> None:
    t.cum[i] += value
    if is_day:
        t.day[i] += value
    if in_week:
        t.week[i] += value


def _resolve(tree: Tree, calendar: ProjectCalendar, node_id: object, day: date, what: str) -> int:
    i = tree.index.get(node_id)
    if i is None:
        raise ValueError(f"{what}: bilinmeyen dugum {node_id!r}")
    if not calendar.contains(day):
        raise ValueError(f"{what} {node_id!r}: {day} proje takvimi disinda")
    return i


def accumulate(
    tree: Tree,
    calendar: ProjectCalendar,
    qty_entries: Iterable[QtyEntry],
    hours_entries: Iterable[HoursEntry],
    report_date: date,
) -> Points:
    n = len(tree)
    window_start, _ = calendar.window(report_date)
    qty, earned = Triple(n), Triple(n)
    # K12: oransiz (bos/0) yaprak orani 0 sayilir → kazanilmisa GIRMEZ; giris listede doner.
    rates = [node.unit_mhr if node.unit_mhr is not None else ZERO for node in tree.nodes]
    unrated: list[QtyEntry] = []
    # Prorata paydasi icin gun → {yaprak dizini: o gunku miktar} (yalniz t <= d).
    qty_by_day: dict[date, dict[int, Decimal]] = defaultdict(dict)

    for e in qty_entries:
        i = _resolve(tree, calendar, e.node_id, e.day, "Miktar")
        if not tree.is_leaf[i]:
            raise ValueError(f"Miktar yalniz yapraga girilir: {e.node_id!r} bir baslik")
        if e.day > report_date:
            continue
        if not rates[i] and e.qty:
            unrated.append(e)
        # Sicak dongu (1.500 dugum × 1.000 gun'de ~10^6 giris): `_add` cagrisi elle acildi.
        v = e.qty
        ev = v * rates[i]  # earned = qty × yapragin KENDI orani (spec §3.2)
        qty.cum[i] += v
        earned.cum[i] += ev
        if e.day >= window_start:
            qty.week[i] += v
            earned.week[i] += ev
            if e.day == report_date:
                qty.day[i] += v
                earned.day[i] += ev
        day_map = qty_by_day[e.day]
        day_map[i] = day_map.get(i, ZERO) + v

    spent, unallocated = Triple(n), Triple(n)
    source_day = source_cum = ZERO
    day_index = _DayIndex(qty_by_day)
    for h in hours_entries:
        m = _resolve(tree, calendar, h.node_id, h.day, "Saat")
        if h.day > report_date:
            continue
        is_day, in_week = h.day == report_date, h.day >= window_start
        source_cum += h.hours
        if is_day:
            source_day += h.hours
        if h.rule is AllocationRule.DIRECT:
            # direct: M'de kalir; M ve atalari gorur, alttaki yapraklara DAGILMAZ.
            _add(spent, m, h.hours, is_day, in_week)
            continue
        weights = day_index.leaves_in(h.day, m, tree.subtree_end[m])
        if prorata_by_earned(tree.uom_of[m]):
            # K11: karma birimli M'de miktarlar toplanamaz → pay = qty × unit_mhr (kazanilmis).
            weights = [(i, q * rates[i]) for i, q in weights]
        parts = prorata_parts(h.hours, weights)
        if parts is None:
            _add(spent, m, h.hours, is_day, in_week)
            _add(unallocated, m, h.hours, is_day, in_week)
            continue
        for leaf, part in parts:
            _add(spent, leaf, part, is_day, in_week)

    return Points(qty, earned, spent, unallocated, source_day, source_cum, tuple(unrated))


class _DayIndex:
    """Gun basina miktarli yapraklar, on-sira dizinine gore sirali (bisect icin)."""

    def __init__(self, qty_by_day: dict[date, dict[int, Decimal]]) -> None:
        self._raw = qty_by_day
        self._sorted: dict[date, tuple[list[int], list[Decimal]]] = {}

    def leaves_in(self, day: date, lo: int, hi: int) -> list[tuple[int, Decimal]]:
        """[lo, hi) on-sira araligindaki (= M'nin alt agaci) miktarli yapraklar."""
        cached = self._sorted.get(day)
        if cached is None:
            items = sorted(self._raw.get(day, {}).items())
            cached = ([i for i, _ in items], [q for _, q in items])
            self._sorted[day] = cached
        keys, values = cached
        a, b = bisect_left(keys, lo), bisect_left(keys, hi)
        return list(zip(keys[a:b], values[a:b], strict=True))


def prorata_parts(
    hours: Decimal, leaf_weights: list[tuple[int, Decimal]]
) -> list[tuple[int, Decimal]] | None:
    """Saati o gunku agirlik payina gore boler; pay yoksa None (→ M'de unallocated).

    Agirlik: ayni birimde qty_day, karma birimde qty × unit_mhr (K11). Pay yok = o gun net
    agirlik <= 0 (hic giris yok, duzeltmeler sifirliyor ya da yapraklar oransiz). Son
    yaprak KALANI alir: Σ pay == kaynak saat TAM esittir.

    🔴 Paylar `PRORATA_QUANTUM`a (1e-12 sa) indirilir. Olculdu (2026-09-25, rastgele agac
    seed 0): 28 haneli ham paylar yapraklarda binlerce kez toplaninca HER toplama yeniden
    yuvarlaniyor ve Σ spent kaynaktan 1e-25 sapiyordu (903,2000…0001 ≠ 903,2). Sabit
    kuantumlu paylarin toplami 10^15 saate kadar KESINDIR (28 hane − 12 ondalik), yani
    mutabakat `==` ile tutar. 1e-12 sa ≈ 3,6 ns: sunumda hicbir basamagi degistirmez.
    """
    nonzero = [(i, q) for i, q in leaf_weights if q != 0]
    total = sum((q for _, q in nonzero), ZERO)
    if total <= 0:
        return None
    parts: list[tuple[int, Decimal]] = []
    given = ZERO
    for i, q in nonzero[:-1]:
        part = (hours * q / total).quantize(PRORATA_QUANTUM, rounding=ROUND_HALF_EVEN)
        parts.append((i, part))
        given += part
    parts.append((nonzero[-1][0], hours - given))
    return parts
