import uuid

from sqlalchemy import select

from app.core.access import AccessLevel
from app.modules.audit.models import AuditAction, AuditLog
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.users.models import UserProjectAccess


async def _set_permission(session, role_key: str, module_key: str, level: AccessLevel) -> None:
    """Bir rolun modul iznini dogrudan ayarlar.

    Yetki kapisi testleri seed degerine BAGIMLI olmamali: matris degistiginde
    test sessizce anlamsizlasmasin diye ilgili hucre testte acikca kurulur.
    """
    role_id = (await session.execute(select(Role.id).where(Role.key == role_key))).scalar_one()
    module_id = (
        await session.execute(select(Module.id).where(Module.key == module_key))
    ).scalar_one()
    permission = (
        await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.module_id == module_id
            )
        )
    ).scalar_one()
    permission.access_level = level
    await session.flush()


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
    """site_chief projects=view tasir; POST admin ister."""
    token = await _login(client, user_factory, "site_chief")
    resp = await client.post(
        "/projects",
        json={"code": "X-1", "name": "X", "project_type": "taahhut"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_create_requires_admin_not_full(client, db_session, user_factory):
    """Kullanici karari 2026-07-28: proje olusturma ADMIN isidir.

    `full` yetmez. Bu, olusturana otomatik UserProjectAccess yazmadan da
    tutarli kalmasini saglar: admin gorunurluk suzgecini zaten atlar (P1 spec
    §5.2), dolayisiyla yarattigi projeyi gorebilir. `full` seviyesine izin
    verilseydi, kapsamli bir kullanici goremedigi bir proje yaratirdi.
    """
    # is_draft: taahhüt zorunluluklarına takılmadan izin kapısını test etmek için (B4).
    body = {"code": "ADM-1", "name": "Admin Testi", "project_type": "taahhut", "is_draft": True}

    await _set_permission(db_session, "patron", "projects", AccessLevel.full)
    full_token = await _login(client, user_factory, "patron")
    forbidden = await client.post("/projects", json=body, headers=_auth(full_token))
    assert forbidden.status_code == 403

    admin_token = await _login(client, user_factory, "system_admin")
    allowed = await client.post("/projects", json=body, headers=_auth(admin_token))
    assert allowed.status_code == 201
    assert allowed.json()["code"] == "ADM-1"


async def test_create_kat_karsiligi_and_audit(client, db_session, user_factory):
    token = await _login(client, user_factory, "system_admin")

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
    token = await _login(client, user_factory, "system_admin")
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
    token = await _login(client, user_factory, "system_admin")
    resp = await client.post(
        "/projects",
        json={"code": "GK-A", "name": "Kopya", "project_type": "taahhut", "is_draft": True},
        headers=_auth(token),
    )
    assert resp.status_code == 409


async def _login_with_all_access(client, db_session, user_factory, role_key: str) -> str:
    user = await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await db_session.flush()
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_patch_project_outside_access_is_404_and_changes_nothing(
    client, db_session, user_factory, project_factory
):
    """IDOR: GET 404 verirken PATCH gecirirse yetki suzgeci YARIM demektir.

    Yalnizca "GK-A" projesine erisimi olan bir patron, "OSB-1"i GET ile
    goremiyor; ayni kimlikle PATCH atarsa da goremiyor olmali. Aksi halde
    kullanici, listede hic gormedigi bir projenin adini/sozlesme bedelini
    yalnizca UUID'sini bilerek degistirebilir.
    """
    granted = await project_factory("GK-A")
    hidden = await project_factory("OSB-1", name="Dokunulmamis Ad")
    user = await user_factory(email="scoped-pm@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "scoped-pm@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    assert (await client.get(f"/projects/{hidden.id}", headers=_auth(token))).status_code == 404

    resp = await client.patch(
        f"/projects/{hidden.id}", json={"name": "ELE GEÇİRİLDİ"}, headers=_auth(token)
    )

    assert resp.status_code == 404
    await db_session.refresh(hidden)
    assert hidden.name == "Dokunulmamis Ad"
    # Erisimi olan proje etkilenmemeli — duzeltme fazla genis olmamali.
    allowed = await client.patch(
        f"/projects/{granted.id}", json={"name": "Yeni Ad"}, headers=_auth(token)
    )
    assert allowed.status_code == 200


async def test_patch_updates_and_audits(client, db_session, user_factory, project_factory):
    project = await project_factory("T-1", name="Eski Ad")
    token = await _login_with_all_access(client, db_session, user_factory, "project_manager")

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


async def test_patch_ignores_project_type(client, db_session, user_factory, project_factory):
    """ProjectUpdate'te alan yok — gonderilirse sessizce yok sayilir (extra alan)."""
    project = await project_factory("T-2", project_type="taahhut")
    token = await _login_with_all_access(client, db_session, user_factory, "patron")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"project_type": "kendi_yatirim", "name": "Ad"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["project_type"] == "taahhut"
