"""P8 T2 — `customers` uçlarının izin kapıları ve denetim günlüğü.

İzin modülü `sales` (spec §8 S1). Kapılar: okuma `sales:view`, yazma `sales:full`.
`customers` proje-bağımsızdır — `visible_projects` süzgeci UYGULANMAZ, dolayısıyla
burada kapsam (IDOR) testi YOKTUR, yalnız SEVİYE testi vardır.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.audit import messages
from app.modules.audit.models import AuditLog

GERCEK_KISI = {
    "customer_type": "person",
    "name": "Serkan Öz",
    "national_id": "12345678901",
}


async def _mevcut_kimlikler(db_session) -> set[uuid.UUID]:
    return set(await db_session.scalars(select(AuditLog.id)))


async def _yeni_kaydin_metni(db_session, onceki: set[uuid.UUID]) -> str:
    rows = await db_session.scalars(select(AuditLog))
    yeni = [row for row in rows if row.id not in onceki]
    assert len(yeni) == 1, f"tam bir yeni satır beklenirdi, {len(yeni)} bulundu"
    return yeni[0].detail


# --- İzin kapıları ---


@pytest.mark.asyncio
async def test_yetkisiz_rol_listede_403(client, yetkisiz_headers):
    yanit = await client.get("/customers", headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_yetkisiz_rol_detayda_403(client, yetkisiz_headers):
    yanit = await client.get(f"/customers/{uuid.uuid4()}", headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_yetkisiz_rol_olusturmada_403(client, yetkisiz_headers):
    yanit = await client.post("/customers", json=GERCEK_KISI, headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_yetkisiz_rol_guncellemede_403(client, yetkisiz_headers):
    yanit = await client.patch(
        f"/customers/{uuid.uuid4()}", json={"name": "X"}, headers=yetkisiz_headers
    )
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_view_rolu_listeyi_gorur(client, view_headers):
    yanit = await client.get("/customers", headers=view_headers)
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_view_rolu_olusturamaz_403(client, view_headers):
    yanit = await client.post("/customers", json=GERCEK_KISI, headers=view_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_view_rolu_guncelleyemez_403(client, view_headers, admin_headers):
    olustur = await client.post("/customers", json=GERCEK_KISI, headers=admin_headers)
    assert olustur.status_code == 201, olustur.text
    yanit = await client.patch(
        f"/customers/{olustur.json()['id']}", json={"name": "X"}, headers=view_headers
    )
    assert yanit.status_code == 403


# --- Denetim günlüğü ---


@pytest.mark.asyncio
async def test_olusturma_denetime_yazar(client, admin_headers, db_session):
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post("/customers", json=GERCEK_KISI, headers=admin_headers)
    assert yanit.status_code == 201, yanit.text
    assert await _yeni_kaydin_metni(db_session, onceki) == messages.customer_created("Serkan Öz")


@pytest.mark.asyncio
async def test_guncelleme_denetime_yazar(client, admin_headers, db_session):
    olustur = await client.post("/customers", json=GERCEK_KISI, headers=admin_headers)
    assert olustur.status_code == 201, olustur.text
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.patch(
        f"/customers/{olustur.json()['id']}", json={"name": "Serkan Öz II"}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert await _yeni_kaydin_metni(db_session, onceki) == messages.customer_updated("Serkan Öz II")


@pytest.mark.asyncio
async def test_okuma_uclari_denetime_yazmaz(client, admin_headers, db_session):
    olustur = await client.post("/customers", json=GERCEK_KISI, headers=admin_headers)
    assert olustur.status_code == 201, olustur.text
    onceki = await _mevcut_kimlikler(db_session)
    assert (await client.get("/customers", headers=admin_headers)).status_code == 200
    assert (
        await client.get(f"/customers/{olustur.json()['id']}", headers=admin_headers)
    ).status_code == 200
    assert await _mevcut_kimlikler(db_session) == onceki
