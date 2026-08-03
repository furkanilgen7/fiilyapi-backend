"""Puantajdan türeyen İŞÇİ SAYISI sayaçları (T4, spec §4).

`sites`/`projects` servislerindeki `_TIMESHEET` yer tutucularının TEK veri
kaynağı burasıdır. O modüller kendi `SELECT`ini yazmaz: iki ayrı sayım mantığı
zamanla ayrışır ve şantiye kartı ile proje kartı aynı ayda farklı sayı gösterir.

## Dönem — İÇİNDE BULUNULAN AY (karar, T4)

Bu sayaçları taşıyan uçların hiçbirinde `year`/`month` parametresi YOKTUR
(şantiye listesi/detayı, bölüm detayı, proje listesi/detayı), dolayısıyla dönem
sunucuda seçilir. Puantajın dönem birimi AYDIR (matris uçları `year`+`month`
ister, spec §3) ve mockup'taki rozet ("48 işçi", ŞP 118) anlık bir "şu an sahada
kaç kişi var" göstergesidir — bu yüzden dönem, görüntüleme saat dilimindeki
(`core.timezone.today`) içinde bulunulan aydır. Sunucunun yerel saati (Railway'de
UTC) KULLANILMAZ: TR gecesi 00:00-03:00 arasında ay sınırı bir gün kayardı.

## Sayılan şey: DISTINCT PERSONEL

Aynı kişinin 20 günü 20 işçi DEĞİLDİR. Proje düzeyi de distinct'tir: iki
şantiyede birden çalışan kişi proje toplamında BİR kez sayılır — bu yüzden proje
sayacı kart sayaçlarının toplamı DEĞİLDİR ve ayrı sorgulanır.

## N+1 YOK

Her fonksiyon TEK gruplu sorgudur; çağıran kimlik listesini toplu geçirir. Kaydı
olmayan kimlik sonuçta YOKTUR — çağıran `.get(id, 0)` ile okur.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.timesheet.models import TimesheetEntry
from app.modules.timesheet.repository import period_bounds


def current_period() -> tuple[int, int]:
    """Sayaçların dönemi — (yıl, ay). TEK yerde durur ki testler de onu okusun."""
    now = today()
    return now.year, now.month


async def _distinct_personnel_by(
    session: AsyncSession, column: ColumnElement[uuid.UUID], ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    start, end = period_bounds(*current_period())
    stmt = (
        select(column, func.count(func.distinct(TimesheetEntry.personnel_id)))
        .where(
            column.in_(list(ids)),
            TimesheetEntry.work_date >= start,
            TimesheetEntry.work_date <= end,
        )
        .group_by(column)
    )
    return {key: count for key, count in (await session.execute(stmt)).all()}


async def by_site(session: AsyncSession, site_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Şantiye kartı / detayı (ŞP 118 "48 işçi")."""
    return await _distinct_personnel_by(session, TimesheetEntry.site_id, site_ids)


async def by_project(
    session: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Taahhüt kartı + şantiye listesinin alt KPI şeridi ("aktif işçi").

    `project_id` hücrede KAPSAM alanıdır (şantiyeden kopyalanır) — şantiyeler
    üzerinden JOIN'e gerek yoktur.
    """
    return await _distinct_personnel_by(session, TimesheetEntry.project_id, project_ids)


async def by_section(
    session: AsyncSession, section_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Bölüm satırı / detayı.

    `section_id` hücrede NULLABLE bir bilgi alanıdır: bölümü işaretlenmemiş
    hücre HİÇBİR bölümün sayacına girmez (uydurma dağıtım yapılmaz).
    """
    return await _distinct_personnel_by(session, TimesheetEntry.section_id, section_ids)
