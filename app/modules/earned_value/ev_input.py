"""Santiye → motor girdisi: raporlarin (panel, gunluk, QURR, AYP onizleme, K4) TEK kaynagi.

* Agac = AKTIF (donmus) baseline (K8); dugumler `budget_engine.to_engine_nodes`.
* Planli = donmus yaprak × gun egrisi (K9, `PlannedMhr.for_leaf`).
* Miktar = santiyenin BUTUN gunluk satirlari, TASLAK DAHIL (K13 — taslak gun isaretlenir).
  Yaprak = kalem × bolum (satirin `section_id`i; NULL = Bolumsuz). Baseline'da olmayan
  kalem × bolum UYARI olur, sessizce dusmez (`unknown_lines`).
* Saat = gun dagitimi hucreleri (B2): kodun kurali (direct | prorata) ile.
* Takvim (K7): baslangic/bitis ayar DEGIL — baseline pencereleri ∪ giris gunleri ∪ `as_of`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.earned_value import budget_repository as repo
from app.modules.earned_value import settings_service
from app.modules.earned_value.budget_engine import calendar_bounds, to_engine_nodes
from app.modules.earned_value.budget_snapshot import frozen_tree, load_curves, load_leaves
from app.modules.earned_value.budget_tree import BudgetTree, leaf_node_id
from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    EngineInput,
    HoursEntry,
    PfBands,
    PlannedMhr,
    QtyEntry,
)
from app.modules.earned_value.models import (
    EvDayCell,
    EvDayCode,
    EvDayRow,
    EvRevision,
    RevisionStatus,
)
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry, SiteDiaryLine

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class SiteInput:
    revision: EvRevision
    tree: BudgetTree
    inp: EngineInput
    diary_status: dict[date, DiaryStatus]  # gun → gunluk durumu (taslak/gonderildi)
    last_entry_day: date | None  # son miktar/saat girisi olan gun
    unknown_lines: list[tuple[date, uuid.UUID, uuid.UUID | None]] = field(default_factory=list)


async def _diaries(session: AsyncSession, site_id: uuid.UUID) -> dict[date, SiteDiaryEntry]:
    rows = await session.execute(select(SiteDiaryEntry).where(SiteDiaryEntry.site_id == site_id))
    return {e.entry_date: e for e in rows.scalars()}


async def _qty(
    session: AsyncSession, diaries: dict[date, SiteDiaryEntry], known: set[str]
) -> tuple[list[QtyEntry], list[tuple[date, uuid.UUID, uuid.UUID | None]]]:
    if not diaries:
        return [], []
    by_id = {e.id: e.entry_date for e in diaries.values()}
    lines = await session.execute(
        select(SiteDiaryLine).where(SiteDiaryLine.entry_id.in_(list(by_id)))
    )
    qty: list[QtyEntry] = []
    unknown: list[tuple[date, uuid.UUID, uuid.UUID | None]] = []
    for line in lines.scalars():
        if line.boq_item_id is None:
            continue
        day = by_id[line.entry_id]
        node = leaf_node_id(line.boq_item_id, line.section_id)
        if node in known:
            qty.append(QtyEntry(node, day, line.quantity))
        else:
            unknown.append((day, line.boq_item_id, line.section_id))
    return qty, unknown


async def _hours(session: AsyncSession, site_id: uuid.UUID, known: set[str]) -> list[HoursEntry]:
    codes = {
        (c.day, c.node_id): c.rule
        for c in (
            await session.execute(select(EvDayCode).where(EvDayCode.site_id == site_id))
        ).scalars()
    }
    cells = await session.execute(
        select(EvDayRow.day, EvDayCell.node_id, EvDayCell.hours)
        .join(EvDayCell, EvDayCell.row_id == EvDayRow.id)
        .where(EvDayRow.site_id == site_id)
    )
    merged: dict[tuple[date, str], Decimal] = {}
    for day, node, hours in cells.all():
        if node in known:
            merged[(day, node)] = merged.get((day, node), ZERO) + hours
    return [
        HoursEntry(node, day, h, AllocationRule(codes.get((day, node), "direct")))
        for (day, node), h in merged.items()
    ]


def bands_of(settings) -> tuple[PfBands, PfBands]:  # noqa: ANN001
    daily = settings.pf_bands.daily
    weekly = settings.pf_bands.weekly
    return (
        PfBands(daily.red_below, daily.green_from, daily.high_above),
        PfBands(weekly.red_below, weekly.green_from),
    )


async def build_site_input(
    session: AsyncSession, site_id: uuid.UUID, as_of: date
) -> SiteInput | None:
    """Aktif baseline yoksa None (rapor yok)."""
    rev = await repo.revision_by_status(session, site_id, RevisionStatus.ACTIVE)
    if rev is None:
        return None
    calendar = await repo.load_calendar(session, site_id)
    tree = await frozen_tree(
        session, rev, await repo.load_disciplines(session), calendar.is_working_day
    )
    nodes = to_engine_nodes(tree)
    known = {n.id for n in nodes}
    leaves = await load_leaves(session, rev.id)
    curves = await load_curves(session, leaves)
    planned = [
        PlannedMhr.for_leaf(node, day, mhr)
        for node, days in curves.items()
        if node in known
        for day, mhr in days.items()
    ]
    diaries = await _diaries(session, site_id)
    qty, unknown = await _qty(session, diaries, known)
    hours = await _hours(session, site_id, known)
    entry_days = [q.day for q in qty] + [h.day for h in hours]
    bounds = calendar_bounds(tree, [*entry_days, *(p.day for p in planned), as_of])
    assert bounds is not None  # as_of her zaman var
    settings = await settings_service.get_settings(session, site_id)
    daily_bands, cumulative_bands = bands_of(settings)
    inp = EngineInput(
        calendar=CalendarSettings(
            bounds[0],
            bounds[1],
            week_start_dow=calendar.week_start_dow,
            weekly_holidays=calendar.weekly_off_days,
            extra_holidays=calendar.holidays,
        ),
        nodes=nodes,
        qty_entries=qty,
        hours_entries=hours,
        planned_mhr=planned,
        tolerance_points=settings.tolerance_points,
        daily_pf_bands=daily_bands,
        cumulative_pf_bands=cumulative_bands,
    )
    return SiteInput(
        revision=rev,
        tree=tree,
        inp=inp,
        diary_status={d: e.status for d, e in diaries.items()},
        last_entry_day=max(entry_days, default=None),
        unknown_lines=unknown,
    )
