"""Task 8 — santiye/bolum yetki ve gorunurluk negatif testleri (spec §7).

Iki AYRI koruma katmani sinanir ve karistirilmamalidir:

1. IZIN KAPISI (`require_permission("sites", ...)`) -> 403.
   Rol o modulde hicbir seviyeye sahip degilse ya da yazma icin gereken
   seviyeyi tasimiyorsa istek daha servise ulasmadan reddedilir.

2. PROJE GORUNURLUGU (`visible_projects`, spec §5.2) -> 404, 403 DEGIL.
   Kullanicinin izni vardir ama proje onun erisim kumesinde degildir; bu
   durumda kaydin VARLIGI bile sizdirilmaz.

En kritik acik `PATCH /sections/{id}`: bolum kimligi santiye ve proje
kimliginden bagimsiz gorundugu icin, gorunurluk suzgeci yukari dogru
cozulmezse baska bir projenin bolumu sessizce duzenlenebilir.
"""

import uuid

from app.modules.sites.models import Section, Site
from app.modules.users.models import UserProjectAccess

# procurement seed matrisinde sites = none tasir. Spec §5.1'deki "Taseron"
# satirinin sistemdeki karsiligi yoktur (roller: 8 sabit rol); _N profilini
# tasiyan tek rol procurement oldugu icin "hicbir uca erisemez" iddiasi bu rol
# uzerinden dogrulanir.
NO_ACCESS_ROLE = "procurement"
# site_chief sites = view/limited: gorur, yazamaz.
VIEW_ONLY_ROLE = "site_chief"
# patron sites = full: yazar, ama gorunurlugu user_project_access'e baglidir.
WRITE_ROLE = "patron"


async def _login(client, user_factory, role_key: str, *, grant_all: bool, session=None) -> str:
    address = f"{role_key}@t.co"
    user = await user_factory(email=address, password="parola1234", role_key=role_key)
    if grant_all:
        session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
        await session.flush()
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _fixture_tree(session, project_factory) -> tuple[Site, Section]:
    project = await project_factory(f"HID-{uuid.uuid4().hex[:6]}")
    site = Site(project_id=project.id, code="A-BLOK", name="A-Blok Şantiyesi")
    session.add(site)
    await session.flush()
    section = Section(site_id=site.id, name="Kat 6-10")
    session.add(section)
    await session.flush()
    return site, section


def _all_endpoints(site: Site, section: Section) -> list[tuple[str, str, dict | None]]:
    return [
        ("get", f"/projects/{site.project_id}/sites", None),
        ("post", f"/projects/{site.project_id}/sites", {"name": "Sızıntı"}),
        ("get", f"/sites/{site.id}", None),
        ("patch", f"/sites/{site.id}", {"name": "Sızıntı"}),
        ("get", f"/sites/{site.id}/sections", None),
        ("post", f"/sites/{site.id}/sections", {"name": "Sızıntı"}),
        ("patch", f"/sections/{section.id}", {"name": "Sızıntı"}),
    ]


def _write_endpoints(site: Site, section: Section) -> list[tuple[str, str, dict]]:
    return [item for item in _all_endpoints(site, section) if item[0] in ("post", "patch")]


async def _call(client, method: str, url: str, payload: dict | None, token: str):
    kwargs = {"headers": _auth(token)}
    if payload is not None:
        kwargs["json"] = payload
    return await getattr(client, method)(url, **kwargs)


# --- 1. Izin kapisi -> 403 ---


async def test_role_without_sites_permission_is_forbidden_everywhere(
    client, db_session, user_factory, project_factory
):
    site, section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, NO_ACCESS_ROLE, grant_all=True, session=db_session)

    for method, url, payload in _all_endpoints(site, section):
        resp = await _call(client, method, url, payload, token)
        assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}"


async def test_view_level_cannot_write(client, db_session, user_factory, project_factory):
    """sites:view var ama sites:full yok -> POST/PATCH 403 (spec §7)."""
    site, section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, VIEW_ONLY_ROLE, grant_all=True, session=db_session)

    for method, url, payload in _write_endpoints(site, section):
        resp = await _call(client, method, url, payload, token)
        assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}"


async def test_view_level_can_still_read(client, db_session, user_factory, project_factory):
    """403 kapisi fazla genis olmamali: gorme yetkisi calismaya devam etmeli."""
    site, _section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, VIEW_ONLY_ROLE, grant_all=True, session=db_session)

    assert (await client.get(f"/sites/{site.id}", headers=_auth(token))).status_code == 200
    assert (await client.get(f"/sites/{site.id}/sections", headers=_auth(token))).status_code == 200


async def test_unauthenticated_is_401_not_403(client, db_session, project_factory):
    site, section = await _fixture_tree(db_session, project_factory)

    for method, url, payload in _all_endpoints(site, section):
        kwargs = {"json": payload} if payload is not None else {}
        resp = await getattr(client, method)(url, **kwargs)
        assert resp.status_code == 401, f"{method.upper()} {url} -> {resp.status_code}"


# --- 2. Proje gorunurlugu -> 404 (403 DEGIL) ---


async def test_read_endpoints_hide_invisible_project(
    client, db_session, user_factory, project_factory
):
    """Izin var, proje erisimi yok -> 404: varligin kendisi sizdirilmaz."""
    site, _section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, VIEW_ONLY_ROLE, grant_all=False)

    for url in (
        f"/projects/{site.project_id}/sites",
        f"/sites/{site.id}",
        f"/sites/{site.id}/sections",
    ):
        resp = await client.get(url, headers=_auth(token))
        assert resp.status_code == 404, f"GET {url} -> {resp.status_code}"


async def test_write_endpoints_hide_invisible_project(
    client, db_session, user_factory, project_factory
):
    site, section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, WRITE_ROLE, grant_all=False)

    for method, url, payload in _write_endpoints(site, section):
        resp = await _call(client, method, url, payload, token)
        assert resp.status_code == 404, f"{method.upper()} {url} -> {resp.status_code}"


async def test_patch_section_of_invisible_site_is_404_and_changes_nothing(
    client, db_session, user_factory, project_factory
):
    """EN KRITIK ACIK (spec §7): bolum kimligi uzerinden dolayli erisim.

    Bolum id'si proje/santiye kimliginden bagimsiz gorunur; gorunurluk yukari
    dogru cozulmezse baska projenin bolumu sessizce degistirilebilir. 404
    donmesi yetmez — kaydin GERCEKTEN degismedigi de dogrulanir.
    """
    _site, section = await _fixture_tree(db_session, project_factory)
    token = await _login(client, user_factory, WRITE_ROLE, grant_all=False)

    resp = await client.patch(
        f"/sections/{section.id}",
        json={"name": "Sızdı", "status": "completed"},
        headers=_auth(token),
    )

    assert resp.status_code == 404
    await db_session.refresh(section)
    assert section.name == "Kat 6-10"
    assert section.status.value == "planned"


async def test_partial_access_does_not_leak_other_projects(
    client, db_session, user_factory, project_factory
):
    """Bir projeye erisimi olan kullanici DIGER projenin santiyesini gormemeli."""
    granted = await project_factory("VIS-1")
    hidden_site, hidden_section = await _fixture_tree(db_session, project_factory)
    visible_site = Site(project_id=granted.id, code="V-BLOK", name="Görünür Şantiye")
    db_session.add(visible_site)
    user = await user_factory(email="scoped@t.co", password="parola1234", role_key=WRITE_ROLE)
    db_session.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "scoped@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    allowed = await client.get(f"/sites/{visible_site.id}", headers=_auth(token))
    assert allowed.status_code == 200

    for method, url, payload in _all_endpoints(hidden_site, hidden_section):
        resp = await _call(client, method, url, payload, token)
        assert resp.status_code == 404, f"{method.upper()} {url} -> {resp.status_code}"


async def test_unknown_ids_are_404_for_authorized_user(
    client, db_session, user_factory, project_factory
):
    """Var olmayan kayit ile gorunmeyen kayit AYNI yaniti vermeli — aksi halde
    404/403 farkindan kayit varligi cikarilabilir."""
    token = await _login(client, user_factory, WRITE_ROLE, grant_all=True, session=db_session)
    unknown = uuid.uuid4()

    assert (await client.get(f"/projects/{unknown}/sites", headers=_auth(token))).status_code == 404
    assert (await client.get(f"/sites/{unknown}", headers=_auth(token))).status_code == 404
    assert (await client.get(f"/sites/{unknown}/sections", headers=_auth(token))).status_code == 404
    assert (
        await client.patch(f"/sites/{unknown}", json={"name": "X"}, headers=_auth(token))
    ).status_code == 404
    assert (
        await client.patch(f"/sections/{unknown}", json={"name": "X"}, headers=_auth(token))
    ).status_code == 404
