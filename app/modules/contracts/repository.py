"""Birleşik sözleşme listesi için okuma sorguları (spec §6.1, task C5).

`boq/repository.py` deseninin aynısı: filtreler SQL düzeyinde uygulanır, N+1
üretilmez. Taşeron tarafında `SubcontractorContract.items` ilişkisi
`lazy="selectin"` tanımlıdır (models.py) — erişildiğinde tüm sözleşmelerin
kalemleri TEK ek sorguda (IN listesi) toplu gelir.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import ContractStatus, SubcontractorContract
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
