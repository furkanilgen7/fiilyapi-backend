from sqlalchemy import select

from app.modules.users.models import UserProjectAccess


async def test_grant_specific_project_access(db_session, user_factory, project_factory):
    user = await user_factory(email="u@t.co", password="parola1234", role_key="site_chief")
    project = await project_factory("GK-A")
    db_session.add(
        UserProjectAccess(user_id=user.id, project_id=project.id, all_projects=False)
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(UserProjectAccess).where(UserProjectAccess.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].project_id == project.id


async def test_grant_all_projects_access(db_session, user_factory):
    user = await user_factory(email="a@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await db_session.flush()

    row = (
        await db_session.execute(
            select(UserProjectAccess).where(UserProjectAccess.user_id == user.id)
        )
    ).scalar_one()
    assert row.all_projects is True
    assert row.project_id is None
