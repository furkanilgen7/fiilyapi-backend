async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_set_all_projects_access(client, user_factory, project_factory):
    token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="u@t.co", password="parola1234", role_key="patron")
    resp = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": True, "project_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["all_projects"] is True


async def test_set_specific_projects_then_replace(client, user_factory, project_factory):
    token = await _login(client, user_factory, "system_admin")
    p1 = await project_factory("GK-A")
    p2 = await project_factory("MERKEZ-1")
    target = await user_factory(email="s@t.co", password="parola1234", role_key="site_chief")

    r1 = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": False, "project_ids": [str(p1.id), str(p2.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    assert set(r1.json()["project_ids"]) == {str(p1.id), str(p2.id)}

    # replace: yalnizca p1 kalmali
    r2 = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": False, "project_ids": [str(p1.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.json()["project_ids"] == [str(p1.id)]


async def test_project_access_forbidden_for_non_admin(client, user_factory):
    token = await _login(client, user_factory, "accounting")
    target = await user_factory(email="t@t.co", password="parola1234", role_key="site_chief")
    resp = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": True, "project_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
