from sqlalchemy import select

from app.modules.roles.models import Role


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def _role_id(session, key: str):
    return str((await session.execute(select(Role).where(Role.key == key))).scalar_one().id)


async def test_create_and_list_user_as_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _role_id(seeded_db, "accounting")
    resp = await client.post(
        "/users",
        json={"email": "yeni@t.co", "password": "parola1234", "full_name": "Yeni Kullanıcı",
              "role_id": rid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "yeni@t.co"
    assert "password" not in body and "password_hash" not in body

    listing = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert listing.status_code == 200
    assert any(u["email"] == "yeni@t.co" for u in listing.json())


async def test_create_user_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")  # user_management=none
    rid = await _role_id(seeded_db, "accounting")
    resp = await client.post(
        "/users",
        json={"email": "z@t.co", "password": "parola1234", "full_name": "Z", "role_id": rid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_reset_password_admin_only(client, user_factory, seeded_db):
    admin_token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="t@t.co", password="parola1234", role_key="site_chief")
    resp = await client.patch(
        f"/users/{target.id}/password",
        json={"new_password": "yeniParola9"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


async def test_delete_user_admin_only(client, user_factory):
    admin_token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="d@t.co", password="parola1234", role_key="accounting")
    resp = await client.delete(
        f"/users/{target.id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 204
