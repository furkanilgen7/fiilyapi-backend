"""Rapor uyari listeleri (Ek A §4.1 altlik, §6; F0 §4.3) — hepsi HEDEF TIPIYLE.

Bant karari motorun GOSTERILEN degerle verdigi banttan okunur (K18); burada yeniden
hesaplanmaz.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.earned_value.budget_tree import BudgetTree
from app.modules.earned_value.engine import DailyReport, PfBand, ProjectCalendar
from app.modules.earned_value.ev_input import SiteInput
from app.modules.earned_value.schemas_reports import WarningOut
from app.modules.site_diary.models import DiaryStatus

_BAD_DAILY = {PfBand.RED, PfBand.HIGH}


def _names(tree: BudgetTree) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in tree.disciplines:
        for g in d.groups:
            for i in g.items:
                out[i.id] = f"{i.code} {i.description}"
                for lf in i.leaves:
                    out[lf.id] = f"{i.code} · {lf.section_name or 'Bölümsüz'}"
    return out


def pf_warnings(tree: BudgetTree, report: DailyReport) -> list[WarningOut]:
    """Is tipi (L3) duzeyinde: kumulatif PF kirmizi ya da gunluk PF kirmizi/supheli yuksek."""
    names = _names(tree)
    out = []
    for d in tree.disciplines:
        for g in d.groups:
            for i in g.items:
                m = report.nodes.get(i.id)
                if m is None:
                    continue
                if m.pf_cum_band is PfBand.RED or m.pf_day_band in _BAD_DAILY:
                    value = m.pf_day if m.pf_day_band in _BAD_DAILY else m.pf_cum
                    out.append(
                        WarningOut(
                            code="pf_out_of_band",
                            message=f"{names[i.id]}: PF bant dışı",
                            target="node",
                            target_id=i.id,
                            value=value,
                        )
                    )
    return out


def overrun_warnings(tree: BudgetTree, report: DailyReport) -> list[WarningOut]:
    names = _names(tree)
    out = []
    for *_, lf in tree.leaves():
        m = report.nodes.get(lf.id)
        if m and m.qty_cum is not None and m.planned_qty is not None and m.qty_cum > m.planned_qty:
            out.append(
                WarningOut(
                    code="qty_overrun",
                    message=f"{names[lf.id]}: planlı miktar aşıldı",
                    target="leaf",
                    target_id=lf.id,
                    value=m.qty_cum - m.planned_qty,
                )
            )
    return out


def diary_dates(site: SiteInput, until: date) -> tuple[list[date], list[date]]:
    """(eksik, taslak) — eksik = gunlugu HIC olmayan IS gunu (B3-1: engel degil, uyari)."""
    cal = ProjectCalendar(site.inp.calendar)
    missing, drafts = [], []
    day = cal.start_date
    while day <= min(until, cal.end_date):
        status = site.diary_status.get(day)
        if status is None and not cal.is_holiday(day):
            missing.append(day)
        elif status is DiaryStatus.draft:
            drafts.append(day)
        day += timedelta(days=1)
    return missing, drafts


def diary_warnings(missing: list[date], drafts: list[date]) -> list[WarningOut]:
    return [
        WarningOut(
            code="missing_diary",
            message=f"{d.strftime('%d.%m.%Y')} günlüğü yok",
            target="day",
            target_id=d.isoformat(),
        )
        for d in missing
    ] + [
        WarningOut(
            code="draft_diary",
            message=f"{d.strftime('%d.%m.%Y')} günlüğü gönderilmedi (taslak değer)",
            target="day",
            target_id=d.isoformat(),
        )
        for d in drafts
    ]


def unrated_warnings(tree: BudgetTree, report: DailyReport) -> list[WarningOut]:
    names = _names(tree)
    return [
        WarningOut(
            code="unrated_entry",
            message=f"{names.get(str(e.node_id), e.node_id)}: oransız yaprağa miktar",
            target="leaf",
            target_id=str(e.node_id),
            value=e.qty,
        )
        for e in report.unrated_entries
    ]


def unknown_line_warnings(site: SiteInput, until: date) -> list[WarningOut]:
    return [
        WarningOut(
            code="unknown_line",
            message=f"{day.strftime('%d.%m.%Y')}: baseline'da olmayan kalem × bölüm satırı",
            target="day",
            target_id=day.isoformat(),
        )
        for day, _item, _section in site.unknown_lines
        if day <= until
    ]


def undistributed_warning(day: date, undistributed: Decimal) -> list[WarningOut]:
    if undistributed == 0:
        return []
    return [
        WarningOut(
            code="undistributed_hours",
            message=f"{day.strftime('%d.%m.%Y')}: {undistributed} a-s dağıtılmamış",
            target="day",
            target_id=day.isoformat(),
            value=undistributed,
        )
    ]
