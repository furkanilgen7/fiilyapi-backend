"""B6 — okuma yanıtları: employer, contract, budget_lines, is_draft, ProjectCounts.draft."""

from decimal import Decimal

from sqlalchemy import event

from app.modules.dashboard.service import build_summary
from app.modules.projects.models import Employer
from app.modules.projects.schemas import ProjectBudgetInput, ProjectContractInput, ProjectCreate
from app.modules.projects.service import (
    create_project,
    list_projects_overview,
)
from app.modules.users.models import UserProjectAccess


async def _grant_all(seeded_db, user):
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()


async def _actor(seeded_db, user_factory, email="patron@t.co"):
    user = await user_factory(email=email, password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)
    return user


async def test_detail_exposes_employer_contract_budget_lines(db_session):
    employer = Employer(name="ACME İnşaat", tax_number="1234567890")
    db_session.add(employer)
    await db_session.flush()
    project = await create_project(
        db_session,
        ProjectCreate(
            name="Detay",
            project_type="taahhut",
            city="Ankara",
            start_date="2026-01-01",
            end_date="2026-12-31",
            employer_id=employer.id,
            contract=ProjectContractInput(
                contract_no="SZL-2026-100",
                signature_date="2026-01-02",
                amount=Decimal("5000000.00"),
                has_price_escalation=False,
            ),
            budget_lines=ProjectBudgetInput(
                material="100.00", labor="200.00", subcontractor="300.00", overhead="400.00"
            ),
        ),
    )
    await db_session.refresh(project)

    detail = get_project_detail_from_orm(project)

    assert detail.employer is not None
    assert detail.employer.name == "ACME İnşaat"
    assert detail.contract is not None
    assert detail.contract.contract_no == "SZL-2026-100"
    assert detail.contract.amount == Decimal("5000000.00")
    assert detail.budget_lines.material == Decimal("100.00")
    assert detail.budget_lines.overhead == Decimal("400.00")
    assert detail.is_draft is False
    # employer_name anlık görüntüsü KALIR.
    assert detail.employer_name == "ACME İnşaat"


def get_project_detail_from_orm(project, worker_count: int = 0):
    """`to_detail` T4'te isci sayacini PARAMETRE olarak alir (puantaj spec §4):

    sayim `timesheet.counts`ta toplu sorguyla yapilir, saf donusturucu DB'ye
    dokunmaz. Bu testlerin ilgi alani puantaj degil, bu yuzden 0 gecilir.
    """
    from app.modules.projects.service import to_detail

    return to_detail(project, worker_count)


async def test_draft_project_has_none_employer_contract(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(name="Taslak", project_type="taahhut", is_draft=True),
    )
    await db_session.refresh(project)
    detail = get_project_detail_from_orm(project)
    assert detail.employer is None
    assert detail.contract is None
    assert detail.is_draft is True
    assert detail.budget_lines.material == Decimal("0")


async def test_list_item_exposes_new_fields(seeded_db, user_factory):
    await create_project(
        seeded_db,
        ProjectCreate(name="Liste Taslak", project_type="taahhut", is_draft=True),
    )
    user = await _actor(seeded_db, user_factory)

    overview = await list_projects_overview(seeded_db, user, None, None)

    item = overview.items[0]
    assert item.is_draft is True
    assert item.budget_lines is not None
    # taslak: employer/contract None ama alanlar sözleşmede var.
    assert item.employer is None
    assert item.contract is None


async def test_counts_include_draft(seeded_db, user_factory):
    await create_project(seeded_db, ProjectCreate(name="D1", project_type="taahhut", is_draft=True))
    await create_project(seeded_db, ProjectCreate(name="D2", project_type="taahhut", is_draft=True))
    await create_project(
        seeded_db,
        ProjectCreate(
            name="Gerçek",
            project_type="kendi_yatirim",
            city="İstanbul",
            start_date="2026-01-01",
            end_date="2026-06-30",
            is_draft=False,
        ),
    )
    user = await _actor(seeded_db, user_factory)

    overview = await list_projects_overview(seeded_db, user, None, None)

    assert overview.counts.draft == 2
    assert overview.counts.all == 3


async def test_drafts_appear_in_list(seeded_db, user_factory):
    """Taslaklar listede GÖRÜNÜR (spec §5.4) — filtrelenip gizlenmez."""
    await create_project(
        seeded_db, ProjectCreate(name="Taslak", project_type="taahhut", is_draft=True)
    )
    user = await _actor(seeded_db, user_factory)

    overview = await list_projects_overview(seeded_db, user, None, None)

    assert overview.counts.all == 1
    assert len(overview.items) == 1


async def test_dashboard_excludes_draft_from_active_count(seeded_db, user_factory):
    """active_project_count = status active AND NOT is_draft (spec §5.5)."""
    await create_project(
        seeded_db,
        ProjectCreate(
            name="Aktif Gerçek",
            project_type="kendi_yatirim",
            city="İzmir",
            start_date="2026-01-01",
            end_date="2026-12-31",
            is_draft=False,
        ),
    )
    await create_project(
        seeded_db,
        ProjectCreate(name="Aktif Taslak", project_type="taahhut", is_draft=True),
    )
    user = await _actor(seeded_db, user_factory)

    summary = await build_summary(seeded_db, user)

    assert summary.active_project_count == 1


async def test_list_avoids_n_plus_one_for_employer_contract(seeded_db, user_factory):
    """employer/contract selectin ile toplu yüklenir — proje sayısıyla sorgu büyümez."""
    employer = Employer(name="Toplu İşveren", tax_number="9876543210")
    seeded_db.add(employer)
    await seeded_db.flush()
    for i in range(3):
        await create_project(
            seeded_db,
            ProjectCreate(
                name=f"P{i}",
                project_type="taahhut",
                city="Bursa",
                start_date="2026-01-01",
                end_date="2026-12-31",
                employer_id=employer.id,
                contract=ProjectContractInput(
                    contract_no=f"SZL-2026-{i:03d}",
                    signature_date="2026-01-02",
                    amount=Decimal("1000000.00"),
                    has_price_escalation=False,
                ),
            ),
        )
    user = await _actor(seeded_db, user_factory)

    query_count = 0

    @event.listens_for(seeded_db.sync_session, "do_orm_execute")
    def _count(_state):
        nonlocal query_count
        query_count += 1

    overview = await list_projects_overview(seeded_db, user, None, None)

    assert len(overview.items) == 3
    # 3 proje için employer/contract N+1 olsaydı sorgu sayısı proje başına artardı.
    # selectin ile employer + contract tek IN sorgusuyla gelir; toplam küçük kalır.
    assert query_count <= 12
