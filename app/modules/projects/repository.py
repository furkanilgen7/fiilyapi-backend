import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.users.models import UserProjectAccess


async def list_projects(session: AsyncSession) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.code))
    return list(result.scalars().all())


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await session.get(Project, project_id)


async def list_projects_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Project]:
    """Kullanicinin user_project_access satirlarina gore gorunur projeler.

    all_projects=True satiri varsa tumu doner; yoksa yalnizca verilen project_id'ler.
    Hic satir yoksa bos liste. Siralama code artan.
    """
    access_rows = (
        (
            await session.execute(
                select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    if not access_rows:
        return []

    if any(row.all_projects for row in access_rows):
        return await list_projects(session)

    project_ids = [row.project_id for row in access_rows if row.project_id is not None]
    if not project_ids:
        return []

    result = await session.execute(
        select(Project).where(Project.id.in_(project_ids)).order_by(Project.code)
    )
    return list(result.scalars().all())
