from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company.models import Company


async def get_or_create_singleton(session: AsyncSession) -> Company:
    """Tek sirket satirini dondurur; yoksa bos satir olusturur (spec §4.1)."""
    company = await session.scalar(select(Company).limit(1))
    if company is None:
        company = Company()
        session.add(company)
        await session.flush()
    return company
