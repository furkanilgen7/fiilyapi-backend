"""P9 T3 — paylasim ucunun HISSEDAR tasimasi + okuma yuzeyi (spec §4.2-§4.3).

`PATCH /projects/{id}/units/allocation` artik satir basina `shareholder_id`
tasir ve `UnitResponse` yer tutucu yerine GERCEK `shareholder_id` +
`shareholder_name` doner.

Bu dosya spec §4.2'nin dort kuralini ve §4.3'un N+1 yasagini olcer:

1. `contractor`/`None` tarafla gonderilen `shareholder_id` → 422 (PG 221: select
   YALNIZ ARSA satirinda vardir; PG 190 BIZ satiri "Yuklenici payi" basar).
2. Baska projenin hissedari → 404 (IDOR-8 gorunmezlik deseni) ve HICBIR satir
   yazilmaz — durum kodu tek basina kanit degildir, atama sayimi da olculur.
3. `owner_side` `landowner`dan cikinca `shareholder_id` BIRLIKTE temizlenir;
   ayri istek beklenmez (atomik uc yarim durum birakmaz). Alanin GONDERILMEMESI
   `None` sayilir — mevcut DEGISTIRME sozlesmesi korunur.
4. `landowner` + `shareholder_id=None` GECERLIDIR (KKP 119: BIZ unitesinde "—";
   PG akisi atamayi kademeli yapar) — hissedar atamasi zorunlu degildir.

Ayrica ad cozumu TEK sorgudandir: unite sayisi buyurken
`land_share_shareholder` sorgu sayisi SABIT kalir.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import event, func, select

from app.modules.projects.models import LandShareShareholder
from app.modules.units.models import Unit, UnitOwnerSide
from tests.conftest import test_engine
from tests.modules.units.test_units_api import _auth, _block, _login, _site, _unit

_SHAREHOLDER_WRONG_SIDE = "Hissedar yalnızca arsa payı ünitesine atanabilir"
_SHAREHOLDER_MISSING = "Hissedar bulunamadı"


def _url(project_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/units/allocation"


async def _shareholder(session, project, name: str = "A. Yılmaz") -> LandShareShareholder:
    row = LandShareShareholder(project_id=project.id, name=name, share_pct=Decimal("50.00"))
    session.add(row)
    await session.flush()
    return row


async def _assigned_shareholder_count(session, project_id: uuid.UUID) -> int:
    """Hissedari ATANMIS unite sayisi — atomikligin tek gercek kaniti."""
    result = await session.execute(
        select(func.count())
        .select_from(Unit)
        .where(Unit.project_id == project_id, Unit.shareholder_id.is_not(None))
    )
    return int(result.scalar_one())


def _rows(body: dict) -> dict[str, dict]:
    return {unit["id"]: unit for group in body["blocks"] for unit in group["units"]}


@contextmanager
def _sorgu_sayaci() -> Iterator[list[str]]:
    """Surucuye giden HER ifadeyi toplar (`progress_payments/test_summary.py`
    deseninin aynisi): sorgu sayisi iddialari tahmine degil OLCUME dayanir."""
    ifadeler: list[str] = []

    def kaydet(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        ifadeler.append(" ".join(statement.split()))

    event.listen(test_engine.sync_engine, "before_cursor_execute", kaydet)
    try:
        yield ifadeler
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", kaydet)


def _hissedar_sorgulari(ifadeler: list[str]) -> list[str]:
    """Yalniz `land_share_shareholder` tablosuna giden ifadeler — kimlik/izin
    sorgulari sayima girmez, onlar unite sayisindan bagimsizdir."""
    return [i for i in ifadeler if "land_share_shareholder" in i]


# --- Mutlu yol (spec §4.2) ---


async def test_allocation_assigns_shareholder_to_landowner_unit(
    client, db_session, user_factory, project_factory
):
    """PG 221: ARSA satirinda hissedar secilir; yanit ADI da tasir (KKP 91)."""
    project = await project_factory("P9T3-1", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    shareholder = await _shareholder(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(unit.id),
                    "owner_side": "landowner",
                    "shareholder_id": str(shareholder.id),
                }
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    row = _rows(resp.json())[str(unit.id)]
    assert row["shareholder_id"] == str(shareholder.id)
    assert row["shareholder_name"] == "A. Yılmaz"
    assert await _assigned_shareholder_count(db_session, project.id) == 1


async def test_allocation_landowner_without_shareholder_is_valid(
    client, db_session, user_factory, project_factory
):
    """KKP 119: hissedar atamasi ARSA tarafinda ZORUNLU DEGILDIR — "—" basilir."""
    project = await project_factory("P9T3-2", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": "landowner"}]},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    row = _rows(resp.json())[str(unit.id)]
    assert row["shareholder_id"] is None
    assert row["shareholder_name"] is None


# --- 422: hissedar YALNIZ arsa tarafinda anlamlidir (spec §4.2) ---


async def test_allocation_shareholder_with_contractor_side_returns_422(
    client, db_session, user_factory, project_factory
):
    """PG 190: BIZ satiri "Yuklenici payi" basar, hissedar secimi YOKTUR."""
    project = await project_factory("P9T3-3", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    shareholder = await _shareholder(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(unit.id),
                    "owner_side": "contractor",
                    "shareholder_id": str(shareholder.id),
                }
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == _SHAREHOLDER_WRONG_SIDE
    assert await _assigned_shareholder_count(db_session, project.id) == 0


async def test_allocation_shareholder_with_null_side_returns_422(
    client, db_session, user_factory, project_factory
):
    """Atanmamis taraf (`owner_side=null`) da hissedar TASIYAMAZ: "sahibi belli
    degil ama hissedari belli" tutarsiz bir durumdur."""
    project = await project_factory("P9T3-4", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    shareholder = await _shareholder(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(unit.id),
                    "owner_side": None,
                    "shareholder_id": str(shareholder.id),
                }
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == _SHAREHOLDER_WRONG_SIDE
    assert await _assigned_shareholder_count(db_session, project.id) == 0


async def test_allocation_wrong_side_rejects_whole_request(
    client, db_session, user_factory, project_factory
):
    """ATOMIKLIK: listedeki TEK kusurlu satir tum istegi dusurur; onceki
    satirlar yazilmis olarak KALMAZ."""
    project = await project_factory("P9T3-5", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    first = await _unit(db_session, project, block, "1")
    second = await _unit(db_session, project, block, "2")
    shareholder = await _shareholder(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(first.id),
                    "owner_side": "landowner",
                    "shareholder_id": str(shareholder.id),
                },
                {
                    "unit_id": str(second.id),
                    "owner_side": "contractor",
                    "shareholder_id": str(shareholder.id),
                },
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 422
    assert await _assigned_shareholder_count(db_session, project.id) == 0
    await db_session.refresh(first)
    assert first.owner_side is None


# --- 404: baska projenin/var olmayan hissedari (IDOR-8) ---


async def test_allocation_foreign_project_shareholder_returns_404(
    client, db_session, user_factory, project_factory
):
    """Baska projenin hissedari VAR OLMAYANLA ayni yaniti alir (IDOR-8):
    aksi hâlde elinde UUID olan kullanici kaydin var oldugunu ve baskasina ait
    oldugunu ayirt edebilirdi. Hicbir satir yazilmaz."""
    project = await project_factory("P9T3-6", project_type="kat_karsiligi")
    other = await project_factory("P9T3-6B", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    foreign = await _shareholder(db_session, other, name="Yabancı")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(unit.id),
                    "owner_side": "landowner",
                    "shareholder_id": str(foreign.id),
                }
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == _SHAREHOLDER_MISSING
    assert await _assigned_shareholder_count(db_session, project.id) == 0
    await db_session.refresh(unit)
    assert unit.owner_side is None


async def test_allocation_unknown_shareholder_returns_same_404(
    client, db_session, user_factory, project_factory
):
    """Var olmayan UUID, baska projenin hissedariyla AYNI mesaji verir."""
    project = await project_factory("P9T3-7", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    unit = await _unit(db_session, project, block)
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={
            "items": [
                {
                    "unit_id": str(unit.id),
                    "owner_side": "landowner",
                    "shareholder_id": str(uuid.uuid4()),
                }
            ]
        },
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == _SHAREHOLDER_MISSING
    assert await _assigned_shareholder_count(db_session, project.id) == 0


# --- Taraf degisince hissedar BIRLIKTE temizlenir (spec §4.2) ---


async def test_side_change_to_contractor_clears_shareholder(
    client, db_session, user_factory, project_factory
):
    """ARSA'dan BIZ'e gecen unitenin hissedari AYNI istekte temizlenir: ayri bir
    istek beklenseydi uc yarim durum birakirdi (yuklenici payinda hissedar)."""
    project = await project_factory("P9T3-8", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    shareholder = await _shareholder(db_session, project)
    unit = await _unit(
        db_session,
        project,
        block,
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=shareholder.id,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": "contractor"}]},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    assert _rows(resp.json())[str(unit.id)]["shareholder_id"] is None
    await db_session.refresh(unit)
    assert unit.shareholder_id is None


async def test_side_change_to_null_clears_shareholder(
    client, db_session, user_factory, project_factory
):
    """`owner_side=null` atamayi KALDIRIR — hissedar da onunla birlikte gider."""
    project = await project_factory("P9T3-9", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    shareholder = await _shareholder(db_session, project)
    unit = await _unit(
        db_session,
        project,
        block,
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=shareholder.id,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": None}]},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    assert _rows(resp.json())[str(unit.id)]["shareholder_id"] is None
    await db_session.refresh(unit)
    assert unit.shareholder_id is None


async def test_missing_shareholder_field_counts_as_none(
    client, db_session, user_factory, project_factory
):
    """Spec §5: alan GONDERILMEZSE `None` sayilir. Uc kismi guncellemeye
    donusmez — ARSA'da kalan unitenin hissedari da temizlenir."""
    project = await project_factory("P9T3-10", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    shareholder = await _shareholder(db_session, project)
    unit = await _unit(
        db_session,
        project,
        block,
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=shareholder.id,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(
        _url(project.id),
        json={"items": [{"unit_id": str(unit.id), "owner_side": "landowner"}]},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    assert _rows(resp.json())[str(unit.id)]["shareholder_id"] is None
    await db_session.refresh(unit)
    assert unit.shareholder_id is None


# --- Okuma yuzeyi (spec §4.3) ---


async def test_unit_list_carries_real_shareholder_fields(
    client, db_session, user_factory, project_factory
):
    """KKP 91: yer tutucu KALKTI — `shareholder_id`/`shareholder_name` gercektir
    ve `shareholder` anahtari yanittan tamamen cikmistir."""
    project = await project_factory("P9T3-11", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    shareholder = await _shareholder(db_session, project, name="B. Yılmaz")
    unit = await _unit(
        db_session,
        project,
        block,
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=shareholder.id,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get(f"/projects/{project.id}/units", headers=_auth(token))

    assert resp.status_code == 200, resp.text
    row = _rows(resp.json())[str(unit.id)]
    assert "shareholder" not in row
    assert row["shareholder_id"] == str(shareholder.id)
    assert row["shareholder_name"] == "B. Yılmaz"


async def test_single_unit_response_carries_shareholder_name(
    client, db_session, user_factory, project_factory
):
    """Tekil yanit LISTEYLE ayni bilgiyi tasir — PATCH sonrasi ekranin gordugu
    satir listedekiyle ayrisamaz (P8 `unit_response` gerekcesinin aynisi)."""
    project = await project_factory("P9T3-12", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site)
    shareholder = await _shareholder(db_session, project, name="C. Yılmaz")
    unit = await _unit(
        db_session,
        project,
        block,
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=shareholder.id,
    )
    token = await _login(client, user_factory, "system_admin")

    resp = await client.patch(f"/units/{unit.id}", json={"layout": "3+1"}, headers=_auth(token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shareholder_id"] == str(shareholder.id)
    assert body["shareholder_name"] == "C. Yılmaz"


async def test_shareholder_names_come_from_single_query(
    client, db_session, user_factory, project_factory
):
    """N+1 YASAGI (spec §4.3): ad cozumu TEK sorgudan gelir.

    Iki olcum alinir — 1 uniteli ve 20 uniteli proje. Unite sayisi yirmi katina
    cikarken `land_share_shareholder` sorgu sayisi SABIT kalmalidir. Unite
    basina `session.get(LandShareShareholder, ...)` geri gelirse ikinci olcum
    birinciden buyuk cikar ve bu iddia kirmizi doner.
    """
    az_proje = await project_factory("P9T3-13", project_type="kat_karsiligi")
    az_site = await _site(db_session, az_proje)
    az_block = await _block(db_session, az_proje, az_site)
    az_shareholder = await _shareholder(db_session, az_proje)
    await _unit(
        db_session,
        az_proje,
        az_block,
        "1",
        owner_side=UnitOwnerSide.landowner,
        shareholder_id=az_shareholder.id,
    )

    cok_proje = await project_factory("P9T3-14", project_type="kat_karsiligi")
    cok_site = await _site(db_session, cok_proje, code="SANTIYE-2")
    cok_block = await _block(db_session, cok_proje, cok_site)
    cok_shareholders = [
        await _shareholder(db_session, cok_proje, name=f"H{index}") for index in range(4)
    ]
    for index in range(20):
        await _unit(
            db_session,
            cok_proje,
            cok_block,
            str(index + 1),
            sort_order=index,
            owner_side=UnitOwnerSide.landowner,
            shareholder_id=cok_shareholders[index % 4].id,
        )
    token = await _login(client, user_factory, "system_admin")

    with _sorgu_sayaci() as az:
        resp = await client.get(f"/projects/{az_proje.id}/units", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    az_sayi = len(_hissedar_sorgulari(az))

    with _sorgu_sayaci() as cok:
        resp = await client.get(f"/projects/{cok_proje.id}/units", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(_rows(body)) == 20
    assert {row["shareholder_name"] for row in _rows(body).values()} == {"H0", "H1", "H2", "H3"}
    cok_sayi = len(_hissedar_sorgulari(cok))

    assert cok_sayi == az_sayi, f"unite sayisiyla buyudu: {az_sayi} → {cok_sayi}"
    # Ust sinir: adlar TEK sorgudan gelir. Sayi sessizce buyumesin diye sabitlenir.
    assert cok_sayi <= 1, f"beklenenden fazla sorgu: {cok_sayi}"
