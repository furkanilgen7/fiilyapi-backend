"""KPI KAPSAMI (`Scope`) — KPI satirinin ve seri/panel filtresinin TEK tanimi.

Bir kapsam uc eksenle secilir: disiplin koku (`root`; None = tum agac), yuklenici tipi
(`contractor`; None = ikisi) ve dogrudanlik (`direct_only` / `indirect_only`, S3). Nokta
(yaprak degeri ya da saat inisi) kapsama `policy.point_class` ile girer (S2) — kural
kopyasi YOK: `summary` KPI satirlarini ve `series` gunluk serileri AYNI yuklemle kurar.

Disiplin egrisi modunda (K9 yaprak egrisi yoksa) satirin egri agirliklari da buradan:
Overall/disiplin w_D = 1 · own/subcon w_D = butce payi (S1) · dogrudan olmayan planli YOK.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from .numeric import ZERO
from .policy import KPI_ROWS_DIRECT_ONLY, point_class
from .results import SummaryRow
from .tree import Tree
from .types import ContractorType, CurveKey, Node, NodeId, RowKind

Predicate = Callable[[Node], bool]
#: S1 pay agirliklari: yuklenici tipi → {egri: pay} (bayrak kapaliysa None).
ShareFn = Callable[[ContractorType], Mapping[CurveKey, Decimal] | None]


@dataclass(frozen=True, slots=True)
class Scope:
    """KPI kapsami. `label` yalniz etikettir: esitlige/sozluk anahtarina GIRMEZ.

    * `direct_only=True` (varsayilan, S3): yalniz `is_direct` noktalar.
    * `direct_only=False, indirect_only=False`: direct + dolayli (QURR "tum toplam").
    * `indirect_only=True`: yalniz dolayli noktalar ("Dogrudan olmayan" satiri; planlisi yok).
    """

    root: NodeId | None = None
    contractor: ContractorType | None = None
    direct_only: bool = True
    indirect_only: bool = False
    label: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.contractor is not None and not isinstance(self.contractor, ContractorType):
            raise TypeError(f"Scope.contractor ContractorType olmali: {self.contractor!r}")
        if self.direct_only and self.indirect_only:
            raise ValueError("Scope: direct_only ve indirect_only birlikte True olamaz")


def scope_keep(scope: Scope) -> Predicate:
    """Noktanin dustugu dugum kapsama girer mi (S2: dugumun KENDI alanlari)."""

    def keep(node: Node) -> bool:
        is_direct, kind = point_class(node)
        if scope.indirect_only and is_direct:
            return False
        if scope.direct_only and not is_direct:
            return False
        return scope.contractor is None or kind is scope.contractor

    return keep


def root_index(tree: Tree, scope: Scope) -> int | None:
    """Kapsam kokunun on-sira dizini; kok yalniz agac KOKU (disiplin) olabilir."""
    if scope.root is None:
        return None
    i = tree.index.get(scope.root)
    if i is None or tree.parent[i] >= 0:
        raise ValueError(f"Scope.root {scope.root!r} bir disiplin kökü değil")
    return i


def scope_span(tree: Tree, scope: Scope) -> range:
    """Kapsamin on-sira araligi: tum agac ya da kokun alt agaci."""
    r = root_index(tree, scope)
    return range(len(tree)) if r is None else range(r, tree.subtree_end[r])


def has_plan(scope: Scope) -> bool:
    """S3: dogrudan olmayan kapsamin planlisi her iki modda YOK."""
    return not scope.indirect_only


def curve_weights(
    tree: Tree, scope: Scope, curve_keys: Iterable[CurveKey], share: ShareFn
) -> Mapping[CurveKey, Decimal] | None:
    """Disiplin egrisi modunda kapsamin egri agirliklari w_D; planli yoksa None."""
    r = root_index(tree, scope)
    if r is None:
        if scope.contractor is None:
            return dict.fromkeys(curve_keys, Decimal(1))
        return share(scope.contractor)
    curve = tree.curve_of[r]
    if curve is None:
        return None
    if scope.contractor is None:
        return {curve: Decimal(1)}
    shares = share(scope.contractor)
    return None if shares is None else {curve: shares.get(curve, ZERO)}


def row_scope(kind: RowKind, node_id: NodeId | None) -> Scope:
    """KPI satir turu → kapsam. `summary` satirlarini bununla kurar (tek esleme)."""
    if kind is RowKind.OVERALL:
        return Scope()
    if kind is RowKind.OVERALL_OWN:
        return Scope(contractor=ContractorType.OWN)
    if kind is RowKind.OVERALL_SUBCON:
        return Scope(contractor=ContractorType.SUBCON)
    if kind is RowKind.NON_DIRECT:
        return Scope(direct_only=False, indirect_only=True)
    contractor = {
        RowKind.DISCIPLINE: None,
        RowKind.DISCIPLINE_OWN: ContractorType.OWN,
        RowKind.DISCIPLINE_SUBCON: ContractorType.SUBCON,
    }[kind]
    # S3: disiplin satiri yalniz direct noktalari tasir (bayrak kapaliysa hepsini).
    return Scope(root=node_id, contractor=contractor, direct_only=KPI_ROWS_DIRECT_ONLY)


def scope_for_row(row: SummaryRow) -> Scope:
    """Gunluk raporun KPI satirina karsilik gelen kapsam (seri ↔ satir eslemesi)."""
    return row_scope(row.kind, row.node_id)
