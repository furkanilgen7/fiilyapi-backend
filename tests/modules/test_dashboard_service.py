from app.modules.dashboard.service import build_summary
from app.modules.users.models import UserProjectAccess


async def test_summary_counts_only_active_projects(seeded_db, user_factory, project_factory):
    await project_factory("GK-A", status="active")
    await project_factory("OSB-1", status="on_hold")
    await project_factory("SAHIL-2", status="completed")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()

    summary = await build_summary(seeded_db, user)

    assert len(summary.projects) == 3
    assert summary.active_project_count == 1


async def test_summary_uses_role_display_name(seeded_db, user_factory):
    user = await user_factory(email="patron2@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.role_name == "Patron"


async def test_summary_placeholders_are_unavailable(seeded_db, user_factory):
    user = await user_factory(email="patron3@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.portfolio.pending_module == "progress_payments"
    assert summary.receivables.pending_module == "invoicing"
    assert summary.average_margin.pending_module == "progress_payments"
    assert summary.pending_approvals.pending_module == "approvals"
    assert summary.risks.pending_module == "inventory"
    assert not any(
        card.available
        for card in (
            summary.portfolio,
            summary.receivables,
            summary.average_margin,
            summary.pending_approvals,
            summary.risks,
        )
    )
    assert summary.pending_approvals.count == 0


async def test_summary_empty_when_no_project_access(seeded_db, user_factory, project_factory):
    await project_factory("GK-A")
    user = await user_factory(email="patron4@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.projects == []
    assert summary.active_project_count == 0
