"""Alıcı kartoteksi veri erişimi — `contracts/repository.py`nin taşeron

bölümünün birebiri (`list_subcontractors`/`get_subcontractor_by_tax_number`/
`add_subcontractor`).

`visible_projects` süzgeci BİLİNÇLİ OLARAK yoktur: `customers` proje-bağımsızdır
(spec §6), tabloda `project_id` kolonu bile yoktur. IDOR unutulmuş DEĞİLDİR —
erişim `sales` izin seviyesiyle denetlenir (router kapıları).
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer


async def list_customers(session: AsyncSession, q: str | None) -> list[Customer]:
    """Arama ad / TCKN / VKN üzerinde OR'lu KISMİ eşleşmedir (spec §4).

    Kimlik numaralarında da `ILIKE %q%` kullanılır: kullanıcı ekrandaki tek
    arama kutusuna numaranın yalnız son hanelerini yazabilir. Sıralama DB'de
    (`ORDER BY name`, `ix_customers_name`).
    """
    stmt = select(Customer)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.name.ilike(pattern),
                Customer.national_id.ilike(pattern),
                Customer.tax_number.ilike(pattern),
            )
        )
    stmt = stmt.order_by(Customer.name)
    return list((await session.execute(stmt)).scalars().all())


async def get_customer(session: AsyncSession, customer_id: uuid.UUID) -> Customer | None:
    return await session.get(Customer, customer_id)


async def get_customer_by_national_id(
    session: AsyncSession, national_id: str, exclude_id: uuid.UUID | None = None
) -> Customer | None:
    stmt = select(Customer).where(Customer.national_id == national_id)
    if exclude_id is not None:
        stmt = stmt.where(Customer.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_customer_by_tax_number(
    session: AsyncSession, tax_number: str, exclude_id: uuid.UUID | None = None
) -> Customer | None:
    stmt = select(Customer).where(Customer.tax_number == tax_number)
    if exclude_id is not None:
        stmt = stmt.where(Customer.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_customer(session: AsyncSession, customer: Customer) -> Customer:
    session.add(customer)
    await session.flush()
    await session.refresh(customer)
    return customer
