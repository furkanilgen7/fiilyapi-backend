"""Personel veri erişimi — `customers/repository.py` + `users/repository.py`

(sayfalama) desenlerinin birleşimi.

**`visible_projects` süzgeci YOKTUR ama `?project_id=` süzgeci VARDIR** (İK-1 spec
§5 K4): `personnel` yine şirket-geneli bir İK varlığıdır ve tüm projelerde görünür;
İK-1 ile `assigned_project_id` ATAMA kolonu açıldığından `project_id` bir
DARALTMA süzgecidir (yetki genişletmez). Puantaj diliminin "proje süzgeci
eklenmesin" notu atama kolonu YOKKEN geçerliydi; §5 K4 kararı bunu güncelledi —
kolon açıldı, `?project_id=` meşru. IDOR unutulmuş DEĞİLDİR: süzgeç bir yetki
kapısı değildir, erişim yine `personnel` izin seviyesiyle (router kapıları)
denetlenir.
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
    project_id: uuid.UUID | None,
    is_draft: bool | None,
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
    # İK-1 §5 K4: atama kolonuna göre DARALTMA (yetki genişletmez).
    if project_id is not None:
        stmt = stmt.where(Personnel.assigned_project_id == project_id)
    if is_draft is not None:
        stmt = stmt.where(Personnel.is_draft.is_(is_draft))
    return stmt


async def list_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    project_id: uuid.UUID | None = None,
    is_draft: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Personnel]:
    """Arama YALNIZ `full_name` üzerindedir (spec §3) ve `ILIKE %q%` kısmi eşleşmedir.

    Sıralama DB'de (`ORDER BY full_name`) — sayfalama deterministik olsun.
    """
    stmt = _filtreli(
        select(Personnel), q, source, subcontractor_id, is_active, project_id, is_draft
    )
    stmt = stmt.order_by(Personnel.full_name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    project_id: uuid.UUID | None = None,
    is_draft: bool | None = None,
) -> int:
    stmt = _filtreli(
        select(func.count()).select_from(Personnel),
        q,
        source,
        subcontractor_id,
        is_active,
        project_id,
        is_draft,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel | None:
    return await session.get(Personnel, personnel_id)


async def get_personnel_by_tc_no(
    session: AsyncSession, tc_no: str, exclude_id: uuid.UUID | None = None
) -> Personnel | None:
    """DOLU TCKN'nin başka bir kayıtta olup olmadığı (`customers` pre-SELECT deseni).

    Servis bunu `IntegrityError`a düşmeden ÇAĞIRIR ki kullanıcıya alanına özel
    Türkçe 409 verilebilsin; `uq_personnel_tc_no` YARIŞ DURUMU emniyet ağıdır.
    """
    stmt = select(Personnel).where(Personnel.tc_no == tc_no)
    if exclude_id is not None:
        stmt = stmt.where(Personnel.id != exclude_id)
    return (await session.execute(stmt)).scalars().first()


async def add_personnel(session: AsyncSession, personnel: Personnel) -> Personnel:
    session.add(personnel)
    await session.flush()
    await session.refresh(personnel)
    return personnel
