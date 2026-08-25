"""P3.1 T5-T7 — blok/ünite FORM ALANLARI, kod türetme ve satış durumu sayaçları.

`test_units_api.py`nin parçalarından biri (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_units_api.py`dedir.

Kapsam: blok formunun 13 yeni alanı (spec §2.1, §3.1-§3.3, karar 8), ünite
formunun 8 yeni alanı (spec §2.2, §4.1-§4.5) ve satış durumu sayaçları + yeni
süzgeçler (spec §8.2). İKİ SAYAÇ AYRI ŞEYDİR: `totals` süzgeçten etkilenmez.
"""

from sqlalchemy import select

from app.modules.units.codes import effective_block_code
from app.modules.units.models import Block, UnitOwnerSide, UnitSalesStatus

from ._units_api import (
    _auth,
    _block,
    _login,
    _site,
    _unit,
)


async def test_null_kodlu_blokta_anlik_turetme_saklanmaz(db_session, project_factory):
    """Canli bloklarin `code`'u NULL dogar ve NULL KALIR.

    Toplu uretimin `{Blok}` jetonu icin kod ANLIK turetilir; bu cagri `blocks`
    satirini **UPDATE ETMEZ**. Aksi hâlde okuma yolunda gizli bir yazma olur ve
    karar 8'in "backfill migration'i YOKTUR" kurali arka kapidan delinirdi.
    """
    project = await project_factory("P31-0B")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, "C Blok")
    assert block.code is None

    assert effective_block_code(block.code, block.name) == "C"

    block_id = block.id
    db_session.expire_all()
    stored = (await db_session.execute(select(Block.code).where(Block.id == block_id))).scalar_one()
    assert stored is None


# --- P3.1 T5: blok formunun 13 yeni alani (spec §2.1, §3.1, §3.2, §3.3) ---

_BLOK_FORMU = {
    "code": "YV-C",  # BE 71
    "basement_floor_count": 2,  # BE 78
    "floor_count": 8,  # BE 79
    "roof_type": "duplex",  # BE 80
    "units_per_floor": 3,  # BE 81
    "ground_floor_usage": "commercial",  # BE 82
    "shop_count": 2,  # BE 83
    "construction_area_m2": "3200.00",  # BE 84
    "elevator_count": 1,  # BE 85
    "parking_type": "closed",  # BE 86
    "estimated_delivery_date": "2027-06-30",  # BE 100
    "status": "construction",  # BE 101
    "notes": "Zemin katta iki dükkan",  # BE 102
}


async def test_blok_13_alan_yazilir_ve_doner(client, db_session, user_factory, project_factory):
    """BE formunun 13 alani da yazilir ve GET'te geri doner (spec §3.1)."""
    project = await project_factory("T5-1")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "C Blok"} | _BLOK_FORMU,
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    for field, value in _BLOK_FORMU.items():
        assert body[field] == value, field

    listed = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))
    assert listed.json()["blocks"][0]["code"] == "YV-C"
    assert listed.json()["blocks"][0]["notes"] == "Zemin katta iki dükkan"


async def test_blok_kodu_bos_ise_uretilir(client, db_session, user_factory, project_factory):
    """BE 71 ipucu "Boş bırakılırsa otomatik": "C Blok" → `C` (spec §3.2)."""
    project = await project_factory("T5-2")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "C Blok"}, headers=_auth(token)
    )

    assert resp.status_code == 201
    assert resp.json()["code"] == "C"


async def test_ayni_koda_cozulen_ikinci_blok_kod_eki_alir(
    client, db_session, user_factory, project_factory
):
    """Blok ADI proje icinde benzersizdir, ama iki ayri ad AYNI koda cozulebilir
    ("A Blok" ve "A" → ikisi de `A`). Ikincisi `A-2` alir (spec §3.2 adim 5)."""
    project = await project_factory("T5-3")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    first = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=_auth(token)
    )
    second = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A"}, headers=_auth(token)
    )

    assert first.json()["code"] == "A"
    assert second.status_code == 201
    assert second.json()["code"] == "A-2"


async def test_elle_verilen_kod_cakisirsa_409(client, db_session, user_factory, project_factory):
    """Kullanici kodu elle girerse aynen kabul edilir; yalniz benzersizlik
    dogrulanir → cakisma 409 (spec §3.2)."""
    project = await project_factory("T5-4")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "B Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Bu blok kodu bu projede zaten kullanılıyor"


async def test_farkli_projede_ayni_kod_201(client, db_session, user_factory, project_factory):
    """`uq_blocks_project_code` PROJE ICIDIR."""
    first = await project_factory("T5-5")
    second = await project_factory("T5-6")
    await _site(db_session, first)
    await _site(db_session, second, code="SANTIYE-2")
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        f"/projects/{first.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    resp = await client.post(
        f"/projects/{second.id}/blocks",
        json={"name": "A Blok", "code": "YV-A"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["code"] == "YV-A"


async def test_blok_patch_kismi_guncelleme_notes_null_bosaltir(
    client, db_session, user_factory, project_factory
):
    """GONDERILMEYEN alan degismez; `null` GONDERILEN nullable alan bosalir."""
    project = await project_factory("T5-7")
    site = await _site(db_session, project)
    block = await _block(
        db_session, project, site, name="A Blok", code="A", floor_count=8, notes="ilk not"
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"notes": None, "elevator_count": 2}, headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] is None
    assert body["elevator_count"] == 2
    assert body["floor_count"] == 8  # gonderilmedi → degismedi
    assert body["code"] == "A"


async def test_patch_kodu_bos_blokta_kod_uretir(client, db_session, user_factory, project_factory):
    """Karar 8: canli bloklarin kodu NULL dogar; BACKFILL MIGRATION'I YOKTUR —
    kod bir sonraki PATCH'te uretilir (uretim tek yerdedir, spec §3.2)."""
    project = await project_factory("T5-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/blocks/{block.id}", json={"notes": "kat planı"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["code"] == "C"


async def test_estimated_unit_count_8x3_arti_2_esittir_26(
    client, db_session, user_factory, project_factory
):
    """BE 90-93 BIREBIR: "8 kat × 3 daire + 2 dükkan" = 26. SAKLANMAZ, turevdir."""
    project = await project_factory("T5-9")
    site = await _site(db_session, project)
    await _block(
        db_session, project, site, name="C Blok", floor_count=8, units_per_floor=3, shop_count=2
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.json()["blocks"][0]["estimated_unit_count"] == 26


async def test_estimated_unit_count_uc_girdi_none_ise_none(
    client, db_session, user_factory, project_factory
):
    """Uc girdi de bossa `None` doner — **0 DEGIL**: 0 "hesaplandi ve sifir" der
    ve bu yanlis bilgidir (spec §3.3)."""
    project = await project_factory("T5-10")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/blocks", headers=_auth(token))

    assert resp.json()["blocks"][0]["estimated_unit_count"] is None


async def test_blok_negatif_sayac_422(client, db_session, user_factory, project_factory):
    """`floor_count = -1` → 422 (Pydantic, DB CHECK'ine DUSMEDEN)."""
    project = await project_factory("T5-11")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/blocks",
        json={"name": "A Blok", "floor_count": -1},
        headers=_auth(token),
    )

    assert resp.status_code == 422


# --- P3.1 T6: unite formunun 8 yeni alani (spec §2.2, §4.1-§4.5) ---

_UNITE_FORMU = {
    "floor": "3. Kat",  # UE 66 — METIN (karar 4)
    "facing": "southwest",  # UE 78
    "balcony_area_m2": "14.00",  # UE 79
    "bathroom_count": 2,  # UE 80
    "parking_right": "one_closed",  # UE 81
    "min_sale_price": "1380000.00",  # UE 92
    "vat_rate": "10.00",  # UE 93
    "sales_status": "sold",  # UE 94
}


async def test_unite_8_yeni_alan_yazilir_ve_doner(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("T6-1")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "B-12", "unit_kind": "apartment"}
        | _UNITE_FORMU,
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    for field, value in _UNITE_FORMU.items():
        assert body[field] == value, field


async def test_sales_status_gonderilmezse_listed(client, db_session, user_factory, project_factory):
    """UE 94'te "Satışta (Boş)" `selected` gelir → sunucu varsayilani `listed`.

    Varsayilan ZORUNLULUK DEGILDIR (karar 11): alan gonderilmeyebilir.
    """
    project = await project_factory("T6-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["sales_status"] == "listed"


async def test_unit_kind_office_warehouse_parking_201(
    client, db_session, user_factory, project_factory
):
    """UE 74 bes secenek: enum genislemesi uctan uca calisir (spec §4.3)."""
    project = await project_factory("T6-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    for index, kind in enumerate(("office", "warehouse", "parking")):
        resp = await client.post(
            f"/projects/{project.id}/units",
            json={"block_id": str(block.id), "unit_no": f"{index}", "unit_kind": kind},
            headers=_auth(token),
        )
        assert resp.status_code == 201, kind
        assert resp.json()["unit_kind"] == kind


async def test_floor_cati_kati_aynen_doner_21_karakter_422(
    client, db_session, user_factory, project_factory
):
    """Karar 4: kat METINDIR — mockup etiketi AYNEN saklanir, sayiya cevrilmez."""
    project = await project_factory("T6-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "floor": "Çatı Katı",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["floor"] == "Çatı Katı"

    too_long = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "2",
            "unit_kind": "apartment",
            "floor": "K" * 21,
        },
        headers=_auth(token),
    )
    assert too_long.status_code == 422


async def test_floor_gonderilmezse_none_201(client, db_session, user_factory, project_factory):
    """UE 66'da kirmizi `*` var ama zorunluluk DOGURMAZ (karar 11)."""
    project = await project_factory("T6-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["floor"] is None


async def test_patch_sales_status_artik_elle_degistirilemez(
    client, db_session, user_factory, project_factory
):
    """P8 T3 ILE TERSINE CEVRILDI (satis spec §3) — eski adi

    `test_patch_sales_status_sold_200`di ve "durum BUGUN elle degistirilebilir"
    diyordu. O test kendi docstring'inde "P8 geldiginde bu alan otomatiklesecek
    ve elle giris KILITLENECEKTIR" diye yazmisti; P8 T3 geldi ve
    `sales_status` `UnitUpdate` semasindan CIKARILDI. Artik unitenin vitrin
    durumu YALNIZ satis kaydindan turer
    (`sales/service.sync_unit_sales_status`).

    Alan semada olmadigi icin Pydantic'in `extra='ignore'` varsayilaniyla
    SESSIZCE duser: istek 200 doner ama durum DEGISMEZ. Kirici degildir —
    alani kullanan bir UI henuz yoktur (spec §3). Otomasyonun kendisi
    `tests/sales/test_sales_unit_sync.py`de test edilir.
    """
    project = await project_factory("T6-6")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        f"/units/{unit.id}", json={"sales_status": "sold"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["sales_status"] == "listed"


async def test_expected_profit_ve_unit_cost_yer_tutucu(
    client, db_session, user_factory, project_factory
):
    """Karar 3: maliyet ELLE GIRILMEZ → UE 91 ve UE 97-99 YER TUTUCUDUR.

    Maliyet ileride Is Kalemleri/satinalmadan hesaplanacak; bugun kolon ACILMAZ.
    """
    project = await project_factory("T6-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "1")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    unit = resp.json()["blocks"][0]["units"][0]
    for field in ("unit_cost", "expected_profit"):
        assert unit[field]["available"] is False, field
        assert unit[field]["pending_module"] == "project_costs", field


# --- P3.1 T7: satis durumu sayaclari ve yeni suzgecler (spec §8.2) ---


async def _satis_durumu_seti(session, project, site):
    """Dort durumdan biri kadar unite + kat etiketleri (KY 258-259 kirilimi)."""
    block = await _block(session, project, site)
    await _unit(session, project, block, "1", sales_status=UnitSalesStatus.sold, floor="3. Kat")
    await _unit(session, project, block, "2", sales_status=UnitSalesStatus.sold, floor="3")
    await _unit(session, project, block, "3", sales_status=UnitSalesStatus.reserved, floor="Zemin")
    await _unit(session, project, block, "4", sales_status=UnitSalesStatus.listed)
    await _unit(session, project, block, "5", sales_status=UnitSalesStatus.closed)
    return block


async def test_sales_status_suzgeci_listeyi_daraltir(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("T7-1")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units?sales_status=sold", headers=_auth(token))

    assert resp.status_code == 200
    assert [u["unit_no"] for u in resp.json()["blocks"][0]["units"]] == ["1", "2"]


async def test_totals_suzgecten_etkilenmez(client, db_session, user_factory, project_factory):
    """P3 §7.4 kurali KORUNUR: suzgec YALNIZ listeyi daraltir, `totals` daima
    projenin TAMAMINI sayar."""
    project = await project_factory("T7-2")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units?sales_status=sold", headers=_auth(token))

    totals = resp.json()["totals"]
    assert totals["counts"]["total"] == 5
    assert totals["by_sales_status"]["listed"] == 1


async def test_by_sales_status_dort_degeri_de_sayar(
    client, db_session, user_factory, project_factory
):
    """KY 258-259 / KKP 161-163 kirilimi artik GERCEK sayilabilir (spec §8.2)."""
    project = await project_factory("T7-3")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    totals = resp.json()["totals"]
    assert totals["by_sales_status"] == {"listed": 1, "reserved": 1, "sold": 2, "closed": 1}
    assert totals["sold_units"] == 2
    assert totals["reserved_units"] == 1
    assert totals["available_units"] == 1  # `listed` — `closed` BOS DEGILDIR


async def test_taraf_satis_sayaclari_gercektir(client, db_session, user_factory, project_factory):
    """T7 SONRASI TUTARSIZLIK DUZELTMESI (spec §8.2).

    `totals.by_sales_status` / `sold_units` / `reserved_units` /
    `available_units` T7'de GERCEK sayaca dondu, ama `sides[*].sold/reserved/
    listed` (yuklenici · arsa sahibi kirilimi) YER TUTUCU kalmisti. Ikisi de
    AYNI veriden — `sales_status` sutunundan — beslendigi icin bu ayrim
    savunulamazdi: ekran proje toplaminda "34 satildi" gorup taraf tablosunda
    "veri yok" basardi (KKP 161-168 tfoot).

    Sayaclar T7'nin TEK `SELECT`'inden turer; yeni sorgu EKLENMEZ.
    """
    project = await project_factory("T7-6", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    plan = [
        (UnitOwnerSide.contractor, UnitSalesStatus.sold),
        (UnitOwnerSide.contractor, UnitSalesStatus.sold),
        (UnitOwnerSide.contractor, UnitSalesStatus.reserved),
        (UnitOwnerSide.contractor, UnitSalesStatus.listed),
        (UnitOwnerSide.contractor, UnitSalesStatus.closed),
        (UnitOwnerSide.landowner, UnitSalesStatus.sold),
        (UnitOwnerSide.landowner, UnitSalesStatus.listed),
        (None, UnitSalesStatus.reserved),
    ]
    for index, (side, status) in enumerate(plan):
        await _unit(
            db_session, project, block, str(index + 1), owner_side=side, sales_status=status
        )
    token = await _login(client, user_factory, "system_admin")

    totals = (await client.get(f"/projects/{project.id}/units", headers=_auth(token))).json()[
        "totals"
    ]
    by_side = {side["side"]: side for side in totals["sides"]}

    assert (by_side["contractor"]["sold"], by_side["contractor"]["reserved"]) == (2, 1)
    assert by_side["contractor"]["listed"] == 1  # `closed` SAYILMAZ: bos ama satista degil
    assert (by_side["landowner"]["sold"], by_side["landowner"]["reserved"]) == (1, 0)
    assert by_side["landowner"]["listed"] == 1
    assert (by_side[None]["sold"], by_side[None]["reserved"], by_side[None]["listed"]) == (0, 1, 0)
    # Taraf sayaclarinin toplami proje toplamiyla TUTMALI — iki hesap ayrisirsa
    # ekran hangisine guvenecegini bilemez.
    assert sum(side["sold"] for side in totals["sides"]) == totals["sold_units"]
    assert sum(side["reserved"] for side in totals["sides"]) == totals["reserved_units"]
    assert sum(side["listed"] for side in totals["sides"]) == totals["available_units"]


async def test_taraf_satis_sayaclari_artik_yer_tutucu_degil(
    client, db_session, user_factory, project_factory
):
    """Yer tutucu zarfi (`{"available": false, "pending_module": …}`) GITTI.

    Sayilar dogru ama zarf duruyor olsaydi frontend hâlâ "veri yok" basardi;
    bu yuzden TIP de kilitlenir.
    """
    project = await project_factory("T7-7", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    totals = (await client.get(f"/projects/{project.id}/units", headers=_auth(token))).json()[
        "totals"
    ]

    for side in totals["sides"]:
        for field in ("sold", "reserved", "listed"):
            assert side[field] == 0, field
            assert isinstance(side[field], int), field


async def test_floor_suzgeci_tam_eslesme(client, db_session, user_factory, project_factory):
    """Karar 4: kat METINDIR → suzgec TAM ESLESMEDIR. "3" ile "3. Kat" AYRI
    degerlerdir; parcali eslesme sessiz veri karisikligi olurdu."""
    project = await project_factory("T7-4")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    kat = await client.get(f"/projects/{project.id}/units?floor=3.%20Kat", headers=_auth(token))
    sayi = await client.get(f"/projects/{project.id}/units?floor=3", headers=_auth(token))

    assert [u["unit_no"] for u in kat.json()["blocks"][0]["units"]] == ["1"]
    assert [u["unit_no"] for u in sayi.json()["blocks"][0]["units"]] == ["2"]


async def test_sales_revenue_artik_gercek_deger(client, db_session, user_factory, project_factory):
    """P8 T5: ciro YER TUTUCU DEGIL — `unit_sales`ten toplanir.

    Bu projede hic SATIS KAYDI yoktur (yalniz `sales_status` elle kurulmustur),
    bu yuzden ciro 0.00'dir ve ortalama `None`dir. Sifir ile "veri yok" ayrimi
    korunur: ortalama 0 basilsaydi "satis var ama bedeli sifir" anlamina gelirdi.
    """
    project = await project_factory("T7-5")
    site = await _site(db_session, project)
    await _satis_durumu_seti(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    totals = (await client.get(f"/projects/{project.id}/units", headers=_auth(token))).json()[
        "totals"
    ]

    assert totals["sales_revenue"] == "0.00"
    assert totals["average_sale_price"] is None
