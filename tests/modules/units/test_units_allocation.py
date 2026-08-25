"""B10 — paylasim ucu (`PATCH /projects/{id}/units/allocation`, spec §7.10, §5.3).

KKP 25 "Paylasimi Kaydet". Paylar TOPLU URETIMDE ATANMAZ, sonradan bu ucla
girilir (mockup KKP 78: paylasim noterden SONRA girilir) — bu yuzden ayri bir
uc vardir ve `UnitBulkCreate` semasinda `owner_side` YOKTUR.

ATOMIKLIK SINIFI (bulk ile ayni gerekce): tek satir bile reddedilirse HICBIRI
yazilmaz. Testler durum koduyla YETINMEZ, istek oncesi/sonrasi atanmis pay
SAYIMINI olcer — kismi yazma sessiz veri hatasidir.
"""

import uuid

from sqlalchemy import func, select

from app.modules.units.models import Unit, UnitOwnerSide
from tests.modules.units._units_api import _auth, _block, _login, _site, _unit

_ALLOCATION_WRONG_TYPE = "Paylaşım yalnızca kat karşılığı projelerde kaydedilebilir"
_DUPLICATE_IN_PAYLOAD = "Aynı ünite listede birden çok kez var"
_UNIT_MISSING = "Ünite bulunamadı"

# Spec §6.2: `_MAX_ALLOCATION_ITEMS`. KKP'de 42 unite var; sinir 500'dur.
_MAX_ALLOCATION_ITEMS = 500

# KKP tablosundaki unite adedi — "42 unite tek istekte" testinin dayanagi.
_KKP_UNIT_COUNT = 42


def _url(project_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/units/allocation"


async def _units(session, project, block, count: int) -> list[Unit]:
    return [
        await _unit(session, project, block, unit_no=str(index + 1), sort_order=index)
        for index in range(count)
    ]


async def _assigned_count(session, project_id: uuid.UUID) -> int:
    """Atanmis (NULL olmayan) pay sayisi — atomikligin TEK GERCEK KANITI."""
    result = await session.execute(
        select(func.count())
        .select_from(Unit)
        .where(Unit.project_id == project_id, Unit.owner_side.is_not(None))
    )
    return int(result.scalar_one())


def _sides_by_unit_id(body: dict) -> dict[str, str | None]:
    return {unit["id"]: unit["owner_side"] for group in body["blocks"] for unit in group["units"]}


def _side_summary(body: dict, side: str | None) -> dict:
    return next(s for s in body["totals"]["sides"] if s["side"] == side)


# --- Mutlu yol (spec §7.10) ---


async def test_allocation_updates_42_units_in_one_request(
    client, db_session, user_factory, project_factory
):
    """KKP 25: 42 unite TEK istekte paylasilir; yanit GUNCEL `UnitListResponse`tir.

    Ekran tabloyu yanittan yeniden cizer — ikinci bir GET'e ihtiyac duymaz.
    """
    project = await project_factory("A10-1", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    units = await _units(db_session, project, block, _KKP_UNIT_COUNT)
    token = await _login(client, user_factory, "system_admin")
    items = [
        {
            "unit_id": str(unit.id),
            "owner_side": "contractor" if index % 2 == 0 else "landowner",
        }
        for index, unit in enumerate(units)
    ]

    resp = await client.patch(_url(project.id), json={"items": items}, headers=_auth(token))

    assert resp.status_code == 200
    sides = _sides_by_unit_id(resp.json())
    assert len(sides) == _KKP_UNIT_COUNT
    assert sides == {item["unit_id"]: item["owner_side"] for item in items}
    assert await _assigned_count(db_session, project.id) == _KKP_UNIT_COUNT


async def test_allocation_null_clears_owner_side(client, db_session, user_factory, project_factory):
    """Spec §5.3: `owner_side: null` atamayi KALDIRIR — hata degildir.

    Yanlis girilen bir paylasim geri alinabilmelidir; aksi hâlde kullanicinin
    tek caresi uniteyi silip yeniden yaratmak olurdu.
    """
    project = await project_factory("A10-2", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block, owner_side=UnitOwnerSide.landowner)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": None}]},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert _sides_by_unit_id(resp.json()) == {str(unit.id): None}
    assert await _assigned_count(db_session, project.id) == 0


async def test_allocation_response_reflects_new_side_totals(
    client, db_session, user_factory, project_factory
):
    """KKP 161-168 tfoot: `sides` toplamlari ISTEKTEN SONRAKI durumu gosterir."""
    project = await project_factory("A10-3", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    units = await _units(db_session, project, block, 4)
    token = await _login(client, user_factory, "system_admin")
    items = [
        {"unit_id": str(unit.id), "owner_side": "contractor" if index < 3 else "landowner"}
        for index, unit in enumerate(units)
    ]

    resp = await client.patch(_url(project.id), json={"items": items}, headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert _side_summary(body, "contractor")["counts"]["total"] == 3
    assert _side_summary(body, "landowner")["counts"]["total"] == 1
    assert _side_summary(body, None)["counts"]["total"] == 0


# --- Reddedilen istekler: HICBIR satir yazilmaz (spec §7.10) ---


async def test_allocation_duplicate_unit_id_returns_422(
    client, db_session, user_factory, project_factory
):
    """Ayni unite listede iki kez: 422 ve HICBIR satir yazilmamis.

    Tekrar sessizce "son kazanir" diye kabul edilseydi, ekranda iki satira
    dokunan kullanici hangisinin gecerli oldugunu asla goremezdi.
    """
    project = await project_factory("A10-4", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    first, second = await _units(db_session, project, block, 2)
    token = await _login(client, user_factory, "system_admin")
    items = [
        {"unit_id": str(first.id), "owner_side": "contractor"},
        {"unit_id": str(second.id), "owner_side": "landowner"},
        {"unit_id": str(first.id), "owner_side": "landowner"},
    ]

    resp = await client.patch(_url(project.id), json={"items": items}, headers=_auth(token))

    assert resp.status_code == 422
    assert resp.json()["detail"] == _DUPLICATE_IN_PAYLOAD
    assert await _assigned_count(db_session, project.id) == 0


async def test_allocation_in_kendi_yatirim_returns_422(
    client, db_session, user_factory, project_factory
):
    """Spec §3.3: pay YALNIZ kat karsiligi projede belirlenir. Hic islem yapilmaz."""
    project = await project_factory("A10-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": "contractor"}]},
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == _ALLOCATION_WRONG_TYPE
    assert await _assigned_count(db_session, project.id) == 0


async def test_allocation_empty_list_returns_422(client, user_factory, project_factory):
    """`min_length=1`: bos istek hicbir sey yapmaz, sessizce 200 DONMEZ."""
    project = await project_factory("A10-6", project_type="kat_karsiligi")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(_url(project.id), json={"items": []}, headers=_auth(token))

    assert resp.status_code == 422


async def test_allocation_over_500_items_returns_422(client, user_factory, project_factory):
    """`max_length=500` (spec §6.2): tek istekte sinirsiz satir yazilamaz."""
    project = await project_factory("A10-7", project_type="kat_karsiligi")
    token = await _login(client, user_factory, "system_admin")
    items = [
        {"unit_id": str(uuid.uuid4()), "owner_side": "contractor"}
        for _ in range(_MAX_ALLOCATION_ITEMS + 1)
    ]

    resp = await client.patch(_url(project.id), json={"items": items}, headers=_auth(token))

    assert resp.status_code == 422


async def test_allocation_unknown_unit_id_returns_404(
    client, db_session, user_factory, project_factory
):
    """Var olmayan UUID, BASKA projenin unitesiyle AYNI mesaji verir (spec §11.4-7)."""
    project = await project_factory("A10-8", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    token = await _login(client, user_factory, "system_admin")
    items = [
        {"unit_id": str(unit.id), "owner_side": "contractor"},
        {"unit_id": str(uuid.uuid4()), "owner_side": "landowner"},
    ]

    resp = await client.patch(_url(project.id), json={"items": items}, headers=_auth(token))

    assert resp.status_code == 404
    assert resp.json()["detail"] == _UNIT_MISSING
    assert await _assigned_count(db_session, project.id) == 0
