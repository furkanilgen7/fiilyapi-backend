import uuid

from app.core.security import create_refresh_token
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.users.models import UserStatus


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

    assert wrong_password.status_code == unknown_email.status_code
    assert wrong_password.json() == unknown_email.json()


async def test_passive_user_cannot_log_in(client, seeded_db, user_factory):
    await user_factory(
        email="pasif@fiil.com", password="parola", role_key="patron", status="passive"
    )
    response = await client.post(
        "/auth/login", json={"email": "pasif@fiil.com", "password": "parola"}
    )
    assert response.status_code == 401


async def test_unknown_email_still_runs_password_verification(
    client, seeded_db, user_factory, monkeypatch
):
    """Zamanlama sizintisi korumasi: argon2 dogrulamasi hem bilinmeyen e-posta hem de
    bilinen-e-posta/yanlis-parola durumunda calismali — aksi halde suresi cok kisa olan
    yol (kullanici yok) saldirgana e-postanin var olup olmadigini sizdirir. Duvar saati
    zamanlamasi yerine `verify_password` cagrilarini sayiyoruz (flaky olmasin diye)."""
    await user_factory(email="var@fiil.com", password="dogru-parola", role_key="patron")

    calls: list[str] = []
    original_verify = auth_service.verify_password

    def spy_verify_password(plain: str, hashed: str) -> bool:
        calls.append(hashed)
        return original_verify(plain, hashed)

    monkeypatch.setattr(auth_service, "verify_password", spy_verify_password)

    await client.post("/auth/login", json={"email": "yok@fiil.com", "password": "herhangi"})
    assert len(calls) == 1, "Bilinmeyen e-posta icin argon2 dogrulamasi calismadi"

    await client.post("/auth/login", json={"email": "var@fiil.com", "password": "yanlis"})
    assert len(calls) == 2, "Bilinen e-posta/yanlis parola icin argon2 dogrulamasi calismadi"


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


async def test_refresh_for_passive_user_is_rejected(client, seeded_db, user_factory):
    """Pasife alinan bir kullanicinin eski refresh token'i yeni access token basmamali."""
    user = await user_factory(email="pasif-refresh@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "pasif-refresh@fiil.com", "password": "parola"}
    )
    refresh_token = login.json()["refresh_token"]

    user.status = UserStatus.passive
    await seeded_db.flush()

    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

    assert response.status_code == 401


async def test_refresh_for_nonexistent_user_is_rejected(client, seeded_db):
    """Silinmis/hic var olmamis bir kullanici icin gecerli imzali refresh token bile
    yeni token basmamali."""
    fake_refresh_token = create_refresh_token(uuid.uuid4(), 0)

    response = await client.post("/auth/refresh", json={"refresh_token": fake_refresh_token})

    assert response.status_code == 401


async def test_login_stamps_last_login_at(client, seeded_db, user_factory):
    user = await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    assert user.last_login_at is None

    await client.post("/auth/login", json={"email": "patron@fiil.com", "password": "parola"})

    await seeded_db.refresh(user)
    assert user.last_login_at is not None


async def test_me_status_wire_format_is_plain_string(client, seeded_db, user_factory):
    """MeResponse.status daha sıkı tiplense de kablo formatı (frontend'in beklediği)
    düz "active" string'i olmaya devam etmeli, "UserStatus.active" gibi bir şey değil."""
    await user_factory(email="patron2@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron2@fiil.com", "password": "parola"}
    )
    token = login.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.json()["status"] == "active"


def test_me_response_status_schema_references_user_status_enum() -> None:
    schema = app.openapi()
    status_property = schema["components"]["schemas"]["MeResponse"]["properties"]["status"]

    ref_target = status_property.get("$ref") or status_property.get("allOf", [{}])[0].get("$ref")
    assert ref_target is not None
    assert ref_target.endswith("UserStatus")

    enum_schema = schema["components"]["schemas"]["UserStatus"]
    assert set(enum_schema["enum"]) == {"active", "on_leave", "passive"}


async def test_logout_revokes_existing_tokens(client, user_factory) -> None:
    await user_factory(email="logout@fiil.com", password="parola1234", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "logout@fiil.com", "password": "parola1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/auth/me", headers=headers)).status_code == 200
    assert (await client.post("/auth/logout", headers=headers)).status_code == 204
    # logout token_version'ı artırdı — o token'la basılan her şey artık geçersiz.
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


# --- BE-A — /auth/me izin haritasi (frontend `useModulePermission` icin) ---


async def _me(client, user_factory, role_key: str, email: str) -> dict:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    login = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    token = login.json()["access_token"]
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    return resp.json()


async def test_me_returns_permission_map_keyed_by_module(client, seeded_db, user_factory):
    """Frontend `readLevel` yuku: me.permissions[moduleKey] -> AccessLevel dizesi."""
    body = await _me(client, user_factory, "system_admin", "sa@me-perms.co")

    permissions = body["permissions"]
    assert isinstance(permissions, dict)
    assert permissions["boq"] == "admin"
    assert permissions["user_management"] == "admin"


async def test_me_permission_map_covers_every_seeded_module(client, seeded_db, user_factory):
    from sqlalchemy import select

    from app.modules.roles.models import Module

    body = await _me(client, user_factory, "system_admin", "sa2@me-perms.co")

    module_keys = {m.key for m in (await seeded_db.execute(select(Module))).scalars().all()}
    assert set(body["permissions"]) == module_keys


async def test_me_permission_map_is_role_specific(client, seeded_db, user_factory):
    """Salt-okunur rol kendi seviyesini gorur — ek yetki (user_management:view) GEREKMEZ."""
    body = await _me(client, user_factory, "site_chief", "sc@me-perms.co")

    assert body["permissions"]["boq"] == "view"
    # Kanit: bu rol /roles/{id}/permissions'i cagiramaz ama kendi haritasini aldi.
    assert body["permissions"]["user_management"] == "none"


async def test_readonly_role_cannot_read_role_matrix_endpoint(client, seeded_db, user_factory):
    """BE-A'nin gerekcesi: mevcut matris ucu salt-okunur role kapali."""
    await user_factory(email="sc2@me-perms.co", password="parola1234", role_key="site_chief")
    login = await client.post(
        "/auth/login", json={"email": "sc2@me-perms.co", "password": "parola1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/roles", headers=headers)).status_code == 403


async def test_me_keeps_existing_fields(client, seeded_db, user_factory):
    """Alan EKLENIR; hicbir mevcut alan kaldirilmaz/yeniden adlandirilmaz."""
    body = await _me(client, user_factory, "patron", "patron@me-perms.co")

    assert set(body) >= {"id", "email", "full_name", "title", "role_key", "status"}
    assert body["email"] == "patron@me-perms.co"
    assert body["role_key"] == "patron"


def test_me_response_permissions_schema_references_access_level_enum() -> None:
    """Frontend `AccessLevel` tipi schema'dan uretilir — deger AccessLevel enum'una

    referans vermeli, duz `string` olmamali (yoksa `gen:api` tipi genisletir).
    """
    schema = app.openapi()
    prop = schema["components"]["schemas"]["MeResponse"]["properties"]["permissions"]

    values = prop["additionalProperties"]
    ref_target = values.get("$ref") or values.get("allOf", [{}])[0].get("$ref")
    assert ref_target is not None
    assert ref_target.endswith("AccessLevel")
