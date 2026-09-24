"""Butce uclarinin semalari (BUT ekrani; frontend istekleri 1–5, PLN-F0 §4.1).

Sayilar `Decimal`dir, JSON'da string doner (repo deseni). Yuzde/pay 0–1 kesirdir;
yuvarlama yalniz sunumda (§3.6).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.earned_value.engine import ContractorType
from app.modules.earned_value.models import RateSource, RevisionStatus

DistributionName = Literal["linear", "bell", "front", "back"]
Rate = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]


class UserRef(BaseModel):
    id: uuid.UUID
    full_name: str


class RevisionOut(BaseModel):
    id: uuid.UUID
    number: int
    name: str | None
    description: str | None
    status: RevisionStatus
    frozen_at: datetime | None
    frozen_by: UserRef | None
    created_at: datetime
    last_edited_at: datetime


class FindingOut(BaseModel):
    code: str
    count: int
    node_ids: list[str]


class LeafOut(BaseModel):
    id: str
    item_id: uuid.UUID
    section_id: uuid.UUID | None
    section_name: str | None
    planned_qty: Decimal
    unit_mhr: Decimal | None
    rate_source: RateSource | None
    contractor_type: ContractorType
    contractor_source: Literal["inherited", "override"]
    is_direct: bool
    is_direct_source: Literal["inherited", "override"]
    budget_mhr: Decimal
    share: Decimal | None
    window_start: date | None
    window_end: date | None
    window_source: Literal["override", "section", "union", "snapshot"] | None
    outside_section_dates: bool  # §3.10 F0-4 uyari bayragi


class _Sums(BaseModel):
    budget_mhr: Decimal
    direct_budget_mhr: Decimal
    share: Decimal | None  # dogrudan butce ÷ toplam dogrudan butce


class ItemOut(_Sums):
    id: str
    item_id: uuid.UUID
    code: str
    description: str
    uom: str
    planned_qty: Decimal
    contractor_type: ContractorType
    contractor_source: Literal["inherited", "item"]
    is_direct: bool
    catalog_item_id: uuid.UUID | None
    empty_rate_count: int
    leaves: list[LeafOut]


class GroupOut(_Sums):
    id: str
    group_id: uuid.UUID
    name: str
    discipline_id: uuid.UUID | None
    items: list[ItemOut]


class DisciplineOut(_Sums):
    id: str
    discipline_id: uuid.UUID | None
    code: str | None
    name: str | None
    color: str | None
    default_contractor_type: ContractorType
    distribution: DistributionName
    groups: list[GroupOut]


class BudgetTotals(BaseModel):
    direct_budget_mhr: Decimal
    indirect_budget_mhr: Decimal
    item_count: int
    leaf_count: int
    empty_rate_leaf_count: int


class BudgetView(BaseModel):
    revision: RevisionOut | None
    editable: bool
    boq_synced_at: datetime | None
    totals: BudgetTotals
    disciplines: list[DisciplineOut]
    freeze_blockers: list[FindingOut]
    freeze_warnings: list[FindingOut]


# ------------------------------------------------------------------ yazma govdeleri


class GroupDisciplinePair(BaseModel):
    boq_group_id: uuid.UUID
    discipline_id: uuid.UUID | None  # None = eslemeyi kaldir ("Disiplinsiz")


class GroupDisciplinesBody(BaseModel):
    items: Annotated[list[GroupDisciplinePair], Field(min_length=1, max_length=2000)]


def _reject_explicit_null(data: Any, fields: tuple[str, ...]) -> Any:
    """KARARLAR :275 kanonu: acik null → 422, ALAN ADLI."""
    if isinstance(data, dict):
        for name in fields:
            if name in data and data[name] is None:
                raise ValueError(f"{name}: null olamaz")
    return data


class ItemPatch(BaseModel):
    """`contractor_type=null` BILINCLI: "disiplin varsayilanina don" (miras). `is_direct` null
    olamaz."""

    model_config = ConfigDict(extra="forbid")

    contractor_type: ContractorType | None = None
    is_direct: bool | None = None
    catalog_item_id: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def _nulls(cls, data: Any) -> Any:
        return _reject_explicit_null(data, ("is_direct",))


class LeafPatch(BaseModel):
    """Govdede GELEN alanlar yazilir. `unit_mhr=null` orani (ve kaynagini) siler;
    `contractor_type`/`is_direct` null → ezmeyi kaldir (is tipinden miras)."""

    model_config = ConfigDict(extra="forbid")

    boq_item_id: uuid.UUID
    section_id: uuid.UUID | None = None
    unit_mhr: Rate | None = None
    rate_source: RateSource | None = None
    contractor_type: ContractorType | None = None
    is_direct: bool | None = None


class LeavesPatch(BaseModel):
    leaves: Annotated[list[LeafPatch], Field(min_length=1, max_length=5000)]


class DistributionPair(BaseModel):
    discipline_id: uuid.UUID
    distribution: DistributionName


class DistributionsBody(BaseModel):
    items: Annotated[list[DistributionPair], Field(min_length=1, max_length=200)]


class WindowIn(BaseModel):
    discipline_id: uuid.UUID
    section_id: uuid.UUID | None = None
    start_date: date
    end_date: date


class WindowsBody(BaseModel):
    """TAM DEGISTIRME: gonderilmeyen ezme silinir (bolum tarihine doner)."""

    windows: Annotated[list[WindowIn], Field(max_length=5000)]


class FreezeBody(BaseModel):
    name: Annotated[str, Field(max_length=150)] | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None


class WriteResult(BaseModel):
    """Yazma uclari guncel agaci doner (ekran kaydettigini geri gormeli)."""

    budget: BudgetView


# ------------------------------------------------------------------ katalog onerisi


class CandidateOut(BaseModel):
    catalog_item_id: uuid.UUID
    name: str
    uom: str
    standard_unit_mhr: Decimal
    discipline_id: uuid.UUID
    match: Literal["linked", "exact", "partial"]


class SuggestionsOut(BaseModel):
    catalog: list[CandidateOut]
    #: "Son 3 santiye gerceklesen" (K4) — saha verisi B2'de dogar, B3'te dolar. B1'de bos.
    history: list[CandidateOut]


class AmbiguousItemOut(BaseModel):
    boq_item_id: uuid.UUID
    code: str
    description: str
    candidates: list[CandidateOut]


class FillOut(BaseModel):
    filled_item_count: int
    filled_leaf_count: int
    ambiguous_count: int
    unmatched_count: int
    ambiguous: list[AmbiguousItemOut]


# ------------------------------------------------------------------ onizleme


class PreviewBody(BaseModel):
    """Kalici OLMAYAN ezmeler (frontend istegi 2): kaydedilmeden egri canli degisir."""

    revision_id: uuid.UUID | None = None
    distributions: Annotated[list[DistributionPair], Field(max_length=200)] = []
    windows: Annotated[list[WindowIn], Field(max_length=5000)] = []


class DayOut(BaseModel):
    day: date
    mhr: Decimal
    cumulative_mhr: Decimal
    planned_pct_cum: Decimal | None


class WeekOut(BaseModel):
    week_no: int
    week_start: date
    week_end: date
    mhr: Decimal
    working_days: int
    required_people: Decimal | None
    planned_people: int | None  # "bolum plani" cizgisi — yalniz toplam seride


class SeriesOut(BaseModel):
    budget_mhr: Decimal
    start: date | None
    end: date | None
    days: list[DayOut]
    weeks: list[WeekOut]
    peak_week: WeekOut | None


class DisciplinePreviewOut(BaseModel):
    discipline_node_id: str
    discipline_id: uuid.UUID | None
    code: str | None
    name: str | None
    color: str | None
    distribution: DistributionName
    share: Decimal | None
    series: SeriesOut


class PreviewOut(BaseModel):
    start: date | None
    end: date | None
    disciplines: list[DisciplinePreviewOut]
    total: SeriesOut
    indirect_budget_mhr: Decimal
    unspreadable: list[str]


# ------------------------------------------------------------------ zamanlama (Gantt)


class SectionOut(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date | None
    end_date: date | None
    planned_worker_count: int | None


class BarOut(BaseModel):
    discipline_node_id: str
    discipline_id: uuid.UUID
    section_id: uuid.UUID | None
    section_name: str | None
    start_date: date | None
    end_date: date | None
    source: Literal["override", "section", "union", "snapshot"] | None
    outside_section_dates: bool  # §3.10 F0-4
    budget_mhr: Decimal


class ScheduleOut(BaseModel):
    sections: list[SectionOut]
    bars: list[BarOut]
    weekly_off_days: list[int]
    holidays: list[date]


# ------------------------------------------------------------------ revizyon farki


class LeafDiffOut(BaseModel):
    leaf_id: str
    item_code: str
    item_description: str
    section_name: str | None
    uom: str
    prev_qty: Decimal | None
    qty: Decimal | None
    prev_unit_mhr: Decimal | None
    unit_mhr: Decimal | None
    prev_budget_mhr: Decimal
    budget_mhr: Decimal
    delta_mhr: Decimal
    reason: Literal["new", "removed", "qty_changed", "rate_changed", "qty_and_rate_changed"]


class RevisionDiffOut(BaseModel):
    revision: RevisionOut
    against: RevisionOut | None
    direct_before_mhr: Decimal
    direct_after_mhr: Decimal
    direct_delta_mhr: Decimal
    leaves: list[LeafDiffOut]
