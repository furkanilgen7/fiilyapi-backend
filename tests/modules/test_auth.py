async def test_login_returns_token_pair(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="dogru-parola", role_key="patron")

    response = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "dogru-parola"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_with_wrong_password_is_rejected(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="dogru-parola", role_key="patron")

    response = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "yanlis-parola"}
    )

    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client, seeded_db):
    response = await client.post(
        "/auth/login", json={"email": "yok@fiil.com", "password": "herhangi"}
    )
    assert response.status_code == 401


async def test_login_error_does_not_reveal_whether_email_exists(client, seeded_db, user_factory):
    """Kullanıcı sayımını engeller: iki hata da birebir aynı mesajı döndürmeli."""
    await user_factory(email="var@fiil.com", password="dogru-parola", role_key="patron")

    wrong_password = await client.post(
        "/auth/login", json={"email": "var@fiil.com", "password": "yanlis"}
    )
    unknown_email = await client.post(
        "/auth/login", json={"email": "yok@fiil.com", "password": "yanlis"}
    )

    assert wrong_password.json() == unknown_email.json()


async def test_passive_user_cannot_log_in(client, seeded_db, user_factory):
    await user_factory(
        email="pasif@fiil.com", password="parola", role_key="patron", status="passive"
    )
    response = await client.post(
        "/auth/login", json={"email": "pasif@fiil.com", "password": "parola"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )
    token = login.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "patron@fiil.com"
    assert response.json()["role_key"] == "patron"


async def test_me_without_token_is_rejected(client, seeded_db):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_with_garbage_token_is_rejected(client, seeded_db):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer cop-token"})
    assert response.status_code == 401


async def test_refresh_token_cannot_be_used_as_access_token(client, seeded_db, user_factory):
    """Token tipi karıştırılamaz."""
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )
    refresh = login.json()["refresh_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401


async def test_refresh_issues_new_access_token(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )

    response = await client.post(
        "/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_stamps_last_login_at(client, seeded_db, user_factory):
    user = await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    assert user.last_login_at is None

    await client.post("/auth/login", json={"email": "patron@fiil.com", "password": "parola"})

    await seeded_db.refresh(user)
    assert user.last_login_at is not None
