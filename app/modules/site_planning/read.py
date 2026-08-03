"""Planlama OKUMA yolu (T2) — haftalık ızgaranın kurulumu.

`service.py`den ayrı durur (`site_diary/read.py` gerekçesinin aynısı): kapsam
kararı ile yanıt inşası farklı hızda değişir. Yön TEK taraflıdır — bu modül
`service`i çağırır, `service` buradan hiçbir şey İMPORT ETMEZ (döngüsel import
doğmaz).

Yanıt ÜÇ toplu sorgudan kurulur (satırlar+bölüm, hafta hücreleri, hedefler) artı
sprint; satır ya da gün başına sorgu KOŞULMAZ (N+1 yok).
"""

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_planning import repository, service
from app.modules.site_planning.models import PlanResourceKind, SitePlanCell, SitePlanRow
from app.modules.site_planning.schemas import (
    SitePlanCellRead,
    SitePlanDay,
    SitePlanDaySummary,
    SitePlanDaySummaryRange,
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
    context = await service.visible_site(session, actor, site_id)
    return await build_week(session, context, week_start)


async def build_week(
    session: AsyncSession, context: service.SiteContext, week_start: date
) -> SitePlanWeek:
    """Yanıtın İNŞASI — kapsam kararı ÇOKTAN verilmiştir (`context`).

    T3 yazma uçları kaydetmeden sonra güncel ızgarayı buradan alır: `get_week`
    çağrılsaydı kapsam sorgusu istek başına İKİ KEZ koşardı (`site_diary`
    `read.build_detail` gerekçesinin aynısı).
    """
    site, project = context

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


# --- T4: GK gömülü bloğunun gün özeti (spec §4) ---
#
# SALT-OKUNUR TÜREVDİR: yeni tablo/kolon YOKTUR, her şey T1'in `site_plan_rows`
# + `site_plan_cells` kayıtlarından hesaplanır. Izgara (T2/T3) TEK kaynaktır;
# bu ucun yazma karşılığı AÇILMAZ (ONAYLI SAPMA — `schemas` başlığına bakınız).

SUMMARY_TEXT_SEPARATOR = " · "
"""Gün metinlerinin birleştiricisi. Boşluklu orta nokta seçilir çünkü hücre
metinleri kendi noktalama işaretini taşıyabilir (GK 328: "… (60 m³). Kat 8 …")
ve düz nokta ile birleştirmek iki ayrı satırın işini tek cümleye kaynatırdı."""


class _DaySummaryAccumulator:
    """Bir günün biriktiricisi. Aynı satır bir günde EN FAZLA bir hücreye
    sahiptir (UQ `(row_id, plan_date)`), bu yüzden işçi toplamında satır
    tekrarını ayrıca elemek gerekmez."""

    __slots__ = ("texts", "worker_total", "section_names")

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.worker_total = 0
        # Sıra KORUNUR (sözlük ekleme sırası): bölüm etiketleri ızgaranın
        # sırasında görünmelidir; `set` kullanılsaydı sıra istekten isteğe
        # değişirdi ve yanıt kararsız olurdu.
        self.section_names: dict[str, None] = {}

    def add(self, cell: SitePlanCell, row: SitePlanRow, section: Section | None) -> None:
        self.texts.append(cell.text)
        if row.kind is PlanResourceKind.crew:
            # Ekipman satırı toplama GİRMEZ (spec §4). Sayısı olmayan ekip 0'dır
            # — "sayı girilmemiş" ile "sıfır işçi" GK'nin tek kutusunda zaten
            # ayrılamaz.
            self.worker_total += row.planned_worker_count or 0
            if section is not None:
                self.section_names[section.name] = None


def _to_day_summary(day: date, accumulator: _DaySummaryAccumulator | None) -> SitePlanDaySummary:
    """Planı olmayan gün AÇIKÇA "plan yok"tur — pencereden DÜŞMEZ (GK 341-346)."""
    if accumulator is None:
        return SitePlanDaySummary(
            plan_date=day,
            is_weekend=repository.is_weekend(day),
            has_plan=False,
            text="",
            planned_worker_total=0,
            section_names=[],
        )
    return SitePlanDaySummary(
        plan_date=day,
        is_weekend=repository.is_weekend(day),
        has_plan=True,
        text=SUMMARY_TEXT_SEPARATOR.join(accumulator.texts),
        planned_worker_total=accumulator.worker_total,
        section_names=list(accumulator.section_names),
    )


async def get_day_summary(
    session: AsyncSession, actor: User, site_id: uuid.UUID, start: date, days: int
) -> SitePlanDaySummaryRange:
    """F-SD'nin GK gömülü bloğu (mockup 321-348) için gün başına özet.

    `start` HERHANGİ bir gün olabilir — Pazartesi korkuluğu (`assert_week_start`)
    burada ÇAĞRILMAZ: blok "önümüzdeki N gün"dür, haftalık ızgara değildir ve
    penceresi hafta sınırını aşabilir.

    Kapsam kararı ızgara ucuyla AYNI yardımcıdan gelir (`service.visible_site`):
    görünmeyen projenin şantiyesi boş bir pencere DEĞİL 404'tür — boş pencere,
    "planı yok" ile "şantiyeyi göremiyorsun"u aynı cevaba düşürürdü.

    Tek toplu sorgu koşar (`repository.range_cells`); gün başına sorgu YOKTUR.
    """
    context = await service.visible_site(session, actor, site_id)
    site, project = context
    end = start + timedelta(days=days - 1)

    accumulators: dict[date, _DaySummaryAccumulator] = {}
    for cell, row, section in await repository.range_cells(session, site.id, start, end):
        accumulator = accumulators.get(cell.plan_date)
        if accumulator is None:
            accumulator = accumulators[cell.plan_date] = _DaySummaryAccumulator()
        accumulator.add(cell, row, section)

    return SitePlanDaySummaryRange(
        site_id=site.id,
        site_name=site.name,
        project_id=project.id,
        project_name=project.name,
        start=start,
        end=end,
        days=[
            _to_day_summary(day, accumulators.get(day))
            for day in (start + timedelta(days=offset) for offset in range(days))
        ],
    )
