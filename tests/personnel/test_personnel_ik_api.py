"""İK-1 T2 — uçtan uca (HTTP) personel kart genişlemesi.

Spec: `docs/superpowers/specs/2026-08-12-ik1-personel-belge-design.md` §1, §5 K1/K3/K4.

Servis kuralları `test_personnel_ik_service.py`de; burada HTTP STATÜLERİ ve
`?project_id=` süzgeci + IDOR (süzgeç yetki genişletmez) doğrulanır.

⚠️ Duplicate TCKN → **409** (statü/`DuplicateError`); DB SQLSTATE'ine bakılmaz
(PG sürüm tuzağı, WORKFLOW §4).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sites.models import Section, Site

GECERLI_TCKN = "10000000146"

ISCI = {"full_name": "Ahmet Yılmaz", "trade": "Kalıpçı", "source": "company"}


def _tam(project_id: str, **fark) -> dict:
    return {
        "full_name": "Ahmet Yılmaz",
        "source": "company",
        "tc_no": GECERLI_TCKN,
        "birth_date": "1990-01-01",
        "phone": "5551112233",
        "address": "Mahalle Sokak No 1",
        "emergency_contact_name": "Ayşe Yılmaz",
        "emergency_contact_phone": "5559998877",
        "trade": "Kalıpçı",
        "hire_date": "2026-01-01",
        "assigned_project_id": project_id,
        "wage_type": "daily",
        "wage_amount": "1500.00",
        "is_draft": False,
        **fark,
    }


@pytest.fixture
async def proje(seeded_db: AsyncSession, project_factory):
    return await project_factory(code="IK1-API-1", name="API Proje")


@pytest.fixture
async def bolum(seeded_db: AsyncSession, proje):
    santiye = Site(project_id=proje.id, code="S1", name="Şantiye")
    seeded_db.add(santiye)
    await seeded_db.flush()
    section = Section(site_id=santiye.id, name="Bölüm")
    seeded_db.add(section)
    await seeded_db.flush()
    return section


# --- POST: taslak gevşek / yayın sıkı ----------------------------------------


@pytest.mark.asyncio
async def test_post_taslak_gevsek_201(client, ik_headers):
    """`is_draft=True` (varsayılan) → eksik alanla 201."""
    yanit = await client.post("/personnel", json=ISCI, headers=ik_headers)
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["is_draft"] is True


@pytest.mark.asyncio
async def test_post_yayin_tam_201(client, ik_headers, proje):
    yanit = await client.post("/personnel", json=_tam(str(proje.id)), headers=ik_headers)
    assert yanit.status_code == 201, yanit.text
    govde = yanit.json()
    assert govde["is_draft"] is False
    assert govde["tc_no"] == GECERLI_TCKN
    assert govde["assigned_project_id"] == str(proje.id)


@pytest.mark.asyncio
async def test_post_yayin_eksik_422(client, ik_headers):
    yanit = await client.post("/personnel", json={**ISCI, "is_draft": False}, headers=ik_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_gecersiz_tckn_422(client, ik_headers):
    yanit = await client.post(
        "/personnel", json={**ISCI, "tc_no": "10000000140"}, headers=ik_headers
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_duplicate_tckn_409(client, ik_headers):
    """⚠️ 409 statüsüne bakılır, DB SQLSTATE'ine değil (PG sürüm tuzağı)."""
    await client.post("/personnel", json={**ISCI, "tc_no": GECERLI_TCKN}, headers=ik_headers)
    yanit = await client.post(
        "/personnel",
        json={**ISCI, "full_name": "Başka", "tc_no": GECERLI_TCKN},
        headers=ik_headers,
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_var_olmayan_atanan_proje_404(client, ik_headers):
    yanit = await client.post(
        "/personnel",
        json={**ISCI, "assigned_project_id": str(uuid.uuid4())},
        headers=ik_headers,
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_bolum_dogru_projede_201(client, ik_headers, proje, bolum):
    yanit = await client.post(
        "/personnel",
        json={
            **ISCI,
            "assigned_project_id": str(proje.id),
            "assigned_section_id": str(bolum.id),
        },
        headers=ik_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["assigned_section_id"] == str(bolum.id)


# --- PATCH: taslağı yayına çevirme -------------------------------------------


@pytest.mark.asyncio
async def test_patch_taslagi_yayina_cevirir(client, ik_headers, proje):
    taslak = await client.post("/personnel", json=ISCI, headers=ik_headers)
    kimlik = taslak.json()["id"]
    yanit = await client.patch(
        f"/personnel/{kimlik}",
        json={
            "tc_no": GECERLI_TCKN,
            "birth_date": "1990-01-01",
            "phone": "5551112233",
            "address": "Adres",
            "emergency_contact_name": "Yakın",
            "emergency_contact_phone": "5559998877",
            "hire_date": "2026-01-01",
            "assigned_project_id": str(proje.id),
            "wage_type": "daily",
            "wage_amount": "1500.00",
            "is_draft": False,
        },
        headers=ik_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["is_draft"] is False


@pytest.mark.asyncio
async def test_patch_eksik_yayina_cevirme_422(client, ik_headers):
    taslak = await client.post("/personnel", json=ISCI, headers=ik_headers)
    kimlik = taslak.json()["id"]
    yanit = await client.patch(f"/personnel/{kimlik}", json={"is_draft": False}, headers=ik_headers)
    assert yanit.status_code == 422, yanit.text


# --- Liste: ?project_id= süzgeci + IDOR --------------------------------------


@pytest.mark.asyncio
async def test_liste_project_id_suzgeci(client, ik_headers, proje):
    await client.post("/personnel", json=_tam(str(proje.id)), headers=ik_headers)
    await client.post("/personnel", json={**ISCI, "full_name": "Atamasız İşçi"}, headers=ik_headers)
    yanit = await client.get("/personnel", params={"project_id": str(proje.id)}, headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert [k["full_name"] for k in govde["items"]] == ["Ahmet Yılmaz"]
    assert govde["total"] == 1


@pytest.mark.asyncio
async def test_liste_is_draft_suzgeci(client, ik_headers, proje):
    await client.post("/personnel", json=_tam(str(proje.id)), headers=ik_headers)  # yayın
    await client.post(
        "/personnel", json={**ISCI, "full_name": "Taslak İşçi"}, headers=ik_headers
    )  # taslak
    taslaklar = await client.get("/personnel", params={"is_draft": True}, headers=ik_headers)
    assert [k["full_name"] for k in taslaklar.json()["items"]] == ["Taslak İşçi"]


@pytest.mark.asyncio
async def test_project_id_suzgeci_yetki_genisletmez_idor(
    client, ik_headers, kisitli_ik_headers, proje
):
    """`?project_id=` yalnız SÜZGEÇtir; `personnel` şirket-geneli varlıktır.

    Kapsamı alakasız bir projeyle sınırlanmış İK kullanıcısı, `project_id` süzgeciyle
    başka bir projeye atanmış personeli GÖREBİLİR — süzgeç yetki kapısı DEĞİLDİR.
    """
    await client.post("/personnel", json=_tam(str(proje.id)), headers=ik_headers)
    yanit = await client.get(
        "/personnel", params={"project_id": str(proje.id)}, headers=kisitli_ik_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 1
