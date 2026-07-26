from decimal import Decimal

import pytest

from app.core.errors import NotFoundError
from app.modules.projects.models import LandShareShareholder, ProjectLandShare
from app.modules.projects.service import get_project_detail, list_projects_overview
from app.modules.users.models import UserProjectAccess


async def _grant_all(seeded_db, user) -> None:
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()


async def test_counts_ignore_filters(seeded_db, user_factory, project_factory):
    await project_factory("T-1", project_type="taahhut", status="active")
    await project_factory("T-2", project_type="taahhut", status="completed")
    await project_factory("KY-1", project_type="kendi_yatirim", status="active")
    await project_factory("KK-1", project_type="kat_karsiligi", status="active")
    user = await user_factory(email="p@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    result = await list_projects_overview(
        seeded_db, user, type_filter="taahhut", status_filter=None
    )

    assert [p.code for p in result.items] == ["T-1", "T-2"]
    assert result.counts.all == 4
    assert result.counts.taahhut == 2
    assert result.counts.kendi_yatirim == 1
    assert result.counts.kat_karsiligi == 1
    assert result.counts.completed == 1


async def test_status_filter_selects_completed(seeded_db, user_factory, project_factory):
    await project_factory("T-1", status="active")
    await project_factory("T-2", status="completed")
    user = await user_factory(email="p2@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    result = await list_projects_overview(
        seeded_db, user, type_filter=None, status_filter="completed"
    )

    assert [p.code for p in result.items] == ["T-2"]
    assert result.counts.all == 2


async def test_scope_filter_limits_non_admin(seeded_db, user_factory, project_factory):
    granted = await project_factory("T-1")
    await project_factory("T-2")
    user = await user_factory(email="p3@t.co", password="parola1234", role_key="patron")
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await seeded_db.flush()

    result = await list_projects_overview(seeded_db, user, type_filter=None, status_filter=None)

    assert [p.code for p in result.items] == ["T-1"]
    assert result.counts.all == 1


async def test_admin_bypasses_scope_filter(seeded_db, user_factory, project_factory):
    """Ayarlar kilitlenme korumasi: erisim satiri olmayan system_admin her seyi gorur."""
    await project_factory("T-1")
    await project_factory("T-2")
    admin = await user_factory(email="a@t.co", password="parola1234", role_key="system_admin")

    result = await list_projects_overview(seeded_db, admin, type_filter=None, status_filter=None)

    assert [p.code for p in result.items] == ["T-1", "T-2"]


async def test_taahhut_item_has_contracting_placeholders(seeded_db, user_factory, project_factory):
    await project_factory(
        "T-1",
        project_type="taahhut",
        category="Konut",
        city="Ankara",
        employer_name="Güneşkent A.Ş.",
        contract_amount="11200000.00",
    )
    user = await user_factory(email="p4@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    item = (await list_projects_overview(seeded_db, user, None, None)).items[0]

    assert item.investment is None
    assert item.land_share is None
    assert item.contract_amount == Decimal("11200000.00")
    assert item.contracting.spent.available is False
    assert item.contracting.spent.pending_module == "progress_payments"
    assert item.contracting.worker_count.pending_module == "timesheet"
    assert item.contracting.subcontractor_count.pending_module == "subcontracts"


async def test_land_share_item_is_real_where_data_exists(seeded_db, user_factory, project_factory):
    project = await project_factory("KK-1", project_type="kat_karsiligi")
    seeded_db.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    for name in ("A. Yılmaz", "B. Yılmaz", "C. Yılmaz"):
        seeded_db.add(
            LandShareShareholder(project_id=project.id, name=name, share_pct=Decimal("33.33"))
        )
    await seeded_db.flush()
    user = await user_factory(email="p5@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    item = (await list_projects_overview(seeded_db, user, None, None)).items[0]

    assert item.contracting is None
    assert item.land_share.landowner_name == "Yılmaz Ailesi"
    assert item.land_share.our_share_pct == Decimal("55.00")
    assert item.land_share.land_cost == Decimal("0")
    assert item.land_share.shareholder_count == 3
    assert item.land_share.construction_cost.pending_module == "project_costs"
    assert item.land_share.our_unit_count.pending_module == "units"


async def test_detail_outside_visible_set_raises_not_found(
    seeded_db, user_factory, project_factory
):
    hidden = await project_factory("T-1")
    user = await user_factory(email="p6@t.co", password="parola1234", role_key="patron")

    with pytest.raises(NotFoundError):
        await get_project_detail(seeded_db, user, hidden.id)
