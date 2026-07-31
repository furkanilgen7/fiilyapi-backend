"""B4-B7 — blok/unite okuma + yazma + SILME uclari (spec §7.1-§7.6, §7.9, §3.3, §4.5, §8).

Izin: yeni modul ACILMAZ, okuma `projects` · `view` (spec §8). Gorunmeyen kayit
**404** doner, 403 DEGIL — varligin kendisi sizdirilmaz. Testler durum koduyla
yetinmez, GOVDE MESAJINI de dogrular: FastAPI'nin "rota yok" 404'u ile alan
katmaninin "proje yok" 404'u ayni koddur, karistirilirsa kirmizi gorunmez.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.access import AccessLevel
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.sites.models import Site
from app.modules.units.codes import effective_block_code
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide, UnitSalesStatus
from app.modules.users.models import UserProjectAccess


async def _set_permission(session, role_key: str, module_key: str, level: AccessLevel) -> None:
    """Bir rolun modul iznini dogrudan ayarlar (`test_projects_api` deseni).

    Yetki kapisi testleri seed degerine BAGIMLI olmamali: matris degistiginde
    test sessizce anlamsizlasmasin diye ilgili hucre testte acikca kurulur.
    """
    role_id = (await session.execute(select(Role.id).where(Role.key == role_key))).scalar_one()
    module_id = (
        await session.execute(select(Module.id).where(Module.key == module_key))
    ).scalar_one()
    permission = (
        await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.module_id == module_id
            )
        )
    ).scalar_one()
    permission.access_level = level
    await session.flush()


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


def _bos_sayac() -> dict[str, int]:
    """P3.1 §4.3: `UnitKindBreakdown` bes sayacli (UE 74). Karar 13: EKRAN
    etiketleri degismez, yalniz sayaclar eklenir."""
    return {"apartment": 0, "shop": 0, "office": 0, "warehouse": 0, "parking": 0, "total": 0}


async def _count_units_in_block(session, block_id: uuid.UUID) -> int:
    """B7 test 6'nin KANITIDIR: 409 sonrasi unite sayisinin DEGISMEDIGINI olcer.

    Durum kodunu dogrulamak yetmez — cascade yanlislikla acilsaydi 409 yine
    donebilir ama uniteler gitmis olurdu. Sayim tek gercek kanittir.
    """
    result = await session.execute(
        select(func.count()).select_from(Unit).where(Unit.block_id == block_id)
    )
    return int(result.scalar_one())


async def _block_exists(session, block_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(func.count()).select_from(Block).where(Block.id == block_id)
    )
    return int(result.scalar_one()) == 1


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
    # P3.1 §4.3: `UnitKindBreakdown` uc yeni sayac aldi (UE 74).
    assert blocks[0]["counts"] == _bos_sayac()


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
        # P3.1 §8.2: dort degerli satis durumu kirilimi.
        "by_sales_status",
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
    # P3.1 T5: blok formunun 13 alani + turev `estimated_unit_count` EKLENDI.
    assert set(body["blocks"][0]["block"]) == {
        "id",
        "name",
        "site_id",
        "site_name",
        "sort_order",
        "counts",
        "code",
        "basement_floor_count",
        "floor_count",
        "roof_type",
        "units_per_floor",
        "ground_floor_usage",
        "shop_count",
        "construction_area_m2",
        "elevator_count",
        "parking_type",
        "estimated_delivery_date",
        "status",
        "notes",
        "estimated_unit_count",
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
        "floor",
        "facing",
        "balcony_area_m2",
        "bathroom_count",
        "parking_right",
        "min_sale_price",
        "vat_rate",
        "sales_status",
        "sale_price",
        "buyer_name",
        "shareholder",
        "unit_cost",
        "expected_profit",
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
    assert body["counts"] == _bos_sayac()


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


# --- B6: POST /projects/{id}/units (spec §7.5, §3.3) ---


async def test_create_unit_happy_path_201(client, db_session, user_factory, project_factory):
    project = await project_factory("B6-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "12",
            "unit_kind": "apartment",
            "layout": "3+1",
            "gross_area_m2": "142.00",
            "net_area_m2": "120.00",
            "list_price": "1150000.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["unit_no"] == "12"
    assert body["block_name"] == "A Blok"
    assert body["label"] == "A Blok · 12"
    assert body["unit_price_per_m2"] == "8098.59"
    assert body["owner_side"] is None
    assert body["is_landowner_share"] is False


async def test_create_unit_duplicate_no_in_block_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B6-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")
    payload = {"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"}

    first = await client.post(f"/projects/{project.id}/units", json=payload, headers=_auth(token))
    second = await client.post(f"/projects/{project.id}/units", json=payload, headers=_auth(token))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "Bu ünite numarası bu blokta zaten kullanılıyor"


async def test_create_unit_same_no_other_block_returns_201(
    client, db_session, user_factory, project_factory
):
    """SY 76/106: A Blok "1" ile B Blok "1" AYNI ANDA vardir."""
    project = await project_factory("B6-3")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    token = await _login(client, user_factory, "system_admin")

    first = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block_a.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )
    second = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block_b.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_create_unit_foreign_block_returns_404(
    client, db_session, user_factory, project_factory
):
    """IDOR-9: govdedeki `block_id` baska projenin blogu olabilir."""
    project = await project_factory("B6-4A")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("B6-4B")
    other_site = await _site(db_session, other, code="S-FOREIGN")
    foreign_block = await _block(db_session, other, other_site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(foreign_block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"


async def test_create_unit_in_taahhut_project_returns_201(
    client, db_session, user_factory, project_factory
):
    """§3.3: `taahhut` projede unite tanimlamak SERBEST — kisit icat edilmedi."""
    project = await project_factory("B6-5", project_type="taahhut")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 201


async def test_create_unit_owner_side_in_kendi_yatirim_returns_422(
    client, db_session, user_factory, project_factory
):
    """§3.3: `owner_side` YALNIZ kat karsiligi projede dolu olabilir."""
    project = await project_factory("B6-6", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "owner_side": "landowner",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Ünite payı yalnızca kat karşılığı projelerde belirlenebilir"


async def test_create_unit_appraisal_value_in_kendi_yatirim_returns_201(
    client, db_session, user_factory, project_factory
):
    """§3.3/§4.4: iki fiyat sutunu da HER TIPTE kabul edilir — reddetmek mockup'ta
    olmayan bir kisit icat etmek olurdu."""
    project = await project_factory("B6-7", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "appraisal_value": "900000.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["appraisal_value"] == "900000.00"


async def test_create_unit_net_greater_than_gross_returns_422(
    client, db_session, user_factory, project_factory
):
    """DB CHECK'e (ck_units_net_le_gross) DUSMEDEN servis Turkce mesaj verir."""
    project = await project_factory("B6-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "gross_area_m2": "100.00",
            "net_area_m2": "120.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Net alan brüt alandan büyük olamaz"


async def test_create_unit_requires_full_permission(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B6-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 403


# --- B6: PATCH /units/{id} (spec §7.6) ---


async def test_patch_unit_partial_leaves_unsent_fields(
    client, db_session, user_factory, project_factory
):
    """ "Gonderilmedi" alani DEGISTIRMEZ (`model_fields_set` ayrimi)."""
    project = await project_factory("B6-10", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(
        db_session, project, block, "1", layout="3+1", list_price=Decimal("1000000.00")
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"list_price": "1200000.00"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["list_price"] == "1200000.00"
    assert resp.json()["layout"] == "3+1"


async def test_patch_unit_null_clears_layout(client, db_session, user_factory, project_factory):
    """ "null yapildi" ile "gonderilmedi" AYNI SEY DEGILDIR."""
    project = await project_factory("B6-11")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1", layout="3+1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(f"/units/{unit.id}", json={"layout": None}, headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["layout"] is None


async def test_patch_unit_net_gt_gross_returns_422(
    client, db_session, user_factory, project_factory
):
    """Mevcut brut ile GONDERILEN net karsilastirilir — kismi gonderim tuzagi."""
    project = await project_factory("B6-12")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1", gross_area_m2=Decimal("100.00"))
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"net_area_m2": "120.00"}, headers=_auth(token)
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Net alan brüt alandan büyük olamaz"


async def test_patch_unit_moves_to_other_block(client, db_session, user_factory, project_factory):
    """Unite yanlis bloga girilmisse tasinabilir (spec §7.6)."""
    project = await project_factory("B6-13")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    unit = await _unit(db_session, project, block_a, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"block_id": str(block_b.id)}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["block_id"] == str(block_b.id)
    assert resp.json()["block_name"] == "B Blok"
    assert resp.json()["label"] == "B Blok · 1"


async def test_patch_unit_move_with_unit_no_conflict_returns_409(
    client, db_session, user_factory, project_factory
):
    """Hedef blokta ayni `unit_no` varsa tasima reddedilir."""
    project = await project_factory("B6-14")
    site = await _site(db_session, project)
    block_a = await _block(db_session, project, site, name="A Blok")
    block_b = await _block(db_session, project, site, name="B Blok")
    unit = await _unit(db_session, project, block_a, "1")
    await _unit(db_session, project, block_b, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"block_id": str(block_b.id)}, headers=_auth(token)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu ünite numarası bu blokta zaten kullanılıyor"


async def test_patch_unit_move_to_foreign_block_returns_404(
    client, db_session, user_factory, project_factory
):
    """Hedef blok BASKA projede ise 404 — proje sinirini asan tasima yoktur."""
    project = await project_factory("B6-15A")
    site = await _site(db_session, project, code="S-OWN")
    block = await _block(db_session, project, site, name="A Blok")
    unit = await _unit(db_session, project, block, "1")
    other = await project_factory("B6-15B")
    other_site = await _site(db_session, other, code="S-FOREIGN")
    foreign_block = await _block(db_session, other, other_site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"block_id": str(foreign_block.id)}, headers=_auth(token)
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"


async def test_patch_unit_invisible_returns_404(client, db_session, user_factory, project_factory):
    """IDOR-4: gorunmeyen projenin unitesi 404 — mesaj UNITE icin ozeldir."""
    project = await project_factory("B6-16")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "patron")

    resp = await client.patch(f"/units/{unit.id}", json={"layout": "2+1"}, headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ünite bulunamadı"


async def test_patch_unit_unknown_uuid_returns_404_same_message(client, user_factory):
    """IDOR-7: var olmayan unite ile gorunmeyen unite AYIRT EDILEMEZ."""
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{uuid.uuid4()}", json={"layout": "2+1"}, headers=_auth(token)
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ünite bulunamadı"


async def test_patch_unit_owner_side_in_kendi_yatirim_returns_422(
    client, db_session, user_factory, project_factory
):
    """§3.3 korkulugu PATCH'te de gecerlidir — POST'tan kacan yol kapali."""
    project = await project_factory("B6-17", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"owner_side": "contractor"}, headers=_auth(token)
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Ünite payı yalnızca kat karşılığı projelerde belirlenebilir"


# --- B7: DELETE /units/{id} (spec §7.9) ---
#
# VERI KAYBI SINIFI. Bu bolumun testleri UC DUZEYINDEN kosar (HTTP DELETE), yani
# dogruladiklari yol servis korkulugu → ORM `session.delete(...)` yoludur.
# DB duzeyindeki `ON DELETE RESTRICT` ayrica `test_units_models.py::
# test_block_delete_restricted_when_units_exist` ile ham ORM silme uzerinden
# dogrulanir — iki katman, iki ayri test. Modelde `relationship(cascade=...)`
# TANIMLI DEGILDIR, bu yuzden ORM'in kendiliginden unite silme yolu YOKTUR.


async def test_delete_unit_returns_204(client, db_session, user_factory, project_factory):
    project = await project_factory("B7-1")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/units/{unit.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_delete_unit_twice_returns_404(client, db_session, user_factory, project_factory):
    """Silinen unite ARTIK YOKTUR: ikinci istek 404, 204 degil (idempotent
    gorunumu kullaniciya "hâlâ duruyor mu?" sorusunu birakirdi)."""
    project = await project_factory("B7-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    first = await client.delete(f"/units/{unit.id}", headers=_auth(token))
    second = await client.delete(f"/units/{unit.id}", headers=_auth(token))

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json()["detail"] == "Ünite bulunamadı"


async def test_delete_unit_invisible_returns_403_indistinguishable_from_unknown(
    client, db_session, user_factory, project_factory
):
    """IDOR-6 (2026-07-30 karari sonrasi): silme `projects:admin` ister.

    `full` seviyeli `patron` artik YETKI KAPISINDA durur (403) ve gorunurluk
    suzgecine hic ulasmaz. Sizinti YOKTUR: ayni rol var olmayan bir UUID icin de
    birebir ayni 403'u alir, yani 403 kaydin varligi hakkinda hicbir sey soylemez.
    Gorunmeyen kaydin **404** dondugu davranis `guards.visible_unit` uzerinde
    aynen durur ve PATCH ucunda (hâlâ `full`) sinanir — bkz. `test_units_idor`.
    """
    project = await project_factory("B7-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "patron")

    resp = await client.delete(f"/units/{unit.id}", headers=_auth(token))
    unknown = await client.delete(f"/units/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == unknown.status_code == 403
    assert resp.json() == unknown.json()
    assert await _count_units_in_block(db_session, block.id) == 1


async def test_delete_unit_unknown_uuid_returns_404_same_message(client, user_factory):
    """IDOR-7: var olmayan unite ile gorunmeyen unite AYIRT EDILEMEZ."""
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/units/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ünite bulunamadı"


async def test_delete_unit_view_permission_forbidden(
    client, db_session, user_factory, project_factory
):
    """Spec §8: silme yazma iznine baglidir; `view` SILEMEZ (IDOR-13)."""
    project = await project_factory("B7-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await client.delete(f"/units/{unit.id}", headers=_auth(token))

    assert resp.status_code == 403
    assert await _count_units_in_block(db_session, block.id) == 1


async def test_delete_unit_full_permission_forbidden(
    client, db_session, user_factory, project_factory
):
    """KULLANICI KARARI 2026-07-30: silme `projects:admin` ister, `full` YETMEZ.

    `full` seviyeli rol uniteyi PATCH ile duzenleyebilir ama silemez
    (`app/core/access.py`: "full silmeyi KAPSAMAZ — silme yalnizca admin").
    """
    project = await project_factory("B7-4B")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login_with_access(client, db_session, user_factory, "patron")

    patch = await client.patch(f"/units/{unit.id}", json={"unit_no": "9"}, headers=_auth(token))
    resp = await client.delete(f"/units/{unit.id}", headers=_auth(token))

    assert patch.status_code == 200, "on kosul: bu rol uniteyi DUZENLEYEBILMELI"
    assert resp.status_code == 403
    assert await _count_units_in_block(db_session, block.id) == 1


async def test_delete_unit_admin_permission_allowed(
    client, db_session, user_factory, project_factory
):
    """`projects:admin` siler — kapi seviyede, rol adinda DEGIL."""
    project = await project_factory("B7-4C")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    await _set_permission(db_session, "project_manager", "projects", AccessLevel.admin)
    token = await _login_with_access(client, db_session, user_factory, "project_manager")

    resp = await client.delete(f"/units/{unit.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert await _count_units_in_block(db_session, block.id) == 0


# --- B7: DELETE /blocks/{id} (spec §7.9) ---


async def test_delete_block_with_units_returns_409(
    client, db_session, user_factory, project_factory
):
    """Cascade YOKTUR: unitesi olan blok silinemez (spec §7.9)."""
    project = await project_factory("B7-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu blokta ünite var, önce üniteleri silin"


async def test_delete_block_with_units_leaves_block_and_units_intact(
    client, db_session, user_factory, project_factory
):
    """KANIT TESTI (plan B7 test 6): 409 SONRASI blok duruyor ve unite sayisi
    DEGISMEMIS. 24 daireyi tek istekle sessizce silmek geri alinamaz veri
    kaybidir; durum kodu tek basina bunu kanitlamaz."""
    project = await project_factory("B7-6")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for no in (str(n) for n in range(1, 25)):
        await _unit(db_session, project, block, no)
    token = await _login(client, user_factory, "system_admin")
    before = await _count_units_in_block(db_session, block.id)

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    after = await _count_units_in_block(db_session, block.id)
    assert resp.status_code == 409
    assert before == 24
    assert after == before
    assert await _block_exists(db_session, block.id) is True


async def test_delete_block_error_message_omits_unit_count(
    client, db_session, user_factory, project_factory
):
    """Spec §7.9: mesajda unite ADEDI VERILMEZ — gorunurluk disi bilgi sizmaz."""
    project = await project_factory("B7-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for no in ("1", "2", "3"):
        await _unit(db_session, project, block, no)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail == "Bu blokta ünite var, önce üniteleri silin"
    assert not any(char.isdigit() for char in detail)


async def test_delete_empty_block_returns_204(client, db_session, user_factory, project_factory):
    project = await project_factory("B7-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert await _block_exists(db_session, block.id) is False


async def test_delete_block_after_units_removed_returns_204(
    client, db_session, user_factory, project_factory
):
    """Akis dogrulamasi: once uniteler, sonra blok — kullaniciya soylenen yol."""
    project = await project_factory("B7-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    blocked = await client.delete(f"/blocks/{block.id}", headers=_auth(token))
    await client.delete(f"/units/{unit.id}", headers=_auth(token))
    allowed = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert blocked.status_code == 409
    assert allowed.status_code == 204
    assert await _block_exists(db_session, block.id) is False


async def test_delete_block_invisible_returns_403_indistinguishable_from_unknown(
    client, db_session, user_factory, project_factory
):
    """IDOR-6 (2026-07-30 karari sonrasi): silme `projects:admin` ister.

    `full` seviyeli `patron` yetki kapisinda durur; 403 var olmayan UUID icin de
    birebir aynidir, dolayisiyla kaydin varligi sizmaz. Gorunurluk suzgecinin
    **404** davranisi degismedi — PATCH ucunda (hâlâ `full`) sinanir.
    """
    project = await project_factory("B7-10")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "patron")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))
    unknown = await client.delete(f"/blocks/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == unknown.status_code == 403
    assert resp.json() == unknown.json()
    assert await _block_exists(db_session, block.id) is True


async def test_delete_block_unknown_uuid_returns_404_same_message(client, user_factory):
    """IDOR-7: var olmayan blok ile gorunmeyen blok AYIRT EDILEMEZ."""
    token = await _login(client, user_factory, "system_admin")

    resp = await client.delete(f"/blocks/{uuid.uuid4()}", headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"


async def test_delete_block_view_permission_forbidden(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B7-11")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert resp.status_code == 403
    assert await _block_exists(db_session, block.id) is True


async def test_delete_block_full_permission_forbidden(
    client, db_session, user_factory, project_factory
):
    """KULLANICI KARARI 2026-07-30: silme `projects:admin` ister, `full` YETMEZ."""
    project = await project_factory("B7-11B")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login_with_access(client, db_session, user_factory, "patron")

    patch = await client.patch(f"/blocks/{block.id}", json={"name": "Z Blok"}, headers=_auth(token))
    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert patch.status_code == 200, "on kosul: bu rol blogu DUZENLEYEBILMELI"
    assert resp.status_code == 403
    assert await _block_exists(db_session, block.id) is True


async def test_delete_block_admin_permission_allowed(
    client, db_session, user_factory, project_factory
):
    """`projects:admin` siler — kapi seviyede, rol adinda DEGIL."""
    project = await project_factory("B7-11C")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _set_permission(db_session, "project_manager", "projects", AccessLevel.admin)
    token = await _login_with_access(client, db_session, user_factory, "project_manager")

    resp = await client.delete(f"/blocks/{block.id}", headers=_auth(token))

    assert resp.status_code == 204
    assert await _block_exists(db_session, block.id) is False


# --- P3.1 §0.B: kodu NULL olan blokta ANLIK turetme (spec §3.2, karar 8) ---


async def test_null_kodlu_blokta_anlik_turetme_saklanmaz(db_session, project_factory):
    """Canli bloklarin `code`'u NULL dogar ve NULL KALIR.

    Toplu uretimin `{Blok}` jetonu icin kod ANLIK turetilir; bu cagri `blocks`
    satirini **UPDATE ETMEZ**. Aksi hâlde okuma yolunda gizli bir yazma olur ve
    karar 8'in "backfill migration'i YOKTUR" kurali arka kapidan delinirdi.
    """
    project = await project_factory("P31-0B")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, "C Blok")
    assert block.code is None

    assert effective_block_code(block.code, block.name) == "C"

    block_id = block.id
    db_session.expire_all()
    stored = (await db_session.execute(select(Block.code).where(Block.id == block_id))).scalar_one()
    assert stored is None


# --- P3.1 T5: blok formunun 13 yeni alani (spec §2.1, §3.1, §3.2, §3.3) ---

_BLOK_FORMU = {
    "code": "YV-C",  # BE 71
    "basement_floor_count": 2,  # BE 78
    "floor_count": 8,  # BE 79
    "roof_type": "duplex",  # BE 80
    "units_per_floor": 3,  # BE 81
    "ground_floor_usage": "commercial",  # BE 82
    "shop_count": 2,  # BE 83
    "construction_area_m2": "3200.00",  # BE 84
    "elevator_count": 1,  # BE 85
    "parking_type": "closed",  # BE 86
    "estimated_delivery_date": "2027-06-30",  # BE 100
    "status": "construction",  # BE 101
    "notes": "Zemin katta iki dükkan",  # BE 102
}


async def test_blok_13_alan_yazilir_ve_doner(client, db_session, user_factory, project_factory):
    """BE formunun 13 alani da yazilir ve GET'te geri doner (spec §3.1)."""
    project = await project_factory("T5-1")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "C Blok"} | _BLOK_FORMU,
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    for field, value in _BLOK_FORMU.items():
        assert body[field] == value, field

    listed = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))
    assert listed.json()["blocks"][0]["code"] == "YV-C"
    assert listed.json()["blocks"][0]["notes"] == "Zemin katta iki dükkan"


async def test_blok_kodu_bos_ise_uretilir(client, db_session, user_factory, project_factory):
    """BE 71 ipucu "Boş bırakılırsa otomatik": "C Blok" → `C` (spec §3.2)."""
    project = await project_factory("T5-2")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "C Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 201
    assert resp.json()["code"] == "C"


async def test_ayni_koda_cozulen_ikinci_blok_kod_eki_alir(
    client, db_session, user_factory, project_factory
):
    """Blok ADI proje icinde benzersizdir, ama iki ayri ad AYNI koda cozulebilir
    ("A Blok" ve "A" → ikisi de `A`). Ikincisi `A-2` alir (spec §3.2 adim 5)."""
    project = await project_factory("T5-3")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    first = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )
    second = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A"}, headers=_auth(token)
    )

    assert first.json()["code"] == "A"
    assert second.status_code == 201
    assert second.json()["code"] == "A-2"


async def test_elle_verilen_kod_cakisirsa_409(client, db_session, user_factory, project_factory):
    """Kullanici kodu elle girerse aynen kabul edilir; yalniz benzersizlik
    dogrulanir → cakisma 409 (spec §3.2)."""
    project = await project_factory("T5-4")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "B Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu blok kodu bu projede zaten kullanılıyor"


async def test_farkli_projede_ayni_kod_201(client, db_session, user_factory, project_factory):
    """`uq_blocks_project_code` PROJE ICIDIR."""
    first = await project_factory("T5-5")
    second = await project_factory("T5-6")
    await _site(db_session, first)
    await _site(db_session, second, code="SANTIYE-2")
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        f"/projects/{first.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    resp = await client.post(
        f"/projects/{second.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["code"] == "YV-A"


async def test_blok_patch_kismi_guncelleme_notes_null_bosaltir(
    client, db_session, user_factory, project_factory
):
    """GONDERILMEYEN alan degismez; `null` GONDERILEN nullable alan bosalir."""
    project = await project_factory("T5-7")
    site = await _site(db_session, project)
    block = await _block(
        db_session, project, site, name="A Blok", code="A", floor_count=8, notes="ilk not"
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"notes": None, "elevator_count": 2}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] is None
    assert body["elevator_count"] == 2
    assert body["floor_count"] == 8  # gonderilmedi → degismedi
    assert body["code"] == "A"


async def test_patch_kodu_bos_blokta_kod_uretir(client, db_session, user_factory, project_factory):
    """Karar 8: canli bloklarin kodu NULL dogar; BACKFILL MIGRATION'I YOKTUR —
    kod bir sonraki PATCH'te uretilir (uretim tek yerdedir, spec §3.2)."""
    project = await project_factory("T5-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"notes": "kat planı"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["code"] == "C"


async def test_estimated_unit_count_8x3_arti_2_esittir_26(
    client, db_session, user_factory, project_factory
):
    """BE 90-93 BIREBIR: "8 kat × 3 daire + 2 dükkan" = 26. SAKLANMAZ, turevdir."""
    project = await project_factory("T5-9")
    site = await _site(db_session, project)
    await _block(
        db_session, project, site, name="C Blok", floor_count=8, units_per_floor=3, shop_count=2
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.json()["blocks"][0]["estimated_unit_count"] == 26


async def test_estimated_unit_count_uc_girdi_none_ise_none(
    client, db_session, user_factory, project_factory
):
    """Uc girdi de bossa `None` doner — **0 DEGIL**: 0 "hesaplandi ve sifir" der
    ve bu yanlis bilgidir (spec §3.3)."""
    project = await project_factory("T5-10")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.json()["blocks"][0]["estimated_unit_count"] is None


async def test_blok_negatif_sayac_422(client, db_session, user_factory, project_factory):
    """`floor_count = -1` → 422 (Pydantic, DB CHECK'ine DUSMEDEN)."""
    project = await project_factory("T5-11")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "A Blok", "floor_count": -1},
        headers=_auth(token),
    )

    assert resp.status_code == 422


# --- P3.1 T6: unite formunun 8 yeni alani (spec §2.2, §4.1-§4.5) ---

_UNITE_FORMU = {
    "floor": "3. Kat",  # UE 66 — METIN (karar 4)
    "facing": "southwest",  # UE 78
    "balcony_area_m2": "14.00",  # UE 79
    "bathroom_count": 2,  # UE 80
    "parking_right": "one_closed",  # UE 81
    "min_sale_price": "1380000.00",  # UE 92
    "vat_rate": "10.00",  # UE 93
    "sales_status": "sold",  # UE 94
}


async def test_unite_8_yeni_alan_yazilir_ve_doner(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("T6-1")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "B-12", "unit_kind": "apartment"}
        | _UNITE_FORMU,
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    for field, value in _UNITE_FORMU.items():
        assert body[field] == value, field


async def test_sales_status_gonderilmezse_listed(client, db_session, user_factory, project_factory):
    """UE 94'te "Satışta (Boş)" `selected` gelir → sunucu varsayilani `listed`.

    Varsayilan ZORUNLULUK DEGILDIR (karar 11): alan gonderilmeyebilir.
    """
    project = await project_factory("T6-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["sales_status"] == "listed"


async def test_unit_kind_office_warehouse_parking_201(
    client, db_session, user_factory, project_factory
):
    """UE 74 bes secenek: enum genislemesi uctan uca calisir (spec §4.3)."""
    project = await project_factory("T6-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    for index, kind in enumerate(("office", "warehouse", "parking")):
        resp = await client.post(
            f"/projects/{project.id}/units",
            json={"block_id": str(block.id), "unit_no": f"{index}", "unit_kind": kind},
            headers=_auth(token),
        )
        assert resp.status_code == 201, kind
        assert resp.json()["unit_kind"] == kind


async def test_floor_cati_kati_aynen_doner_21_karakter_422(
    client, db_session, user_factory, project_factory
):
    """Karar 4: kat METINDIR — mockup etiketi AYNEN saklanir, sayiya cevrilmez."""
    project = await project_factory("T6-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "floor": "Çatı Katı",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["floor"] == "Çatı Katı"

    too_long = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "2",
            "unit_kind": "apartment",
            "floor": "K" * 21,
        },
        headers=_auth(token),
    )
    assert too_long.status_code == 422


async def test_floor_gonderilmezse_none_201(client, db_session, user_factory, project_factory):
    """UE 66'da kirmizi `*` var ama zorunluluk DOGURMAZ (karar 11)."""
    project = await project_factory("T6-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["floor"] is None


async def test_patch_sales_status_sold_200(client, db_session, user_factory, project_factory):
    """Kullanici karari 2: satis durumu BUGUN ELLE degistirilebilir (spec §4.4).

    P8 geldiginde bu alan otomatiklesecek ve elle giris KILITLENECEKTIR.
    """
    project = await project_factory("T6-6")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"sales_status": "sold"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["sales_status"] == "sold"


async def test_expected_profit_ve_unit_cost_yer_tutucu(
    client, db_session, user_factory, project_factory
):
    """Karar 3: maliyet ELLE GIRILMEZ → UE 91 ve UE 97-99 YER TUTUCUDUR.

    Maliyet ileride Is Kalemleri/satinalmadan hesaplanacak; bugun kolon ACILMAZ.
    """
    project = await project_factory("T6-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    unit = resp.json()["blocks"][0]["units"][0]
    for field in ("unit_cost", "expected_profit"):
        assert unit[field]["available"] is False, field
        assert unit[field]["pending_module"] == "project_costs", field


# --- P3.1 T7: satis durumu sayaclari ve yeni suzgecler (spec §8.2) ---


async def _satis_durumu_seti(session, project, site):
    """Dort durumdan biri kadar unite + kat etiketleri (KY 258-259 kirilimi)."""
    block = await _block(session, project, site)
    await _unit(session, project, block, "1", sales_status=UnitSalesStatus.sold, floor="3. Kat")
    await _unit(session, project, block, "2", sales_status=UnitSalesStatus.sold, floor="3")
    await _unit(session, project, block, "3", sales_status=UnitSalesStatus.reserved, floor="Zemin")
    await _unit(session, project, block, "4", sales_status=UnitSalesStatus.listed)
    await _unit(session, project, block, "5", sales_status=UnitSalesStatus.closed)
    return block


async def test_sales_status_suzgeci_listeyi_daraltir(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("T7-1")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units?sales_status=sold", headers=_auth(token))

    assert resp.status_code == 200
    assert [u["unit_no"] for u in resp.json()["blocks"][0]["units"]] == ["1", "2"]


async def test_totals_suzgecten_etkilenmez(client, db_session, user_factory, project_factory):
    """P3 §7.4 kurali KORUNUR: suzgec YALNIZ listeyi daraltir, `totals` daima
    projenin TAMAMINI sayar."""
    project = await project_factory("T7-2")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units?sales_status=sold", headers=_auth(token))

    totals = resp.json()["totals"]
    assert totals["counts"]["total"] == 5
    assert totals["by_sales_status"]["listed"] == 1


async def test_by_sales_status_dort_degeri_de_sayar(
    client, db_session, user_factory, project_factory
):
    """KY 258-259 / KKP 161-163 kirilimi artik GERCEK sayilabilir (spec §8.2)."""
    project = await project_factory("T7-3")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    totals = resp.json()["totals"]
    assert totals["by_sales_status"] == {"listed": 1, "reserved": 1, "sold": 2, "closed": 1}
    assert totals["sold_units"] == 2
    assert totals["reserved_units"] == 1
    assert totals["available_units"] == 1  # `listed` — `closed` BOS DEGILDIR


async def test_floor_suzgeci_tam_eslesme(client, db_session, user_factory, project_factory):
    """Karar 4: kat METINDIR → suzgec TAM ESLESMEDIR. "3" ile "3. Kat" AYRI
    degerlerdir; parcali eslesme sessiz veri karisikligi olurdu."""
    project = await project_factory("T7-4")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    kat = await client.get(f"/projects/{project.id}/units?floor=3.%20Kat", headers=_auth(token))
    sayi = await client.get(f"/projects/{project.id}/units?floor=3", headers=_auth(token))

    assert [u["unit_no"] for u in kat.json()["blocks"][0]["units"]] == ["1"]
    assert [u["unit_no"] for u in sayi.json()["blocks"][0]["units"]] == ["2"]


async def test_sales_revenue_hala_yer_tutucu(client, db_session, user_factory, project_factory):
    """P8 SINIRI KORUNUYOR: GERCEKLESEN satis tutari hâlâ P8'in verisidir —
    `sales_status` sutunu acildi diye ciro uydurulmaz (spec §8.2)."""
    project = await project_factory("T7-5")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    totals = (await client.get(f"/projects/{project.id}/units", headers=_auth(token))).json()[
        "totals"
    ]

    for field in ("sales_revenue", "average_sale_price"):
        assert totals[field]["available"] is False, field
        assert totals[field]["pending_module"] == "unit_sales", field
