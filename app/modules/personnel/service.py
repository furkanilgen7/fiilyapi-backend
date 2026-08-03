"""Personel servisi (puantaj spec §1, §2, §3, §5).

`customers/service.py`nin kardeşi: proje-bağımsız kartoteks, `NotFoundError` -> 404,
alanlar-arası kural servis korkuluğunda (`guards.validate_personnel_source`) -> 422.

**Silme ucu YOK** (spec §3): `timesheet_entries.personnel_id` FK'si RESTRICT'tir —
puantajı olan bir işçi silinemez ve silinmemelidir (geçmiş adam-gün kaydı kaybolur).
Kartoteksten çıkarma `is_active=false` PATCH'idir.

**İK alanı YOK** (spec §1, §5): belge / izin / SGK / bordro / ücret bu servise
sızmaz — İK'nın geri kalanı ERTELENMİŞTİR.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.personnel import repository
from app.modules.personnel.guards import PERSONNEL_MISSING, validate_personnel_source
from app.modules.personnel.models import Personnel
from app.modules.personnel.schemas import PersonnelCreate, PersonnelUpdate

PERMISSION_MODULE = "personnel"


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel:
    personnel = await repository.get_personnel(session, personnel_id)
    if personnel is None:
        raise NotFoundError(PERSONNEL_MISSING)
    return personnel


async def create_personnel(session: AsyncSession, data: PersonnelCreate) -> Personnel:
    validate_personnel_source(data.source, data.subcontractor_id)
    personnel = Personnel(
        full_name=data.full_name,
        trade=data.trade,
        source=data.source,
        subcontractor_id=data.subcontractor_id,
        user_id=data.user_id,
        is_active=data.is_active,
    )
    return await repository.add_personnel(session, personnel)


async def update_personnel(
    session: AsyncSession, personnel_id: uuid.UUID, data: PersonnelUpdate
) -> Personnel:
    """Kısmi güncelleme (`model_dump(exclude_unset=True)`) — gönderilmeyen alan değişmez.

    Kaynak/taşeron kuralı BİRLEŞİK kayıt üzerinde koşar: gövdedeki değerler
    DB'dekilerin üstüne bindirilir, sonra doğrulanır (`customers` deseni). Yalnız
    gövdeye bakmak, `subcontractor -> company` geçişinde eski taşeron bağını
    kayıtta bırakırdı.
    """
    personnel = await get_personnel(session, personnel_id)
    updates = data.model_dump(exclude_unset=True)

    efektif_kaynak = updates.get("source", personnel.source)
    efektif_taseron = updates.get("subcontractor_id", personnel.subcontractor_id)
    validate_personnel_source(efektif_kaynak, efektif_taseron)

    for field, value in updates.items():
        setattr(personnel, field, value)
    await session.flush()
    await session.refresh(personnel)
    return personnel
