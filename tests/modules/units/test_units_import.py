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
from sqlalchemy import delete, func, select

from app.modules.audit.models import AuditLog
from app.modules.units.importer import (
    COLUMNS,
    normalize_header,
    parse_facing,
    parse_kind,
    parse_owner_side,
    parse_units_file,
)
from app.modules.units.models import Block, Unit, UnitFacing, UnitKind, UnitOwnerSide
from tests.modules.units.test_units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# P3.1 T11 (spec §6.4, EI 85): 9 → 12 sutun, KANONIK sira. Iki baslik yeniden
# adlandirildi (`Tip` → `Oda Tipi`, `Pay` → `Sahiplik`); eskileri ESANLAMLI
# kabul edilir (`_LEGACY_HEADERS`, geriye donuk uyum testi).
_HEADERS = [
    "Blok",
    "Kat",
    "Ünite No",
    "Tür",
    "Oda Tipi",
    "Brüt m²",
    "Net m²",
    "Cephe",
    "Liste Fiyatı",
    "Rayiç Değer",
    "Maliyet",
    "Sahiplik",
]

_LEGACY_HEADERS = ["Blok", "Ünite No", "Tür", "Tip", "Brüt m²", "Net m²", "Liste Fiyatı", "Pay"]

# `Oda Tipi` ve `Brüt m²` P3.1'de ZORUNLU oldu (EI 161, spec §6.5). Bu yuzden
# ortak satir uretecinin varsayilanlari BOS BIRAKILAMAZ: P3'te bos gelen iki
# sutun artik her satiri hataya dusururdu. Testlerin IDDIALARI degismedi,
# yalnizca gecerli bir satirin tanimi genisledi.
_ROW_DEFAULTS: dict = {
    "Kat": None,
    "Oda Tipi": "3+1",
    "Brüt m²": 120,
    "Net m²": None,
    "Cephe": None,
    "Liste Fiyatı": None,
    "Rayiç Değer": None,
    "Maliyet": None,
    "Sahiplik": None,
}


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
    values: dict = {"Blok": block, "Ünite No": unit_no, "Tür": kind, **_ROW_DEFAULTS}
    values.update(cells)
    return [values[label] for label in _HEADERS]


def _legacy_row(unit_no: str = "1", **cells) -> list:
    """Eski 8 sutunlu dosya (P3 sablonu) — `Tip`/`Pay` esanlamli kabul edilir."""
    values: dict = {
        "Blok": "A Blok",
        "Ünite No": unit_no,
        "Tür": "Daire",
        "Tip": "3+1",
        "Brüt m²": 120,
        "Net m²": None,
        "Liste Fiyatı": None,
        "Pay": None,
    }
    values.update(cells)
    return [values[label] for label in _LEGACY_HEADERS]


def _parse(content: bytes):
    """`parse_units_file` ciktisini eski (satirlar, hatalar, uyarilar) uclusune
    indirger — cozumleme testlerinin ilgilenmedigi `ParsedRow` sarmalayicisini
    her testte acmamak icin."""
    parsed = parse_units_file(content)
    return (
        [row.data for row in parsed if row.data is not None],
        [error for row in parsed for error in row.errors],
        [warning for row in parsed for warning in row.warnings],
    )


async def _post_import(
    client, project, content: bytes, token: str, filename="uniteler.xlsx", **form
):
    return await client.post(
        f"/projects/{project.id}/units/import",
        files={"file": (filename, content, _XLSX_MIME)},
        data={key: str(value) for key, value in form.items()},
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

    rows, errors, _ = _parse(content)

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
    assert body["skipped"] == 0
    assert body["blocks_created"] == 0
    # BILEREK DEGISTI (T12, spec §6.3): `errors` alani KALDIRILDI, yerini
    # uyari/basari satirlarini da tasiyabilen `rows` aldi.
    assert body["summary"] == {"total_rows": 10, "valid": 10, "warning": 0, "error": 0}
    assert [r["status"] for r in body["rows"]] == ["ok"] * 10
    assert all(r["imported"] is True for r in body["rows"])
    assert await _count_units(db_session, project.id) == 10


async def test_import_maps_all_columns(client, db_session, user_factory, project_factory):
    """Sutun duzeni spec §6.4 tablosundan BIREBIR: A `Blok` … L `Sahiplik`.

    P3.1 T11'de 9 → 12 sutuna cikti; `Kat` ve `Cephe` de artik unite sutunlarina
    yazilir (`Maliyet` YAZILMAZ — karar 10, ayri test).
    """
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
                    "Kat": "Zemin",
                    "Oda Tipi": "2+1",
                    "Brüt m²": 120,
                    "Net m²": 95,
                    "Cephe": "Güney-Batı",
                    "Liste Fiyatı": 2500000,
                    "Rayiç Değer": 2300000,
                    "Sahiplik": "ARSA",
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
    assert unit.floor == "Zemin"
    assert unit.facing is UnitFacing.southwest
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


async def test_import_kismi_gecerliler_yazilir_hatali_yazilmaz(
    client, db_session, user_factory, project_factory
):
    """P3 §11.3 test 28 BILEREK TERSINE DONDU (spec §6.1, kullanici karari).

    P3'te bu test "tek satir hataliysa unite sayisi 0 kalir" diyordu. EI 38/202
    "22 Gecerli Satiri Aktar" ve EI 101 "veya sadece gecerli satirlari aktarin"
    ile uzlasmadigi icin karar KISMI AKTARIM lehine degisti.

    KISMI YAZIMIN ASIL KANITI (spec §12.5/44): hatali satirin unitesi DB'de
    YOK, gecerlininki VAR. Durum kodu bunu ISPATLAMAZ.
    """
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

    assert resp.status_code == 200
    body = resp.json()
    assert (body["created"], body["skipped"]) == (1, 1)
    assert body["summary"] == {"total_rows": 2, "valid": 1, "warning": 0, "error": 1}
    assert [(r["row"], r["status"], r["imported"]) for r in body["rows"]] == [
        (2, "ok", True),
        (3, "error", False),
    ]
    assert body["rows"][1]["messages"] == ["Net alan brüt alandan büyük olamaz"]
    written = (
        (await db_session.execute(select(Unit).where(Unit.project_id == project.id)))
        .scalars()
        .all()
    )
    assert [unit.unit_no for unit in written] == ["1"]


async def test_import_hic_gecerli_satir_yoksa_blok_da_olusmaz(
    client, db_session, user_factory, project_factory
):
    """BILEREK DEGISTI (T12): 422'nin gerekcesi artik "dosyada hata var" DEGIL,
    "aktarilabilecek gecerli satir yok"tur (spec §8.3, EI mantigi).

    Garanti ayni kaldi: hicbir sey yazilmaz — blok da acilmaz. `created=0` ile
    200 donmek kullanicinin "aktarildi" sanmasina yol acardi.
    """
    project = await project_factory("B9-5", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok", unit_no="1", kind="Villa")])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Aktarılabilecek geçerli satır yok"
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

    # BILEREK DEGISTI (T12): tekrar eden IKINCI satir atlanir, birincisi yazilir.
    assert resp.status_code == 200
    body = resp.json()
    assert (body["created"], body["skipped"]) == (1, 1)
    assert body["rows"][1]["messages"] == ["Bu ünite numarası dosyada birden çok kez var"]
    assert await _count_units(db_session, project.id) == 1


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

    # Tek satirin tamami hatali → yazilacak satir kalmadi (BILEREK DEGISTI: eski
    # gerekce "dosyada hata var"di).
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Aktarılabilecek geçerli satır yok"
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
    # BILEREK DEGISTI (P3.1 T11, spec §6.4): zorunlu sutun sayisi 3 → 5 oldu
    # (`Oda Tipi` ve `Brüt m²`, EI 161). Mesaj KANONIK sirayla uretilir.
    assert resp.json()["detail"] == "Excel başlıkları eksik: Blok, Ünite No, Oda Tipi, Brüt m²"


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


async def test_import_hepsi_hatali_dosya_422(client, db_session, user_factory, project_factory):
    """BILEREK DEGISTI (T12): `errors` alani ve 50'lik kirpma KALKTI.

    Kirpma `UnitImportError` govdesine aitti; kismi aktarimda satir raporu
    `rows` icinde ve kirpilmiyor (spec §6.3). Hicbir satir gecerli degilse
    yanit tek Turkce mesajli 422'dir; satir raporunu gormek isteyen kullanici
    `import/validate` ucunu kullanir.
    """
    project = await project_factory("B9-13", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n), kind="Villa") for n in range(1, 61)])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json() == {"detail": "Aktarılabilecek geçerli satır yok"}
    assert await _count_units(db_session, project.id) == 0


async def test_import_owner_side_in_non_land_share_project_returns_422(
    client, db_session, user_factory, project_factory
):
    """§3.3 korkulugu ice aktarmada da gecerlidir — tekil POST ile AYNI kural."""
    project = await project_factory("B9-14", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Sahiplik": "BİZ"})])

    resp = await _post_import(client, project, content, token)

    # Tek satir hatali → gecerli satir kalmadi. Satir mesaji `validate` ucunda
    # gorunur; burada yalniz "hicbiri yazilmadi" kilitlenir.
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Aktarılabilecek geçerli satır yok"
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


# --- P3.1 T11: 12 sutun, iki yeniden adlandirma, yeni satir kurallari (§6.4, §6.5) ---


def test_basliklar_12_kanonik_sirada():
    """EI 85 KANONU: sira DEGISTIRILEMEZ — eksik baslik mesaji bu sirayla uretilir."""
    assert [column.label for column in COLUMNS] == _HEADERS


def test_eski_basliklar_esanlamli_tip_pay():
    """Spec §6.4 / §12.5/50: `Tip` ve `Pay` ESANLAMLI kabul edilir.

    P3 canlidadir ve kullanicinin elinde eski sablonla doldurulmus dosyalar
    olabilir; esanlamli kabul etmemek sessiz bir "baslik eksik" 422'si uretirdi.
    """
    content = _xlsx(
        [_legacy_row(unit_no="4", **{"Pay": "ARSA"})],
        headers=_LEGACY_HEADERS,
    )

    rows, errors, _ = _parse(content)

    assert errors == []
    assert rows[0].layout == "3+1"
    assert rows[0].owner_side is UnitOwnerSide.landowner


def test_baslik_normalizasyonu_I_tuzagi():
    """`"  ODA TİPİ "` → `Oda Tipi` ile AYNI anahtar (`İ` katlama + bosluk sadelestirme).

    Ham `.lower()` ile `"ODA TİPİ"` hicbir zaman `"oda tipi"`ne esitlenmez
    (birlesik nokta) ve eslestirme SESSIZCE basarisiz olurdu.
    """
    assert normalize_header("  ODA TİPİ ") == normalize_header("Oda Tipi")
    assert normalize_header("SAHİPLİK") == normalize_header("Sahiplik")

    content = _xlsx(
        [_row(unit_no="9")],
        headers=["Blok", "Kat", "ÜNİTE NO", "TÜR", "  ODA TİPİ ", *_HEADERS[5:]],
    )
    rows, errors, _ = _parse(content)

    assert errors == []
    assert rows[0].layout == "3+1"


def test_kat_metin_donusturme_yok():
    """KARAR 4 (spec §6.4): `Kat` METINDIR — SOZLUK YOKTUR.

    `"Zemin" → 0` eslemesi ve `"3" → "3. Kat"` guzellestirmesi YAPILMAZ:
    kullanicinin gosterimini sessizce degistirmek veri donusumudur. Tek kural
    20 karakter sinirdir.
    """
    content = _xlsx(
        [
            _row(unit_no="1", **{"Kat": "Zemin"}),
            _row(unit_no="2", **{"Kat": "3. Kat"}),
            _row(unit_no="3", **{"Kat": 3}),
            _row(unit_no="4", **{"Kat": "A" * 21}),
        ]
    )

    rows, errors, _ = _parse(content)

    assert [row.floor for row in rows] == ["Zemin", "3. Kat", "3"]
    assert [(e.row, e.column) for e in errors] == [(5, "Kat")]
    assert errors[0].message == "Kat bilgisi en fazla 20 karakter olabilir"


def test_cephe_sozlugu_bes_deger():
    """Karar 7 (spec §4.2): mockup'ta gecen TAM OLARAK bes deger; tanınmayan → satir hatasi."""
    assert parse_facing("Güney") is UnitFacing.south
    assert parse_facing("GÜNEY-BATI") is UnitFacing.southwest
    assert parse_facing("Doğu") is UnitFacing.east
    assert parse_facing("kuzey") is UnitFacing.north
    assert parse_facing("Batı") is UnitFacing.west
    assert parse_facing(None) is None
    with pytest.raises(ValueError):
        parse_facing("Kuzeydoğu")


def test_sahiplik_yeni_etiketler_kabul():
    """Spec §6.4: kullanici FORMDA GORDUGU etiketi Excel'e yazar (UE 95)."""
    assert parse_owner_side("Yüklenici (Biz)") is UnitOwnerSide.contractor
    assert parse_owner_side("Arsa Sahibi Payı") is UnitOwnerSide.landowner
    # Eski etiketler KORUNUR (geriye donuk uyum).
    assert parse_owner_side("BİZ") is UnitOwnerSide.contractor
    assert parse_owner_side("ARSA") is UnitOwnerSide.landowner


def test_tur_bes_deger():
    """Spec §4.3 / §6.4: `unit_kind` bes degerli (UE 74) — Excel de besini kabul eder."""
    assert parse_kind("Ofis") is UnitKind.office
    assert parse_kind("Depo") is UnitKind.warehouse
    assert parse_kind("OTOPARK") is UnitKind.parking
    assert parse_kind("Daire") is UnitKind.apartment
    assert parse_kind("Dükkan") is UnitKind.shop


def test_oda_tipi_bos_hata():
    """EI 161: `Oda Tipi` P3.1'de ZORUNLU oldu (P3'te opsiyoneldi)."""
    content = _xlsx([_row(unit_no="1", **{"Oda Tipi": None})])

    rows, errors, _ = _parse(content)

    assert rows == []
    assert [(e.row, e.column, e.message) for e in errors] == [
        (2, "Oda Tipi", "Oda Tipi boş olamaz")
    ]


def test_brut_m2_sifir_hata():
    """EI 161 "Brüt m² sıfır olamaz": bos DA sifir DA hatadir (spec §6.5)."""
    content = _xlsx(
        [
            _row(unit_no="1", **{"Brüt m²": 0}),
            _row(unit_no="2", **{"Brüt m²": None}),
        ]
    )

    rows, errors, _ = _parse(content)

    assert rows == []
    assert [(e.row, e.message) for e in errors] == [
        (2, "Brüt m² sıfır olamaz"),
        (3, "Brüt m² sıfır olamaz"),
    ]


def test_hatali_satir_iki_mesaj_tasir():
    """EI 161 BIR satirda IKI mesaj: ilk hatada DURULMAZ.

    Kullanici 48 satirlik dosyayi hata basina bir kez yuklemek zorunda kalmamali.
    """
    content = _xlsx([_row(unit_no="1", **{"Oda Tipi": None, "Brüt m²": 0})])

    rows, errors, _ = _parse(content)

    assert rows == []
    assert [e.message for e in errors] == ["Oda Tipi boş olamaz", "Brüt m² sıfır olamaz"]


def test_maliyet_okunur_ama_dondurulen_satirda_kolon_yok():
    """KARAR 10 (spec §4.5, §6.5): `Maliyet` OKUNUR → uyariyi uretir → ATILIR.

    Sutunu hic okumamak REDDEDILDI (o zaman EI 173 uyarisi hic uretilemezdi),
    ama `ImportRow`'da maliyet ALANI YOKTUR: veri hicbir yere sizamaz.
    """
    content = _xlsx(
        [
            _row(unit_no="1", **{"Maliyet": 860000, "Liste Fiyatı": 890000}),
            _row(unit_no="2", **{"Maliyet": 860000, "Liste Fiyatı": 800000}),
        ]
    )

    rows, errors, warnings = _parse(content)

    assert errors == []
    assert not hasattr(rows[0], "cost")
    assert "cost" not in {field for field in rows[0].__dataclass_fields__}
    # Uyari YALNIZ fiyat maliyetin ALTINDA kalan satirda dogar (EI 173).
    assert [(w.row, w.message) for w in warnings] == [
        (3, "Fiyat maliyetin altında (₺860.000) — kontrol edin")
    ]


# --- P3.1 T12: KISMI AKTARIM (spec §6.1, §6.2, §6.3, §12.5) ---
#
# Bu bolumun tasidigi tek buyuk risk: "gecerli satir yazilmadi" ya da "hatali
# satir yazildi" SESSIZ veri hatasidir. Bu yuzden testler durum koduyla
# YETINMEZ, hangi unitenin DB'de oldugunu tek tek olcerler.


def _ei_rows() -> list[list]:
    """EI 94-99 senaryosu: 24 satir · 22 gecerli · 1 uyari · 1 hata.

    Uyari satiri EI 173 kuralindan dogar (fiyat maliyetin altinda), hata satiri
    EI 161'den (Oda Tipi bos + Brut m² sifir) ve BIR satirda IKI mesaj tasir.
    """
    rows = [_row(unit_no=str(n)) for n in range(1, 23)]
    rows.append(_row(unit_no="23", **{"Maliyet": 860000, "Liste Fiyatı": 800000}))
    rows.append(_row(unit_no="24", **{"Oda Tipi": None, "Brüt m²": 0}))
    return rows


async def test_summary_EI_sayaclari_birebir(client, db_session, user_factory, project_factory):
    """Spec §12.5: EI 95-98 kutulari — 24 / 22 / 1 / 1."""
    project = await project_factory("T12-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    assert body["summary"] == {"total_rows": 24, "valid": 22, "warning": 1, "error": 1}


async def test_hatali_satir_iki_mesaj_tasir_raporda(
    client, db_session, user_factory, project_factory
):
    """EI 161: BIR satirda IKI mesaj → `messages` LISTEDIR, tek metin degil."""
    project = await project_factory("T12-2", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    error_row = next(r for r in body["rows"] if r["status"] == "error")
    assert error_row["messages"] == ["Oda Tipi boş olamaz", "Brüt m² sıfır olamaz"]
    # EI 118-125: rapor satiri dosyadaki degerleri de tasir (kullanici satiri
    # ancak boyle bulur) — hatali satirda da.
    assert error_row["unit_no"] == "24"
    assert error_row["block_name"] == "A Blok"


async def test_import_include_warnings_true_created_23_skipped_1(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/42: varsayilan `include_warnings=True` → 22 gecerli + 1 uyarili."""
    project = await project_factory("T12-3", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_import(client, project, _xlsx(_ei_rows()), token)).json()

    assert (body["created"], body["skipped"]) == (23, 1)
    assert body["created"] + body["skipped"] == body["summary"]["total_rows"]
    assert await _count_units(db_session, project.id) == 23


async def test_import_include_warnings_false_created_22_skipped_2(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/43 (EI 192 kutucugu isaretsiz): uyarili satir da ATLANIR."""
    project = await project_factory("T12-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (
        await _post_import(client, project, _xlsx(_ei_rows()), token, include_warnings=False)
    ).json()

    assert (body["created"], body["skipped"]) == (22, 2)
    warning_row = next(r for r in body["rows"] if r["status"] == "warning")
    assert warning_row["imported"] is False
    assert await _count_units(db_session, project.id) == 22


async def test_import_hic_gecerli_satir_yoksa_422_nothing_to_write(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/45: `created=0` ile 200 DONMEZ — kullanici "aktarildi" sanardi.

    ISLEM SINIRI: 422 ilk `session.add`'DEN ONCE atilir; ustelik istisna tum
    istek transaction'ini geri alir. Iki kat guvence de olculur (unite VE blok).
    """
    project = await project_factory("T12-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [_row(unit_no="1", **{"Oda Tipi": None}), _row(block="Yeni Blok", kind="Villa")]
    )

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Aktarılabilecek geçerli satır yok"
    assert await _count_units(db_session, project.id) == 0
    assert await _count_blocks(db_session, project.id) == 1  # yalniz onceden var olan


async def test_import_ayni_dosya_ikinci_kez_hepsi_atlanir_422(
    client, db_session, user_factory, project_factory
):
    """Spec §6.1'in 2. gerekcesinin TESTI (§12.5/46).

    P3 hep-ya-hici "duzelt ve yeniden yukle imkânsizlasir" diye savunmustu.
    Kismi aktarimda bu itiraz ZARARSIZDIR: ikinci yuklemede zaten yazilmis
    satirlar "zaten kullaniliyor" hatasiyla RAPORLANIR ve atlanir.
    """
    project = await project_factory("T12-6", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no=str(n)) for n in range(1, 4)])

    first = await _post_import(client, project, content, token)
    second = await _post_import(client, project, content, token)

    assert first.json()["created"] == 3
    assert second.status_code == 422
    assert second.json()["detail"] == "Aktarılabilecek geçerli satır yok"
    assert await _count_units(db_session, project.id) == 3


async def test_import_yeni_blok_olusur_hatali_satirin_blogu_olusmaz(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47: blok olusturma GECERLI satirlara baglidir.

    Hatali satirin blogu acilsaydi kullanici hicbir unitesi olmayan hayalet bir
    blokla kalirdi ve bunu ancak blok listesinde fark ederdi.
    """
    project = await project_factory("T12-7", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(
        [
            _row(block="İyi Blok", unit_no="1"),
            _row(block="Kötü Blok", unit_no="2", kind="Villa"),
        ]
    )

    body = (await _post_import(client, project, content, token)).json()

    assert (body["created"], body["skipped"], body["blocks_created"]) == (1, 1, 1)
    names = (
        (await db_session.execute(select(Block.name).where(Block.project_id == project.id)))
        .scalars()
        .all()
    )
    assert list(names) == ["İyi Blok"]


async def test_import_cok_santiyeli_site_id_yok_422_site_required(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47b: cok santiyeli projede otomatik atama YANLIS veri uretirdi."""
    project = await project_factory("T12-8", project_type="kendi_yatirim")
    await _site(db_session, project, code="S1")
    await _site(db_session, project, code="S2")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, _xlsx([_row(block="Yeni Blok")]), token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Birden fazla şantiye var, blok için şantiye seçilmelidir"
    assert await _count_blocks(db_session, project.id) == 0


async def test_import_site_id_ile_yeni_bloklar_o_santiyede(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/47b (EI 61 "Hedef Şantiye", karar 3): bugun 422 veren yol boyle acilir."""
    project = await project_factory("T12-9", project_type="kendi_yatirim")
    await _site(db_session, project, code="S1")
    second = await _site(db_session, project, code="S2")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(
        client, project, _xlsx([_row(block="Yeni Blok")]), token, site_id=second.id
    )

    assert resp.status_code == 200
    block = (
        await db_session.execute(select(Block).where(Block.project_id == project.id))
    ).scalar_one()
    assert block.site_id == second.id


async def test_import_mevcut_blogun_site_id_si_degismez(
    client, db_session, user_factory, project_factory
):
    """Spec §6.2: `site_id` YALNIZ yeni blok acarken kullanilir.

    SESSIZ VERI TASIMA RISKI: dosyadaki blok zaten varsa bloğun santiyesi
    DEGISTIRILMEZ — blok tasimak bu ucun isi degildir ve kullanici uniteye
    ekleme yaparken bloğunu tasidigini fark edemezdi.
    """
    project = await project_factory("T12-10", project_type="kendi_yatirim")
    first = await _site(db_session, project, code="S1")
    second = await _site(db_session, project, code="S2")
    block = await _block(db_session, project, first, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_import(client, project, _xlsx([_row(unit_no="9")]), token, site_id=second.id)

    assert resp.status_code == 200
    await db_session.refresh(block)
    assert block.site_id == first.id


async def test_import_baska_projenin_site_id_404(client, db_session, user_factory, project_factory):
    """Spec §12.5/47c — YENI IDOR YUZEYI (karar 3 ile acildi).

    Baska projenin santiyesi VAR OLMAYAN kimlikle AYNI 404'u alir: aksi hâlde
    elinde UUID olan kullanici kaydin var oldugunu ve baskasina ait oldugunu
    ayirt edebilirdi.
    """
    project = await project_factory("T12-11A", project_type="kendi_yatirim")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("T12-11B", project_type="kendi_yatirim")
    foreign = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok")])

    foreign_resp = await _post_import(client, project, content, token, site_id=foreign.id)
    unknown_resp = await _post_import(client, project, content, token, site_id=uuid.uuid4())

    assert foreign_resp.status_code == 404
    assert foreign_resp.json() == {"detail": "Şantiye bulunamadı"}
    assert unknown_resp.json() == foreign_resp.json()
    assert await _count_blocks(db_session, project.id) == 0


async def test_import_maliyet_hicbir_kolona_yazilmaz(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/48 (karar 10): `Maliyet` DB'de karsiligi olmayan bir sutundur."""
    project = await project_factory("T12-12", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Maliyet": 860000, "Liste Fiyatı": 890000})])

    resp = await _post_import(client, project, content, token)

    assert resp.status_code == 200
    unit = (
        await db_session.execute(select(Unit).where(Unit.project_id == project.id))
    ).scalar_one()
    values = {str(getattr(unit, column.name)) for column in Unit.__table__.columns}
    assert not any("860000" in value for value in values)


async def test_import_fiyat_maliyetin_altinda_warning(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/49 (EI 173) — mockup'taki TEK uyari kurali."""
    project = await project_factory("T12-13", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(unit_no="1", **{"Maliyet": 860000, "Liste Fiyatı": 800000})])

    body = (await _post_import(client, project, content, token)).json()

    assert body["rows"][0]["status"] == "warning"
    assert body["rows"][0]["messages"] == ["Fiyat maliyetin altında (₺860.000) — kontrol edin"]
    assert body["rows"][0]["imported"] is True


# --- P3.1 T13: POST /projects/{id}/units/import/validate (spec §6.2, §12.5/40-41) ---
#
# `bulk/preview` ile AYNI garanti: **HICBIR SEY YAZMAZ**. Garanti sessizce
# bozulabilecegi icin testler durum koduyla yetinmez; unite, blok VE denetim
# satiri sayimlarini olcer.


async def _post_validate(client, project, content: bytes, token: str, **form):
    return await client.post(
        f"/projects/{project.id}/units/import/validate",
        files={"file": ("uniteler.xlsx", content, _XLSX_MIME)},
        data={key: str(value) for key, value in form.items()},
        headers=_auth(token),
    )


async def test_validate_EI_senaryosu_summary_birebir(
    client, db_session, user_factory, project_factory
):
    """Spec §12.5/40: EI 95-98 kutulari 24 / 22 / 1 / 1; `rows` 24 satir."""
    project = await project_factory("T13-1", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_validate(client, project, _xlsx(_ei_rows()), token)

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == {"total_rows": 24, "valid": 22, "warning": 1, "error": 1}
    assert len(body["rows"]) == 24
    assert body["blocks_to_create"] == []
    error_row = next(r for r in body["rows"] if r["status"] == "error")
    assert error_row["messages"] == ["Oda Tipi boş olamaz", "Brüt m² sıfır olamaz"]


async def test_validate_hicbir_satir_yazilmaz(client, db_session, user_factory, project_factory):
    """Spec §12.5/41: oncesi/sonrasi unite VE blok sayimi ESIT.

    `blocks_to_create` dolu OLSA BILE hicbir blok acilmaz — dogrulama yalniz
    "acilacak" der, acmaz.
    """
    project = await project_factory("T13-2", project_type="kendi_yatirim")
    await _site(db_session, project)
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx([_row(block="Yeni Blok", unit_no="1")])

    resp = await _post_validate(client, project, content, token)

    assert resp.status_code == 200
    assert resp.json()["blocks_to_create"] == ["Yeni Blok"]
    assert await _count_units(db_session, project.id) == 0
    assert await _count_blocks(db_session, project.id) == 0


async def test_validate_denetim_yazmaz(client, db_session, user_factory, project_factory):
    """Spec §9: dogrulama bir OKUMA ucudur → denetim satiri URETMEZ (P4 T7).

    Sayim MUTLAKTIR (`== 0`): tek satir bile "yazan uc denetim yazar" kuralini
    bir bayraga bagli hâle getirirdi.
    """
    project = await project_factory("T13-3", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    await db_session.execute(delete(AuditLog))

    resp = await _post_validate(client, project, _xlsx(_ei_rows()), token)

    assert resp.status_code == 200
    assert (
        int((await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one())
        == 0
    )


async def test_validate_ve_import_ayni_rapor_uretir(
    client, db_session, user_factory, project_factory
):
    """TEK KAYNAK KANITI (spec §6.2): iki uc de `_plan_rows`'tan beslenir.

    Ayni dosya icin `rows` BIREBIR aynidir; tek fark `imported` bayragidir.
    Ayrisirlarsa "dogrulamada gecerli gorunup aktarimda atlanan satir" sinifi
    dogar ve kullanici bunu ancak eksik unitelerden fark ederdi.
    """
    project = await project_factory("T13-4", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")
    content = _xlsx(_ei_rows())

    validated = (await _post_validate(client, project, content, token)).json()
    imported = (await _post_import(client, project, content, token)).json()

    assert validated["summary"] == imported["summary"]
    assert [{**r, "imported": None} for r in validated["rows"]] == [
        {**r, "imported": None} for r in imported["rows"]
    ]


async def test_validate_imported_daima_false(client, db_session, user_factory, project_factory):
    """Spec §6.3: dogrulamada `imported` DAIMA `False` — "gecerli" ile "yazildi"
    ayri sorulardir ve tek alana indirilseydi dogrulama sonucu aktarim sonucu
    gibi okunabilirdi."""
    project = await project_factory("T13-5", project_type="kendi_yatirim")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _post_validate(client, project, _xlsx(_ei_rows()), token)).json()

    assert all(row["imported"] is False for row in body["rows"])
    assert any(row["status"] == "ok" for row in body["rows"])


async def test_validate_requires_full_permission(client, db_session, user_factory, project_factory):
    """Spec §6.2 / IDOR-13: `view` YETMEZ — dogrulama yazma akisinin parcasidir."""
    project = await project_factory("T13-6", project_type="kendi_yatirim")
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await _post_validate(client, project, _xlsx([_row()]), token)

    assert resp.status_code == 403


async def test_validate_baska_projenin_site_id_404(
    client, db_session, user_factory, project_factory
):
    """`site_id` dogrulama ucunda da denetlenir: kullanici gecersiz hedef
    santiyeyi AKTARIMDAN ONCE ogrenmelidir (spec §6.2)."""
    project = await project_factory("T13-7A", project_type="kendi_yatirim")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("T13-7B", project_type="kendi_yatirim")
    foreign = await _site(db_session, other, code="S-FOREIGN")
    token = await _login(client, user_factory, "system_admin")

    resp = await _post_validate(client, project, _xlsx([_row()]), token, site_id=foreign.id)

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Şantiye bulunamadı"}
