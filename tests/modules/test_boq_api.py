"""T4 — GET /sites/{site_id}/boq ucu + router kaydi (spec §4, §5.1, §5.4, §5.5)."""

import uuid
from decimal import Decimal

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.sites.models import Site
from app.modules.users.models import UserProjectAccess


async def _login(client, user_factory, role_key: str, email: str | None = None) -> str:
    address = email or f"{role_key}@boq-api.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


async def _login_with_access(client, session, user_factory, role_key: str, email: str) -> str:
    """system_admin disindaki roller icin gorunurluk user_project_access'ten gelir."""
    user = await user_factory(email=email, password="parola1234", role_key=role_key)
    session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await session.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _site(session, project, code: str = "A-BLOK", **kwargs) -> Site:
    site = Site(project_id=project.id, code=code, name=kwargs.pop("name", "A-Blok Şantiyesi"))
    for field, value in kwargs.items():
        setattr(site, field, value)
    session.add(site)
    await session.flush()
    return site


async def _group(session, site, name: str = "TOPRAK VE TEMEL İŞLERİ", **kwargs) -> BoqGroup:
    group = BoqGroup(site_id=site.id, name=name, **kwargs)
    session.add(group)
    await session.flush()
    return group


async def _item(session, site, group, code: str = "01.001", **kwargs) -> BoqItem:
    defaults = {
        "description": "Kazı (Makine ile)",
        "unit": "m³",
        "quantity": Decimal("1240.000"),
        "unit_price": Decimal("280.00"),
    }
    defaults.update(kwargs)
    item = BoqItem(site_id=site.id, group_id=group.id, code=code, **defaults)
    session.add(item)
    await session.flush()
    return item


async def test_get_boq_unauthenticated(client, db_session, project_factory):
    project = await project_factory("BOQ-API-1")
    site = await _site(db_session, project)

    resp = await client.get(f"/sites/{site.id}/boq")

    assert resp.status_code == 401


async def test_get_boq_role_without_boq_permission_forbidden(
    client, db_session, user_factory, project_factory
):
    """hr_manager: seed matrisinde boq=none (spec §4 karari sites satirini izler)."""
    project = await project_factory("BOQ-API-2")
    site = await _site(db_session, project)
    token = await _login_with_access(
        client, db_session, user_factory, "hr_manager", "hr@boq-api.co"
    )

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 403


async def test_get_boq_field_engineer_forbidden(client, db_session, user_factory, project_factory):
    """Kullanici karari kaniti (spec §4): saha muhendisi BOQ'yu goremez."""
    project = await project_factory("BOQ-API-3")
    site = await _site(db_session, project)
    token = await _login_with_access(
        client, db_session, user_factory, "field_engineer", "fe@boq-api.co"
    )

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 403


async def test_get_boq_site_chief_allowed(client, db_session, user_factory, project_factory):
    """Kullanici karari kaniti (spec §4): santiye sefi BOQ'yu gorur."""
    project = await project_factory("BOQ-API-4")
    site = await _site(db_session, project)
    token = await _login_with_access(
        client, db_session, user_factory, "site_chief", "sc@boq-api.co"
    )

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 200


async def test_get_boq_invisible_site_returns_404(
    client, db_session, user_factory, project_factory
):
    """P2 §5.2 deseni: proje gorunurluk suzgecinden gecmeyen santiye 404 doner, 403 degil."""
    project = await project_factory("BOQ-API-5")
    site = await _site(db_session, project)
    # user_project_access verilmedi -> proje/santiye kullaniciya gorunmez.
    token = await _login(client, user_factory, "site_chief", "sc2@boq-api.co")

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Şantiye bulunamadı"


async def test_get_boq_missing_site_returns_404(client, user_factory):
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{uuid.uuid4()}/boq", headers=_auth(token))

    assert resp.status_code == 404


async def test_get_boq_empty_site_returns_zero_grand_total(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-6")
    site = await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"] == []
    assert body["totals"]["grand_total"] == "0.00"


async def test_get_boq_happy_path_matches_spec_5_1_shape(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-7")
    site = await _site(db_session, project)
    group = await _group(db_session, site, name="TOPRAK VE TEMEL İŞLERİ", sort_order=1)
    await _item(
        db_session,
        site,
        group,
        code="01.001",
        description="Kazı (Makine ile)",
        unit="m³",
        quantity=Decimal("1240.000"),
        unit_price=Decimal("280.00"),
        sort_order=1,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()

    totals = body["totals"]
    assert totals["contract_total"] == {
        "available": False,
        "value": None,
        "pending_module": "contracts",
    }
    assert totals["realized_total"] == {
        "available": False,
        "value": None,
        "pending_module": "progress_payments",
    }
    assert totals["remaining_total"] == {
        "available": False,
        "value": None,
        "pending_module": "progress_payments",
    }
    assert totals["revision_total"] == {
        "available": False,
        "value": None,
        "pending_module": "contracts",
    }
    assert totals["grand_total"] == "347200.00"
    assert totals["grand_progress_pct"] == {
        "available": False,
        "value": None,
        "pending_module": "progress_payments",
    }

    assert len(body["groups"]) == 1
    group_body = body["groups"][0]
    assert group_body["name"] == "TOPRAK VE TEMEL İŞLERİ"
    assert group_body["sort_order"] == 1
    assert group_body["group_total"] == "347200.00"
    assert len(group_body["items"]) == 1

    item_body = group_body["items"][0]
    assert item_body["code"] == "01.001"
    assert item_body["description"] == "Kazı (Makine ile)"
    assert item_body["unit"] == "m³"
    assert item_body["quantity"] == "1240.000"
    assert item_body["unit_price"] == "280.00"
    assert item_body["amount"] == "347200.00"
    assert item_body["sort_order"] == 1
    assert item_body["progress_pct"] == {
        "available": False,
        "value": None,
        "pending_module": "progress_payments",
    }
