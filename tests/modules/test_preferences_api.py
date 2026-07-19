async def _login(client, user_factory, email: str, role_key: str = "patron") -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    return resp.json()["access_token"]


async def test_get_preferences_defaults_when_no_row(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "a@t.co")
    resp = await client.get("/settings/preferences", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["locale"] == "tr"
    assert body["currency"] == "TRY"
    assert body["theme"] == "light"


async def test_update_preferences_upsert(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "b@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"locale": "en", "currency": "USD", "density": "compact"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    again = await client.get("/settings/preferences", headers={"Authorization": f"Bearer {token}"})
    assert again.json()["locale"] == "en"
    assert again.json()["currency"] == "USD"
    assert again.json()["density"] == "compact"


async def test_update_preferences_dark_theme_rejected(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "c@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"theme": "dark"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_update_preferences_invalid_currency(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "d@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"currency": "GBP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_preferences_are_per_user(client, user_factory, seeded_db):
    token_a = await _login(client, user_factory, "u1@t.co")
    token_b = await _login(client, user_factory, "u2@t.co")
    await client.put(
        "/settings/preferences",
        json={"locale": "en"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get(
        "/settings/preferences", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert resp_b.json()["locale"] == "tr"  # B kullanicisi etkilenmedi
