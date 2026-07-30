"""B9 — Excel ice aktarma ucu (spec §6.4, §7.8).

BELGE SAKLAMA ALTYAPISI YOKTUR ve kurulmayacaktir. Dosya `multipart/form-data`
ile alinir, BELLEKTE `openpyxl` ile okunur, uniteler yaratilir ve dosya ATILIR.
`test_import_does_not_persist_file` bunun TEK GERCEK KANITIDIR: istek oncesi ve
sonrasi gecici dizin listesi karsilastirilir. Bu test kirmiziya donerse dosya bir
yere yaziliyor demektir ve uc GERI CEKILMELIDIR — P3'e sigmasinin tek sebebi
hicbir sey saklamamasidir.

HEP-YA-HIC + satir bazli rapor (spec §7.8 karari): tek satir bile hataliysa
HICBIR unite yazilmaz, ama yanit hangi satirda ne hata oldugunu listeler. Bu
yuzden hata testleri durum koduyla YETINMEZ, unite sayisini da olcer.

Turkce `İ/ı` tuzagi: `"İ".lower()` Python'da iki karakter uretir (`i` + birlesik
nokta) ve ham `.lower()` ile yapilan baslik eslestirmesi SESSIZCE calismaz —
`test_header_normalization_*` testleri bunu kilitler.
"""

import io
import os
import tempfile
import uuid

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.modules.units.importer import (
    normalize_header,
    parse_kind,
    parse_owner_side,
    parse_units_file,
)
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from tests.modules.units.test_units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_HEADERS = [
    "Blok",
    "Ünite No",
    "Tür",
    "Tip",
    "Brüt m²",
    "Net m²",
    "Liste Fiyatı",
    "Rayiç Değer",
    "Pay",
]


def _xlsx(rows: list[list], headers: list | None = None) -> bytes:
    """Bellekte bir `.xlsx` uretir — testler de diske dosya BIRAKMAZ."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(_HEADERS if headers is None else headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _row(block: str = "A Blok", unit_no: str = "1", kind: str = "Daire", **cells) -> list:
    values: dict = {
        "Tip": None,
        "Brüt m²": None,
        "Net m²": None,
        "Liste Fiyatı": None,
        "Rayiç Değer": None,
        "Pay": None,
    }
    values.update(cells)
    return [block, unit_no, kind, *[values[label] for label in _HEADERS[3:]]]


async def _post_import(client, project, content: bytes, token: str, filename="uniteler.xlsx"):
    return await client.post(
        f"/projects/{project.id}/units/import",
        files={"file": (filename, content, _XLSX_MIME)},
        headers=_auth(token),
    )


async def _count_units(session, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Unit).where(Unit.project_id == project_id)
    )
    return int(result.scalar_one())


async def _count_blocks(session, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Block).where(Block.project_id == project_id)
    )
    return int(result.scalar_one())


# --- Birim: baslik / hucre cozumleme (DB'siz) ---


def test_header_normalization_trims_and_lowercases():
    assert normalize_header("  liste fiyatı ") == normalize_header("Liste Fiyatı")


def test_header_normalization_turkish_uppercase():
    """`"LİSTE FİYATI".lower()` ham hâlde `"liste fiyatı"` VERMEZ (birlesik nokta)."""
    assert normalize_header("LİSTE FİYATI") == normalize_header("Liste Fiyatı")


def test_header_normalization_dotless_i():
    """`ÜNİTE NO` / `ünite no` / `UNITE NO` ayni anahtara duser."""
    canonical = normalize_header("Ünite No")

    assert normalize_header("ÜNİTE NO") == canonical
    assert normalize_header("ünite no") == canonical


def test_unknown_extra_columns_ignored():
    """Beklenmeyen ek sutunlar YOK SAYILIR (spec §7.8) — dosya reddedilmez."""
    content = _xlsx(
        [[*_row(unit_no="7"), "kullanicinin kendi notu"]],
        headers=[*_HEADERS, "Notlar"],
    )

    rows, errors = parse_units_file(content)

    assert errors == []
    assert len(rows) == 1
    assert rows[0].unit_no == "7"


def test_kind_dictionary_mapping():
    assert parse_kind("Daire") is UnitKind.apartment
    assert parse_kind("DÜKKAN") is UnitKind.shop
    with pytest.raises(ValueError):
        parse_kind("Villa")


def test_owner_side_dictionary_mapping():
    assert parse_owner_side("BİZ") is UnitOwnerSide.contractor
    assert parse_owner_side("Arsa") is UnitOwnerSide.landowner
    assert parse_owner_side(None) is None
    assert parse_owner_side("   ") is None
    with pytest.raises(ValueError):
        parse_owner_side("Banka")


# --- API: POST /projects/{id}/units/import (spec §7.8) ---


async def test_import_valid_10_rows_returns_200(client, db_session, user_factory, project_factory):
    project = await project_factory("B9-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n)) for n in range(1, 11)])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 10
    assert body["blocks_created"] == 0
    assert body["errors"] == []
    assert await _count_units(db_session, project.id) == 10


async def test_import_maps_all_columns(client, db_session, user_factory, project_factory):
    """Sutun duzeni spec §7.8 tablosundan BIREBIR: A `Blok` … I `Pay`."""
    project = await project_factory("B9-2", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [
            _row(
                unit_no="12",
                kind="Dükkan",
                **{
                    "Tip": "2+1",
                    "Brüt m²": 120,
                    "Net m²": 95,
                    "Liste Fiyatı": 2500000,
                    "Rayiç Değer": 2300000,
                    "Pay": "ARSA",
                },
            )
        ]
    )

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    unit = (await db_session.execute(select(Unit).where(Unit.block_id == block.id))).scalar_one()
    assert unit.unit_no == "12"
    assert unit.unit_kind is UnitKind.shop
    assert unit.layout == "2+1"
    assert str(unit.gross_area_m2) == "120.00"
    assert str(unit.net_area_m2) == "95.00"
    assert str(unit.list_price) == "2500000.00"
    assert str(unit.appraisal_value) == "2300000.00"
    assert unit.owner_side is UnitOwnerSide.landowner


async def test_import_creates_missing_block(client, db_session, user_factory, project_factory):
    """Dosyadaki yeni blok adi ACILIR ve §4.5 santiye kuraliyla tek santiyeye baglanir."""
    project = await project_factory("B9-3", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="C Blok", unit_no="1"), _row(block="C Blok", unit_no="2")])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    assert resp.json()["blocks_created"] == 1
    assert resp.json()["created"] == 2
    block = (
        await db_session.execute(select(Block).where(Block.project_id == project.id))
    ).scalar_one()
    assert block.name == "C Blok"
    assert block.site_id == site.id


async def test_import_row_error_returns_422_and_writes_nothing(
    client, db_session, user_factory, project_factory
):
    """HEP-YA-HIC KANITI: tek satir hataliysa unite sayisi 0 kalir."""
    project = await project_factory("B9-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [
            _row(unit_no="1"),
            _row(unit_no="2", **{"Brüt m²": 80, "Net m²": 95}),
        ]
    )

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert errors[0]["row"] == 3
    assert errors[0]["message"] == "Net alan brüt alandan büyük olamaz"
    assert await _count_units(db_session, project.id) == 0


async def test_import_error_does_not_create_blocks(
    client, db_session, user_factory, project_factory
):
    """Hep-ya-hic BLOKLARI da kapsar: hatali dosya yarim blok BIRAKMAZ."""
    project = await project_factory("B9-5", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok", unit_no="1", kind="Villa")])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert await _count_blocks(db_session, project.id) == 0


async def test_import_duplicate_pair_within_file_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B9-6", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="5"), _row(unit_no="5")])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["errors"][0]["row"] == 3
    assert await _count_units(db_session, project.id) == 0


async def test_import_existing_unit_no_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B9-7", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    await _unit(db_session, project, block, unit_no="3")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="3")])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["errors"][0]["message"] == "Bu ünite numarası bu blokta zaten kullanılıyor"
    assert await _count_units(db_session, project.id) == 1


async def test_import_missing_required_header_returns_422(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B9-8", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([["Daire"]], headers=["Tür"])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Excel başlıkları eksik: Blok, Ünite No"


async def test_import_csv_returns_422(client, db_session, user_factory, project_factory):
    project = await project_factory("B9-9", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(
        client, project, b"Blok,Unite No\nA,1\n", token, filename="uniteler.csv"
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Yalnızca .xlsx dosyası yüklenebilir"


async def test_import_xls_returns_422(client, db_session, user_factory, project_factory):
    project = await project_factory("B9-10", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, b"\xd0\xcf\x11\xe0", token, filename="eski.xls")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Yalnızca .xlsx dosyası yüklenebilir"


async def test_import_oversize_file_returns_422(client, db_session, user_factory, project_factory):
    """Sinir asimi 413 DEGIL 422: hata sozlesmesi ayni kalsin, govde Turkce mesaj tasisin."""
    project = await project_factory("B9-11", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, b"0" * (2 * 1024 * 1024 + 1), token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Dosya çok büyük (en fazla 2 MB)"


async def test_import_too_many_rows_returns_422(client, db_session, user_factory, project_factory):
    project = await project_factory("B9-12", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n)) for n in range(1, 1002)])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Dosyada en fazla 1000 satır olabilir"
    assert await _count_units(db_session, project.id) == 0


async def test_import_error_list_capped_at_50(client, db_session, user_factory, project_factory):
    """60 hatali satir → 50 hata listelenir, kalani ozetlenir (spec §7.8)."""
    project = await project_factory("B9-13", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n), kind="Villa") for n in range(1, 61)])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    body = resp.json()
    assert len(body["errors"]) == 50
    assert body["truncated"] == "Ve 10 hata daha"
    assert body["detail"] == "Dosya işlenemedi, 60 satırda hata var"


async def test_import_owner_side_in_non_land_share_project_returns_422(
    client, db_session, user_factory, project_factory
):
    """§3.3 korkulugu ice aktarmada da gecerlidir — tekil POST ile AYNI kural."""
    project = await project_factory("B9-14", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Pay": "BİZ"})])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert (
        resp.json()["errors"][0]["message"]
        == "Ünite payı yalnızca kat karşılığı projelerde belirlenebilir"
    )
    assert await _count_units(db_session, project.id) == 0


async def test_import_does_not_persist_file(client, db_session, user_factory, project_factory):
    """DOSYA IZI TESTI (plan B9 test 19). Istek sonrasi gecici dizinde YENI dosya
    yok ve DB'de dosya icerigi tasiyan hicbir satir yok — belge saklama
    altyapisinin gerekmedigi kaniti (spec §7.8)."""
    project = await project_factory("B9-15", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n)) for n in range(1, 6)])
    temp_dir = tempfile.gettempdir()
    before = set(os.listdir(temp_dir))

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    assert set(os.listdir(temp_dir)) - before == set()
    # Dosya icerigi hicbir sutuna sizmadi: `.xlsx` bir ZIP'tir ve "PK" ile baslar.
    units = (
        (await db_session.execute(select(Unit).where(Unit.project_id == project.id)))
        .scalars()
        .all()
    )
    assert all("PK" not in (unit.layout or "") for unit in units)


async def test_import_foreign_project_returns_404(client, user_factory, project_factory):
    project = await project_factory("B9-16", project_type="kendi_yatirim")
    token = await _login(client, user_factory, "patron")

    resp = await _post_import(client, project, _xlsx([_row()]), token)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_import_unknown_project_returns_same_404(client, user_factory):
    token = await _login(client, user_factory, "system_admin")

    resp = await client.post(
        f"/projects/{uuid.uuid4()}/units/import",
        files={"file": ("u.xlsx", _xlsx([_row()]), _XLSX_MIME)},
        headers=_auth(token),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Proje bulunamadı"


async def test_import_requires_full_permission(client, db_session, user_factory, project_factory):
    """`view` yetmez (spec §8 / IDOR-13)."""
    project = await project_factory("B9-17", project_type="kendi_yatirim")
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await _post_import(client, project, _xlsx([_row()]), token)

    assert resp.status_code == 403


async def test_import_requires_token(client, project_factory):
    project = await project_factory("B9-18", project_type="kendi_yatirim")

    resp = await client.post(
        f"/projects/{project.id}/units/import",
        files={"file": ("u.xlsx", _xlsx([_row()]), _XLSX_MIME)},
    )

    assert resp.status_code == 401
