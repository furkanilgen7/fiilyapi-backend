"""B11 — blok/unite uclarinin denetim gunlugu (spec §9).

Iki kural bu dosyada KILITLENIR:

1. **Okuma uclari YAZMAZ.** `GET .../blocks` ve `GET .../units` denetim satiri
   uretmez; aksi hâlde bir liste ekranini acan kullanici gunlugu doldururdu
   (P4 T7 kurali).
2. **Toplu uclarda ISTEK BASINA TEK SATIR.** 24 unitelik toplu uretim, 10
   satirlik ice aktarma ve 42 unitelik paylasim BIR satir yazar — satir basina
   gunluk, denetim gunlugunu okunamaz hâle getirirdi (spec §9).

Sayimlar mutlak yapilir (`== 1`), "en az bir" DEGIL: `>= 1` iddiasi tam da
onlemek istedigimiz 24-satirlik davranisi yesil gosterirdi.
"""

import io
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import delete, select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.units.models import Unit, UnitKind, UnitOwnerSide
from app.modules.units.schemas import UnitNumberingPattern
from tests.modules.units.test_units_api import _block, _login, _site, _unit

_IP = "203.0.113.42"
_IP_HEADER = {"x-forwarded-for": _IP}
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# P3.1 T11 (spec §6.4): 12 kanonik sutun. `Oda Tipi` ve `Brüt m²` ZORUNLU
# oldugu icin satir uretecinin varsayilanlari da dolu gelir (EI 161).
_IMPORT_HEADERS = [
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


async def _admin(client, db_session, user_factory) -> dict[str, str]:
    """Giris yapar ve LOGIN'in urettigi denetim satirini temizler.

    Temizlik sart: `login` de bir denetim eylemidir ve silinmezse "tam bir
    satir yazildi" iddialari toplam sayim uzerinden yanlis olurdu.
    """
    token = await _login(client, user_factory, "system_admin")
    await db_session.execute(delete(AuditLog))
    return {"Authorization": f"Bearer {token}", **_IP_HEADER}


async def _rows(db_session, action: AuditAction | None = None) -> list[AuditLog]:
    stmt = select(AuditLog)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return list((await db_session.execute(stmt)).scalars().all())


async def _count(db_session) -> int:
    return len(await _rows(db_session))


def _xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(_IMPORT_HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- Blok uclari (spec §9) ---


async def test_block_create_writes_one_audit_row(client, db_session, user_factory, project_factory):
    project = await project_factory("B11-1", name="Yeşil Vadi")
    await _site(db_session, project)
    headers = await _admin(client, db_session, user_factory)

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=headers
    )

    assert resp.status_code == 201
    rows = await _rows(db_session, AuditAction.create)
    assert len(rows) == 1
    assert rows[0].detail == "Yeni blok oluşturuldu: Yeşil Vadi · A Blok"


async def test_block_update_writes_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("B11-2", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.patch(f"/blocks/{block.id}", json={"name": "B Blok"}, headers=headers)

    assert resp.status_code == 200
    rows = await _rows(db_session, AuditAction.update)
    assert len(rows) == 1
    assert rows[0].detail == "Blok güncellendi: Yeşil Vadi · B Blok"


async def test_block_delete_writes_audit_with_delete_action(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B11-3", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.delete(f"/blocks/{block.id}", headers=headers)

    assert resp.status_code == 204
    rows = await _rows(db_session, AuditAction.delete)
    assert len(rows) == 1
    assert rows[0].detail == "Blok silindi: Yeşil Vadi · A Blok"


# --- Unite uclari (spec §9) ---


async def test_unit_create_writes_audit(client, db_session, user_factory, project_factory):
    """Mesajda PROJE ADI da vardir: "A Blok · Daire 1" her projede olabilir,
    proje adi olmadan denetim satiri anlamsizlasir (spec §9)."""
    project = await project_factory("B11-4", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.post(
        f"/projects/{project.id}/units",
        json={"block_id": str(block.id), "unit_no": "1", "unit_kind": "apartment"},
        headers=headers,
    )

    assert resp.status_code == 201
    rows = await _rows(db_session, AuditAction.create)
    assert len(rows) == 1
    assert rows[0].detail == "Yeni ünite oluşturuldu: Yeşil Vadi · A Blok · 1"


async def test_unit_update_writes_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("B11-5", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    unit = await _unit(db_session, project, block, "1")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.patch(f"/units/{unit.id}", json={"unit_no": "2"}, headers=headers)

    assert resp.status_code == 200
    rows = await _rows(db_session, AuditAction.update)
    assert len(rows) == 1
    assert rows[0].detail == "Ünite güncellendi: Yeşil Vadi · A Blok · 2"


async def test_unit_delete_writes_audit_with_delete_action(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B11-6", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    unit = await _unit(db_session, project, block, "1")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.delete(f"/units/{unit.id}", headers=headers)

    assert resp.status_code == 204
    rows = await _rows(db_session, AuditAction.delete)
    assert len(rows) == 1
    assert rows[0].detail == "Ünite silindi: Yeşil Vadi · A Blok · 1"


# --- Toplu uclar: ISTEK BASINA TEK SATIR (spec §9) ---


async def test_bulk_writes_exactly_one_audit_row_for_24_units(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B11-7", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)

    resp = await client.post(
        f"/projects/{project.id}/units/bulk",
        json={
            "block_id": str(block.id),
            # P3.1 T8: `floor_based` → `floor_sequence` (spec §5.2). Yeniden
            # ADLANDIRMA; bu testin olctugu sey (istek basina TEK denetim
            # satiri) degismedi.
            "numbering": UnitNumberingPattern.floor_sequence.value,
            "start_floor": 1,
            "end_floor": 12,
            "units_per_floor": 2,
            "unit_kind": UnitKind.apartment.value,
        },
        headers=headers,
    )

    assert resp.status_code == 201
    created = (
        await db_session.execute(select(Unit).where(Unit.project_id == project.id))
    ).scalars()
    assert len(list(created)) == 24
    rows = await _rows(db_session, AuditAction.create)
    assert len(rows) == 1
    assert rows[0].detail == "Toplu ünite üretildi: Yeşil Vadi · A Blok · 24 ünite"


async def test_import_writes_exactly_one_audit_row_for_10_units(
    client, db_session, user_factory, project_factory
):
    project = await project_factory("B11-8", name="Yeşil Vadi")
    site = await _site(db_session, project)
    await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)
    content = _xlsx(
        [
            ["A Blok", None, str(no), "Daire", "3+1", 120, None, None, None, None, None, None]
            for no in range(1, 11)
        ]
    )

    resp = await client.post(
        f"/projects/{project.id}/units/import",
        files={"file": ("uniteler.xlsx", content, _XLSX_MIME)},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["created"] == 10
    rows = await _rows(db_session, AuditAction.create)
    assert len(rows) == 1
    assert rows[0].detail == "Üniteler Excel'den içe aktarıldı: Yeşil Vadi · 10 ünite"


async def test_allocation_writes_exactly_one_audit_row_for_42_units(
    client, db_session, user_factory, project_factory
):
    """42 satirlik bir kayit denetim gunlugunu bogar (spec §9): TEK satir yazilir."""
    project = await project_factory("B11-9", name="Yeşil Vadi", project_type="kat_karsiligi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    units = [await _unit(db_session, project, block, str(no)) for no in range(1, 43)]
    headers = await _admin(client, db_session, user_factory)

    resp = await client.patch(
        f"/projects/{project.id}/units/allocation",
        json={
            "items": [
                {"unit_id": str(unit.id), "owner_side": UnitOwnerSide.contractor.value}
                for unit in units
            ]
        },
        headers=headers,
    )

    assert resp.status_code == 200
    rows = await _rows(db_session, AuditAction.update)
    assert len(rows) == 1
    assert rows[0].detail == "Ünite paylaşımı güncellendi: Yeşil Vadi · 42 ünite"


# --- Okuma uclari YAZMAZ + ortak alanlar + reddedilen istek ---


async def test_read_endpoints_write_no_audit(client, db_session, user_factory, project_factory):
    project = await project_factory("B11-10", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    await _unit(db_session, project, block, "1")
    headers = await _admin(client, db_session, user_factory)

    assert (await client.get(f"/projects/{project.id}/blocks", headers=headers)).status_code == 200
    assert (await client.get(f"/projects/{project.id}/units", headers=headers)).status_code == 200

    assert await _count(db_session) == 0


async def test_audit_rows_carry_actor_and_ip(client, db_session, user_factory, project_factory):
    project = await project_factory("B11-11", name="Yeşil Vadi")
    await _site(db_session, project)
    headers = await _admin(client, db_session, user_factory)

    resp = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=headers
    )

    assert resp.status_code == 201
    rows = await _rows(db_session, AuditAction.create)
    assert len(rows) == 1
    assert rows[0].actor_user_id is not None
    # INET sutunu `ipaddress` nesnesi dondurur; karsilastirma metne cevrilerek yapilir.
    assert str(rows[0].ip_address) == _IP


async def test_failed_write_writes_no_audit(client, db_session, user_factory, project_factory):
    """409 (cakisan blok adi) ve 422 (net > brut) reddedilen isteklerdir: denetim
    satiri asil islemle AYNI transaction'da oldugu icin gunluk BOS kalir."""
    project = await project_factory("B11-12", name="Yeşil Vadi")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="A Blok")
    headers = await _admin(client, db_session, user_factory)

    duplicate = await client.post(
        f"/projects/{project.id}/blocks", json={"name": "A Blok"}, headers=headers
    )
    invalid = await client.post(
        f"/projects/{project.id}/units",
        json={
            "block_id": str(block.id),
            "unit_no": "1",
            "unit_kind": "apartment",
            "gross_area_m2": str(Decimal("100.00")),
            "net_area_m2": str(Decimal("120.00")),
        },
        headers=headers,
    )

    assert duplicate.status_code == 409
    assert invalid.status_code == 422
    assert await _count(db_session) == 0
