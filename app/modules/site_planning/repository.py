"""Planlama veri erişimi — `timesheet/repository.py` deseninin kardeşi.

Hafta sınırları TEK yerde hesaplanır (`week_bounds`): okuma (T2) ve yazmanın
DEĞİŞTİRME kapsamı (T3) AYNI aralığı kullanmazsa bir haftanın kaydetmesi komşu
haftanın hücrelerini süpürür.

Kapsam süzgeci (`visible_projects`) burada DEĞİL `service.py`dedir: bu katman
yalnız SQL kurar, yetki/kapsam kararı vermez.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_planning.models import (
    SitePlanCell,
    SitePlanGoal,
    SitePlanRow,
    SitePlanSprint,
)
from app.modules.sites.models import Section

DAYS_IN_WEEK = 7
"""Izgara HER ZAMAN yedi sütundur (P110-119) — hafta sonu dahil, çünkü mockup
Cmt/Paz sütunlarını (vurgulu da olsa) çiziyor ve o günlere hücre yazılabiliyor."""


def is_monday(day: date) -> bool:
    """`date.weekday()` Pazartesi için 0 döner."""
    return day.weekday() == 0


def week_bounds(week_start: date) -> tuple[date, date]:
    """Haftanın ilk ve SON günü (dahil). Çağıran `week_start`in Pazartesi
    olduğunu doğrulamış olmalıdır (`service.assert_week_start`)."""
    return week_start, week_start + timedelta(days=DAYS_IN_WEEK - 1)


def week_days(week_start: date) -> list[date]:
    """Haftanın YEDİ günü — sütun iskeleti (P110-119)."""
    return [week_start + timedelta(days=offset) for offset in range(DAYS_IN_WEEK)]


def is_weekend(day: date) -> bool:
    """Cmt/Paz — P118-119 vurgusu. TÜREVDİR, kolon açılmaz (spec §3)."""
    return day.weekday() >= 5


async def plan_rows(session: AsyncSession, site_id: uuid.UUID) -> list[tuple[SitePlanRow, Section]]:
    """Şantiyenin TÜM ızgara satırları + (varsa) bölümü.

    Sıralama DB'de yapılır — sayfa yenilendiğinde satır sırası değişmesin.
    Bölümü olan ekip satırları önce (bölüm `sort_order`u), sonra bölümsüzler,
    en sonda ekipman grubu gelir; grup içi sıra satırın `sort_order`udur.

    `outerjoin`: bölüm silinince `section_id` NULL'a düşer (`SET NULL`) ve satır
    ayakta kalır — `join` olsaydı o satırlar ızgaradan SESSİZCE kaybolurdu.
    """
    stmt = (
        select(SitePlanRow, Section)
        .outerjoin(Section, Section.id == SitePlanRow.section_id)
        .where(SitePlanRow.site_id == site_id)
        .order_by(
            SitePlanRow.kind,
            Section.sort_order.nulls_last(),
            Section.name.nulls_last(),
            SitePlanRow.sort_order,
            SitePlanRow.label,
        )
    )
    return [(row, section) for row, section in (await session.execute(stmt)).all()]


async def week_cells(
    session: AsyncSession, site_id: uuid.UUID, week_start: date
) -> list[SitePlanCell]:
    """YALNIZ o haftanın hücreleri — şantiye süzgeci `row_id` üzerinden.

    Hücrede `site_id` kolonu YOKTUR (spec §2): satırın şantiyesi TEK kaynaktır,
    kopyalansaydı iki alan zamanla ayrışabilirdi. Bu yüzden şantiye koşulu
    alt sorguyla satırlar üzerinden kurulur.
    """
    start, end = week_bounds(week_start)
    site_rows = select(SitePlanRow.id).where(SitePlanRow.site_id == site_id)
    stmt = (
        select(SitePlanCell)
        .where(
            SitePlanCell.row_id.in_(site_rows),
            SitePlanCell.plan_date >= start,
            SitePlanCell.plan_date <= end,
        )
        .order_by(SitePlanCell.plan_date)
    )
    return list((await session.execute(stmt)).scalars().all())


async def week_goals(
    session: AsyncSession, site_id: uuid.UUID, week_start: date
) -> list[SitePlanGoal]:
    """O haftanın hedefleri (P205-227), `sort_order` ile sıralı."""
    stmt = (
        select(SitePlanGoal)
        .where(SitePlanGoal.site_id == site_id, SitePlanGoal.week_start == week_start)
        .order_by(SitePlanGoal.sort_order, SitePlanGoal.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def active_sprint(session: AsyncSession, site_id: uuid.UUID) -> SitePlanSprint | None:
    """Aktif sprint (P108). Kısmi UQ sayesinde en fazla BİR tanedir."""
    stmt = select(SitePlanSprint).where(
        SitePlanSprint.site_id == site_id, SitePlanSprint.is_active.is_(True)
    )
    return (await session.execute(stmt)).scalars().first()


# --- T3 yazma yolu: kilitli okumalar + toplu silme ---
#
# Kilit KAPSAM BAŞINA alınır, kayıt başına değil (`timesheet.locked_period_entries`
# gerekçesinin aynısı): "değiştirme" tek bir mantıksal işlemdir ve iki eşzamanlı
# kaydetme birbirinin sildiği/eklediği satırları yarıştırırsa ızgara ikisinin de
# olmadığı bir hâlde kalır. Sıralama her sorguda SABİTTİR — iki istek kayıtları
# farklı sırada kilitlerse kilitlenme (deadlock) doğar.


async def locked_site_rows(session: AsyncSession, site_id: uuid.UUID) -> list[SitePlanRow]:
    """`SELECT … FOR UPDATE` — şantiyenin TÜM plan satırları.

    Satır kümesi bir bütün olarak değiştirilir (etiket tekilliği kümenin
    tamamına bakar), bu yüzden kilit de kümenin tamamınadır.
    """
    stmt = (
        select(SitePlanRow)
        .where(SitePlanRow.site_id == site_id)
        .order_by(SitePlanRow.id)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars().all())


async def locked_week_cells(
    session: AsyncSession, site_id: uuid.UUID, week_start: date
) -> list[SitePlanCell]:
    """`SELECT … FOR UPDATE` — YALNIZ o hafta + o şantiyenin hücreleri.

    ⚠️ Kilidin kapsamı silme koşuluyla BİREBİR aynıdır (`week_cells` ile aynı üç
    koşul): kilit daha darsa yarış penceresi kalır, daha genişse komşu haftanın
    kaydetmesi gereksiz yere bloklanır.
    """
    start, end = week_bounds(week_start)
    site_rows = select(SitePlanRow.id).where(SitePlanRow.site_id == site_id)
    stmt = (
        select(SitePlanCell)
        .where(
            SitePlanCell.row_id.in_(site_rows),
            SitePlanCell.plan_date >= start,
            SitePlanCell.plan_date <= end,
        )
        .order_by(SitePlanCell.row_id, SitePlanCell.plan_date)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars().all())


async def locked_week_goals(
    session: AsyncSession, site_id: uuid.UUID, week_start: date
) -> list[SitePlanGoal]:
    """`SELECT … FOR UPDATE` — o haftanın hedefleri (silme koşuluyla aynı ikili)."""
    stmt = (
        select(SitePlanGoal)
        .where(SitePlanGoal.site_id == site_id, SitePlanGoal.week_start == week_start)
        .order_by(SitePlanGoal.id)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars().all())


async def locked_site_sprints(session: AsyncSession, site_id: uuid.UUID) -> list[SitePlanSprint]:
    """`SELECT … FOR UPDATE` — şantiyenin TÜM sprintleri (pasifler dahil).

    Yalnız aktifi kilitlemek YETMEZ: iki eşzamanlı istek "aktif yok" görüp ikisi
    de yeni aktif satır açarsa kısmi UQ ihlali doğar. Şantiye başına kilit bu
    pencereyi kapatır.
    """
    stmt = (
        select(SitePlanSprint)
        .where(SitePlanSprint.site_id == site_id)
        .order_by(SitePlanSprint.id)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_rows(session: AsyncSession, row_ids: list[uuid.UUID]) -> None:
    """Satırları siler; hücreleri FK `ondelete="CASCADE"` ile DB'de düşer —
    uygulama katmanı hücreleri ayrıca silmez (iki kaynak ayrışırdı)."""
    if not row_ids:
        return
    await session.execute(delete(SitePlanRow).where(SitePlanRow.id.in_(row_ids)))


async def delete_cells(session: AsyncSession, cell_ids: list[uuid.UUID]) -> None:
    if not cell_ids:
        return
    await session.execute(delete(SitePlanCell).where(SitePlanCell.id.in_(cell_ids)))


async def delete_goals(session: AsyncSession, goal_ids: list[uuid.UUID]) -> None:
    if not goal_ids:
        return
    await session.execute(delete(SitePlanGoal).where(SitePlanGoal.id.in_(goal_ids)))
