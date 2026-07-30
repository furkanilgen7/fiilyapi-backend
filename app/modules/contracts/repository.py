"""Birleşik sözleşme listesi için okuma sorguları (spec §6.1, task C5).

`boq/repository.py` deseninin aynısı: filtreler SQL düzeyinde uygulanır, N+1
üretilmez. Taşeron tarafında `SubcontractorContract.items` ilişkisi
`lazy="selectin"` tanımlıdır (models.py) — erişildiğinde tüm sözleşmelerin
kalemleri TEK ek sorguda (IN listesi) toplu gelir.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import (
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
    SubcontractorContract,
)
from app.modules.projects.models import Project, ProjectContract


async def list_employer_contracts(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> list[tuple[Project, ProjectContract]]:
    """İşveren "sözleşme kaydı" = `project_contracts` satırı olan proje (spec §6.1).

    INNER JOIN: sözleşmesi olmayan proje listede ÇIKMAZ.
    """
    if not visible_project_ids:
        return []
    stmt = (
        select(Project, ProjectContract)
        .join(ProjectContract, ProjectContract.project_id == Project.id)
        .where(Project.id.in_(visible_project_ids))
        .order_by(Project.code)
    )
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)
    if status_filter is not None:
        stmt = stmt.where(ProjectContract.status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                ProjectContract.contract_no.ilike(pattern),
                Project.employer_name.ilike(pattern),
            )
        )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def list_subcontractor_contracts(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> list[SubcontractorContract]:
    if not visible_project_ids:
        return []
    stmt = (
        select(SubcontractorContract)
        .where(SubcontractorContract.project_id.in_(visible_project_ids))
        .order_by(SubcontractorContract.created_at)
    )
    if project_id is not None:
        stmt = stmt.where(SubcontractorContract.project_id == project_id)
    if status_filter is not None:
        stmt = stmt.where(SubcontractorContract.status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                SubcontractorContract.contract_no.ilike(pattern),
                SubcontractorContract.subcontractor_name.ilike(pattern),
            )
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- İşveren sözleşmesi poz grup/kalem (task C6, `boq/repository.py` deseninin
# aynısı — spec §3.2, §6.2) ---


async def list_employer_groups(
    session: AsyncSession, project_id: uuid.UUID
) -> list[EmployerContractGroup]:
    """Bir sözleşmenin poz grupları, sıralı. Kalemler ayrı sorgu ATILMAZ:

    `EmployerContractGroup.items` ilişkisi `lazy="selectin"` tanımlıdır (C1),
    erişildiğinde tüm grupların kalemleri TEK ek sorguda toplu gelir.
    """
    result = await session.execute(
        select(EmployerContractGroup)
        .where(EmployerContractGroup.project_id == project_id)
        .order_by(EmployerContractGroup.sort_order, EmployerContractGroup.created_at)
    )
    return list(result.scalars().all())


async def get_employer_group(
    session: AsyncSession, group_id: uuid.UUID
) -> EmployerContractGroup | None:
    return await session.get(EmployerContractGroup, group_id)


async def get_employer_item(
    session: AsyncSession, item_id: uuid.UUID
) -> EmployerContractItem | None:
    return await session.get(EmployerContractItem, item_id)


async def get_employer_item_by_code(
    session: AsyncSession,
    project_id: uuid.UUID,
    code: str,
    exclude_item_id: uuid.UUID | None = None,
) -> EmployerContractItem | None:
    """`(project_id, code)` çakışmasını `IntegrityError`'a düşmeden ÖNCE yakalar

    (`DuplicateError` deseni, `boq/repository.py.get_item_by_code` emsali).
    """
    stmt = select(EmployerContractItem).where(
        EmployerContractItem.project_id == project_id, EmployerContractItem.code == code
    )
    if exclude_item_id is not None:
        stmt = stmt.where(EmployerContractItem.id != exclude_item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_distributed_boq_items(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> list[BoqItem]:
    """Spec §6.3 (`POZ` ekranı): verilen sözleşme kalemlerine bağlı TÜM BOQ

    satırları TEK sorguda (`IN` listesi) — `distribution.build_distribution`
    kalem başına ayrı sorgu ATMAZ. `contract_item_id IS NULL` satırlar zaten
    `item_ids` filtresiyle elenir (spec §3.3: bu satırlar dağıtım ekranında
    görünmez).
    """
    if not item_ids:
        return []
    stmt = select(BoqItem).where(BoqItem.contract_item_id.in_(item_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_boq_items_for_sites(
    session: AsyncSession, site_ids: list[uuid.UUID]
) -> list[BoqItem]:
    """Verilen şantiyelerin TÜM BOQ satırları TEK sorguda (task C8).

    `contract_item_id IS NULL` satırlar da gelir — dağıtım yazarken
    `uq_boq_items_site_code` çakışması bu satırlardan da doğabilir
    (şantiyenin kendi başına girdiği poz aynı numarayı tutuyor olabilir).
    """
    if not site_ids:
        return []
    stmt = select(BoqItem).where(BoqItem.site_id.in_(site_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_boq_groups_for_sites(
    session: AsyncSession, site_ids: list[uuid.UUID]
) -> list[BoqGroup]:
    """Verilen şantiyelerin BOQ grupları TEK sorguda (task C8 grup önbelleği).

    Sıralama DETERMİNİSTİK olmak ZORUNDA: `BoqGroup`'ta `(site_id, name)`
    benzersizliği yok, aynı adlı iki grup varsa önbelleğin hangisini seçtiği
    sıralamaya bağlıdır. `created_at, id` → her zaman EN ESKİ grup.
    """
    if not site_ids:
        return []
    stmt = (
        select(BoqGroup)
        .where(BoqGroup.site_id.in_(site_ids))
        .order_by(BoqGroup.created_at, BoqGroup.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def sum_distributed_quantities(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Spec §3.3: `distributed_quantity` bağlı `boq_items.quantity` toplamı.

    Kalem başına ayrı sorgu ATILMAZ — `GROUP BY` ile TEK sorguda toplanır
    (`GET .../contract/items` N kalemli listede N+1 üretmez).
    """
    if not item_ids:
        return {}
    stmt = (
        select(BoqItem.contract_item_id, func.sum(BoqItem.quantity))
        .where(BoqItem.contract_item_id.in_(item_ids))
        .group_by(BoqItem.contract_item_id)
    )
    result = await session.execute(stmt)
    return {row[0]: row[1] for row in result.all()}
