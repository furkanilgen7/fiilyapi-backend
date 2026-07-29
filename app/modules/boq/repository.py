import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem


async def list_groups_for_site(session: AsyncSession, site_id: uuid.UUID) -> list[BoqGroup]:
    """Bir santiyenin poz gruplari, sirali (spec §5.1: `sort_order, created_at`).

    Kalemler ayri bir sorgu ATILMAZ: `BoqGroup.items` iliskisi lazy="selectin"
    tanimlidir (T1), bu yuzden erisildiginde SQLAlchemy tum gruplarin kalemlerini
    TEK ek sorguda (IN listesi) toplu ceker — N+1 yoktur.
    """
    result = await session.execute(
        select(BoqGroup)
        .where(BoqGroup.site_id == site_id)
        .order_by(BoqGroup.sort_order, BoqGroup.created_at)
    )
    return list(result.scalars().all())


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> BoqGroup | None:
    return await session.get(BoqGroup, group_id)


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> BoqItem | None:
    return await session.get(BoqItem, item_id)


async def get_item_by_code(
    session: AsyncSession, site_id: uuid.UUID, code: str, exclude_item_id: uuid.UUID | None = None
) -> BoqItem | None:
    """(site_id, code) çakışmasını IntegrityError'a düşmeden ÖNCE yakalamak içindir

    (spec §5.4, DuplicateError deseni — `projects.service.create_employer` emsali).
    PATCH'te kalemin kendisini hariç tutmak için `exclude_item_id` verilir.
    """
    stmt = select(BoqItem).where(BoqItem.site_id == site_id, BoqItem.code == code)
    if exclude_item_id is not None:
        stmt = stmt.where(BoqItem.id != exclude_item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
