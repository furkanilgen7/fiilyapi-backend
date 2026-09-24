"""Is kirilimi agaci dizini — dogrulama + on-sira (preorder) yerlesimi.

On-sirada bir dugumun alt agaci BITISIK bir araliktir: `[i, subtree_end[i])`. Alt agac
toplamlari (baslik = Σ yaprak) tek geriye tarama ile, prorata'da "M'nin yapraklari"
ise bu araliktan `bisect` ile alinir. Kardes sirasi girdideki siradir (sort_order'i
cagiran belirler).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .types import CurveKey, Node, NodeId

_HEADER_ONLY_EMPTY = ("uom", "planned_qty", "unit_mhr", "prev_planned_qty", "prev_unit_mhr")


@dataclass(frozen=True, slots=True)
class Tree:
    nodes: tuple[Node, ...]  # on-sira
    index: dict[NodeId, int]
    parent: tuple[int, ...]  # kok → -1
    subtree_end: tuple[int, ...]
    is_leaf: tuple[bool, ...]
    roots: tuple[int, ...]
    root_of: tuple[int, ...]
    curve_of: tuple[CurveKey | None, ...]
    #: Yaprak: kendi birimi. Baslik: tum yapraklarin ortak birimi; karma ise None (S4).
    uom_of: tuple[str | None, ...]

    def __len__(self) -> int:
        return len(self.nodes)


def _children_in_input_order(
    nodes: Sequence[Node],
) -> tuple[list[NodeId], dict[NodeId, list[NodeId]]]:
    ids: set[NodeId] = set()
    for n in nodes:
        if n.id in ids:
            raise ValueError(f"Dugum kimligi tekrar ediyor: {n.id!r}")
        ids.add(n.id)
    roots: list[NodeId] = []
    children: dict[NodeId, list[NodeId]] = {n.id: [] for n in nodes}
    for n in nodes:
        if n.parent_id is None:
            roots.append(n.id)
        elif n.parent_id not in ids:
            raise ValueError(f"Dugum {n.id!r}: ust dugum {n.parent_id!r} yok")
        else:
            children[n.parent_id].append(n.id)
    if not roots:
        raise ValueError("Agacin koku yok (dongu ya da bos girdi)")
    return roots, children


def _preorder(roots: list[NodeId], children: dict[NodeId, list[NodeId]]) -> list[NodeId]:
    order: list[NodeId] = []
    stack = list(reversed(roots))
    while stack:
        node_id = stack.pop()
        order.append(node_id)
        stack.extend(reversed(children[node_id]))
    return order


def _validate_shape(node: Node, is_leaf: bool) -> None:
    if is_leaf:
        if not node.uom:
            raise ValueError(f"Yaprak {node.id!r}: uom zorunlu")
        if node.planned_qty is None:
            raise ValueError(f"Yaprak {node.id!r}: planned_qty zorunlu")
        # unit_mhr bos olabilir (K12: oransiz yaprak reddedilmez, kazanilmisa girmez).
        return
    filled = [name for name in _HEADER_ONLY_EMPTY if getattr(node, name) is not None]
    if filled:
        raise ValueError(
            f"Baslik {node.id!r} miktar/oran tutmaz (alt toplamdan turer); dolu: {filled}"
        )


def build_tree(nodes: Sequence[Node]) -> Tree:
    roots, children = _children_in_input_order(nodes)
    by_id = {n.id: n for n in nodes}
    order_ids = _preorder(roots, children)
    if len(order_ids) != len(nodes):
        unreachable = sorted(map(repr, set(by_id) - set(order_ids)))
        raise ValueError(f"Kokten erisilemeyen dugumler (dongu): {unreachable}")

    index = {node_id: i for i, node_id in enumerate(order_ids)}
    ordered = tuple(by_id[node_id] for node_id in order_ids)
    n = len(ordered)
    parent = tuple(-1 if node.parent_id is None else index[node.parent_id] for node in ordered)
    is_leaf = tuple(not children[node.id] for node in ordered)
    for node, leaf in zip(ordered, is_leaf, strict=True):
        _validate_shape(node, leaf)

    subtree_end = list(range(1, n + 1))
    for i in range(n - 1, -1, -1):
        p = parent[i]
        if p >= 0 and subtree_end[i] > subtree_end[p]:
            subtree_end[p] = subtree_end[i]

    root_of = [0] * n
    curve_of: list[CurveKey | None] = [None] * n
    for i, node in enumerate(ordered):
        p = parent[i]
        root_of[i] = i if p < 0 else root_of[p]
        inherited = None if p < 0 else curve_of[p]
        curve_of[i] = node.curve_discipline if node.curve_discipline is not None else inherited

    return Tree(
        nodes=ordered,
        index=index,
        parent=parent,
        subtree_end=tuple(subtree_end),
        is_leaf=is_leaf,
        roots=tuple(index[r] for r in roots),
        root_of=tuple(root_of),
        curve_of=tuple(curve_of),
        uom_of=_uniform_uoms(ordered, parent, is_leaf),
    )


_MIXED = object()


def _uniform_uoms(
    ordered: tuple[Node, ...], parent: tuple[int, ...], is_leaf: tuple[bool, ...]
) -> tuple[str | None, ...]:
    n = len(ordered)
    seen: list[object] = [None] * n  # None = henuz yaprak gorulmedi
    for i in range(n - 1, -1, -1):
        if is_leaf[i]:
            seen[i] = ordered[i].uom
        p = parent[i]
        if p < 0:
            continue
        if seen[p] is None:
            seen[p] = seen[i]
        elif seen[p] != seen[i]:
            seen[p] = _MIXED
    return tuple(u if isinstance(u, str) else None for u in seen)
