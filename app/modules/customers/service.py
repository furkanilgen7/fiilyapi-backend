"""Alıcı kartoteksi servisi (P8 spec §2, §4, §6).

`contracts/subcontractors.py`nin birebir kardeşi: proje-bağımsız kartoteks,
kısmi benzersiz indeksli VKN, `DuplicateError` -> 409, `NotFoundError` -> 404.

**Proje-bağımsız kasıtlı fark:** `Subcontractor`/`Employer` gibi `Customer` da
`visible_projects` süzgecinden GEÇMEZ (spec §6) — bir alıcı projeye ait değildir,
aynı kişi birden çok projeden daire alabilir. IDOR açığı DEĞİL, bilinçli tasarım
kararıdır; erişim `sales` izin seviyesindedir.

**Silme ucu YOK** (spec §4): alıcıya bağlı satış kaydı bulunabilir ve
`unit_sales.customer_id` FK'si RESTRICT'tir. Kartoteksten çıkarma ihtiyacı
doğarsa çözüm `is_active` benzeri bir bayraktır, DELETE değil.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, NotFoundError
from app.modules.customers import repository
from app.modules.customers.guards import CUSTOMER_MISSING, validate_customer_identity
from app.modules.customers.models import Customer
from app.modules.customers.schemas import CustomerCreate, CustomerUpdate

_DUPLICATE_NATIONAL_ID = "Bu TCKN ile kayıtlı bir müşteri zaten var."
_DUPLICATE_TAX_NUMBER = "Bu VKN ile kayıtlı bir müşteri zaten var."


async def _assert_identity_free(
    session: AsyncSession,
    national_id: str | None,
    tax_number: str | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Servis ÖNCE SELECT ile bakar ki kullanıcıya alanına özel Türkçe mesaj

    verilsin; kısmi benzersiz indeksler (`uq_customers_national_id`/
    `uq_customers_tax_number`) + `IntegrityError` -> 409 handler'ı YARIŞ DURUMU
    emniyet ağı olarak KALIR (`subcontractors.create_subcontractor` deseni).
    """
    if national_id is not None:
        if await repository.get_customer_by_national_id(session, national_id, exclude_id):
            raise DuplicateError(_DUPLICATE_NATIONAL_ID)
    if tax_number is not None:
        if await repository.get_customer_by_tax_number(session, tax_number, exclude_id):
            raise DuplicateError(_DUPLICATE_TAX_NUMBER)


async def list_customers(session: AsyncSession, q: str | None) -> list[Customer]:
    return await repository.list_customers(session, q)


async def get_customer(session: AsyncSession, customer_id: uuid.UUID) -> Customer:
    customer = await repository.get_customer(session, customer_id)
    if customer is None:
        raise NotFoundError(CUSTOMER_MISSING)
    return customer


async def create_customer(session: AsyncSession, data: CustomerCreate) -> Customer:
    validate_customer_identity(data.customer_type, data.national_id, data.tax_number)
    await _assert_identity_free(session, data.national_id, data.tax_number)
    customer = Customer(
        customer_type=data.customer_type,
        name=data.name,
        national_id=data.national_id,
        tax_number=data.tax_number,
        phone=data.phone,
        email=data.email,
        address=data.address,
    )
    return await repository.add_customer(session, customer)


async def update_customer(
    session: AsyncSession, customer_id: uuid.UUID, data: CustomerUpdate
) -> Customer:
    """Kısmi güncelleme (`model_dump(exclude_unset=True)`) — gönderilmeyen alan

    değişmez. Tip/kimlik kuralı BİRLEŞİK kayıt üzerinde koşar: gövdedeki değerler
    DB'dekilerin üstüne bindirilir, sonra doğrulanır. Yalnız gövdeye bakmak,
    `person -> company` geçişinde eski TCKN'yi kayıtta bırakırdı.
    """
    customer = await get_customer(session, customer_id)
    updates = data.model_dump(exclude_unset=True)

    efektif_tip = updates.get("customer_type", customer.customer_type)
    efektif_tckn = updates.get("national_id", customer.national_id)
    efektif_vkn = updates.get("tax_number", customer.tax_number)
    validate_customer_identity(efektif_tip, efektif_tckn, efektif_vkn)

    await _assert_identity_free(
        session,
        efektif_tckn if "national_id" in updates else None,
        efektif_vkn if "tax_number" in updates else None,
        exclude_id=customer.id,
    )

    for field, value in updates.items():
        setattr(customer, field, value)
    await session.flush()
    await session.refresh(customer)
    return customer
