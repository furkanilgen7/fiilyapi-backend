"""BOQ — T6 GÜNCELLEME uçları (PATCH grup + kalem) ve T7 DENETİM GÜNLÜĞÜ.

`test_boq_api.py`nin parçalarından biri (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_boq.py`dedir.

Dört yazma ucu denetim kaydı açar, OKUMA ucu AÇMAZ — sonuncusu denetim
gürültüsünün tek gerçek bekçisidir.
"""

import uuid

from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog

from ._boq import (
    _audit_details,
    _auth,
    _group,
    _item,
    _login,
    _login_with_access,
    _site,
)


async def test_update_boq_group_happy_path(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-23")
    site = await _site(db_session, project)
    group = await _group(db_session, site, name="ESKI AD", sort_order=1)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/groups/{group.id}",
        headers=_auth(token),
        json={"name": "YENI AD", "sort_order": 5},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "YENI AD"
    assert body["sort_order"] == 5


async def test_update_boq_group_invisible_returns_404_not_403(
    client, db_session, user_factory, project_factory
):
    """IDOR (spec §5.5): grup->santiye->proje suzgecinden gecmeyen kayit 404 doner."""
    project = await project_factory("BOQ-API-24")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    # user_project_access verilmedi -> proje/santiye gorunmez.
    token = await _login(client, user_factory, "project_manager", "pm@boq-api-24.co")

    resp = await client.patch(
        f"/boq/groups/{group.id}", headers=_auth(token), json={"name": "YENI AD"}
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "İş kalemi grubu bulunamadı"


async def test_update_boq_group_missing_returns_404(client, user_factory):
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/groups/{uuid.uuid4()}", headers=_auth(token), json={"name": "YENI AD"}
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "İş kalemi grubu bulunamadı"


async def test_update_boq_group_view_only_role_forbidden(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-25")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    token = await _login_with_access(
        client, db_session, user_factory, "site_chief", "sc@boq-api-25.co"
    )

    resp = await client.patch(
        f"/boq/groups/{group.id}", headers=_auth(token), json={"name": "YENI AD"}
    )

    assert resp.status_code == 403


# --- T6 — PATCH /boq/items/{item_id} ---


async def test_update_boq_item_happy_path(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-26")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item.id}",
        headers=_auth(token),
        json={"description": "Yeni tarif", "quantity": "500.000", "unit_price": "300.00"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "Yeni tarif"
    assert body["quantity"] == "500.000"
    assert body["unit_price"] == "300.00"
    assert body["amount"] == "150000.00"


async def test_update_boq_item_invisible_returns_404_not_403(
    client, db_session, user_factory, project_factory
):
    """IDOR (spec §5.5): kalem->santiye->proje suzgecinden gecmeyen kayit 404 doner."""
    project = await project_factory("BOQ-API-27")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login(client, user_factory, "project_manager", "pm@boq-api-27.co")

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"description": "Yeni tarif"}
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "İş kalemi bulunamadı"


async def test_update_boq_item_missing_returns_404(client, user_factory):
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{uuid.uuid4()}", headers=_auth(token), json={"description": "Yeni tarif"}
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "İş kalemi bulunamadı"


async def test_update_boq_item_move_to_group_of_other_site_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-28")
    site_a = await _site(db_session, project, code="A-BLOK-28")
    site_b = await _site(db_session, project, code="B-BLOK-28", name="B-Blok Şantiyesi")
    group_a = await _group(db_session, site_a)
    group_b = await _group(db_session, site_b)
    item = await _item(db_session, site_a, group_a, code="01.001")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"group_id": str(group_b.id)}
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Grup bu şantiyeye ait değil"


async def test_update_boq_item_duplicate_code_returns_409(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-29")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    await _item(db_session, site, group, code="01.001")
    item_to_rename = await _item(db_session, site, group, code="01.002")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item_to_rename.id}", headers=_auth(token), json={"code": "01.001"}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu poz numarası bu şantiyede zaten kullanılıyor"


async def test_update_boq_item_same_code_does_not_conflict_with_itself(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-30")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"code": "01.001", "sort_order": 9}
    )

    assert resp.status_code == 200
    assert resp.json()["sort_order"] == 9


async def test_update_boq_item_nonpositive_quantity_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-31")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(f"/boq/items/{item.id}", headers=_auth(token), json={"quantity": "0"})

    assert resp.status_code == 422


async def test_update_boq_item_negative_unit_price_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-32")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"unit_price": "-1"}
    )

    assert resp.status_code == 422


async def test_update_boq_item_view_only_role_forbidden(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("BOQ-API-33")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.001")
    token = await _login_with_access(
        client, db_session, user_factory, "site_chief", "sc@boq-api-33.co"
    )

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"description": "Yeni tarif"}
    )

    assert resp.status_code == 403


# --- T7 — denetim gunlugu (4 yazma ucu) ---


async def test_create_boq_group_records_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-34")
    site = await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/sites/{site.id}/boq/groups",
        headers=_auth(token),
        json={"name": "SIVA VE BOYA İŞLERİ"},
    )

    assert resp.status_code == 201
    details = await _audit_details(db_session, AuditAction.create)
    assert any("SIVA VE BOYA İŞLERİ" in d for d in details)


async def test_update_boq_group_records_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-35")
    site = await _site(db_session, project)
    group = await _group(db_session, site, name="ESKI AD")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/groups/{group.id}", headers=_auth(token), json={"name": "YENI AD"}
    )

    assert resp.status_code == 200
    details = await _audit_details(db_session, AuditAction.update)
    assert any("YENI AD" in d for d in details)


async def test_create_boq_item_records_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-36")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/sites/{site.id}/boq/items",
        headers=_auth(token),
        json={
            "group_id": str(group.id),
            "code": "01.009",
            "description": "Kazı (Makine ile)",
            "unit": "m³",
            "quantity": "1",
            "unit_price": "1",
        },
    )

    assert resp.status_code == 201
    details = await _audit_details(db_session, AuditAction.create)
    assert any("01.009" in d and "Kazı (Makine ile)" in d for d in details)


async def test_update_boq_item_records_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("BOQ-API-37")
    site = await _site(db_session, project)
    group = await _group(db_session, site)
    item = await _item(db_session, site, group, code="01.010", description="Eski tarif")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/boq/items/{item.id}", headers=_auth(token), json={"description": "Yeni tarif"}
    )

    assert resp.status_code == 200
    details = await _audit_details(db_session, AuditAction.update)
    assert any("01.010" in d and "Yeni tarif" in d for d in details)


async def test_get_boq_does_not_record_audit(client, db_session, user_factory, project_factory):
    """Okuma uclari denetim kaydi yazmaz (T7 tuzagi)."""
    project = await project_factory("BOQ-API-38")
    site = await _site(db_session, project)
    await _group(db_session, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/sites/{site.id}/boq", headers=_auth(token))

    assert resp.status_code == 200
    all_rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert all(row.action != AuditAction.create for row in all_rows)


# --- BE-B — DELETE /boq/items/{item_id} (frontend F13 kalem silme) ---
