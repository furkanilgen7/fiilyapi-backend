"""Puantaj T2 — `personnel` uçları: liste (arama + filtreler), POST, GET/PATCH.

Spec: `docs/superpowers/specs/2026-08-03-puantaj-design.md` §2, §3, §5.

Kapsam sınırları BİLİNÇLİDİR ve burada sınanır:
* **DELETE ucu YOKTUR** — pasifleştirme `PATCH {is_active: false}` ile yapılır;
* **proje süzgeci YOKTUR** — `personnel` şirket-geneli bir İK varlığıdır;
* `source != 'subcontractor'` iken `subcontractor_id` verilirse DB CHECK'e
  DÜŞMEDEN 422 (anlaşılır Türkçe mesaj).
"""

import uuid

import pytest

ISCI = {"full_name": "Ahmet Yılmaz", "trade": "Kalıpçı", "source": "company"}


async def _olustur(client, headers, **alanlar) -> dict:
    govde = {**ISCI, **alanlar}
    yanit = await client.post("/personnel", json=govde, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


# --- Oluşturma ---


@pytest.mark.asyncio
async def test_ik_personel_olusturur(client, ik_headers):
    kayit = await _olustur(client, ik_headers)
    assert kayit["full_name"] == "Ahmet Yılmaz"
    assert kayit["trade"] == "Kalıpçı"
    assert kayit["source"] == "company"
    assert kayit["subcontractor_id"] is None
    assert kayit["is_active"] is True


@pytest.mark.asyncio
async def test_taseron_kaynakli_personel_firmaya_baglanir(client, ik_headers, taseron):
    kayit = await _olustur(
        client, ik_headers, source="subcontractor", subcontractor_id=str(taseron.id)
    )
    assert kayit["subcontractor_id"] == str(taseron.id)


@pytest.mark.asyncio
async def test_ad_bos_olamaz_422(client, ik_headers):
    yanit = await client.post("/personnel", json={**ISCI, "full_name": ""}, headers=ik_headers)
    assert yanit.status_code == 422


# --- 422: kaynak/taşeron uyuşmazlığı (DB CHECK'e düşmeden) ---


@pytest.mark.asyncio
async def test_sirket_kaynakli_personele_taseron_verilemez_422(client, ik_headers, taseron):
    """CHECK ihlali 409 "Veri bütünlüğü hatası" verirdi — servis 422 + Türkçe mesaj verir."""
    yanit = await client.post(
        "/personnel",
        json={**ISCI, "source": "company", "subcontractor_id": str(taseron.id)},
        headers=ik_headers,
    )
    assert yanit.status_code == 422, yanit.text
    assert "taşeron" in yanit.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_ile_kaynak_taserondan_cikarken_taseron_bagi_kalamaz_422(
    client, ik_headers, taseron
):
    """Kural BİRLEŞİK kayıt üzerinde koşar: gövdede yalnız `source` gelse bile

    DB'deki `subcontractor_id` hesaba katılır (customers `guards` deseni).
    """
    kayit = await _olustur(
        client, ik_headers, source="subcontractor", subcontractor_id=str(taseron.id)
    )
    yanit = await client.patch(
        f"/personnel/{kayit['id']}", json={"source": "company"}, headers=ik_headers
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_patch_ile_kaynak_ve_taseron_birlikte_temizlenebilir(client, ik_headers, taseron):
    kayit = await _olustur(
        client, ik_headers, source="subcontractor", subcontractor_id=str(taseron.id)
    )
    yanit = await client.patch(
        f"/personnel/{kayit['id']}",
        json={"source": "company", "subcontractor_id": None},
        headers=ik_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["subcontractor_id"] is None


# --- Detay / güncelleme / 404 ---


@pytest.mark.asyncio
async def test_detay_donulur(client, ik_headers):
    kayit = await _olustur(client, ik_headers)
    yanit = await client.get(f"/personnel/{kayit['id']}", headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["id"] == kayit["id"]


@pytest.mark.asyncio
async def test_var_olmayan_personel_detayda_404(client, ik_headers):
    yanit = await client.get(f"/personnel/{uuid.uuid4()}", headers=ik_headers)
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_var_olmayan_personel_guncellemede_404(client, ik_headers):
    yanit = await client.patch(
        f"/personnel/{uuid.uuid4()}", json={"full_name": "X"}, headers=ik_headers
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_kismi_guncelleme_gonderilmeyen_alani_degistirmez(client, ik_headers):
    kayit = await _olustur(client, ik_headers)
    yanit = await client.patch(
        f"/personnel/{kayit['id']}", json={"trade": "Demirci"}, headers=ik_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["trade"] == "Demirci"
    assert yanit.json()["full_name"] == "Ahmet Yılmaz"


# --- Silme YOK, pasifleştirme var ---


@pytest.mark.asyncio
async def test_silme_ucu_yoktur_405(client, ik_headers):
    """Puantaj kayıtları personele bağlıdır (FK RESTRICT) — silme AÇILMAZ (spec §3)."""
    kayit = await _olustur(client, ik_headers)
    yanit = await client.delete(f"/personnel/{kayit['id']}", headers=ik_headers)
    assert yanit.status_code == 405, yanit.text


@pytest.mark.asyncio
async def test_pasiflestirme_patch_ile_yapilir(client, ik_headers):
    kayit = await _olustur(client, ik_headers)
    yanit = await client.patch(
        f"/personnel/{kayit['id']}", json={"is_active": False}, headers=ik_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["is_active"] is False


# --- Liste: arama + filtreler + sayfalama ---


@pytest.mark.asyncio
async def test_liste_ada_gore_arar(client, ik_headers):
    await _olustur(client, ik_headers, full_name="Ahmet Yılmaz")
    await _olustur(client, ik_headers, full_name="Mehmet Kaya")
    yanit = await client.get("/personnel", params={"q": "mehmet"}, headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert [k["full_name"] for k in govde["items"]] == ["Mehmet Kaya"]
    assert govde["total"] == 1


@pytest.mark.asyncio
async def test_liste_source_filtreler(client, ik_headers, taseron):
    await _olustur(client, ik_headers, full_name="Şirket İşçisi", source="company")
    await _olustur(
        client,
        ik_headers,
        full_name="Taşeron İşçisi",
        source="subcontractor",
        subcontractor_id=str(taseron.id),
    )
    yanit = await client.get("/personnel", params={"source": "subcontractor"}, headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    assert [k["full_name"] for k in yanit.json()["items"]] == ["Taşeron İşçisi"]


@pytest.mark.asyncio
async def test_liste_subcontractor_id_filtreler(client, ik_headers, taseron):
    await _olustur(client, ik_headers, full_name="Şirket İşçisi", source="company")
    await _olustur(
        client,
        ik_headers,
        full_name="Taşeron İşçisi",
        source="subcontractor",
        subcontractor_id=str(taseron.id),
    )
    yanit = await client.get(
        "/personnel", params={"subcontractor_id": str(taseron.id)}, headers=ik_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert [k["full_name"] for k in yanit.json()["items"]] == ["Taşeron İşçisi"]


@pytest.mark.asyncio
async def test_liste_is_active_filtreler(client, ik_headers):
    aktif = await _olustur(client, ik_headers, full_name="Aktif İşçi")
    pasif = await _olustur(client, ik_headers, full_name="Pasif İşçi")
    await client.patch(f"/personnel/{pasif['id']}", json={"is_active": False}, headers=ik_headers)

    aktifler = await client.get("/personnel", params={"is_active": True}, headers=ik_headers)
    assert [k["id"] for k in aktifler.json()["items"]] == [aktif["id"]]

    pasifler = await client.get("/personnel", params={"is_active": False}, headers=ik_headers)
    assert [k["id"] for k in pasifler.json()["items"]] == [pasif["id"]]


@pytest.mark.asyncio
async def test_liste_varsayilanda_pasifleri_de_dondurur(client, ik_headers):
    """`is_active` GÖNDERİLMEZSE süzgeç uygulanmaz — pasif kayıt sessizce saklanmaz."""
    await _olustur(client, ik_headers, full_name="Aktif İşçi")
    pasif = await _olustur(client, ik_headers, full_name="Pasif İşçi")
    await client.patch(f"/personnel/{pasif['id']}", json={"is_active": False}, headers=ik_headers)
    yanit = await client.get("/personnel", headers=ik_headers)
    assert yanit.json()["total"] == 2


@pytest.mark.asyncio
async def test_liste_sayfalanir(client, ik_headers):
    for ad in ("Ali", "Bora", "Cem"):
        await _olustur(client, ik_headers, full_name=ad)
    yanit = await client.get("/personnel", params={"limit": 2, "offset": 1}, headers=ik_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 3
    assert govde["limit"] == 2
    assert govde["offset"] == 1
    assert [k["full_name"] for k in govde["items"]] == ["Bora", "Cem"]


# --- BİLİNÇLİ KARAR: proje süzgeci YOK ---


@pytest.mark.asyncio
async def test_personel_listesi_sirket_genelidir_proje_suzgeci_uygulanmaz(
    client, ik_headers, kisitli_ik_headers
):
    """`personnel` bir İK varlığıdır, projeye ait DEĞİLDİR (spec §3).

    `user_project_access`i tek (ve alakasız) bir projeyle sınırlanmış İK
    kullanıcısı da TÜM personeli görür. IDOR unutulmuş DEĞİLDİR — tabloda
    `project_id` kolonu bile yoktur; sonraki okuyucu buraya proje süzgeci
    EKLEMESİN.
    """
    await _olustur(client, ik_headers, full_name="Ahmet Yılmaz")
    yanit = await client.get("/personnel", headers=kisitli_ik_headers)
    assert yanit.status_code == 200, yanit.text
    assert [k["full_name"] for k in yanit.json()["items"]] == ["Ahmet Yılmaz"]
