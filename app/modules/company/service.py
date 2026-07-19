from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company import repository
from app.modules.company.models import Company
from app.modules.company.schemas import CompanyUpdate


async def get_company(session: AsyncSession) -> Company:
    return await repository.get_or_create_singleton(session)


async def update_company(session: AsyncSession, data: CompanyUpdate) -> Company:
    company = await repository.get_or_create_singleton(session)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await session.flush()
    return company
