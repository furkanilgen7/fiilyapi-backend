"""Puantaj veri erişimi — `site_diary/repository.py` deseninin kardeşi.

Dönem sınırları TEK yerde hesaplanır (`period_bounds`): okuma, yazma ve silme
AYNI aralığı kullanmazsa "değiştirme" semantiği kapsamını kaybeder ve bir ayın
kaydetmesi komşu ayın hücrelerini süpürür (spec §7 S4).

Kapsam süzgeci (`visible_projects`) burada DEĞİL `service.py`dedir: bu katman
yalnız SQL kurar, yetki/kapsam kararı vermez.
"""

import calendar
import uuid
from datetime import date

from sqlalchemy import Select, delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import Subcontractor
from app.modules.personnel.models import Personnel
from app.modules.timesheet.models import TimesheetEntry


def period_bounds(year: int, month: int) -> tuple[date, date]:
    """Ayın ilk ve SON günü (dahil). `calendar.monthrange` artık yılı da bilir."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def period_days(year: int, month: int) -> list[date]:
    """Ayın TÜM takvim günleri — gün sütunu iskeleti (ŞP 127-141).

    İskelet hücrelerden DEĞİL takvimden üretilir: kaydı olmayan gün de bir
    sütundur, aksi hâlde matris ayın ortasında delik gösterirdi.
    """
    _, last = period_bounds(year, month)
    return [date(year, month, day) for day in range(1, last.day + 1)]


def _period_conditions(site_id: uuid.UUID, year: int, month: int) -> list:
    start, end = period_bounds(year, month)
    return [
        TimesheetEntry.site_id == site_id,
        TimesheetEntry.work_date >= start,
        TimesheetEntry.work_date <= end,
    ]


def _scoped(site_id: uuid.UUID, year: int, month: int, section_id: uuid.UUID | None) -> Select:
    stmt = select(TimesheetEntry).where(*_period_conditions(site_id, year, month))
    if section_id is not None:
        stmt = stmt.where(TimesheetEntry.section_id == section_id)
    return stmt


async def matrix_rows(
    session: AsyncSession,
    site_id: uuid.UUID,
    *,
    year: int,
    month: int,
    section_id: uuid.UUID | None,
) -> list[tuple[TimesheetEntry, Personnel, str | None]]:
    """Matrisin TEK sorgusu: hücre + personel + taşeron adı.

    Satır ya da gün başına sorgu KOŞMAZ (N+1 yok) ve sıralamayı DB yapar
    (`full_name`, sonra `work_date`) — sayfa yenilendiğinde satır sırası
    değişmesin.
    """
    stmt = (
        _scoped(site_id, year, month, section_id)
        .join(Personnel, Personnel.id == TimesheetEntry.personnel_id)
        .outerjoin(Subcontractor, Subcontractor.id == Personnel.subcontractor_id)
        .add_columns(Personnel, Subcontractor.name)
        .order_by(Personnel.full_name, Personnel.id, TimesheetEntry.work_date)
    )
    return [tuple(row) for row in (await session.execute(stmt)).all()]


async def locked_period_entries(
    session: AsyncSession, site_id: uuid.UUID, *, year: int, month: int
) -> list[TimesheetEntry]:
    """`SELECT … FOR UPDATE` — dönem+şantiye kapsamının TAMAMI kilitlenir.

    Kilit hücre başına DEĞİL kapsam başına alınır: "değiştirme" tek bir mantıksal
    işlemdir ve iki eşzamanlı kaydetme birbirinin sildiği/eklediği satırları
    yarıştırırsa matris ikisinin de olmadığı bir hâlde kalır.

    Sıralama (`personnel_id`, `work_date`) SABİTTİR — iki istek satırları farklı
    sırada kilitlerse kilitlenme (deadlock) doğar.

    ⚠️ Kilit BAŞKA şantiyelerin satırlarını kapsamaz; kişi-gün tekliğinin gerçek
    koruması UQ'dur (`uq_timesheet_entries_personnel_date`) ve servis onu açık
    bir SELECT ile önceden okur.
    """
    stmt = (
        select(TimesheetEntry)
        .where(*_period_conditions(site_id, year, month))
        .order_by(TimesheetEntry.personnel_id, TimesheetEntry.work_date)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars().all())


async def conflicting_entries(
    session: AsyncSession,
    keys: list[tuple[uuid.UUID, date]],
    *,
    exclude_site_id: uuid.UUID,
) -> list[TimesheetEntry]:
    """Gövdedeki kişi-gün ikililerinden BAŞKA şantiyede kayıtlı olanlar.

    `IntegrityError`a düşmeden önce çakışmayı adıyla söylemek için (spec §3).
    Tek sorgudur: hücre başına SELECT koşulmaz.
    """
    if not keys:
        return []
    stmt = select(TimesheetEntry).where(
        tuple_(TimesheetEntry.personnel_id, TimesheetEntry.work_date).in_(keys),
        TimesheetEntry.site_id != exclude_site_id,
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_personnel_by_ids(
    session: AsyncSession, personnel_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Personnel]:
    if not personnel_ids:
        return {}
    stmt = select(Personnel).where(Personnel.id.in_(personnel_ids))
    return {row.id: row for row in (await session.execute(stmt)).scalars().all()}


async def delete_entries(session: AsyncSession, entry_ids: list[uuid.UUID]) -> None:
    """Toplu silme — ORM nesne nesne `session.delete` etmek yerine TEK DELETE.

    `synchronize_session=False`: silinen satırlar bu istekte bir daha okunmaz,
    kimlik haritasını taramak boşuna iştir.
    """
    if not entry_ids:
        return
    await session.execute(
        delete(TimesheetEntry).where(TimesheetEntry.id.in_(entry_ids)),
    )
