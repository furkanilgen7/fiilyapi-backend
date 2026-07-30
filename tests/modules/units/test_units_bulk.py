"""B8 — toplu unite uretimi (spec §6.3, §7.7).

ATOMIKLIK SINIFI. Kismi yazma SESSIZ VERI HATASIDIR: kullanici 48 uniteden
3'unun atlandigini asla fark etmez. Bu yuzden `test_bulk_conflict_...` testleri
durum koduyla YETINMEZ, istek oncesi/sonrasi `count(*)` esitligini olcer —
plan B8'in acik talebi ve bu davranisin TEK GERCEK KANITIDIR.

Numaralandirma saf fonksiyonlari (`app/modules/units/bulk.py`) DB'siz test edilir:
sira/on ek/kat mantigi bir HTTP istegine ihtiyac duymaz.
"""

import uuid

from sqlalchemy import func, select

from app.modules.units.bulk import generate_unit_numbers
from app.modules.units.models import Unit
from app.modules.units.schemas import UnitBulkCreate, UnitKind, UnitNumberingPattern
from tests.modules.units.test_units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

_ANY_BLOCK = uuid.uuid4()


def _bulk(**kwargs) -> UnitBulkCreate:
    payload: dict = {
        "block_id": _ANY_BLOCK,
        "unit_kind": UnitKind.apartment,
        "start_floor": 1,
        "end_floor": 1,
        "units_per_floor": 1,
    }
    payload.update(kwargs)
    return UnitBulkCreate(**payload)


async def _count_units_in_block(session, block_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Unit).where(Unit.block_id == block_id)
    )
    return int(result.scalar_one())


# --- Birim: numaralandirma (spec §6.3) ---


def test_sequential_numbering_1_to_24():
    """SY 76-99: 2 kat x 12 daire → "1".."24". Sira KAT KAT ilerler."""
    numbers = generate_unit_numbers(_bulk(start_floor=1, end_floor=2, units_per_floor=12))

    assert numbers == [str(n) for n in range(1, 25)]


def test_sequential_numbering_with_prefix():
    """SY 132-135: `prefix="D"` → D1..D4."""
    numbers = generate_unit_numbers(
        _bulk(start_floor=1, end_floor=1, units_per_floor=4, prefix="D")
    )

    assert numbers == ["D1", "D2", "D3", "D4"]


def test_sequential_numbering_respects_start_number():
    """Blok yarim doldurulmussa uretim kaldigi yerden devam edebilmeli."""
    numbers = generate_unit_numbers(
        _bulk(start_floor=1, end_floor=1, units_per_floor=3, start_number=101)
    )

    assert numbers == ["101", "102", "103"]


def test_floor_based_numbering():
    """Spec §6.3 formulu: `prefix + f"{floor}{sira:02d}"` → 101, 102, 201, 202."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=2,
            numbering=UnitNumberingPattern.floor_based,
        )
    )

    assert numbers == ["101", "102", "201", "202"]


def test_floor_based_numbering_negative_floors():
    """Bodrum katlar (`ge=-5`). Spec §6.3 formulu HARFI HARFINE uygulanir:
    kat -1 → "-101". Alternatif bir bodrum gosterimi ("B101") spec'te YOKTUR ve
    icat EDILMEZ; kullanici baska bir gosterim isterse `prefix` alani hazirdir."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=-1,
            end_floor=-1,
            units_per_floor=2,
            numbering=UnitNumberingPattern.floor_based,
        )
    )

    assert numbers == ["-101", "-102"]


def test_floor_based_numbering_pads_to_two_digits():
    """`{sira:02d}` sifir dolgusu: ilk daire "101" ("11" DEGIL), onuncu "110"."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=1,
            units_per_floor=10,
            numbering=UnitNumberingPattern.floor_based,
        )
    )

    assert numbers[0] == "101"
    assert numbers[-1] == "110"


def test_generated_numbers_are_unique_within_request():
    """Uretim deseninin kendisi cakisma URETMEZ — DB kontrolunden onceki garanti."""
    numbers = generate_unit_numbers(_bulk(start_floor=1, end_floor=5, units_per_floor=20))

    assert len(numbers) == len(set(numbers)) == 100


# --- API: POST /projects/{id}/units/bulk (spec §7.7) ---


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
    assert resp.json()["totals"]["counts"] == {"apartment": 0, "shop": 2, "total": 2}


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
