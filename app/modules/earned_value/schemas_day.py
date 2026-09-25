"""Gunluk saat dagitimi + gun kilidi semalari (Santiye - Gunluk Kayit (Ilerleme); F0 §4.2).

🔴 KVKK (§3.11 B1-11): kisi × kod × saat hucreleri kisisel veridir. Modul AI'da AGREGA —
kisi adi tasiyan bu yuzeye AI araci KAYDEDILEMEZ (`ai/exposure.py`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.earned_value.decimal_out import EvDecimal

RowKind = Literal["personnel", "subcontractor"]
Rule = Literal["direct", "prorata_by_daily_qty"]
Hours = Annotated[EvDecimal, Field(gt=0, le=1000, max_digits=6, decimal_places=2)]


class UserRef(BaseModel):
    id: uuid.UUID
    full_name: str


class CodeNodeOut(BaseModel):
    id: str
    parent_id: str | None
    level: int  # 1 disiplin · 2 BOQ grubu · 3 is tipi · 4 kalem × bolum
    code: str | None
    label: str
    uom: str | None
    has_rate: bool | None  # yaprakta: oranli mi (oransiz yaprak secilemez); baslikta None
    unit_mhr: EvDecimal | None


class UnlockOut(BaseModel):
    unlocked_at: datetime
    unlocked_by: UserRef | None
    reason: str


class LockOut(BaseModel):
    locked: bool
    report_date: date | None
    approved_at: datetime | None
    approved_by: UserRef | None
    unlock: UnlockOut | None


class RowOut(BaseModel):
    kind: RowKind
    ref_id: uuid.UUID
    label: str
    trade: str | None
    source: str | None
    subcontractor_name: str | None
    headcount: int | None
    hours: EvDecimal  # CANLI kaynak saat
    saved_hours: EvDecimal | None  # dagitim anindaki kopya
    changed: bool  # "⚠ Puantaj degisti (saved → hours)"


class CodeOut(BaseModel):
    node_id: str
    rule: Rule
    label: str | None  # aktif baseline'da yoksa None (uyari)
    level: int | None


class CellOut(BaseModel):
    kind: RowKind
    ref_id: uuid.UUID
    node_id: str
    hours: EvDecimal


class TotalsOut(BaseModel):
    source_hours: EvDecimal
    allocated_hours: EvDecimal
    unallocated_hours: EvDecimal  # K14 "dagitilmamis saat" (eksi = fazla dagitilmis)


class LeafProgressOut(BaseModel):
    node_id: str
    qty_day: EvDecimal | None
    earned_day: EvDecimal
    spent_day: EvDecimal
    pf_day: EvDecimal | None


class ProgressOut(BaseModel):
    leaves: list[LeafProgressOut]
    earned_day: EvDecimal
    spent_day: EvDecimal
    pf_day: EvDecimal | None


class SubmitCheckOut(BaseModel):
    can_submit: bool
    reasons: list[str]


class DayView(BaseModel):
    day: date
    day_no: int | None
    week_no: int | None
    has_baseline: bool
    revision_number: int | None
    lock: LockOut
    rows: list[RowOut]
    codes: list[CodeOut]
    cells: list[CellOut]
    totals: TotalsOut
    unallocated_reason: str | None
    warnings: list[str]
    progress: ProgressOut | None
    submit: SubmitCheckOut | None  # gunluk kaydi yoksa None


class RowRef(BaseModel):
    kind: RowKind
    ref_id: uuid.UUID


class CodeIn(BaseModel):
    node_id: Annotated[str, Field(min_length=3, max_length=90)]
    rule: Rule


class CellIn(BaseModel):
    row: RowRef
    node_id: Annotated[str, Field(min_length=3, max_length=90)]
    hours: Hours


class AllocationSave(BaseModel):
    """TAM DEGISTIRME: govde gunun kod + hucre kumesinin TAMAMIDIR."""

    model_config = ConfigDict(extra="forbid")

    codes: Annotated[list[CodeIn], Field(max_length=500)]
    cells: Annotated[list[CellIn], Field(max_length=20000)]
    unallocated_reason: Annotated[str, Field(max_length=2000)] | None = None


class ShareOut(BaseModel):
    node_id: str
    share: EvDecimal  # satirin saatinin o koda dusen payi (0–1)


class RowPatternOut(BaseModel):
    kind: RowKind
    ref_id: uuid.UUID
    shares: list[ShareOut]


class PreviousAllocationOut(BaseModel):
    """B2-7: son GONDERILMIS gunun deseni. Doldurma/olcekleme istemcide."""

    day: date | None
    codes: list[CodeIn]
    rows: list[RowPatternOut]


class UnlockBody(BaseModel):
    reason: Annotated[str, Field(min_length=3, max_length=2000)]
