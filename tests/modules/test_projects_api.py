import uuid

from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.users.models import UserProjectAccess


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_list_projects_unauthenticated(client):
    resp = await client.get("/projects")
    assert resp.status_code == 401


async def test_list_projects_forbidden_for_procurement(client, user_factory):
    """seed: projects satirinda procurement = none."""
    token = await _login(client, user_factory, "procurement")
    resp = await client.get("/projects", headers=_auth(token))
    assert resp.status_code == 403


async def test_system_admin_without_access_rows_sees_all(client, user_factory, project_factory):
    """KRITIK GECIS REGRESYONU (spec §5.4): Ayarlar'daki kullanici-proje erisim
    ekrani bu ucu tuketir; erisim satiri olmayan system_admin tum projeleri gormeli."""
    await project_factory("GK-A", name="Güneşkent A-Blok")
    await project_factory("OSB-1", name="Çelik OSB Fabrika")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get("/projects", headers=_auth(token))

    assert resp.status_code == 200
    assert [p["code"] for p in resp.json()["items"]] == ["GK-A", "OSB-1"]
    assert "password_hash" not in resp.text


async def test_patron_now_allowed_and_scoped(client, db_session, user_factory, project_factory):
    """Eski test patron'a 403 bekliyordu (user_management kapisi); artik projects=full."""
    granted = await project_factory("GK-A")
    await project_factory("OSB-1")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "patron@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/projects", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert [p["code"] for p in body["items"]] == ["GK-A"]
    assert body["counts"]["all"] == 1


async def test_list_filters_and_counts(client, user_factory, project_factory):
    await project_factory("T-1", project_type="taahhut", status="active")
    await project_factory("KY-1", project_type="kendi_yatirim", status="completed")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get("/projects?type=taahhut", headers=_auth(token))

    body = resp.json()
    assert [p["code"] for p in body["items"]] == ["T-1"]
    assert body["counts"] == {
        "all": 2,
        "taahhut": 1,
        "kendi_yatirim": 1,
        "kat_karsiligi": 0,
        "completed": 1,
    }


async def test_get_project_not_found(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.get(f"/projects/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_create_forbidden_for_view_level(client, user_factory):
    """site_chief projects=view tasir; POST full ister."""
    token = await _login(client, user_factory, "site_chief")
    resp = await client.post(
        "/projects",
        json={"code": "X-1", "name": "X", "project_type": "taahhut"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_create_kat_karsiligi_and_audit(client, db_session, user_factory):
    token = await _login(client, user_factory, "patron")

    resp = await client.post(
        "/projects",
        json={
            "code": "KK-1",
            "name": "Bahçelievler Konut",
            "project_type": "kat_karsiligi",
            "category": "Konut",
            "city": "Ankara",
            "land_share": {
                "landowner_name": "Yılmaz Ailesi",
                "our_share_pct": "55.00",
                "owner_share_pct": "45.00",
                "shareholders": [
                    {"name": "A. Yılmaz", "share_pct": "60.00"},
                    {"name": "B. Yılmaz", "share_pct": "40.00"},
                ],
            },
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["project_type"] == "kat_karsiligi"
    assert body["land_share"]["landowner_name"] == "Yılmaz Ailesi"
    assert body["land_share"]["land_cost"] == "0"
    assert body["land_share"]["shareholder_count"] == 2
    assert body["land_share"]["our_unit_count"]["pending_module"] == "units"
    assert body["contracting"] is None
    assert body["investment"] is None

    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.create)))
        .scalars()
        .all()
    )
    assert any("Bahçelievler Konut" in row.detail for row in audit_rows)


async def test_create_type_mismatch_returns_422(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/projects",
        json={
            "code": "T-9",
            "name": "Yanlış",
            "project_type": "taahhut",
            "investment": {"sales_target": "1.00"},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_create_duplicate_code_returns_409(client, user_factory, project_factory):
    await project_factory("GK-A")
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/projects",
        json={"code": "GK-A", "name": "Kopya", "project_type": "taahhut"},
        headers=_auth(token),
    )
    assert resp.status_code == 409


async def test_patch_updates_and_audits(client, db_session, user_factory, project_factory):
    project = await project_factory("T-1", name="Eski Ad")
    token = await _login(client, user_factory, "project_manager")

    resp = await client.patch(
        f"/projects/{project.id}", json={"name": "Yeni Ad"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Yeni Ad"
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert any("Yeni Ad" in row.detail for row in audit_rows)


async def test_patch_ignores_project_type(client, user_factory, project_factory):
    """ProjectUpdate'te alan yok — gonderilirse sessizce yok sayilir (extra alan)."""
    project = await project_factory("T-2", project_type="taahhut")
    token = await _login(client, user_factory, "patron")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"project_type": "kendi_yatirim", "name": "Ad"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["project_type"] == "taahhut"
