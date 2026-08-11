"""ST T2 — depo uçları: liste / POST / PATCH / DELETE.

Spec: `docs/superpowers/specs/2026-08-11-st-stok-cekirdegi-design.md` §2, §4, §7 S2.

Bu dosyanın DONDURDUĞU kararlar:
1. **Ad tekilliği UYGULAMA katmanındadır.** `uq_warehouses_site_name` Postgres'in
   varsayılan `NULLS DISTINCT` semantiği yüzünden MERKEZ depolarda
   (`site_id IS NULL`) fiilen ÇALIŞMAZ (T1 notu, `document_folders` ile aynı
   durum). İki dal da AYRI AYRI sınanır — biri düşerse tekillik o daldan
   tamamen kaybolur.
2. **Merkez depo (§7 S2b) proje kapsamına TABİ DEĞİLDİR:** `inventory` izni olan
   herkes görür. Şantiyeli depo ise `visible_projects` süzgecinden geçer.
3. **DELETE yalnız hareketsizken ve yalnız `admin` seviyesinde.** Hareketi olan
   depo 409 döner — `stock_entries.warehouse_id` FK'si RESTRICT'tir ve korkuluk
   olmasa kullanıcı anlaşılmaz bir "Veri bütünlüğü hatası" görürdü. Kaynak depo
   bacağı (`source_warehouse_id`) da AYNI korumadadır.
"""

import uuid
from datetime import date

import pytest

from app.modules.inventory.models import StockEntry, StockEntryType

MERKEZ = {"name": "Merkez Depo (Sincan)"}


async def _olustur(client, headers, **alanlar) -> dict:
    govde = {**MERKEZ, **alanlar}
    yanit = await client.post("/warehouses", json=govde, headers=headers)
    assert yanit.status_code == 201, yanit.text
    return yanit.json()


# --- Oluşturma ---


@pytest.mark.asyncio
async def test_merkez_depo_santiyesiz_acilir(client, satinalma_headers):
    """SG 84 "Merkez Depo (Sincan)": hiçbir şantiyeye bağlı değildir."""
    depo = await _olustur(client, satinalma_headers)
    assert depo["name"] == "Merkez Depo (Sincan)"
    assert depo["site_id"] is None


@pytest.mark.asyncio
async def test_santiyeli_depo_acilir(client, satinalma_headers, gorunen_santiye):
    depo = await _olustur(
        client, satinalma_headers, name="D-1 Ambar", site_id=str(gorunen_santiye.id)
    )
    assert depo["site_id"] == str(gorunen_santiye.id)


@pytest.mark.asyncio
async def test_gorunmeyen_santiyeye_depo_acilamaz_422(
    client, satinalma_headers, gorunmeyen_santiye
):
    """Kapsam dışı `site_id` gövdedeki düzeltilebilir bir ALAN DEĞERİDİR (422),
    404 değil — ve mesajı VAR OLMAYAN kimliğinkiyle AYNIDIR, kimlik varlığı
    sızdırılmaz (`documents.SITE_NOT_IN_PROJECT` gerekçesi)."""
    yanit = await client.post(
        "/warehouses",
        json={"name": "D-9 Ambar", "site_id": str(gorunmeyen_santiye.id)},
        headers=satinalma_headers,
    )
    assert yanit.status_code == 422, yanit.text
    olmayan = await client.post(
        "/warehouses",
        json={"name": "D-9 Ambar", "site_id": str(uuid.uuid4())},
        headers=satinalma_headers,
    )
    assert olmayan.status_code == 422, olmayan.text
    assert olmayan.json()["detail"] == yanit.json()["detail"]


# --- 409: ad tekilliği (İKİ DAL) ---


@pytest.mark.asyncio
async def test_ayni_santiyede_ayni_ad_409(client, satinalma_headers, gorunen_santiye):
    await _olustur(client, satinalma_headers, name="D-1 Ambar", site_id=str(gorunen_santiye.id))
    yanit = await client.post(
        "/warehouses",
        json={"name": "D-1 Ambar", "site_id": str(gorunen_santiye.id)},
        headers=satinalma_headers,
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_merkez_dalinda_da_ayni_ad_409(client, satinalma_headers):
    """⚠️ DB KISITI BU DALDA ÇALIŞMAZ (`NULLS DISTINCT`): tek savunma servis
    korkuluğudur. Bu test kaldırılırsa aynı adlı iki merkez depo sessizce açılır."""
    await _olustur(client, satinalma_headers)
    yanit = await client.post("/warehouses", json=MERKEZ, headers=satinalma_headers)
    assert yanit.status_code == 409, yanit.text
    assert "depo" in yanit.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ayni_ad_farkli_santiyede_serbesttir(
    client, admin_headers, gorunen_santiye, gorunmeyen_santiye
):
    """Tekillik KAPSAM İÇİNDEDİR: "D-1 Ambar" her şantiyede olabilir."""
    await _olustur(client, admin_headers, name="D-1 Ambar", site_id=str(gorunen_santiye.id))
    ikinci = await _olustur(
        client, admin_headers, name="D-1 Ambar", site_id=str(gorunmeyen_santiye.id)
    )
    assert ikinci["site_id"] == str(gorunmeyen_santiye.id)


@pytest.mark.asyncio
async def test_merkez_ile_santiyeli_ayni_adi_tasiyabilir(
    client, satinalma_headers, gorunen_santiye
):
    """Merkez depo ile şantiye deposu FARKLI kapsamlardır."""
    await _olustur(client, satinalma_headers, name="Ana Ambar")
    ikinci = await _olustur(
        client, satinalma_headers, name="Ana Ambar", site_id=str(gorunen_santiye.id)
    )
    assert ikinci["site_id"] == str(gorunen_santiye.id)


# --- PATCH ---


@pytest.mark.asyncio
async def test_depo_adi_degistirilir(client, satinalma_headers):
    depo = await _olustur(client, satinalma_headers)
    yanit = await client.patch(
        f"/warehouses/{depo['id']}", json={"name": "Merkez Ambar"}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["name"] == "Merkez Ambar"


@pytest.mark.asyncio
async def test_patch_ad_cakismasi_409_merkez_dalinda(client, satinalma_headers):
    await _olustur(client, satinalma_headers, name="Ana Ambar")
    ikinci = await _olustur(client, satinalma_headers, name="Yedek Ambar")
    yanit = await client.patch(
        f"/warehouses/{ikinci['id']}", json={"name": "Ana Ambar"}, headers=satinalma_headers
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_patch_ad_cakismasi_409_santiye_dalinda(client, satinalma_headers, gorunen_santiye):
    await _olustur(client, satinalma_headers, name="D-1 Ambar", site_id=str(gorunen_santiye.id))
    ikinci = await _olustur(
        client, satinalma_headers, name="D-2 Açık Alan", site_id=str(gorunen_santiye.id)
    )
    yanit = await client.patch(
        f"/warehouses/{ikinci['id']}", json={"name": "D-1 Ambar"}, headers=satinalma_headers
    )
    assert yanit.status_code == 409, yanit.text


@pytest.mark.asyncio
async def test_patch_ayni_adi_yeniden_gonderebilir(client, satinalma_headers):
    depo = await _olustur(client, satinalma_headers)
    yanit = await client.patch(
        f"/warehouses/{depo['id']}", json={"name": MERKEZ["name"]}, headers=satinalma_headers
    )
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_patch_kapsam_degistiremez(client, satinalma_headers, gorunen_santiye):
    """`site_id` PATCH gövdesinde YOKTUR (spec §4 sessiz, `documents` deseni):
    kapsam değişimi bir IDOR yüzeyidir ve hiçbir mockup istemez. Alan gönderilse
    bile sessizce yok sayılır — depo merkez kalır."""
    depo = await _olustur(client, satinalma_headers)
    yanit = await client.patch(
        f"/warehouses/{depo['id']}",
        json={"name": "Merkez Ambar", "site_id": str(gorunen_santiye.id)},
        headers=satinalma_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["site_id"] is None


@pytest.mark.asyncio
async def test_var_olmayan_depo_patchte_404(client, satinalma_headers):
    yanit = await client.patch(
        f"/warehouses/{uuid.uuid4()}", json={"name": "X"}, headers=satinalma_headers
    )
    assert yanit.status_code == 404, yanit.text


# --- DELETE ---


@pytest.mark.asyncio
async def test_hareketsiz_depo_silinir(client, admin_headers):
    depo = await _olustur(client, admin_headers)
    yanit = await client.delete(f"/warehouses/{depo['id']}", headers=admin_headers)
    assert yanit.status_code == 204, yanit.text
    kalan = await client.get("/warehouses", headers=admin_headers)
    assert kalan.json()["total"] == 0


@pytest.mark.asyncio
async def test_hareketi_olan_depo_409(client, admin_headers, seeded_db):
    """`stock_entries.warehouse_id` FK'si RESTRICT'tir; korkuluk olmasaydı
    kullanıcı anlaşılmaz bir "Veri bütünlüğü hatası" görürdü."""
    depo = await _olustur(client, admin_headers)
    seeded_db.add(
        StockEntry(
            entry_type=StockEntryType.purchase,
            entry_date=date(2026, 8, 11),
            warehouse_id=uuid.UUID(depo["id"]),
        )
    )
    await seeded_db.flush()
    yanit = await client.delete(f"/warehouses/{depo['id']}", headers=admin_headers)
    assert yanit.status_code == 409, yanit.text
    assert "hareket" in yanit.json()["detail"].lower()


@pytest.mark.asyncio
async def test_kaynak_depo_bacagi_da_engeller_409(client, admin_headers, seeded_db):
    """Transfer'in KAYNAK bacağı (`source_warehouse_id`) de hareket sayılır.

    ⚠️ **Kod DEĞİL METİN sınanır** (mutasyon denetimi bulgusu): kaynak bacağı
    korkuluktan çıkarılsa bile DB'nin `RESTRICT`i `IntegrityError` → 409
    üretirdi, yani yalnız durum koduna bakan bir iddia YANLIŞ SEBEPLE yeşil
    kalırdı. Kullanıcı o hâlde eyleme dönük cümle yerine "Veri bütünlüğü hatası"
    görür — bu yüzden mesajın kendisi iddiaya girer.
    """
    kaynak = await _olustur(client, admin_headers, name="Kaynak Ambar")
    hedef = await _olustur(client, admin_headers, name="Hedef Ambar")
    seeded_db.add(
        StockEntry(
            entry_type=StockEntryType.transfer,
            entry_date=date(2026, 8, 11),
            warehouse_id=uuid.UUID(hedef["id"]),
            source_warehouse_id=uuid.UUID(kaynak["id"]),
        )
    )
    await seeded_db.flush()
    yanit = await client.delete(f"/warehouses/{kaynak['id']}", headers=admin_headers)
    assert yanit.status_code == 409, yanit.text
    assert "hareket" in yanit.json()["detail"].lower()


@pytest.mark.asyncio
async def test_var_olmayan_depo_silmede_404(client, admin_headers):
    yanit = await client.delete(f"/warehouses/{uuid.uuid4()}", headers=admin_headers)
    assert yanit.status_code == 404, yanit.text


# --- Liste + sayfalama ---


@pytest.mark.asyncio
async def test_liste_sayfalanir(client, admin_headers):
    for ad in ("A Ambar", "B Ambar", "C Ambar"):
        await _olustur(client, admin_headers, name=ad)
    yanit = await client.get("/warehouses", params={"limit": 2, "offset": 1}, headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert govde["total"] == 3
    assert govde["limit"] == 2
    assert govde["offset"] == 1
    assert [d["name"] for d in govde["items"]] == ["B Ambar", "C Ambar"]


@pytest.mark.asyncio
async def test_limit_tavani_asilamaz_422(client, admin_headers):
    yanit = await client.get("/warehouses", params={"limit": 201}, headers=admin_headers)
    assert yanit.status_code == 422, yanit.text
