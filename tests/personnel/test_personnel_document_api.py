"""İK-1 T3 — personel belge alt-kaynağı uçtan uca (HTTP).

Spec: `docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §2, §3, §5 K5.

Fixtures `conftest.py`de. Testler create_all şemasıyla koşar (migration DEĞİL) —
belge tipleri migration seed'idir, o yüzden tipler BURADA elle açılır.

Yetki (spec §5): okuma `view`, yazma `full`, SİLME `admin`. hr_manager `full`dur
(silmez → 403), system_admin `admin`dır (siler → 204).

⚠️ Görünmez BC belgesi → **404** (IDOR): `personnel` şirket-genelidir ama BC arşivi
`visible_projects` kapsamlıdır — görmediği projedeki belgeye bağ kurulamaz.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.modules.documents.models import Document
from app.modules.personnel.models import Personnel, PersonnelDocument, PersonnelDocumentType
from app.modules.site_diary.models import WorkerSource
from tests.conftest import test_engine


@pytest.fixture
async def proje(seeded_db: AsyncSession, project_factory):
    return await project_factory(code="IK1-T3-DOC", name="Belge Proje")


@pytest.fixture
async def personel(seeded_db: AsyncSession) -> Personnel:
    kayit = Personnel(full_name="Belge Sahibi", source=WorkerSource.company)
    seeded_db.add(kayit)
    await seeded_db.flush()
    return kayit


@pytest.fixture
async def belge_tipi(seeded_db: AsyncSession) -> PersonnelDocumentType:
    tip = PersonnelDocumentType(
        name="Sağlık Raporu", is_mandatory=True, validity_months=12, sort_order=1
    )
    seeded_db.add(tip)
    await seeded_db.flush()
    return tip


@pytest.fixture
async def pasif_tip(seeded_db: AsyncSession) -> PersonnelDocumentType:
    tip = PersonnelDocumentType(name="Pasif Tip", is_active=False)
    seeded_db.add(tip)
    await seeded_db.flush()
    return tip


@pytest.fixture
async def arsiv_belgesi(seeded_db: AsyncSession, proje) -> Document:
    """BC arşivinde `proje` kapsamında bir belge — hr_manager bu projeyi GÖRMEZ."""
    belge = Document(
        project_id=proje.id,
        filename="rapor.pdf",
        mime_type="application/pdf",
        size_bytes=10,
    )
    seeded_db.add(belge)
    await seeded_db.flush()
    return belge


# --- GET liste ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_liste_gorunmeyen_personel_404(client, ik_headers):
    yanit = await client.get(f"/personnel/{uuid.uuid4()}/documents", headers=ik_headers)
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_liste_bos_200(client, ik_headers, personel):
    yanit = await client.get(f"/personnel/{personel.id}/documents", headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json() == []


# --- POST: XOR + tip doğrulama -----------------------------------------------


@pytest.mark.asyncio
async def test_post_tip_ile_201_durum_ve_kunye(client, ik_headers, personel, belge_tipi):
    yakin = (timezone.today() + timedelta(days=10)).isoformat()
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"type_id": str(belge_tipi.id), "valid_until": yakin},
        headers=ik_headers,
    )
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["type_name"] == "Sağlık Raporu"
    assert govde["is_mandatory"] is True
    assert govde["validity_months"] == 12
    assert govde["free_label"] is None
    assert govde["status"] == "expiring"
    assert govde["days_left"] == 10


@pytest.mark.asyncio
async def test_post_serbest_etiket_201(client, ik_headers, personel):
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"free_label": "Diploma"},
        headers=ik_headers,
    )
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["free_label"] == "Diploma"
    assert govde["type_id"] is None
    assert govde["type_name"] is None
    assert govde["status"] == "valid"  # valid_until yok → süresiz


@pytest.mark.asyncio
async def test_post_ikisi_birden_422(client, ik_headers, personel, belge_tipi):
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"type_id": str(belge_tipi.id), "free_label": "İkisi"},
        headers=ik_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_post_hicbiri_422(client, ik_headers, personel):
    yanit = await client.post(f"/personnel/{personel.id}/documents", json={}, headers=ik_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_post_pasif_tip_422(client, ik_headers, personel, pasif_tip):
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"type_id": str(pasif_tip.id)},
        headers=ik_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_post_var_olmayan_tip_404(client, ik_headers, personel):
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"type_id": str(uuid.uuid4())},
        headers=ik_headers,
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_post_gorunmeyen_personel_404(client, ik_headers, belge_tipi):
    yanit = await client.post(
        f"/personnel/{uuid.uuid4()}/documents",
        json={"type_id": str(belge_tipi.id)},
        headers=ik_headers,
    )
    assert yanit.status_code == 404, yanit.text


# --- POST: BC bağı (IDOR) ----------------------------------------------------


@pytest.mark.asyncio
async def test_post_gorunmeyen_bc_belge_404_idor(client, ik_headers, personel, arsiv_belgesi):
    """hr_manager `arsiv_belgesi`nin projesini GÖRMEZ → bağ kurdurulmaz (404)."""
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"free_label": "Bağlı Belge", "document_id": str(arsiv_belgesi.id)},
        headers=ik_headers,
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_post_gorunur_bc_belge_201(client, admin_headers, personel, arsiv_belgesi):
    """system_admin TÜM projeleri görür → bağ kurulur (201)."""
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"free_label": "Bağlı Belge", "document_id": str(arsiv_belgesi.id)},
        headers=admin_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["document_id"] == str(arsiv_belgesi.id)


# --- PATCH -------------------------------------------------------------------


async def _belge_olustur(client, headers, personel_id) -> str:
    yanit = await client.post(
        f"/personnel/{personel_id}/documents",
        json={"free_label": "Serbest"},
        headers=headers,
    )
    assert yanit.status_code == 201, yanit.text
    return yanit.json()["id"]


@pytest.mark.asyncio
async def test_patch_kunye_gunceller_200(client, ik_headers, personel):
    doc_id = await _belge_olustur(client, ik_headers, personel.id)
    yanit = await client.patch(
        f"/personnel/documents/{doc_id}",
        json={"note": "güncel", "valid_until": (timezone.today() - timedelta(days=1)).isoformat()},
        headers=ik_headers,
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["note"] == "güncel"
    assert govde["status"] == "expired"


@pytest.mark.asyncio
async def test_patch_yok_404(client, ik_headers):
    yanit = await client.patch(
        f"/personnel/documents/{uuid.uuid4()}", json={"note": "x"}, headers=ik_headers
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_patch_gorunmeyen_bc_belge_404_idor(client, ik_headers, personel, arsiv_belgesi):
    doc_id = await _belge_olustur(client, ik_headers, personel.id)
    yanit = await client.patch(
        f"/personnel/documents/{doc_id}",
        json={"document_id": str(arsiv_belgesi.id)},
        headers=ik_headers,
    )
    assert yanit.status_code == 404, yanit.text


# --- DELETE: admin kapısı + SET NULL -----------------------------------------


@pytest.mark.asyncio
async def test_delete_full_yetki_403(client, ik_headers, personel):
    """hr_manager `full`dur; silme `admin` ister → 403 (`full` silmeyi kapsamaz)."""
    doc_id = await _belge_olustur(client, ik_headers, personel.id)
    yanit = await client.delete(f"/personnel/documents/{doc_id}", headers=ik_headers)
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_delete_admin_204_bc_kunye_durur(
    client, admin_headers, seeded_db, personel, arsiv_belgesi
):
    """admin siler (204); SET NULL: BC arşiv künyesi DOKUNULMAZ (dosya arşivde kalır)."""
    yanit = await client.post(
        f"/personnel/{personel.id}/documents",
        json={"free_label": "Bağlı", "document_id": str(arsiv_belgesi.id)},
        headers=admin_headers,
    )
    doc_id = yanit.json()["id"]

    sil = await client.delete(f"/personnel/documents/{doc_id}", headers=admin_headers)
    assert sil.status_code == 204, sil.text

    # İK kaydı gitti ama BC künyesi DURUYOR.
    kalan_ik = await seeded_db.execute(
        select(PersonnelDocument).where(PersonnelDocument.id == uuid.UUID(doc_id))
    )
    assert kalan_ik.scalar_one_or_none() is None
    kalan_bc = await seeded_db.execute(select(Document).where(Document.id == arsiv_belgesi.id))
    assert kalan_bc.scalar_one_or_none() is not None, "BC künyesi SET NULL ile durmalı"


# --- N+1 önlemi --------------------------------------------------------------


@pytest.mark.asyncio
async def test_liste_tek_join_sorgusu_n_plus_1_yok(client, ik_headers, personel, belge_tipi):
    """Liste ucu tip künyesini TEK JOIN'le getirir; belge başına ayrı tip SELECT'i

    (N+1) atmaz. İki tipli kayıt açılır; GET sırasında `personnel_document_types`
    tablosuna STANDALONE (`FROM personnel_document_types`) hiç SELECT gitmemeli —
    tek dokunuş JOIN'dedir (`JOIN personnel_document_types`).
    """
    for _ in range(2):
        r = await client.post(
            f"/personnel/{personel.id}/documents",
            json={"type_id": str(belge_tipi.id)},
            headers=ik_headers,
        )
        assert r.status_code == 201, r.text

    standalone: list[str] = []

    def _yakala(conn, cursor, statement, parameters, context, executemany):
        if "from personnel_document_types" in statement.lower():
            standalone.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _yakala)
    try:
        yanit = await client.get(f"/personnel/{personel.id}/documents", headers=ik_headers)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _yakala)

    assert yanit.status_code == 200, yanit.text
    assert len(yanit.json()) == 2
    assert standalone == [], f"N+1: tip tablosuna standalone SELECT gitti: {standalone}"
