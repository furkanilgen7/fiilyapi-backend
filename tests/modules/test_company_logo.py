_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # kucuk sahte PNG govdesi


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_upload_and_fetch_logo(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    up = await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up.status_code == 200
    assert up.json()["has_logo"] is True

    got = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/png")
    assert got.content == _PNG
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in got.headers["content-disposition"]


async def test_upload_logo_invalid_content_type(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.gif", _PNG, "image/gif")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_upload_logo_too_large(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    big = b"0" * (1_048_576 + 1)
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.png", big, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413


async def test_upload_logo_content_mismatch(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.post(
        "/company/logo",
        files={"file": ("fake.png", b"<svg>x</svg>", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_logo_filename_sanitized_in_header(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    up = await client.post(
        "/company/logo",
        files={"file": ('ev"il\r\n.png', _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up.status_code == 200

    got = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 200
    disposition = got.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert 'ev"il' not in disposition


async def test_get_logo_when_none(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")
    resp = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_upload_logo_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_delete_logo(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    deleted = await client.delete("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 204
    got = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 404
