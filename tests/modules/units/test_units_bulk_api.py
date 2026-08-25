"""B8 — toplu üretim UCU: POST /projects/{id}/units/bulk (spec §7.7, §12.4).

`test_units_bulk.py`nin ikinci parçası (800 satır tavanı bölmesi); paylaşılan
yardımcılar `_units_bulk.py`dedir.

ATOMİKLİK SINIFI. Kısmi yazma SESSİZ VERİ HATASIDIR: kullanıcı 48 üniteden
3'ünün atlandığını asla fark etmez. Bu yüzden `test_bulk_conflict_...` testleri
durum koduyla YETİNMEZ, istek öncesi/sonrası `count(*)` eşitliğini ölçer —
plan B8'in açık talebi ve bu davranışın TEK GERÇEK KANITIDIR.
"""

from tests.modules.units._units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

# TU govdesi TEK yerde durur (`test_units_bulk_preview.py`): T10'un asil iddiasi
# "onizleme ile uretim AYNI govdeden AYNI sonucu verir"dir ve govde kopyalanirsa
# biri degistiginde digeri sessizce bayatlar — iddia da bosa duser.
from tests.modules.units.test_units_bulk_preview import _TU_SLOT_ROWS, _tu_payload

from ._units_bulk import (
    _count_units_in_block,
)


async def test_bulk_creates_24_units_returns_201(client, db_session, user_factory, project_factory):
    project = await project_factory("B8-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 2,
            "units_per_floor": 12,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert resp.json()["totals"]["counts"]["total"] == 24
    assert await _count_units_in_block(db_session, block.id) == 24


async def test_bulk_response_is_full_unit_list(client, db_session, user_factory, project_factory):
    """Yanit guncel `UnitListResponse`'tir (spec §7.7): ekran tabloyu yeniden cizer."""
    project = await project_factory("B8-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 3,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"totals", "blocks"}
    assert [u["unit_no"] for u in body["blocks"][0]["units"]] == ["1", "2", "3"]


async def test_bulk_preserves_generation_order(client, db_session, user_factory, project_factory):
    """`sort_order` uretim sirasina gore atanir: `unit_no` METINDIR, alfabetik
    sira "10" < "2" verirdi (spec §4.2 gerekcesi)."""
    project = await project_factory("B8-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 12,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert [u["unit_no"] for u in resp.json()["blocks"][0]["units"]] == [
        str(n) for n in range(1, 13)
    ]


async def test_bulk_applies_common_defaults(client, db_session, user_factory, project_factory):
    """Spec §6.3: ortak varsayilanlar TUM uretilen unitelere uygulanir."""
    project = await project_factory("B8-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "shop",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
            "layout": "3+1",
            "gross_area_m2": "142.00",
            "net_area_m2": "120.00",
            "list_price": "1150000.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    units = resp.json()["blocks"][0]["units"]
    assert all(u["unit_kind"] == "shop" for u in units)
    assert all(u["layout"] == "3+1" for u in units)
    assert all(u["list_price"] == "1150000.00" for u in units)
    assert resp.json()["totals"]["counts"] == {
        "apartment": 0,
        "shop": 2,
        "office": 0,
        "warehouse": 0,
        "parking": 0,
        "total": 2,
    }


async def test_bulk_conflict_returns_409_and_writes_nothing(
    client, db_session, user_factory, project_factory
):
    """ATOMIKLIK KANITI (plan B8 test 8): uretilecek numaralardan BIRI bile
    blokta varsa HICBIRI yazilmaz. Oncesi/sonrasi sayim ESIT."""
    project = await project_factory("B8-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "7")
    token = await _login(client, user_factory, "system_admin")
    before = await _count_units_in_block(db_session, block.id)

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 2,
            "units_per_floor": 12,
        },
        headers=_auth(token),
    )

    after = await _count_units_in_block(db_session, block.id)
    assert resp.status_code == 409
    assert before == 1
    assert after == before


async def test_bulk_conflict_lists_first_20_numbers(
    client, db_session, user_factory, project_factory
):
    """Spec §7.7: cakisan ILK 20 numara yanitta listelenir — kullanici hangi
    numaralari duzeltecegini bilmeli. 25 cakismanin tamami yazilmaz."""
    project = await project_factory("B8-6")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    for number in range(1, 26):
        await _unit(db_session, project, block, str(number))
    token = await _login(client, user_factory, "system_admin")
    before = await _count_units_in_block(db_session, block.id)

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 3,
            "units_per_floor": 10,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail.startswith("Üretilecek ünite numaralarından bazıları blokta zaten var")
    listed = detail.split(": ", 1)[1].split(", ")
    assert listed == [str(n) for n in range(1, 21)]
    assert await _count_units_in_block(db_session, block.id) == before


async def test_bulk_inverted_floor_range_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B8-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 5,
            "end_floor": 2,
            "units_per_floor": 2,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert "Bitiş katı başlangıç katından küçük olamaz" in resp.text
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_over_limit_returns_422(client, db_session, user_factory, project_factory):
    """`_MAX_BULK_UNITS = 500` (spec §6.3): 26 kat x 20 = 520 reddedilir."""
    project = await project_factory("B8-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 26,
            "units_per_floor": 20,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert "Tek seferde en fazla 500 ünite üretilebilir" in resp.text
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_net_gt_gross_returns_422_and_writes_nothing(
    client, db_session, user_factory, project_factory
):
    """Ortak varsayilanlar da tekil POST ile AYNI kurallara tabidir; hata
    yazmadan ONCE yakalanir (DB CHECK'ine dusulmez)."""
    project = await project_factory("B8-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 4,
            "gross_area_m2": "100.00",
            "net_area_m2": "120.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Net alan brüt alandan büyük olamaz"
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_never_sets_owner_side_in_kendi_yatirim(
    client, db_session, user_factory, project_factory
):
    """§3.3 korkulugu toplu yolda YAPISAL olarak saglanir.

    ONEMLI — plan B8 test 12 (`test_bulk_owner_side_type_mismatch_returns_422`)
    ile spec §6.3 CELISIR: `UnitBulkCreate` semasinda `owner_side` alani YOKTUR
    (B2'de spec §6.3'ten birebir uygulandi), dolayisiyla toplu uretimle tip
    uyusmazligi URETILEMEZ. Semaya alan EKLENMEDI (icat olurdu); bunun yerine
    garanti burada kilitlenir: govdeye `owner_side` konsa bile uretilen
    unitelerin hicbirinde pay atanmaz. Karar kullanicidadir (rapora islendi).
    """
    project = await project_factory("B8-10", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
            "owner_side": "landowner",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    assert all(u["owner_side"] is None for u in resp.json()["blocks"][0]["units"])


async def test_bulk_foreign_block_returns_404(client, db_session, user_factory, project_factory):
    """IDOR-9: govdedeki `block_id` baska projenin blogu olabilir → 404."""
    project = await project_factory("B8-11A")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("B8-11B")
    other_site = await _site(db_session, other, code="S-FOREIGN")
    foreign_block = await _block(db_session, other, other_site)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(foreign_block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"
    assert await _count_units_in_block(db_session, foreign_block.id) == 0


async def test_bulk_requires_full_permission(client, db_session, user_factory, project_factory):
    """Spec §8: toplu uretim `projects` · `full` ister; `view` YETMEZ."""
    project = await project_factory("B8-12")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 403
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_invisible_project_returns_404(
    client, db_session, user_factory, project_factory
):
    """IDOR-3: gorunmeyen projeye toplu yazma 404 doner, 403 DEGIL."""
    project = await project_factory("B8-13")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "patron")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
        },
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_appends_after_existing_units(client, db_session, user_factory, project_factory):
    """Yari dolu blokta uretim: mevcut satirlar KORUNUR, yenileri sonrasina
    eklenir (`sort_order` mevcut en buyugun ustunden devam eder)."""
    project = await project_factory("B8-14")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    await _unit(db_session, project, block, "A", sort_order=0)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
            "gross_area_m2": "80.00",
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    units = resp.json()["blocks"][0]["units"]
    assert [u["unit_no"] for u in units] == ["A", "1", "2"]
    assert units[0]["gross_area_m2"] is None
    assert units[1]["gross_area_m2"] == "80.00"


# --- P3.1 T10: slot + kat artisi GERCEK URETIME baglanir (spec §12.4/34-39) ---


async def _bulk_post(client, project_id, token, payload):
    return await client.post(
        f"/projects/{project_id}/units/bulk", json=payload, headers=_auth(token)
    )


async def test_bulk_preview_ile_ayni_numara_ve_fiyat(
    client, db_session, user_factory, project_factory
):
    """Spec §12.4/34 — TEK KAYNAK KANITI.

    Ayni govde once `preview`'a, sonra `bulk`'a gonderilir; uretilen numaralar,
    fiyatlar VE slot alanlari BIREBIR ayni olmalidir. Ayrisirlarsa kullanici
    onizlemede gordugunden baska bir sey kaydetmis olur ve bunu FARK EDEMEZ —
    iki yolun da `bulk.generate_units` saf fonksiyonundan besleniyor olmasinin
    tek gozlemlenebilir kaniti budur.

    `floor` sutununa yazilan deger `floor_label`'dir (METIN, karar 4), onizleme
    satirindaki sayisal `floor` DEGILDIR.
    """
    project = await project_factory("T10-1")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")
    payload = _tu_payload(block.id)

    preview = await client.post(
        f"/projects/{project.id}/units/bulk/preview", json=payload, headers=_auth(token)
    )
    created = await _bulk_post(client, project.id, token, payload)

    assert preview.status_code == 200
    assert created.status_code == 201
    rows = preview.json()["rows"]
    units = created.json()["blocks"][0]["units"]
    assert len(units) == len(rows) == 24
    assert [(u["unit_no"], u["list_price"]) for u in units] == [
        (r["unit_no"], r["list_price"]) for r in rows
    ]
    assert [
        (u["floor"], u["layout"], u["gross_area_m2"], u["net_area_m2"], u["facing"]) for u in units
    ] == [
        (r["floor_label"], r["layout"], r["gross_area_m2"], r["net_area_m2"], r["facing"])
        for r in rows
    ]


async def test_bulk_cakisma_409_hicbir_satir_yazilmaz(
    client, db_session, user_factory, project_factory
):
    """Spec §12.4/35 — P3 karari KORUNUYOR: uretimde cakisma HEP-YA-HICtir.

    Onizleme ayni cakismayi `conflict=true` ile 200 doner (§5.6); blokaj yalniz
    KAYDETMEDEDIR. Slot'lu uretimde de kural degismez: 24 satirin 1'i cakisiyorsa
    23'u de yazilmaz.
    """
    project = await project_factory("T10-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    await _unit(db_session, project, block, "C-13")
    token = await _login(client, user_factory, "system_admin")
    before = await _count_units_in_block(db_session, block.id)

    resp = await _bulk_post(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 409
    assert "C-13" in resp.json()["detail"]
    assert before == 1
    assert await _count_units_in_block(db_session, block.id) == before


async def test_bulk_slots_bos_eski_davranis(client, db_session, user_factory, project_factory):
    """Spec §12.4/36: `slots` bos → P3'un davranisi (ortak varsayilanlar) KORUNUR.

    Geriye donuk uyum: mevcut cagiranlar slot gondermiyor ve kirilmamalidir.
    `facing` ortak varsayilanlarda YOKTUR (mockup vermiyor) → `None` dogar.
    """
    project = await project_factory("T10-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    token = await _login(client, user_factory, "system_admin")

    resp = await _bulk_post(
        client,
        project.id,
        token,
        {
            "block_id": str(block.id),
            "unit_kind": "apartment",
            "start_floor": 1,
            "end_floor": 1,
            "units_per_floor": 2,
            "layout": "3+1",
            "gross_area_m2": "142.00",
            "list_price": "1150000.00",
        },
    )

    assert resp.status_code == 201
    units = resp.json()["blocks"][0]["units"]
    assert [u["unit_no"] for u in units] == ["1", "2"]
    assert all(u["layout"] == "3+1" for u in units)
    assert all(u["gross_area_m2"] == "142.00" for u in units)
    assert all(u["list_price"] == "1150000.00" for u in units)
    assert all(u["facing"] is None for u in units)
    # Kat etiketi slot'suz uretimde de YAZILIR: kat turu her hâlde vardir.
    assert all(u["floor"] == "1. Kat" for u in units)


async def test_bulk_slot_count_mismatch_422(client, db_session, user_factory, project_factory):
    """Spec §12.4/37: `len(slots) != units_per_floor` → 422, hicbir satir yazilmaz."""
    project = await project_factory("T10-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _bulk_post(client, project.id, token, _tu_payload(block.id, units_per_floor=4))

    assert resp.status_code == 422
    assert "Kat şablonu satır sayısı kat başına daire sayısıyla eşleşmiyor" in resp.text
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_slot_sequence_tekrarli_422(client, db_session, user_factory, project_factory):
    """Spec §12.4/38: tekrarli `sequence` → 422, hicbir satir yazilmaz.

    Tekrar sessiz gecseydi ayni kat ici sira iki kez uretilir ve
    `floor_sequence` deseninde AYNI numara iki unite dogururdu.
    """
    project = await project_factory("T10-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")
    slots = [{**_TU_SLOT_ROWS[0]}, {**_TU_SLOT_ROWS[1], "sequence": 1}, {**_TU_SLOT_ROWS[2]}]

    resp = await _bulk_post(client, project.id, token, _tu_payload(block.id, slots=slots))

    assert resp.status_code == 422
    assert "Kat şablonunda sıra numaraları geçersiz veya tekrarlı" in resp.text
    assert await _count_units_in_block(db_session, block.id) == 0


async def test_bulk_owner_side_yok_sayilir(client, db_session, user_factory, project_factory):
    """Spec §12.4/39: slot'lu uretimde de `owner_side` govdeden GECMEZ.

    `test_bulk_never_sets_owner_side_in_kendi_yatirim` slot'suz yolu kilitler;
    bu test slot yolunun ayni garantiyi tasidigini kilitler (§3.3 korkulugu
    yapisaldir, kod yoluna bagli degildir).
    """
    project = await project_factory("T10-6", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _bulk_post(
        client,
        project.id,
        token,
        _tu_payload(block.id, end_floor=1, owner_side="landowner"),
    )

    assert resp.status_code == 201
    units = resp.json()["blocks"][0]["units"]
    assert len(units) == 3
    assert all(u["owner_side"] is None for u in units)
