"""P8 T2 — `customers` uçları (spec §2, §4, §6).

Kapsam: `GET /customers` (+ arama), `POST /customers`, `GET /customers/{id}`,
`PATCH /customers/{id}`. DELETE ucu YOKTUR (spec §4: satış kaydı bağlı olabilir).

Mockup `Form - Daire Satisi.dc.html`:
- 70 "Alıcı Tipi" (Gerçek Kişi / Tüzel Kişi)
- 71 "Ad Soyad / Ünvan *"
- 72 "TCKN / VKN *"  — TEK alan; tipe göre biri doldurulur
- 73 "Telefon" · 74 "E-posta" · 76 "Adres"
"""

import uuid

import pytest

from app.modules.customers.guards import CUSTOMER_MISSING

GERCEK_KISI = {
    "customer_type": "person",
    "name": "Serkan Öz",
    "national_id": "12345678901",
    "phone": "0532 123 45 67",
    "email": "serkan@example.com",
    "address": "Kadıköy / İstanbul",
}

TUZEL_KISI = {
    "customer_type": "company",
    "name": "Aksoy Yapı A.Ş.",
    "tax_number": "1234567890",
}


async def _olustur(client, headers, govde: dict) -> dict:
    yanit = await client.post("/customers", json=govde, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


# --- POST mutlu yollar ---


@pytest.mark.asyncio
async def test_gercek_kisi_olusturma(client, admin_headers):
    govde = await _olustur(client, admin_headers, GERCEK_KISI)
    assert govde["customer_type"] == "person"
    assert govde["name"] == "Serkan Öz"
    assert govde["national_id"] == "12345678901"
    assert govde["tax_number"] is None
    assert govde["phone"] == "0532 123 45 67"
    assert govde["email"] == "serkan@example.com"
    assert govde["address"] == "Kadıköy / İstanbul"


@pytest.mark.asyncio
async def test_tuzel_kisi_olusturma(client, admin_headers):
    govde = await _olustur(client, admin_headers, TUZEL_KISI)
    assert govde["customer_type"] == "company"
    assert govde["tax_number"] == "1234567890"
    assert govde["national_id"] is None


# --- Tip-alan uyuşmazlığı (spec §2 "tip başına biri dolu") ---


@pytest.mark.asyncio
async def test_gercek_kiside_tckn_zorunlu_422(client, admin_headers):
    yanit = await client.post(
        "/customers",
        json={"customer_type": "person", "name": "TCKN'siz"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_tuzel_kiside_vkn_zorunlu_422(client, admin_headers):
    yanit = await client.post(
        "/customers",
        json={"customer_type": "company", "name": "VKN'siz Ltd"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_gercek_kiside_vkn_dolu_422(client, admin_headers):
    """Mockup 72'de TEK bir "TCKN / VKN" alanı var — iki alanın birden dolu

    gelmesi istemci hatasıdır; sessizce temizlenmez, 422 döner.
    """
    yanit = await client.post(
        "/customers",
        json={**GERCEK_KISI, "tax_number": "1234567890"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_tuzel_kiside_tckn_dolu_422(client, admin_headers):
    yanit = await client.post(
        "/customers",
        json={**TUZEL_KISI, "national_id": "12345678901"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_tip_degisiminde_kalan_alan_422(client, admin_headers):
    """PATCH ile tip değişirse doğrulama BİRLEŞİK kayıt üzerinde koşar:

    `person` -> `company` derken TCKN temizlenmediyse 422.
    """
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.patch(
        f"/customers/{musteri['id']}",
        json={"customer_type": "company", "tax_number": "1234567890"},
        headers=admin_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_tip_degisimi_alanlar_birlikte_gonderilirse_gecerli(client, admin_headers):
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.patch(
        f"/customers/{musteri['id']}",
        json={"customer_type": "company", "national_id": None, "tax_number": "1234567890"},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["national_id"] is None
    assert yanit.json()["tax_number"] == "1234567890"


# --- Benzersizlik (409) ---


@pytest.mark.asyncio
async def test_ayni_tckn_409(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.post(
        "/customers", json={**GERCEK_KISI, "name": "Başka Kişi"}, headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_ayni_vkn_409(client, admin_headers):
    await _olustur(client, admin_headers, TUZEL_KISI)
    yanit = await client.post(
        "/customers", json={**TUZEL_KISI, "name": "Başka Ltd"}, headers=admin_headers
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_guncellemede_tckn_cakismasi_409(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    ikinci = await _olustur(
        client, admin_headers, {**GERCEK_KISI, "name": "İkinci", "national_id": "99999999999"}
    )
    yanit = await client.patch(
        f"/customers/{ikinci['id']}",
        json={"national_id": "12345678901"},
        headers=admin_headers,
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_kendi_tcknsini_yeniden_gondermek_409_degil(client, admin_headers):
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.patch(
        f"/customers/{musteri['id']}",
        json={"national_id": "12345678901", "name": "Serkan Öz (düzeltme)"},
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text


# --- Liste + arama ---


@pytest.mark.asyncio
async def test_liste_ada_gore_siralanir(client, admin_headers):
    await _olustur(client, admin_headers, TUZEL_KISI)
    await _olustur(client, admin_headers, GERCEK_KISI)
    govde = (await client.get("/customers", headers=admin_headers)).json()
    isimler = [m["name"] for m in govde["items"]]
    assert isimler == sorted(isimler)
    assert {"Serkan Öz", "Aksoy Yapı A.Ş."} <= set(isimler)


@pytest.mark.asyncio
async def test_ada_gore_arama_kismi_ve_buyuk_kucuk_harf_duyarsiz(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    await _olustur(client, admin_headers, TUZEL_KISI)
    yanit = await client.get("/customers?q=serkan", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    isimler = [m["name"] for m in yanit.json()["items"]]
    assert isimler == ["Serkan Öz"]


@pytest.mark.asyncio
async def test_tckn_ile_arama_kismi(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    await _olustur(client, admin_headers, TUZEL_KISI)
    yanit = await client.get("/customers?q=345678901", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    isimler = [m["name"] for m in yanit.json()["items"]]
    assert isimler == ["Serkan Öz"]


@pytest.mark.asyncio
async def test_vkn_ile_arama_kismi(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    await _olustur(client, admin_headers, TUZEL_KISI)
    yanit = await client.get("/customers?q=1234567890", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    isimler = {m["name"] for m in yanit.json()["items"]}
    # TCKN "12345678901" de bu deseni İÇERİR — arama üç kolonda da OR'lanır.
    assert isimler == {"Aksoy Yapı A.Ş.", "Serkan Öz"}


@pytest.mark.asyncio
async def test_eslesmeyen_arama_bos_liste(client, admin_headers):
    await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.get("/customers?q=bulunmayan", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["items"] == []


# --- Detay + kısmi güncelleme ---


@pytest.mark.asyncio
async def test_detay_getir(client, admin_headers):
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.get(f"/customers/{musteri['id']}", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["id"] == musteri["id"]


@pytest.mark.asyncio
async def test_var_olmayan_musteri_404(client, admin_headers):
    yanit = await client.get(f"/customers/{uuid.uuid4()}", headers=admin_headers)
    assert yanit.status_code == 404, yanit.text
    # Metin de doğrulanır: aksi hâlde "rota hiç yok" 404'ü testi yeşil gösterirdi.
    assert yanit.json()["detail"] == CUSTOMER_MISSING


@pytest.mark.asyncio
async def test_var_olmayan_musteriyi_guncelleme_404(client, admin_headers):
    yanit = await client.patch(
        f"/customers/{uuid.uuid4()}", json={"name": "X"}, headers=admin_headers
    )
    assert yanit.status_code == 404, yanit.text
    assert yanit.json()["detail"] == CUSTOMER_MISSING


@pytest.mark.asyncio
async def test_kismi_guncelleme_gonderilmeyen_alan_degismez(client, admin_headers):
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.patch(
        f"/customers/{musteri['id']}", json={"phone": "0533 111 11 11"}, headers=admin_headers
    )
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["phone"] == "0533 111 11 11"
    assert govde["name"] == "Serkan Öz"
    assert govde["national_id"] == "12345678901"
    assert govde["email"] == "serkan@example.com"


# --- Silme ucu AÇILMAZ (spec §4) ---


@pytest.mark.asyncio
async def test_silme_ucu_yok(client, admin_headers):
    musteri = await _olustur(client, admin_headers, GERCEK_KISI)
    yanit = await client.delete(f"/customers/{musteri['id']}", headers=admin_headers)
    assert yanit.status_code == 405, yanit.text


def test_openapi_customers_silme_yolu_icermez():
    from app.main import app

    yollar = app.openapi()["paths"]
    assert "/customers" in yollar
    assert "delete" not in yollar["/customers/{customer_id}"]
