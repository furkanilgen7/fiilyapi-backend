"""ST T2 — malzeme kartı (katalog) uçları: liste / POST / PATCH.

Spec: `docs/superpowers/specs/2026-08-11-st-stok-cekirdegi-design.md` §2, §4.

Bu dosyanın DONDURDUĞU kararlar:
1. **`code` GLOBAL tekildir** ve ihlali **409**'dur — 500 ya da anlaşılmaz bir
   "Veri bütünlüğü hatası" değil. Aynı kural PATCH'te de geçerlidir.
2. **DELETE ucu YOKTUR** (spec §4): hareketi olan kart `stock_entry_lines`
   RESTRICT'i yüzünden zaten silinemez; kullanımdan kaldırma
   `PATCH {"is_active": false}` iledir. 405 bekçisi bu kararı KİLİTLER.
3. **`visible_projects` süzgeci YOKTUR**: katalog şirket-genelidir, tabloda
   `project_id` kolonu bile yoktur (`personnel` deseni). Proje kapsamı yalnız
   DEPOLARA uygulanır.
"""

import uuid

import pytest

KART = {"code": "SNK-0421", "name": "Nervürlü Demir Ø12", "category": "steel", "unit": "Ton"}


async def _olustur(client, headers, **alanlar) -> dict:
    govde = {**KART, **alanlar}
    yanit = await client.post("/stock/items", json=govde, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


# --- Oluşturma ---


@pytest.mark.asyncio
async def test_kart_olusturulur(client, satinalma_headers):
    kart = await _olustur(client, satinalma_headers)
    assert kart["code"] == "SNK-0421"
    assert kart["name"] == "Nervürlü Demir Ø12"
    assert kart["category"] == "steel"
    assert kart["unit"] == "Ton"
    assert kart["min_stock"] is None
    assert kart["is_active"] is True


@pytest.mark.asyncio
async def test_min_stok_esigi_saklanir(client, satinalma_headers):
    kart = await _olustur(client, satinalma_headers, min_stock="10.000")
    assert kart["min_stock"] == "10.000"


@pytest.mark.asyncio
async def test_min_stok_negatif_olamaz_422(client, satinalma_headers):
    """Negatif eşik durum formülünü (spec §3) anlamsız kılardı."""
    yanit = await client.post(
        "/stock/items", json={**KART, "min_stock": "-1"}, headers=satinalma_headers
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_birim_serbest_metindir(client, satinalma_headers):
    """`unit` enum DEĞİLDİR (spec §2): mockup kümesi açık uçludur, yeni bir birim
    migration gerektirmemelidir."""
    kart = await _olustur(client, satinalma_headers, code="OZL-0001", unit="m³")
    assert kart["unit"] == "m³"


@pytest.mark.asyncio
async def test_kategori_kapali_kumedir_422(client, satinalma_headers):
    yanit = await client.post(
        "/stock/items", json={**KART, "category": "uydurma"}, headers=satinalma_headers
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_bos_kod_reddedilir_422(client, satinalma_headers):
    yanit = await client.post("/stock/items", json={**KART, "code": ""}, headers=satinalma_headers)
    assert yanit.status_code == 422, yanit.text


# --- 409: kod tekilliği ---


@pytest.mark.asyncio
async def test_ayni_kod_ikinci_kez_409(client, satinalma_headers):
    """DB `UNIQUE` ihlali kullanıcıya 500 ya da anlaşılmaz 409 olarak DÜŞMEZ:
    servis açık kontrolle alanına özel Türkçe mesaj verir."""
    await _olustur(client, satinalma_headers)
    yanit = await client.post("/stock/items", json=KART, headers=satinalma_headers)
    assert yanit.status_code == 409, yanit.text
    assert "kod" in yanit.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_ile_baskasinin_koduna_gecilemez_409(client, satinalma_headers):
    await _olustur(client, satinalma_headers, code="SNK-0421")
    ikinci = await _olustur(client, satinalma_headers, code="SNK-0108", name="CTP32,5 Çimento")
    yanit = await client.patch(
        f"/stock/items/{ikinci['id']}", json={"code": "SNK-0421"}, headers=satinalma_headers
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_patch_ile_ayni_kod_yeniden_gonderilebilir(client, satinalma_headers):
    """Kaydın KENDİSİ çakışma sayılmaz — aksi hâlde aynı kodla ikinci kez
    "Kaydet" basmak 409 verirdi."""
    kart = await _olustur(client, satinalma_headers)
    yanit = await client.patch(
        f"/stock/items/{kart['id']}",
        json={"code": "SNK-0421", "name": "Nervürlü Demir Ø14"},
        headers=satinalma_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["name"] == "Nervürlü Demir Ø14"


# --- Güncelleme / 404 ---


@pytest.mark.asyncio
async def test_kismi_guncelleme_gonderilmeyen_alani_degistirmez(client, satinalma_headers):
    kart = await _olustur(client, satinalma_headers, min_stock="10.000")
    yanit = await client.patch(
        f"/stock/items/{kart['id']}", json={"name": "Nervürlü Demir Ø16"}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["name"] == "Nervürlü Demir Ø16"
    assert govde["code"] == "SNK-0421"
    assert govde["min_stock"] == "10.000"


@pytest.mark.asyncio
async def test_min_stok_null_ile_temizlenebilir(client, satinalma_headers):
    """Eşik silinince durum `None` olur (spec §3: uydurma yok)."""
    kart = await _olustur(client, satinalma_headers, min_stock="10.000")
    yanit = await client.patch(
        f"/stock/items/{kart['id']}", json={"min_stock": None}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["min_stock"] is None


@pytest.mark.asyncio
async def test_var_olmayan_kart_guncellemede_404(client, satinalma_headers):
    yanit = await client.patch(
        f"/stock/items/{uuid.uuid4()}", json={"name": "X"}, headers=satinalma_headers
    )
    assert yanit.status_code == 404, yanit.text


# --- Silme YOK, pasifleştirme var ---


@pytest.mark.asyncio
async def test_silme_ucu_yoktur_405(client, admin_headers, satinalma_headers):
    """Spec §4: hareketi olan kart silinemez, kullanımdan kaldırma
    `is_active=false` iledir. Yol TANIMLI DEĞİLDİR, bu yüzden en yetkili
    kullanıcı (`inventory=_A`) bile 405 alır — bu bekçi, ileride birinin DELETE
    ucu eklemesi hâlinde kırılmak İÇİN vardır."""
    kart = await _olustur(client, satinalma_headers)
    yanit = await client.delete(f"/stock/items/{kart['id']}", headers=admin_headers)
    assert yanit.status_code == 405, yanit.text


@pytest.mark.asyncio
async def test_pasiflestirme_patch_ile_yapilir(client, satinalma_headers):
    kart = await _olustur(client, satinalma_headers)
    yanit = await client.patch(
        f"/stock/items/{kart['id']}", json={"is_active": False}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["is_active"] is False


# --- Liste: filtreler + arama + sayfalama ---


@pytest.mark.asyncio
async def test_liste_kategoriye_gore_suzulur(client, satinalma_headers):
    await _olustur(client, satinalma_headers, code="SNK-0421", category="steel")
    await _olustur(
        client, satinalma_headers, code="SNK-0108", name="CTP32,5 Çimento", category="structural"
    )
    yanit = await client.get(
        "/stock/items", params={"category": "structural"}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert [k["code"] for k in yanit.json()["items"]] == ["SNK-0108"]


@pytest.mark.asyncio
async def test_liste_q_hem_kodda_hem_adda_arar(client, satinalma_headers):
    await _olustur(client, satinalma_headers, code="SNK-0421", name="Nervürlü Demir Ø12")
    await _olustur(client, satinalma_headers, code="ELK-0334", name="NYY 4x16 Kablo")

    adla = await client.get("/stock/items", params={"q": "kablo"}, headers=satinalma_headers)
    assert [k["code"] for k in adla.json()["items"]] == ["ELK-0334"]

    kodla = await client.get("/stock/items", params={"q": "snk"}, headers=satinalma_headers)
    assert [k["code"] for k in kodla.json()["items"]] == ["SNK-0421"]


@pytest.mark.asyncio
async def test_arama_joker_karakteri_metin_olarak_arar(client, satinalma_headers):
    """`%` kaçırılmazsa arama kutusuna yüzde işareti yazan kullanıcı TÜM
    kataloğu görürdü — serbest metin aradığını sanarak."""
    await _olustur(client, satinalma_headers, code="SNK-0421")
    yanit = await client.get("/stock/items", params={"q": "%"}, headers=satinalma_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0


@pytest.mark.asyncio
async def test_liste_is_active_suzgeci(client, satinalma_headers):
    aktif = await _olustur(client, satinalma_headers, code="SNK-0421")
    pasif = await _olustur(client, satinalma_headers, code="SNK-0108", name="CTP32,5 Çimento")
    await client.patch(
        f"/stock/items/{pasif['id']}", json={"is_active": False}, headers=satinalma_headers
    )

    aktifler = await client.get(
        "/stock/items", params={"is_active": True}, headers=satinalma_headers
    )
    assert [k["id"] for k in aktifler.json()["items"]] == [aktif["id"]]

    pasifler = await client.get(
        "/stock/items", params={"is_active": False}, headers=satinalma_headers
    )
    assert [k["id"] for k in pasifler.json()["items"]] == [pasif["id"]]


@pytest.mark.asyncio
async def test_liste_varsayilanda_pasifleri_de_dondurur(client, satinalma_headers):
    """`is_active` GÖNDERİLMEZSE süzgeç uygulanmaz — pasif kart sessizce
    gizlenmez; ekran hangi kümeyi istediğini açıkça söyler (`personnel` deseni)."""
    await _olustur(client, satinalma_headers, code="SNK-0421")
    pasif = await _olustur(client, satinalma_headers, code="SNK-0108", name="CTP32,5 Çimento")
    await client.patch(
        f"/stock/items/{pasif['id']}", json={"is_active": False}, headers=satinalma_headers
    )
    yanit = await client.get("/stock/items", headers=satinalma_headers)
    assert yanit.json()["total"] == 2


@pytest.mark.asyncio
async def test_liste_sayfalanir(client, satinalma_headers):
    for kod, ad in (("A-1", "Alçı"), ("B-1", "Boya"), ("C-1", "Cam")):
        await _olustur(client, satinalma_headers, code=kod, name=ad)
    yanit = await client.get(
        "/stock/items", params={"limit": 2, "offset": 1}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 3
    assert govde["limit"] == 2
    assert govde["offset"] == 1
    assert [k["name"] for k in govde["items"]] == ["Boya", "Cam"]


@pytest.mark.asyncio
async def test_limit_tavani_asilamaz_422(client, satinalma_headers):
    """TB3 korkuluğu: tavan aşımı sessizce kırpılmaz, 422 döner."""
    yanit = await client.get("/stock/items", params={"limit": 201}, headers=satinalma_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_liste_varsayilan_limit_50(client, satinalma_headers):
    yanit = await client.get("/stock/items", headers=satinalma_headers)
    assert yanit.json()["limit"] == 50


# --- BİLİNÇLİ KARAR: katalogda proje süzgeci YOK ---


@pytest.mark.asyncio
async def test_katalog_sirket_genelidir_proje_suzgeci_uygulanmaz(
    client, admin_headers, satinalma_headers
):
    """Katalogda `project_id` kolonu YOKTUR (spec §2): aynı malzeme kartı her
    projede kullanılır. Kapsamı tek projeye kısıtlı satınalma kullanıcısı da,
    tüm projeleri gören yönetici de AYNI kataloğu görür. IDOR unutulmuş
    DEĞİLDİR — proje kapsamı yalnız DEPOLARA uygulanır."""
    await _olustur(client, admin_headers, code="SNK-0421")
    yanit = await client.get("/stock/items", headers=satinalma_headers)
    assert yanit.status_code == 200, yanit.text
    assert [k["code"] for k in yanit.json()["items"]] == ["SNK-0421"]
