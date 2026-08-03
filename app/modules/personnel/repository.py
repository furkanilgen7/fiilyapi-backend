"""Personel veri erişimi — `customers/repository.py` + `users/repository.py`

(sayfalama) desenlerinin birleşimi.

**`visible_projects` süzgeci BİLİNÇLİ OLARAK yoktur** (spec §3): `personnel`
şirket-geneli bir İK varlığıdır, tabloda `project_id` kolonu bile YOKTUR — aynı
işçi ay içinde farklı projelerin şantiyelerinde çalışabilir. IDOR unutulmuş
DEĞİLDİR; erişim `personnel` izin seviyesiyle denetlenir (router kapıları).
Kapsam süzgeci PUANTAJ uçlarının (T3) işidir, personel kartoteksinin değil.
"""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import Personnel
from app.modules.site_diary.models import WorkerSource


def _filtreli(
    stmt: Select,
    q: str | None,
    source: WorkerSource | None,
    subcontractor_id: uuid.UUID | None,
    is_active: bool | None,
) -> Select:
    """Liste ve sayım AYNI süzgeçleri kullanır — `total` gösterilen listeyle uyuşsun."""
    if q:
        stmt = stmt.where(Personnel.full_name.ilike(f"%{q}%"))
    if source is not None:
        stmt = stmt.where(Personnel.source == source)
    if subcontractor_id is not None:
        stmt = stmt.where(Personnel.subcontractor_id == subcontractor_id)
    if is_active is not None:
        stmt = stmt.where(Personnel.is_active.is_(is_active))
    return stmt


async def list_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Personnel]:
    """Arama YALNIZ `full_name` üzerindedir (spec §3) ve `ILIKE %q%` kısmi eşleşmedir.

    Sıralama DB'de (`ORDER BY full_name`) — sayfalama deterministik olsun.
    """
    stmt = _filtreli(select(Personnel), q, source, subcontractor_id, is_active)
    stmt = stmt.order_by(Personnel.full_name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
) -> int:
    stmt = _filtreli(
        select(func.count()).select_from(Personnel), q, source, subcontractor_id, is_active
    )
    return (await session.execute(stmt)).scalar_one()


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel | None:
    return await session.get(Personnel, personnel_id)


async def add_personnel(session: AsyncSession, personnel: Personnel) -> Personnel:
    session.add(personnel)
    await session.flush()
    await session.refresh(personnel)
    return personnel
