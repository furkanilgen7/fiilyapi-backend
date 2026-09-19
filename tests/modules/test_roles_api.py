import pytest
from sqlalchemy import select

from app.modules.roles.models import Role


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def _rid(session, key):
    return str((await session.execute(select(Role).where(Role.key == key))).scalar_one().id)


async def test_list_roles_and_modules(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    roles = await client.get("/roles", headers=h)
    assert roles.status_code == 200 and len(roles.json()) == 8
    modules = await client.get("/modules", headers=h)
    assert modules.status_code == 200 and len(modules.json()) == 22


async def test_update_permission_cell(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "site_chief")
    resp = await client.put(
        f"/roles/{rid}/permissions/dashboard",
        json={"access_level": "full", "scope": "all"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_level"] == "full"


async def test_update_system_admin_cell_locked(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "system_admin")
    resp = await client.put(
        f"/roles/{rid}/permissions/dashboard",
        json={"access_level": "view", "scope": "all"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_update_permission_unknown_module_404(client, user_factory, seeded_db):
    admin = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "patron")
    resp = await client.put(
        f"/roles/{rid}/permissions/olmayan_modul",
        json={"access_level": "view", "scope": "all"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 404


async def test_create_and_delete_custom_role(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/roles",
        json={"key": "saha_amiri", "name": "Saha Amiri", "emoji": "🚧", "description": ""},
        headers=h,
    )
    assert created.status_code == 201
    new_id = created.json()["id"]
    deleted = await client.delete(f"/roles/{new_id}", headers=h)
    assert deleted.status_code == 204


async def test_roles_forbidden_for_non_admin(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.get("/roles", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_DUSEN_kapsam_uctan_yazilamaz(client, user_factory, seeded_db):
    """Düşen kapsam (`own`) uçtan da yazılamaz; satır DEĞİŞMEDEN kalır.

    🔴 Docstring düzeltildi (2026-09-19 akşamı): eski hâli "arkasında kod yok,
    `permissions.py` içinde `scope` geçmez" diyordu — artık geçiyor. `own`
    reddedilir çünkü matristen DÜŞÜRÜLDÜ; uygulanan `limited`/`finance` ise
    aşağıdaki pozitif kontrolde 200 alır.
    """
    token = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "site_chief")

    resp = await client.put(
        f"/roles/{rid}/permissions/personnel",
        json={"access_level": "view", "scope": "own"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]

    hucreler = await client.get(
        f"/roles/{rid}/permissions", headers={"Authorization": f"Bearer {token}"}
    )
    personel = [c for c in hucreler.json() if c["module_key"] == "personnel"][0]
    assert personel["scope"] == "all"


@pytest.mark.parametrize("uygulanan", ["limited", "finance"])
async def test_UYGULANAN_kapsam_UCTAN_atanabilir(client, user_factory, seeded_db, uygulanan: str):
    """🔴 POZİTİF KONTROL — ekranın sunduğu "Sınırlı"/"Mali" düğmesi 200 almalı.

    `permission-presets.ts` bu iki preset'i HER hücrede sunuyor ve kendi kuralı
    "UI, backend'in reddedeceği bir düğme sunmamalı" diyor. Kapsam 2026-09-19'da
    gerçekten uygulandığı hâlde uç 403 döndürüyordu; ekran çalışmayan bir düğme
    gösteriyordu. Bu bekçi servis testinin AYNISI değildir: uçta `PermissionUpdate`
    şeması ve 403 eşlemesi de araya girer.
    """
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    rid = await _rid(seeded_db, "site_chief")

    resp = await client.put(
        f"/roles/{rid}/permissions/personnel",
        json={"access_level": "view", "scope": uygulanan},
        headers=h,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["scope"] == uygulanan
    hucreler = await client.get(f"/roles/{rid}/permissions", headers=h)
    personel = [c for c in hucreler.json() if c["module_key"] == "personnel"][0]
    assert personel["scope"] == uygulanan, "Yazma KALICI olmalı"


async def test_MASKELEYEN_kapsam_YAZAN_seviyeyle_UCTAN_reddedilir(client, user_factory, seeded_db):
    """Maskeli veri yazma yüzeyine düşemez (gerekçe `test_role_service.py`de).

    Ekranın dokuz preset'inin hiçbiri bu çifti üretmez; kapı, uca doğrudan
    gönderilen gövdeye karşıdır.
    """
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    rid = await _rid(seeded_db, "site_chief")

    resp = await client.put(
        f"/roles/{rid}/permissions/personnel",
        json={"access_level": "full", "scope": "finance"},
        headers=h,
    )

    assert resp.status_code == 403, resp.text
    hucreler = await client.get(f"/roles/{rid}/permissions", headers=h)
    personel = [c for c in hucreler.json() if c["module_key"] == "personnel"][0]
    assert (personel["access_level"], personel["scope"]) == ("view", "all")
