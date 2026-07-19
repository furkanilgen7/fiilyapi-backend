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


async def set_logo(
    session: AsyncSession, content_type: str, filename: str | None, data: bytes
) -> Company:
    company = await get_or_create_singleton(session)
    company.logo_data = data
    company.logo_content_type = content_type
    company.logo_filename = filename
    await session.flush()
    return company


async def clear_logo(session: AsyncSession) -> Company:
    company = await get_or_create_singleton(session)
    company.logo_data = None
    company.logo_content_type = None
    company.logo_filename = None
    await session.flush()
    return company
