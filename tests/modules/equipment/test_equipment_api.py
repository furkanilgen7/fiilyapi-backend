"""MK-1 T3 — ekipman kartı uçları (spec §4 "Ekipman" bloğu).

Kilitlenen kararlar: **K2** (koşullu zorunluluk, İKİ YÖNLÜ) · TB3 sayfalama
kanonu (`limit ≤ 200`, `total`) · DELETE ucunun YOKLUĞU · izin kapıları.

Görünürlük (K20) AYRI dosyadadır (`test_equipment_idor.py`), özet ucu da öyle
(`test_equipment_summary.py`) — bir dosyada toplanırlarsa kırıldıklarında hangi
kuralın çöktüğü okunmaz.
"""

import uuid

import pytest

from app.modules.equipment.models import EquipmentCategory, EquipmentOwnership


def _govde(**kwargs) -> dict:
    govde: dict = {"name": "Tower Crane TC-48", "category": EquipmentCategory.crane.value}
    govde.update(kwargs)
    return govde


# --- K2: `ownership == owned` iken `purchase_amount` ZORUNLU ---


@pytest.mark.asyncio
async def test_k2_sahip_olunan_makinede_alis_bedeli_zorunlu_422(client, sef_headers):
    """K2: kural SERVİSTEDİR (DB CHECK'i değil) ve 422 üretir."""
    yanit = await client.post(
        "/equipment",
        json=_govde(ownership=EquipmentOwnership.owned.value),
        headers=sef_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_k2_kiralik_makinede_alis_bedeli_serbest(client, sef_headers):
    """Kiralık makinenin alış bedeli YOKTUR — zorunluluk onu kapsasaydı hiç
    kaydedilemezdi."""
    yanit = await client.post(
        "/equipment",
        json=_govde(name="Ekskavatör CAT 320", ownership=EquipmentOwnership.rented.value),
        headers=sef_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["purchase_amount"] is None


@pytest.mark.asyncio
async def test_k2_sahip_olunan_makine_bedelle_kaydedilir(client, sef_headers):
    yanit = await client.post(
        "/equipment",
        json=_govde(ownership=EquipmentOwnership.owned.value, purchase_amount="4250000.00"),
        headers=sef_headers,
    )
    assert yanit.status_code == 201, yanit.text
    assert yanit.json()["purchase_amount"] == "4250000.00"


@pytest.mark.asyncio
async def test_k2_patchte_kiraliktan_sahipligie_gecis_bedelsiz_422(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """🔴 K2 İKİNCİ YÖN: kural PATCH'te MEVCUT SATIR + GÖVDE birleşimi üzerinden
    denetlenir. Yalnız POST'ta bakılsaydı `rented` kaydedip sonra `owned`a
    çekmek kuralı tamamen atlardı."""
    makine = await ekipman_fabrikasi(
        "Kiralık Vinç", site=gorunen_santiye, ownership=EquipmentOwnership.rented
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}",
        json={"ownership": EquipmentOwnership.owned.value},
        headers=sef_headers,
    )
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_k2_patchte_gecis_bedelle_birlikte_gecerli(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    makine = await ekipman_fabrikasi(
        "Kiralık Vinç", site=gorunen_santiye, ownership=EquipmentOwnership.rented
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}",
        json={"ownership": EquipmentOwnership.owned.value, "purchase_amount": "1000000.00"},
        headers=sef_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["ownership"] == EquipmentOwnership.owned.value


@pytest.mark.asyncio
async def test_k2_mevcut_bedelli_owned_kayitta_baska_alan_patchlenebilir(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """Kural BİRLEŞİMDEN bakar: DB'de bedel varken `ownership` gövdede olmasa da
    kayıt güncellenebilmelidir, yoksa her PATCH bedeli tekrar istemek zorunda
    kalırdı."""
    from decimal import Decimal

    makine = await ekipman_fabrikasi(
        "Sahipli Vinç",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.owned,
        purchase_amount=Decimal("500000.00"),
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"brand": "Liebherr"}, headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_k2_owned_kayitta_bedeli_nulla_cekmek_422(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """Ters yönden aynı kural: bedeli AÇIKÇA `null`a çekmek de ihlaldir."""
    from decimal import Decimal

    makine = await ekipman_fabrikasi(
        "Sahipli Vinç",
        site=gorunen_santiye,
        ownership=EquipmentOwnership.owned,
        purchase_amount=Decimal("500000.00"),
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"purchase_amount": None}, headers=sef_headers
    )
    assert yanit.status_code == 422, yanit.text


# --- TB3 sayfalama kanonu ---


@pytest.mark.asyncio
async def test_limit_tavani_201_422(client, admin_headers):
    yanit = await client.get("/equipment?limit=201", headers=admin_headers)
    assert yanit.status_code == 422, yanit.text


@pytest.mark.asyncio
async def test_limit_200_kabul_edilir(client, admin_headers):
    yanit = await client.get("/equipment?limit=200", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_total_sayfa_degil_tum_kumeyi_sayar(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye
):
    """`total` sayfa uzunluğunu değil SÜZÜLMÜŞ KÜMEYİ sayar — aksi hâlde
    sayfalama kontrolü hep "1 sayfa" derdi."""
    for i in range(3):
        await ekipman_fabrikasi(f"Makine {i}", site=gorunen_santiye)

    yanit = await client.get("/equipment?limit=1", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    assert len(govde["items"]) == 1
    assert govde["total"] == 3
    assert govde["limit"] == 1
    assert govde["offset"] == 0


# --- Süzgeçler ---


@pytest.mark.asyncio
async def test_suzgecler_andlidir(client, admin_headers, ekipman_fabrikasi, gorunen_santiye):
    from app.modules.equipment.models import EquipmentStatus

    hedef = await ekipman_fabrikasi(
        "Ekskavatör CAT 320",
        site=gorunen_santiye,
        category=EquipmentCategory.machinery,
        status=EquipmentStatus.broken,
        ownership=EquipmentOwnership.rented,
    )
    await ekipman_fabrikasi(
        "Tower Crane TC-48", site=gorunen_santiye, category=EquipmentCategory.crane
    )

    yanit = await client.get(
        "/equipment?status=broken&category=machinery&ownership=rented"
        f"&site_id={gorunen_santiye.id}",
        headers=admin_headers,
    )
    assert yanit.status_code == 200, yanit.text
    assert [e["id"] for e in yanit.json()["items"]] == [str(hedef.id)]


@pytest.mark.asyncio
async def test_q_ad_marka_model_plaka_seri_uzerinde_arar(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye
):
    """M1 kartı ad + marka/model + plakayı üst üste basar; tek alanda aramak
    kullanıcıyı "yok" sanısına düşürürdü."""
    kayitlar = {
        "ad": await ekipman_fabrikasi("Bulunacak Vinç", site=gorunen_santiye),
        "marka": await ekipman_fabrikasi("M2", site=gorunen_santiye, brand="Liebherr"),
        "model": await ekipman_fabrikasi("M3", site=gorunen_santiye, model="TC-48"),
        "plaka": await ekipman_fabrikasi("M4", site=gorunen_santiye, plate_no="34 ABC 123"),
        "seri": await ekipman_fabrikasi("M5", site=gorunen_santiye, serial_no="SN-90210"),
    }
    for arama, anahtar in (
        ("Bulunacak", "ad"),
        ("liebherr", "marka"),
        ("tc-48", "model"),
        ("34 ABC", "plaka"),
        ("90210", "seri"),
    ):
        yanit = await client.get(f"/equipment?q={arama}", headers=admin_headers)
        assert yanit.status_code == 200, yanit.text
        assert [e["id"] for e in yanit.json()["items"]] == [str(kayitlar[anahtar].id)], arama


@pytest.mark.asyncio
async def test_q_joker_karakterleri_kacirilir(
    client, admin_headers, ekipman_fabrikasi, gorunen_santiye
):
    """`%` yazan kullanıcı TÜM listeyi görmemelidir."""
    await ekipman_fabrikasi("Vinç", site=gorunen_santiye)
    yanit = await client.get("/equipment?q=%25", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["total"] == 0


# --- Detay + pasifleştirme ---


@pytest.mark.asyncio
async def test_detay_ucu_karti_doner(client, admin_headers, ekipman_fabrikasi, gorunen_santiye):
    makine = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    yanit = await client.get(f"/equipment/{makine.id}", headers=admin_headers)
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["name"] == "Tower Crane TC-48"


@pytest.mark.asyncio
async def test_olmayan_kimlik_404(client, admin_headers):
    yanit = await client.get(f"/equipment/{uuid.uuid4()}", headers=admin_headers)
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_silme_ucu_yoktur_405(client, admin_headers, ekipman_fabrikasi, gorunen_santiye):
    """🔴 Spec §4: DELETE ucu YOKTUR; pasifleştirme PATCH iledir. Yol tanımlı
    olmadığı için FastAPI 405 döner — bu BEKÇİ TESTİ ileride biri DELETE
    eklemeye kalkarsa kırılır."""
    makine = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    yanit = await client.delete(f"/equipment/{makine.id}", headers=admin_headers)
    assert yanit.status_code == 405, yanit.text


@pytest.mark.asyncio
async def test_k2_dokunulmamis_alan_kaydi_kilitlemez(
    client, sef_headers, ekipman_fabrikasi, gorunen_santiye
):
    """K2 denetimi YALNIZ iki alandan birine dokunulduğunda koşar (F-İK
    "touched" deseni). Her PATCH'te koşsaydı, doğrudan DB'den açılmış bedelsiz
    bir `owned` satır bir daha HİÇ güncellenemez — hurdaya bile ayrılamaz —
    hâle gelirdi."""
    makine = await ekipman_fabrikasi(
        "Bedelsiz Sahipli", site=gorunen_santiye, ownership=EquipmentOwnership.owned
    )
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"status_note": "Rutin bakım"}, headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text


@pytest.mark.asyncio
async def test_pasiflestirme_patch_iledir(client, sef_headers, ekipman_fabrikasi, gorunen_santiye):
    makine = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"is_active": False}, headers=sef_headers
    )
    assert yanit.status_code == 200, yanit.text
    assert yanit.json()["is_active"] is False

    detay = await client.get(f"/equipment/{makine.id}", headers=sef_headers)
    assert detay.status_code == 200, "pasif kartın detayı OKUNABİLİR kalmalı"


# --- Gövde içi varlık referansı (ST kanonu: 404) ---


@pytest.mark.asyncio
async def test_olmayan_operator_referansi_404(client, sef_headers):
    yanit = await client.post(
        "/equipment",
        json=_govde(operator_id=str(uuid.uuid4())),
        headers=sef_headers,
    )
    assert yanit.status_code == 404, yanit.text


@pytest.mark.asyncio
async def test_olmayan_tedarikci_referansi_404(client, sef_headers):
    yanit = await client.post(
        "/equipment",
        json=_govde(supplier_id=str(uuid.uuid4())),
        headers=sef_headers,
    )
    assert yanit.status_code == 404, yanit.text


# --- İzin kapıları ---


@pytest.mark.asyncio
async def test_view_izniyle_post_403(client, muhendis_headers):
    """`field_engineer` = `equipment:view`: okur, YAZAMAZ."""
    yanit = await client.post("/equipment", json=_govde(), headers=muhendis_headers)
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_view_izniyle_patch_403(client, muhendis_headers, ekipman_fabrikasi, gorunen_santiye):
    makine = await ekipman_fabrikasi("Tower Crane TC-48", site=gorunen_santiye)
    yanit = await client.patch(
        f"/equipment/{makine.id}", json={"brand": "X"}, headers=muhendis_headers
    )
    assert yanit.status_code == 403, yanit.text


@pytest.mark.asyncio
async def test_izinsiz_rol_okumada_bile_403(client, yetkisiz_headers):
    for yol in ("/equipment", "/equipment/summary"):
        yanit = await client.get(yol, headers=yetkisiz_headers)
        assert yanit.status_code == 403, (yol, yanit.text)
