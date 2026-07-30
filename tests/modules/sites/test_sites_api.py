"""Task 7 — santiye/bolum uclari ve denetim gunlugu (spec §4, §7)."""

import uuid

from sqlalchemy import select

from app.core.timezone import today
from app.modules.audit.models import AuditAction, AuditLog
from app.modules.sites.models import Section, Site
from app.modules.users.models import UserProjectAccess


async def _login(client, user_factory, role_key: str, email: str | None = None) -> str:
    address = email or f"{role_key}@t.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


async def _login_with_access(client, session, user_factory, role_key: str) -> str:
    """system_admin disindaki roller icin gorunurluk user_project_access'ten gelir."""
    address = f"{role_key}@t.co"
    user = await user_factory(email=address, password="parola1234", role_key=role_key)
    session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await session.flush()
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
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


async def _audit_details(session, action: AuditAction) -> list[str]:
    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    )
    return [row.detail for row in rows]


async def test_list_sites_unauthenticated(client, project_factory):
    project = await project_factory("A-1")
    resp = await client.get(f"/projects/{project.id}/sites")
    assert resp.status_code == 401


async def test_list_sites_happy_path(client, db_session, user_factory, project_factory):
    project = await project_factory("A-2", city="Ankara")
    await _site(db_session, project, "A-BLOK", address="Kuyubaşı Mah.", site_manager_name="S. Ö.")
    await _site(db_session, project, "B-BLOK", name="B-Blok Şantiyesi")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/sites", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert [s["code"] for s in body["items"]] == ["A-BLOK", "B-BLOK"]
    # `draft` T4'te eklendi (§5.2) — mevcut sayaclar aynen KALDI.
    assert body["counts"] == {"all": 2, "active": 2, "on_hold": 0, "completed": 0, "draft": 0}
    assert body["items"][0]["city"] == "Ankara"
    assert body["items"][0]["city_inherited"] is True
    assert body["items"][0]["site_manager_name"] == "S. Ö."
    assert body["totals"]["average_margin"] == {
        "available": False,
        "value": None,
        "pending_module": "project_costs",
    }


async def test_list_sites_empty_project(client, user_factory, project_factory):
    project = await project_factory("A-3")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/sites", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["counts"]["all"] == 0


async def test_get_site_detail(client, db_session, user_factory, project_factory):
    project = await project_factory("A-4", name="Güneşkent", employer_name="GK A.Ş.")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, name="Kat 6-10", sort_order=1))
    await db_session.flush()
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{site.id}", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["name"] == "Güneşkent"
    assert body["project"]["employer_name"] == "GK A.Ş."
    assert body["section_count"] == 1
    assert body["section_status_counts"] == {"planned": 1, "active": 0, "completed": 0}
    assert body["sections"][0]["name"] == "Kat 6-10"
    assert body["contract_amount"]["pending_module"] == "contracts"
    assert "delay_risk" not in resp.text


async def test_get_site_missing_returns_404(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.get(f"/sites/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_list_sections(client, db_session, user_factory, project_factory):
    project = await project_factory("A-5")
    site = await _site(db_session, project)
    db_session.add(Section(site_id=site.id, name="İkinci", sort_order=2))
    db_session.add(Section(site_id=site.id, name="Birinci", sort_order=1))
    await db_session.flush()
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{site.id}/sections", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert [s["name"] for s in body["items"]] == ["Birinci", "İkinci"]
    assert body["counts"]["planned"] == 2
    assert body["items"][0]["boq_item_count"]["pending_module"] == "boq"


async def test_create_site_and_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("A-6")
    token = await _login_with_access(client, db_session, user_factory, "patron")

    resp = await client.post(
        f"/projects/{project.id}/sites",
        json={"name": "A-Blok Şantiyesi", "address": "Kuyubaşı Mah."},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    # Kod SNT-{YYYY}-{NNN} ureticisinden gelir (spec §3.2), addan TURETILMEZ.
    assert body["code"] == f"SNT-{today().year}-001"
    assert body["status"] == "active"
    assert body["section_count"] == 0
    assert body["sections"] == []
    details = await _audit_details(db_session, AuditAction.create)
    assert any("A-Blok Şantiyesi" in d for d in details)


async def test_create_site_duplicate_code_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("A-7")
    await _site(db_session, project, "A-BLOK")
    token = await _login_with_access(client, db_session, user_factory, "patron")

    resp = await client.post(
        f"/projects/{project.id}/sites",
        json={"name": "Kopya", "code": "A-BLOK"},
        headers=_auth(token),
    )

    assert resp.status_code == 409


async def test_patch_site_and_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("A-8")
    site = await _site(db_session, project, name="Eski Ad")
    token = await _login_with_access(client, db_session, user_factory, "project_manager")

    resp = await client.patch(
        f"/sites/{site.id}", json={"name": "Yeni Ad", "status": "on_hold"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Yeni Ad"
    assert resp.json()["status"] == "on_hold"
    assert any("Yeni Ad" in d for d in await _audit_details(db_session, AuditAction.update))


async def test_create_section_and_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("A-9")
    site = await _site(db_session, project)
    token = await _login_with_access(client, db_session, user_factory, "patron")

    resp = await client.post(
        f"/sites/{site.id}/sections",
        json={"name": "Kat 6-10 Kaba İnşaat", "sort_order": 2},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "planned"
    assert body["sort_order"] == 2
    assert body["budget"]["pending_module"] == "boq"
    details = await _audit_details(db_session, AuditAction.create)
    assert any("Kat 6-10 Kaba İnşaat" in d and "A-Blok Şantiyesi" in d for d in details)


async def test_patch_section_and_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("A-10")
    site = await _site(db_session, project)
    section = Section(site_id=site.id, name="Eski Bölüm")
    db_session.add(section)
    await db_session.flush()
    token = await _login_with_access(client, db_session, user_factory, "patron")

    resp = await client.patch(
        f"/sections/{section.id}",
        json={"name": "Yeni Bölüm", "status": "active"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Yeni Bölüm"
    assert resp.json()["status"] == "active"
    assert any("Yeni Bölüm" in d for d in await _audit_details(db_session, AuditAction.update))


async def test_patch_section_missing_returns_404(client, db_session, user_factory):
    token = await _login_with_access(client, db_session, user_factory, "patron")
    resp = await client.patch(f"/sections/{uuid.uuid4()}", json={"name": "X"}, headers=_auth(token))
    assert resp.status_code == 404


async def test_no_password_hash_leaks(client, db_session, user_factory, project_factory):
    project = await project_factory("A-11")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/sites", headers=_auth(token))

    assert "password_hash" not in resp.text
