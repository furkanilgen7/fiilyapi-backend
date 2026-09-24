"""Motorun cikti tipleri. `None` = tanimsiz (sifira bolme ya da karma birim); UI "–" basar."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .calendar import CalendarPosition
from .types import ContractorMix, NodeId, PfBand, QtyEntry, RowKind, Status


@dataclass(frozen=True, slots=True)
class NodeMetrics:
    """Bir agac dugumunun rapor gunu d'deki degerleri (TUM alt agac; S3).

    `*_day` = d · `*_cum` = t <= d · `*_week` = W(d) penceresi.
    qty tabanli alanlar karma birimli baslikta None (S4).
    """

    node_id: NodeId
    is_leaf: bool
    uom: str | None
    # miktar
    qty_day: Decimal | None
    qty_cum: Decimal | None
    qty_week: Decimal | None
    planned_qty: Decimal | None
    remaining_qty: Decimal | None
    # adam-saat
    budget_mhr: Decimal
    earned_day: Decimal
    earned_cum: Decimal
    earned_week: Decimal
    spent_day: Decimal
    spent_cum: Decimal
    spent_week: Decimal
    unallocated_day: Decimal
    unallocated_cum: Decimal
    unallocated_week: Decimal
    remaining_mhr: Decimal
    togo_mhr: Decimal
    # oranlar
    planned_unit_mhr: Decimal | None
    actual_unit_mhr_day: Decimal | None
    actual_unit_mhr_cum: Decimal | None
    actual_unit_mhr_week: Decimal | None
    unit_rate_pf_day: Decimal | None
    unit_rate_pf_cum: Decimal | None
    unit_rate_pf_week: Decimal | None
    pf_day: Decimal | None
    pf_cum: Decimal | None
    pf_week: Decimal | None
    pf_day_band: PfBand | None
    pf_cum_band: PfBand | None
    pf_week_band: PfBand | None
    progress_pct_day: Decimal | None
    progress_pct_cum: Decimal | None
    progress_pct_week: Decimal | None
    # K9: yaprak modunda alt agactaki yaprak egrilerinin toplamindan; egri modunda None
    planned_pct_day: Decimal | None
    planned_pct_cum: Decimal | None
    # onceki revizyon (QURR a / f / m)
    prev_planned_qty: Decimal | None
    prev_unit_mhr: Decimal | None
    prev_budget_mhr: Decimal | None


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """KPI satiri (Overall / Own / Subcon / disiplin / dogrudan olmayan) — yalniz adam-saat."""

    kind: RowKind
    node_id: NodeId | None  # disiplin satirlarinda kok dugum; digerlerinde None
    contractor_mix: ContractorMix | None  # yalniz DISCIPLINE satirinda (S7 rozeti)
    budget_mhr: Decimal
    earned_day: Decimal
    earned_cum: Decimal
    earned_week: Decimal
    spent_day: Decimal
    spent_cum: Decimal
    spent_week: Decimal
    unallocated_day: Decimal
    unallocated_cum: Decimal
    unallocated_week: Decimal
    remaining_mhr: Decimal
    pf_day: Decimal | None
    pf_cum: Decimal | None
    pf_week: Decimal | None
    pf_day_band: PfBand | None
    pf_cum_band: PfBand | None
    pf_week_band: PfBand | None
    progress_pct_day: Decimal | None
    progress_pct_cum: Decimal | None
    progress_pct_week: Decimal | None
    planned_pct_day: Decimal | None
    planned_pct_cum: Decimal | None
    variance: Decimal | None
    status: Status | None


@dataclass(frozen=True, slots=True)
class Totals:
    """Mutabakat (spec §4): kaynaga yazilan saat = koklere inen saat; fark unallocated'da."""

    source_hours_day: Decimal
    source_hours_cum: Decimal
    spent_day: Decimal
    spent_cum: Decimal
    unallocated_day: Decimal
    unallocated_cum: Decimal


@dataclass(frozen=True, slots=True)
class DailyReport:
    report_date: date
    position: CalendarPosition
    nodes: Mapping[NodeId, NodeMetrics]
    rows: tuple[SummaryRow, ...]
    totals: Totals
    #: K12: orani bos/0 yapraga t <= d girilmis miktarlar ("oransiz giris" uyarisi).
    unrated_entries: tuple[QtyEntry, ...]

    def row(self, kind: RowKind, node_id: NodeId | None = None) -> SummaryRow:
        for r in self.rows:
            if r.kind is kind and r.node_id == node_id:
                return r
        raise KeyError((kind, node_id))
