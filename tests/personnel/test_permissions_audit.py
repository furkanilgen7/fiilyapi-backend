"""Puantaj T2 — `personnel` uçlarının izin kapıları ve denetim günlüğü.

İzin modülü `personnel` (spec §3): okuma `personnel:view`, yazma `personnel:full`.
**Şantiye şefi `view`'dir (spec §5 bilinçli sınır): işçi EKLEYEMEZ, yalnız okur** —
matris kararı bu dilimde DEĞİŞMEZ.

Kapsam (IDOR) testi burada YOKTUR ve olmamalıdır: `personnel` şirket-genelidir
(bkz. `test_personnel.py::test_personel_listesi_sirket_genelidir_...`).
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.audit import messages
from app.modules.audit.models import AuditLog

ISCI = {"full_name": "Ahmet Yılmaz", "trade": "Kalıpçı", "source": "company"}


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
    yanit = await client.get("/personnel", headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_yetkisiz_rol_detayda_403(client, yetkisiz_headers):
    yanit = await client.get(f"/personnel/{uuid.uuid4()}", headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_yetkisiz_rol_olusturmada_403(client, yetkisiz_headers):
    yanit = await client.post("/personnel", json=ISCI, headers=yetkisiz_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_santiye_sefi_listeyi_gorur(client, sef_headers):
    yanit = await client.get("/personnel", headers=sef_headers)
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_santiye_sefi_personel_olusturamaz_403(client, sef_headers):
    """spec §5: işçiyi İK ekler, şantiye şefi yalnız görür."""
    yanit = await client.post("/personnel", json=ISCI, headers=sef_headers)
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_santiye_sefi_personel_guncelleyemez_403(client, sef_headers, ik_headers):
    olustur = await client.post("/personnel", json=ISCI, headers=ik_headers)
    assert olustur.status_code == 201, olustur.text
    yanit = await client.patch(
        f"/personnel/{olustur.json()['id']}", json={"full_name": "X"}, headers=sef_headers
    )
    assert yanit.status_code == 403


@pytest.mark.asyncio
async def test_kimliksiz_istek_401(client):
    yanit = await client.get("/personnel")
    assert yanit.status_code == 401


# --- Denetim günlüğü ---


@pytest.mark.asyncio
async def test_olusturma_denetime_yazilir(client, ik_headers, db_session):
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.post("/personnel", json=ISCI, headers=ik_headers)
    assert yanit.status_code == 201, yanit.text
    assert await _yeni_kaydin_metni(db_session, onceki) == messages.personnel_created(
        "Ahmet Yılmaz"
    )


@pytest.mark.asyncio
async def test_guncelleme_denetime_yazilir(client, ik_headers, db_session):
    olustur = await client.post("/personnel", json=ISCI, headers=ik_headers)
    assert olustur.status_code == 201, olustur.text
    onceki = await _mevcut_kimlikler(db_session)
    yanit = await client.patch(
        f"/personnel/{olustur.json()['id']}", json={"trade": "Demirci"}, headers=ik_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert await _yeni_kaydin_metni(db_session, onceki) == messages.personnel_updated(
        "Ahmet Yılmaz"
    )
