"""Planlama OKUMA yolu (T2) — haftalık ızgaranın kurulumu.

`service.py`den ayrı durur (`site_diary/read.py` gerekçesinin aynısı): kapsam
kararı ile yanıt inşası farklı hızda değişir. Yön TEK taraflıdır — bu modül
`service`i çağırır, `service` buradan hiçbir şey İMPORT ETMEZ (döngüsel import
doğmaz).

Yanıt ÜÇ toplu sorgudan kurulur (satırlar+bölüm, hafta hücreleri, hedefler) artı
sprint; satır ya da gün başına sorgu KOŞULMAZ (N+1 yok).
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_planning import repository, service
from app.modules.site_planning.models import SitePlanCell, SitePlanRow
from app.modules.site_planning.schemas import (
    SitePlanCellRead,
    SitePlanDay,
    SitePlanGoalRead,
    SitePlanGroup,
    SitePlanRowRead,
    SitePlanSprintRead,
    SitePlanWeek,
)
from app.modules.sites.models import Section
from app.modules.users.models import User

_GroupKey = tuple[str, uuid.UUID | None]


class _Group:
    """Bir grup başlığının biriktiricisi (P125-126 / P158).

    Sözlük EKLEME SIRASINI korur ve satır sorgusu zaten sıralı gelir
    (`repository.plan_rows`) — grupların çıktı sırası da DB sırasıdır.
    """

    __slots__ = ("kind", "section", "rows")

    def __init__(self, row: SitePlanRow, section: Section | None) -> None:
        self.kind = row.kind
        self.section = section
        self.rows: list[SitePlanRowRead] = []


def _group_key(row: SitePlanRow) -> _GroupKey:
    """Anahtar `(kind, section_id)` İKİLİSİDİR — gerekçe `schemas.SitePlanGroup`da."""
    return (row.kind.value, row.section_id)


def _cells_by_row(cells: list[SitePlanCell]) -> dict[uuid.UUID, list[SitePlanCellRead]]:
    """Hücreleri satıra dağıtır. Hücresi olmayan satır sözlükte HİÇ görünmez ve
    boş liste alır — "hücre yokluğu = plan yok" (spec §2)."""
    by_row: dict[uuid.UUID, list[SitePlanCellRead]] = {}
    for cell in cells:
        by_row.setdefault(cell.row_id, []).append(
            SitePlanCellRead(plan_date=cell.plan_date, text=cell.text, tag=cell.tag)
        )
    return by_row


def _to_row(row: SitePlanRow, cells: list[SitePlanCellRead]) -> SitePlanRowRead:
    return SitePlanRowRead(
        id=row.id,
        kind=row.kind,
        section_id=row.section_id,
        label=row.label,
        planned_worker_count=row.planned_worker_count,
        sort_order=row.sort_order,
        cells=cells,
    )


def _to_group(group: _Group) -> SitePlanGroup:
    section = group.section
    return SitePlanGroup(
        kind=group.kind,
        section_id=section.id if section is not None else None,
        section_name=section.name if section is not None else None,
        section_manager_name=section.manager_name if section is not None else None,
        rows=group.rows,
    )


async def get_week(
    session: AsyncSession, actor: User, site_id: uuid.UUID, week_start: date
) -> SitePlanWeek:
    """P (Planlama) ekranının bir haftası.

    Kapsam kararı ŞANTİYE üzerinden verilir (`service.visible_site`): görünmeyen
    şantiye boş ızgara DEĞİL 404'tür — boş ızgara, "şantiye var ama planı yok"
    ile "şantiyeyi göremiyorsun"u aynı cevaba düşürürdü.

    Hafta korkuluğu kapsam kararından ÖNCE koşar: geçersiz bir haftanın
    şantiyesini boşuna sorgulamayız ve 422 cevabı kaydın varlığından bağımsız
    kalır (var olmayan şantiye + Salı → yine 422, bilgi sızmaz).
    """
    week_start = service.assert_week_start(week_start)
    site, project = await service.visible_site(session, actor, site_id)

    rows = await repository.plan_rows(session, site.id)
    by_row = _cells_by_row(await repository.week_cells(session, site.id, week_start))

    groups: dict[_GroupKey, _Group] = {}
    for row, section in rows:
        key = _group_key(row)
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(row, section)
        group.rows.append(_to_row(row, by_row.get(row.id, [])))

    goals = await repository.week_goals(session, site.id, week_start)
    sprint = await repository.active_sprint(session, site.id)
    _, week_end = repository.week_bounds(week_start)

    return SitePlanWeek(
        site_id=site.id,
        site_name=site.name,
        project_id=project.id,
        project_name=project.name,
        week_start=week_start,
        week_end=week_end,
        days=[
            SitePlanDay(plan_date=day, is_weekend=repository.is_weekend(day))
            for day in repository.week_days(week_start)
        ],
        groups=[_to_group(group) for group in groups.values()],
        goals=[
            SitePlanGoalRead(
                id=goal.id,
                title=goal.title,
                note=goal.note,
                is_done=goal.is_done,
                status=goal.status,
                sort_order=goal.sort_order,
            )
            for goal in goals
        ],
        active_sprint=(
            None if sprint is None else SitePlanSprintRead(id=sprint.id, name=sprint.name)
        ),
    )
