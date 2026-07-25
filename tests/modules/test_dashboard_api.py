from decimal import Decimal

from app.modules.dashboard.schemas import (
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)
from app.modules.users.models import UserProjectAccess


def test_metric_placeholder_defaults_to_unavailable():
    metric = MetricPlaceholder(pending_module="progress_payments")

    assert metric.available is False
    assert metric.value is None
    assert metric.pending_module == "progress_payments"


def test_pending_approvals_placeholder_has_zero_count():
    placeholder = PendingApprovalsPlaceholder(pending_module="approvals")

    assert placeholder.available is False
    assert placeholder.count == 0
    assert placeholder.items == []


def test_summary_serializes_decimal_project_fields():
    summary = DashboardSummaryResponse(
        role_name="Patron",
        active_project_count=1,
        projects=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "code": "GK-A",
                "name": "Güneşkent A-Blok",
                "status": "active",
                "budget": Decimal("1500000.00"),
                "progress_pct": Decimal("42.50"),
            }
        ],
        portfolio=MetricPlaceholder(pending_module="progress_payments"),
        receivables=MetricPlaceholder(pending_module="invoicing"),
        average_margin=MetricPlaceholder(pending_module="progress_payments"),
        pending_approvals=PendingApprovalsPlaceholder(pending_module="approvals"),
        risks=ListPlaceholder(pending_module="inventory"),
    )

    dumped = summary.model_dump(mode="json")

    assert dumped["projects"][0]["budget"] == "1500000.00"
    assert dumped["risks"]["available"] is False
    assert dumped["risks"]["items"] == []


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_summary_requires_authentication(client):
    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 401


async def test_summary_forbidden_without_dashboard_permission(client, user_factory):
    # seed_data.py:140 -> dashboard satirinda procurement = none
    token = await _login(client, user_factory, "procurement")
    resp = await client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_summary_returns_projects_for_permitted_role(
    client, db_session, user_factory, project_factory
):
    await project_factory("GK-A", name="Güneşkent A-Blok", status="active")
    await project_factory("OSB-1", name="Çelik OSB Fabrika", status="on_hold")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "patron@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert [p["code"] for p in body["projects"]] == ["GK-A", "OSB-1"]
    assert body["active_project_count"] == 1
    assert body["role_name"] == "Patron"
    assert body["portfolio"]["available"] is False
    assert body["pending_approvals"]["count"] == 0
    assert "password_hash" not in resp.text


async def test_summary_empty_state_is_not_an_error(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.get("/dashboard/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["projects"] == []
    assert resp.json()["active_project_count"] == 0
