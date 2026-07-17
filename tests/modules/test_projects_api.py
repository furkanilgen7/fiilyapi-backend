async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_list_projects_as_system_admin(client, user_factory, project_factory):
    await project_factory("GK-A", name="Güneşkent A-Blok")
    token = await _login(client, user_factory, "system_admin")
    resp = await client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    codes = [p["code"] for p in resp.json()]
    assert "GK-A" in codes
    assert "password_hash" not in resp.text


async def test_list_projects_forbidden_for_non_admin(client, user_factory, project_factory):
    await project_factory("GK-A")
    token = await _login(client, user_factory, "patron")  # patron'da user_management=none
    resp = await client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_get_project_not_found(client, user_factory):
    import uuid

    token = await _login(client, user_factory, "system_admin")
    resp = await client.get(
        f"/projects/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


async def test_list_projects_unauthenticated(client):
    resp = await client.get("/projects")
    assert resp.status_code == 401
