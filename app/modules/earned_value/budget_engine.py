"""Butce agaci → hesap motoru girdisi (B2/B3'un rapor yolu bunu kullanir).

* Dugum kimlikleri agacla AYNI (`d:` · `g:` · `i:` · `l:`), motor `NodeId`sine birebir gecer.
* L1 disiplin ve L2 BOQ grubu dugumlerinin `contractor_type` / `is_direct` alani =
  disiplinin varsayilani · dogrudan (CEO karari, B0 AÇIK KALAN 4). Motor S2 geregi basliga
  inen saati o dugumun KENDI alaniyla siniflar; alan bos kalsaydi `own/direct`a dusecekti.
* Egri disiplini = L1 dugumu (`curve_discipline = d:<id>`); yaprak egrisi (K9) varsa
  motor onu kullanir.
* Takvim (K7): baslangic/bitis AYAR DEGILDIR — `calendar_bounds` aktif baseline'in
  pencerelerinden ve ilk/son giris tarihinden turetir: start = min(en erken pencere,
  ilk giris) · end = max(en gec pencere, son giris). Motor takvim disi girdide ValueError
  atmaya DEVAM eder (CEO: adaptor takvimi dogru kursun).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.modules.earned_value.budget_tree import BudgetTree
from app.modules.earned_value.engine import Node


def to_engine_nodes(tree: BudgetTree) -> list[Node]:
    """Bos baslik (yapraksiz kalem, kalemsiz grup, grupsuz disiplin) motora GITMEZ: motor
    cocuksuz dugumu yaprak sayar ve `planned_qty` ister."""
    nodes: list[Node] = []
    for d in tree.disciplines:
        default = d.default_contractor_type
        group_nodes: list[Node] = []
        for g in d.groups:
            item_nodes: list[Node] = []
            for i in g.items:
                if not i.leaves:
                    continue
                item_nodes.append(
                    Node(i.id, g.id, contractor_type=i.contractor_type, is_direct=i.is_direct)
                )
                item_nodes.extend(
                    Node(
                        lf.id,
                        i.id,
                        uom=i.uom,
                        planned_qty=lf.planned_qty,
                        unit_mhr=lf.unit_mhr,
                        contractor_type=lf.contractor_type,
                        is_direct=lf.is_direct,
                    )
                    for lf in i.leaves
                )
            if item_nodes:
                group_nodes.append(Node(g.id, d.id, contractor_type=default))
                group_nodes.extend(item_nodes)
        if group_nodes:
            nodes.append(Node(d.id, None, contractor_type=default, curve_discipline=d.id))
            nodes.extend(group_nodes)
    return nodes


def calendar_bounds(tree: BudgetTree, entry_days: Iterable[date] = ()) -> tuple[date, date] | None:
    """K7: baseline pencereleri + giris gunleri birlesimi. Hicbiri yoksa None."""
    days = [d for d in entry_days]
    for *_, lf in tree.leaves():
        if lf.window_start and lf.window_end:
            days += [lf.window_start, lf.window_end]
    if not days:
        return None
    return min(days), max(days)
