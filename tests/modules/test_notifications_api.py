from app.modules.settings.constants import NOTIFICATION_EVENTS


async def _login(client, user_factory, email: str, role_key: str = "patron") -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    return resp.json()["access_token"]


async def test_get_notifications_returns_full_catalog(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n1@t.co")
    resp = await client.get("/settings/notifications", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(NOTIFICATION_EVENTS)
    assert {item["event_key"] for item in body} == {e["event_key"] for e in NOTIFICATION_EVENTS}
    assert all("label" in item for item in body)


async def test_update_notification_overrides_default(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n2@t.co")
    key = NOTIFICATION_EVENTS[0]["event_key"]
    resp = await client.put(
        "/settings/notifications",
        json={"items": [{"event_key": key, "email": False, "in_app": False, "sms": True}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    again = await client.get(
        "/settings/notifications", headers={"Authorization": f"Bearer {token}"}
    )
    row = next(i for i in again.json() if i["event_key"] == key)
    assert row["email"] is False and row["in_app"] is False and row["sms"] is True


async def test_update_notification_unknown_event_rejected(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n3@t.co")
    resp = await client.put(
        "/settings/notifications",
        json={
            "items": [{"event_key": "bilinmeyen_olay", "email": True, "in_app": True, "sms": False}]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_update_notification_duplicate_event_rejected(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n6@t.co")
    key = NOTIFICATION_EVENTS[0]["event_key"]
    resp = await client.put(
        "/settings/notifications",
        json={
            "items": [
                {"event_key": key, "email": True, "in_app": True, "sms": False},
                {"event_key": key, "email": False, "in_app": False, "sms": True},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_notifications_are_per_user(client, user_factory, seeded_db):
    token_a = await _login(client, user_factory, "n4@t.co")
    token_b = await _login(client, user_factory, "n5@t.co")
    key = NOTIFICATION_EVENTS[0]["event_key"]
    await client.put(
        "/settings/notifications",
        json={"items": [{"event_key": key, "email": True, "in_app": True, "sms": True}]},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get(
        "/settings/notifications", headers={"Authorization": f"Bearer {token_b}"}
    )
    row_b = next(i for i in resp_b.json() if i["event_key"] == key)
    default = next(e for e in NOTIFICATION_EVENTS if e["event_key"] == key)
    assert row_b["sms"] == default["sms"]  # B kullanicisi varsayilanda kaldi
