"""B4/B5 — blok/unite okuma + blok yazma uclari (spec §7.1-§7.4, §4.5, §8).

Izin: yeni modul ACILMAZ, okuma `projects` · `view` (spec §8). Gorunmeyen kayit
**404** doner, 403 DEGIL — varligin kendisi sizdirilmaz. Testler durum koduyla
yetinmez, GOVDE MESAJINI de dogrular: FastAPI'nin "rota yok" 404'u ile alan
katmaninin "proje yok" 404'u ayni koddur, karistirilirsa kirmizi gorunmez.
"""

import uuid
from decimal import Decimal

from app.modules.sites.models import Site
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from app.modules.users.models import UserProjectAccess


async def _login(client, user_factory, role_key: str, email: str | None = None) -> str:
    address = email or f"{role_key}@t.co"
    await user_factory(email=address, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


async def _login_with_access(client, session, user_factory, role_key: str) -> str:
    """system_admin disindaki roller icin gorunurluk `user_project_access`'ten gelir."""
    address = f"{role_key}@t.co"
    user = await user_factory(email=address, password="parola1234", role_key=role_key)
    session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await session.flush()
    resp = await client.post("/auth/login", json={"email": address, "password": "parola1234"})
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _site(session, project, code: str = "SANTIYE-1", name: str = "Merkez") -> Site:
    site = Site(project_id=project.id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


async def _block(session, project, site, name: str = "A Blok", **kwargs) -> Block:
    block = Block(project_id=project.id, site_id=site.id, name=name, **kwargs)
    session.add(block)
    await session.flush()
    return block


async def _unit(session, project, block, unit_no: str = "1", **kwargs) -> Unit:
    defaults: dict = {"unit_kind": UnitKind.apartment}
    defaults.update(kwargs)
    unit = Unit(project_id=project.id, block_id=block.id, unit_no=unit_no, **defaults)
    session.add(unit)
    await session.flush()
    return unit


# --- GET /projects/{id}/blocks (spec §7.1) ---


async def test_get_blocks_requires_token(client, project_factory):
    project = await project_factory("A4-1")

    resp = await client.get(f"/projects/{project.id}/blocks")

    assert resp.status_code == 401


async def test_get_blocks_forbidden_without_projects_view(
    client, db_session, user_factory, project_factory
):
    """Satinalma rolunde `projects` izni yok (seed matrisi) — 403."""
    project = await project_factory("A4-2")
    token = await _login_with_access(client, db_session, user_factory, "procurement")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.status_code == 403


async def test_get_blocks_invisible_project_returns_404(client, user_factory, project_factory):
    """Erisim verilmemis proje: 403 DEGIL 404, ve govde alan mesajini tasir."""
    project = await project_factory("A4-3")
    token = await _login(client, user_factory, "patron")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_get_blocks_unknown_project_returns_same_404(client, user_factory):
    """Var olmayan proje ile gorunmeyen proje AYIRT EDILEMEZ."""
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{uuid.uuid4()}/blocks", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_get_blocks_returns_empty_block(client, db_session, user_factory, project_factory):
    project = await project_factory("A4-4")
    site = await _site(db_session, project, name="Kuzey")
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.status_code == 200
    blocks = resp.json()["blocks"]
    assert [b["name"] for b in blocks] == ["A Blok"]
    assert blocks[0]["site_name"] == "Kuzey"
    assert blocks[0]["counts"] == {"apartment": 0, "shop": 0, "total": 0}


# --- GET /projects/{id}/units (spec §7.4) ---


async def test_get_units_happy_path_matches_spec_envelope(
    client, db_session, user_factory, project_factory
):
    """Yanit zarfi spec §6.1 ile BIREBIR — alan alan dogrulanir."""
    project = await project_factory("A4-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    await _unit(
        db_session,
        project,
        block,
        "12",
        layout="3+1",
        gross_area_m2=Decimal("142.00"),
        net_area_m2=Decimal("120.00"),
        list_price=Decimal("1150000.00"),
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"totals", "blocks"}
    assert set(body["totals"]) == {
        "counts",
        "value_basis",
        "total_value",
        "average_value",
        "total_list_price",
        "total_appraisal_value",
        "total_gross_area_m2",
        "sides",
        "sold_units",
        "reserved_units",
        "available_units",
        "sales_revenue",
        "average_sale_price",
    }
    assert set(body["totals"]["sides"][0]) == {
        "side",
        "counts",
        "total_value",
        "average_value",
        "share_pct",
        "sold",
        "reserved",
        "listed",
    }
    assert set(body["blocks"][0]) == {"block", "units"}
    assert set(body["blocks"][0]["block"]) == {
        "id",
        "name",
        "site_id",
        "site_name",
        "sort_order",
        "counts",
    }
    unit = body["blocks"][0]["units"][0]
    assert set(unit) == {
        "id",
        "block_id",
        "block_name",
        "unit_no",
        "label",
        "unit_kind",
        "layout",
        "gross_area_m2",
        "net_area_m2",
        "list_price",
        "appraisal_value",
        "unit_price_per_m2",
        "owner_side",
        "is_landowner_share",
        "sort_order",
        "sales_status",
        "sale_price",
        "buyer_name",
        "shareholder",
        "unit_cost",
    }
    assert unit["label"] == "A Blok · 12"
    assert unit["unit_price_per_m2"] == "8098.59"
    assert unit["is_landowner_share"] is False
    assert body["totals"]["total_value"] == "1150000.00"


async def test_get_units_invisible_project_returns_404(client, user_factory, project_factory):
    project = await project_factory("A4-6")
    token = await _login(client, user_factory, "patron")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_get_units_filter_by_block_id(client, db_session, user_factory, project_factory):
    project = await project_factory("A4-7")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    await _unit(db_session, project, block_a, "1")
    await _unit(db_session, project, block_b, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units", params={"block_id": str(block_b.id)}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert [g["block"]["name"] for g in resp.json()["blocks"]] == ["B Blok"]


async def test_get_units_filter_by_site_id(client, db_session, user_factory, project_factory):
    project = await project_factory("A4-8")
    site_a = await _site(db_session, project, code="S-A", name="Kuzey")
    site_b = await _site(db_session, project, code="S-B", name="Guney")
    block_a = await _block(db_session, project, site_a, name="A Blok")
    block_b = await _block(db_session, project, site_b, name="B Blok")
    await _unit(db_session, project, block_a, "1")
    await _unit(db_session, project, block_b, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units", params={"site_id": str(site_a.id)}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert [g["block"]["name"] for g in resp.json()["blocks"]] == ["A Blok"]


async def test_get_units_filter_by_kind(client, db_session, user_factory, project_factory):
    project = await project_factory("A4-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1", unit_kind=UnitKind.apartment)
    await _unit(db_session, project, block, "D1", unit_kind=UnitKind.shop)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units", params={"kind": "shop"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert [u["unit_no"] for u in resp.json()["blocks"][0]["units"]] == ["D1"]


async def test_get_units_filter_owner_side_unassigned(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("A4-10", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1", owner_side=UnitOwnerSide.landowner)
    await _unit(db_session, project, block, "2", owner_side=None)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units",
        params={"owner_side": "unassigned"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert [u["unit_no"] for u in resp.json()["blocks"][0]["units"]] == ["2"]


async def test_get_units_totals_unaffected_by_filters(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("A4-11", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    await _unit(db_session, project, block_a, "1", list_price=Decimal("100.00"))
    await _unit(db_session, project, block_b, "1", list_price=Decimal("300.00"))
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units", params={"block_id": str(block_a.id)}, headers=_auth(token)
    )

    body = resp.json()
    assert [g["block"]["name"] for g in body["blocks"]] == ["A Blok"]
    assert body["totals"]["counts"]["total"] == 2
    assert body["totals"]["total_value"] == "400.00"


async def test_get_units_value_basis_by_project_type(
    client, db_session, user_factory, project_factory
):
    investment = await project_factory("A4-12A", project_type="kendi_yatirim")
    land_share = await project_factory("A4-12B", project_type="kat_karsiligi")
    token = await _login(client, user_factory, "system_admin")

    investment_resp = await client.get(f"/projects/{investment.id}/units", headers=_auth(token))
    land_share_resp = await client.get(f"/projects/{land_share.id}/units", headers=_auth(token))

    assert investment_resp.json()["totals"]["value_basis"] == "list_price"
    assert land_share_resp.json()["totals"]["value_basis"] == "appraisal_value"


async def test_get_units_invalid_enum_returns_422(client, user_factory, project_factory):
    project = await project_factory("A4-13")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(
        f"/projects/{project.id}/units", params={"kind": "villa"}, headers=_auth(token)
    )

    assert resp.status_code == 422


async def test_admin_role_bypasses_visibility(client, db_session, user_factory, project_factory):
    """P1 kilitlenme korumasi: `projects=admin` suzgeci atlar (erisim atamak icin
    tum projeleri gormek gerekir)."""
    project = await project_factory("A4-14")
    site = await _site(db_session, project)
    await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    assert resp.status_code == 200
    assert len(resp.json()["blocks"]) == 1


async def test_get_units_with_project_access_grant(
    client, db_session, user_factory, project_factory
):
    """Admin olmayan rol, `user_project_access` ile gorunurluk kazanir."""
    project = await project_factory("A4-15")
    site = await _site(db_session, project)
    await _block(db_session, project, site)
    token = await _login_with_access(client, db_session, user_factory, "patron")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    assert resp.status_code == 200
    assert len(resp.json()["blocks"]) == 1


# --- B5: POST /projects/{id}/blocks (spec §7.2, §4.5) ---


async def test_create_block_auto_assigns_single_site(
    client, db_session, user_factory, project_factory
):
    """§4.5 satir 1: tek santiyeli projede `site_id` GONDERILMEDEN 201.

    Mockup'ta (KY 38 / KK 39) santiye secici YOKTUR — otomatik atama bu sadakati korur.
    """
    project = await project_factory("B5-1")
    site = await _site(db_session, project, name="Kuzey")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["site_id"] == str(site.id)
    assert body["site_name"] == "Kuzey"
    assert body["name"] == "A Blok"
    assert body["counts"] == {"apartment": 0, "shop": 0, "total": 0}


async def test_create_block_without_any_site_returns_422(client, user_factory, project_factory):
    """§4.5 satir 3: santiyesiz projede blok acilamaz."""
    project = await project_factory("B5-2")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Blok tanımlamadan önce projeye şantiye eklenmelidir"


async def test_create_block_multi_site_without_site_id_returns_422(
    client, db_session, user_factory, project_factory
):
    """§4.5 satir 4: >=2 santiyede otomatik atama YANLIS VERI uretirdi."""
    project = await project_factory("B5-3")
    await _site(db_session, project, code="S-A", name="Kuzey")
    await _site(db_session, project, code="S-B", name="Guney")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Birden fazla şantiye var, blok için şantiye seçilmelidir"


async def test_create_block_multi_site_with_site_id_returns_201(
    client, db_session, user_factory, project_factory
):
    """§4.5 satir 5: secim yapilmissa dogrulanir ve kabul edilir."""
    project = await project_factory("B5-4")
    await _site(db_session, project, code="S-A", name="Kuzey")
    site_b = await _site(db_session, project, code="S-B", name="Guney")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "B Blok", "site_id": str(site_b.id)},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["site_id"] == str(site_b.id)
    assert resp.json()["site_name"] == "Guney"


async def test_create_block_with_foreign_site_returns_404(
    client, db_session, user_factory, project_factory
):
    """§4.5 satir 2 (negatif): baska projenin santiyesi enjekte edilemez."""
    project = await project_factory("B5-5A")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("B5-5B")
    foreign_site = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "A Blok", "site_id": str(foreign_site.id)},
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Şantiye bulunamadı"


async def test_create_block_duplicate_name_returns_409(
    client, db_session, user_factory, project_factory
):
    """Blok adi PROJE icinde benzersizdir; 500 degil, Turkce 409 doner."""
    project = await project_factory("B5-6")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    payload = {"name": "A Blok"}

    first = await client.post(f"/projects/{project.id}/blocks", json=payload, headers=_auth(token))
    second = await client.post(f"/projects/{project.id}/blocks", json=payload, headers=_auth(token))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "Bu blok adı bu projede zaten kullanılıyor"


async def test_create_block_same_name_other_project_returns_201(
    client, db_session, user_factory, project_factory
):
    """Benzersizlik PROJE kapsamlidir — baska projede ayni ad serbesttir."""
    first_project = await project_factory("B5-7A")
    await _site(db_session, first_project, code="S-1")
    second_project = await project_factory("B5-7B")
    await _site(db_session, second_project, code="S-2")
    token = await _login(client, user_factory, "system_admin")
    payload = {"name": "A Blok"}

    first = await client.post(
        f"/projects/{first_project.id}/blocks", json=payload, headers=_auth(token)
    )
    second = await client.post(
        f"/projects/{second_project.id}/blocks", json=payload, headers=_auth(token)
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_create_block_requires_full_permission(
    client, db_session, user_factory, project_factory
):
    """Spec §8: yazma `projects` · `full` ister; `view` yetmez (IDOR-13)."""
    project = await project_factory("B5-8")
    await _site(db_session, project)
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 403


async def test_create_block_invisible_project_returns_404(client, user_factory, project_factory):
    """IDOR-3: gorunmeyen projeye yazma 404 doner, 403 DEGIL."""
    project = await project_factory("B5-9")
    token = await _login(client, user_factory, "patron")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


# --- B5: PATCH /blocks/{id} (spec §7.3) ---


async def test_patch_block_renames(client, db_session, user_factory, project_factory):
    project = await project_factory("B5-10")
    site = await _site(db_session, project, name="Kuzey")
    block = await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(f"/blocks/{block.id}", json={"name": "Zemin"}, headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["name"] == "Zemin"
    assert resp.json()["site_id"] == str(site.id)


async def test_patch_block_duplicate_name_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B5-11")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block_b.id}", json={"name": "A Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu blok adı bu projede zaten kullanılıyor"


async def test_patch_block_changes_site_within_project(
    client, db_session, user_factory, project_factory
):
    """§4.5: blok yanlis santiyeye acilmissa tasinabilir."""
    project = await project_factory("B5-12")
    site_a = await _site(db_session, project, code="S-A", name="Kuzey")
    site_b = await _site(db_session, project, code="S-B", name="Guney")
    block = await _block(db_session, project, site_a, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"site_id": str(site_b.id)}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["site_id"] == str(site_b.id)
    assert resp.json()["site_name"] == "Guney"


async def test_patch_block_foreign_site_returns_404(
    client, db_session, user_factory, project_factory
):
    """§4.5 son paragraf: yeni santiye ayni projede olmali, degilse 404."""
    project = await project_factory("B5-13A")
    site = await _site(db_session, project, code="S-OWN")
    block = await _block(db_session, project, site, name="A Blok")
    other = await project_factory("B5-13B")
    foreign_site = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"site_id": str(foreign_site.id)}, headers=_auth(token)
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Şantiye bulunamadı"


async def test_patch_block_invisible_returns_404(client, db_session, user_factory, project_factory):
    """IDOR-5: gorunmeyen projenin blogu 404 — mesaj BLOK icin ozeldir."""
    project = await project_factory("B5-14")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "patron")

    resp = await client.patch(f"/blocks/{block.id}", json={"name": "Zemin"}, headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"


async def test_patch_block_unknown_uuid_returns_404_same_message(client, user_factory):
    """IDOR-7: var olmayan blok ile gorunmeyen blok AYIRT EDILEMEZ."""
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{uuid.uuid4()}", json={"name": "Zemin"}, headers=_auth(token)
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"
