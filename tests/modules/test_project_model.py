from decimal import Decimal

from sqlalchemy import select

from app.modules.projects.models import Project, ProjectStatus


async def test_create_and_read_project(db_session):
    project = Project(
        code="GK-A",
        name="Güneşkent A-Blok",
        status=ProjectStatus.active,
        budget=Decimal("1500000.00"),
        progress_pct=Decimal("42.50"),
    )
    db_session.add(project)
    await db_session.flush()

    loaded = (
        await db_session.execute(select(Project).where(Project.code == "GK-A"))
    ).scalar_one()
    assert loaded.name == "Güneşkent A-Blok"
    assert loaded.status is ProjectStatus.active
    assert loaded.budget == Decimal("1500000.00")


def test_project_status_values():
    assert {s.value for s in ProjectStatus} == {"active", "on_hold", "completed"}
