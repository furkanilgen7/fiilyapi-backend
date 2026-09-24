"""K9 — yaprak anahtarli planli egri (PLANLAMA-SPEC §3.8 K9).

Yaprak egrisi planned_mhr(L, t) verildiginde bir satirin (ya da dugumun) planli serisi,
kapsadigi yapraklarin egrilerinin TOPLAMIDIR:

    plan_row(t)      = Σ_{L ∈ satir} planned_mhr(L, t)
    planned_pct_day  = plan_row(d) / Σ_t plan_row(t)
    planned_pct_cum  = Σ_{t<=d} plan_row(t) / Σ_t plan_row(t)

Satir/dugum basina yalniz uc sayi gerekir (d gunu, t <= d kumulatifi, toplam); bunlar
yaprak dizini basina TEK tarama ile (O(nokta)) biriktirilir, satir toplami O(dugum).
Hangi mod secilir: `policy.use_leaf_curves` (karisik girdide yaprak kazanir).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .calendar import ProjectCalendar
from .numeric import ZERO, ratio
from .policy import use_leaf_curves
from .tree import Tree
from .types import PlannedMhr


@dataclass(frozen=True, slots=True)
class LeafPlan:
    """Dugum dizini basina yaprak egrisi toplamlari (baslik ve egrisiz yaprak 0)."""

    day: list[Decimal]
    cum: list[Decimal]
    total: list[Decimal]

    def pct(self, indices: Iterable[int]) -> tuple[Decimal | None, Decimal | None]:
        """Verilen dugum kumesindeki yaprak egrilerinin toplamindan planli % (gun, kum)."""
        day = cum = total = ZERO
        for i in indices:
            day += self.day[i]
            cum += self.cum[i]
            total += self.total[i]
        return ratio(day, total), ratio(cum, total)

    def subtree_pct(self, tree: Tree) -> list[tuple[Decimal | None, Decimal | None]]:
        """Her dugum icin ALT AGACINDAKI yaprak egrilerinden planli % (tek geriye tarama)."""
        day, cum, total = list(self.day), list(self.cum), list(self.total)
        for i in range(len(tree) - 1, 0, -1):
            p = tree.parent[i]
            if p < 0:
                continue
            day[p] += day[i]
            cum[p] += cum[i]
            total[p] += total[i]
        return [(ratio(d, t), ratio(c, t)) for d, c, t in zip(day, cum, total, strict=True)]


def validate_planned(
    tree: Tree, calendar: ProjectCalendar, planned: Sequence[PlannedMhr]
) -> tuple[bool, bool]:
    """Tum noktalari dogrular; (yaprak noktasi var mi, disiplin noktasi var mi) doner."""
    has_leaf = has_curve = False
    for p in planned:
        key = p.curve if p.node_id is None else p.node_id
        if p.node_id is not None:
            has_leaf = True
            i = tree.index.get(p.node_id)
            if i is None:
                raise ValueError(f"Yaprak egrisi: bilinmeyen dugum {p.node_id!r}")
            if not tree.is_leaf[i]:
                raise ValueError(f"Yaprak egrisi {p.node_id!r}: dugum yaprak degil (baslik)")
        else:
            has_curve = True
        if not calendar.contains(p.day):
            raise ValueError(f"Planli egri {key!r}: {p.day} proje takvimi disinda")
    return has_leaf, has_curve


def leaf_plan(
    tree: Tree, calendar: ProjectCalendar, planned: Sequence[PlannedMhr], report_date: date
) -> LeafPlan | None:
    """Yaprak modunda yaprak egrisi toplamlari; disiplin egrisi modunda None."""
    has_leaf, has_curve = validate_planned(tree, calendar, planned)
    if not use_leaf_curves(has_leaf, has_curve):
        return None
    n = len(tree)
    day, cum, total = [ZERO] * n, [ZERO] * n, [ZERO] * n
    index = tree.index
    for p in planned:
        if p.node_id is None:
            continue  # K9: karisik girdide disiplin noktalari yok sayilir
        i = index[p.node_id]
        v = p.mhr
        total[i] += v
        if p.day <= report_date:
            cum[i] += v
            if p.day == report_date:
                day[i] += v
    return LeafPlan(day, cum, total)
