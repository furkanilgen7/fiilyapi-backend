"""Taşeron kartoteksi servisi (spec §3.4, §6.4, task C9).

`projects/service.py`'deki `list_employers`/`create_employer` desenlerinin
birebiri: `Employer` ile `Subcontractor` simetriktir.

**Proje-bağımsız kasıtlı fark:** `Employer` gibi `Subcontractor` da
`visible_projects` süzgecinden GEÇMEZ — bir taşeron firması projeye ait
değildir, kartoteks tüm görünür kullanıcılar için ortaktır (spec §6.4). IDOR
açığı DEĞİL, bilinçli tasarım kararıdır.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, NotFoundError
from app.modules.contracts import repository
from app.modules.contracts.guards import SUBCONTRACTOR_MISSING
from app.modules.contracts.models import Subcontractor
from app.modules.contracts.schemas import SubcontractorCreate, SubcontractorUpdate

_DUPLICATE_TAX_NUMBER = "Bu VKN ile kayıtlı bir taşeron zaten var."


async def list_subcontractors(
    session: AsyncSession, q: str | None, active_only: bool
) -> list[Subcontractor]:
    return await repository.list_subcontractors(session, q, active_only)


async def create_subcontractor(session: AsyncSession, data: SubcontractorCreate) -> Subcontractor:
    """Yinelenen VKN -> DuplicateError (409). Servis ÖNCE SELECT ile bakar ki

    kullanıcıya alanına özel Türkçe mesaj verilsin; IntegrityError -> 409
    handler'ı yarış durumu emniyet ağı olarak KALIR (`create_employer` deseni).
    VKN'siz kayıtlar serbestçe çoğalabilir (spec §3.4 kısmi benzersiz indeks).
    """
    if data.tax_number is not None:
        existing = await repository.get_subcontractor_by_tax_number(session, data.tax_number)
        if existing is not None:
            raise DuplicateError(_DUPLICATE_TAX_NUMBER)
    subcontractor = Subcontractor(
        name=data.name,
        tax_number=data.tax_number,
        contact_person=data.contact_person,
        phone=data.phone,
        email=data.email,
        category=data.category,
        is_active=data.is_active,
    )
    return await repository.add_subcontractor(session, subcontractor)


async def update_subcontractor(
    session: AsyncSession, subcontractor_id: uuid.UUID, data: SubcontractorUpdate
) -> Subcontractor:
    """Kısmi güncelleme (`model_dump(exclude_unset=True)`, `update_employer_group`

    deseninin aynısı) — gönderilmeyen alan değişmez. `tax_number` değişirse
    tekillik yeniden kontrol edilir (kendi kaydı hariç tutularak).
    """
    subcontractor = await repository.get_subcontractor(session, subcontractor_id)
    if subcontractor is None:
        raise NotFoundError(SUBCONTRACTOR_MISSING)
    updates = data.model_dump(exclude_unset=True)
    if "tax_number" in updates and updates["tax_number"] is not None:
        existing = await repository.get_subcontractor_by_tax_number(
            session, updates["tax_number"], exclude_id=subcontractor.id
        )
        if existing is not None:
            raise DuplicateError(_DUPLICATE_TAX_NUMBER)
    for field, value in updates.items():
        setattr(subcontractor, field, value)
    await session.flush()
    await session.refresh(subcontractor)
    return subcontractor
