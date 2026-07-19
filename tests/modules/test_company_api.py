async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_get_company_any_authenticated_user(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")  # settings=none ama okuma serbest
    resp = await client.get("/company", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_logo"] is False
    assert body["logo_url"] == "/company/logo"
    assert body["brand_color"] == "#2563eb"
    assert "logo_data" not in body


async def test_get_company_requires_auth(client, seeded_db):
    resp = await client.get("/company")
    assert resp.status_code == 401


async def test_update_company_as_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put(
        "/company",
        json={"name": "FIIL Yapi A.S.", "tax_number": "1234567890", "default_vat_rate": "10.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "FIIL Yapi A.S."
    # kalicilik: yeniden oku
    again = await client.get("/company", headers={"Authorization": f"Bearer {token}"})
    assert again.json()["tax_number"] == "1234567890"
    assert again.json()["default_vat_rate"] == "10.00"


async def test_update_company_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "accounting")  # settings=none
    resp = await client.put(
        "/company", json={"name": "X"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_update_company_invalid_brand_color(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put(
        "/company", json={"brand_color": "mavi"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 422


async def test_update_company_invalid_email(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put(
        "/company", json={"email": "gecersiz"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 422


async def test_update_company_vat_out_of_range(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put(
        "/company",
        json={"default_vat_rate": "150.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
