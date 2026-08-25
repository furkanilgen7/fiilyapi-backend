"""P3.1 T9 — `POST /projects/{id}/units/bulk/preview` (spec §5.4, §5.6, §12.4/30-33).

BU DOSYANIN VAROLUS SEBEBI TEK BIR GARANTIDIR: **onizleme HICBIR SEY YAZMAZ.**

Garanti sessizce bozulabilir — serviste tek bir `flush`/`commit`, ya da denetim
satiri yazan bir router dekoratoru yeterlidir. Bu yuzden testler durum koduyla
YETINMEZ: istek oncesi/sonrasi `units` ve `blocks` sayimlarini VE `audit_logs`
sayimini olcerler. Ayri uc (yerine `dry_run` bayragi) kararinin tek gerekcesi
de budur (spec §5.4/2).

Onizleme OTORITER DEGILDIR, tekrarlanabilir bir HESAPTIR (TU 182 "Onizlemeyi
Yenile"): gercek uretim onizlemeden gelen satirlari kabul etmez, ayni saf
fonksiyonla YENIDEN uretir.
"""

import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.modules.audit.models import AuditLog
from app.modules.units.models import Block, Unit
from tests.modules.units._units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

# TU 107-133 "Kat Sablonu" — mockup'tan BIREBIR (gövde JSON'u oldugu icin
# `test_units_bulk.py`'deki `_TU_SLOTS` sema nesnelerinden ayri durur).
_TU_SLOT_ROWS = [
    {
        "sequence": 1,
        "layout": "3+1",
        "gross_area_m2": "148.00",
        "net_area_m2": "128.00",
        "facing": "south",
        "list_price": "1280000.00",
    },
    {
        "sequence": 2,
        "layout": "2+1",
        "gross_area_m2": "112.00",
        "net_area_m2": "96.00",
        "facing": "east",
        "list_price": "940000.00",
    },
    {
        "sequence": 3,
        "layout": "3+1",
        "gross_area_m2": "148.00",
        "net_area_m2": "128.00",
        "facing": "west",
        "list_price": "1240000.00",
    },
]


def _tu_payload(block_id: uuid.UUID, **overrides) -> dict:
    """TU formunun tamami: 8 kat x 3 slot, `{Blok}-{Sira}`, %1,5 kat artisi."""
    payload: dict = {
        "block_id": str(block_id),
        "unit_kind": "apartment",
        "start_floor": 1,
        "end_floor": 8,
        "units_per_floor": 3,
        "numbering": "block_sequence",
        "slots": _TU_SLOT_ROWS,
        "floor_price_increase_pct": "1.50",
    }
    payload.update(overrides)
    return payload


async def _count(session, model) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _preview(client, project_id, token, payload) -> object:
    return await client.post(
        f"/projects/{project_id}/units/bulk/preview", json=payload, headers=_auth(token)
    )


# --- #30: TU senaryosunun tamami ---


async def test_preview_TU_senaryosunun_tamami(client, db_session, user_factory, project_factory):
    """Spec §12.4/30: `rows[0..6]` mockup TU 159-165 ile BIREBIR.

    `floor` SAYISALDIR (TU 152 1/2/3 basiyor) ve `floor_label` METINDIR
    ("1. Kat") — karar 4. Ikisi ayri alandir: biri numaralandirmanin girdisi,
    digeri uniteye YAZILACAK deger.
    """
    project = await project_factory("T9-1")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _preview(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_units"] == 24
    assert body["conflicting_unit_nos"] == []
    assert len(body["rows"]) == 24
    assert [
        (r["unit_no"], r["floor"], r["floor_label"], r["layout"], r["facing"], r["list_price"])
        for r in body["rows"][:7]
    ] == [
        ("C-1", 1, "1. Kat", "3+1", "south", "1280000.00"),
        ("C-2", 1, "1. Kat", "2+1", "east", "940000.00"),
        ("C-3", 1, "1. Kat", "3+1", "west", "1240000.00"),
        ("C-4", 2, "2. Kat", "3+1", "south", "1299200.00"),
        ("C-5", 2, "2. Kat", "2+1", "east", "954100.00"),
        ("C-6", 2, "2. Kat", "3+1", "west", "1258600.00"),
        ("C-7", 3, "3. Kat", "3+1", "south", "1318700.00"),
    ]
    assert body["rows"][0]["gross_area_m2"] == "148.00"
    assert body["rows"][0]["net_area_m2"] == "128.00"
    assert all(r["conflict"] is False for r in body["rows"])


async def test_preview_total_list_value_satirlardan_toplanir(
    client, db_session, user_factory, project_factory
):
    """KARAR 5 / onayli sapma §11.6: mockup'in ₺27.264.000 sayisi HEDEFLENMEZ.

    Mockup'in toplami kendi verisiyle uzlasmiyor (artissiz toplam bile
    27.680.000). Kanon: toplam SATIRLARDAN toplanir.
    """
    project = await project_factory("T9-2")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (await _preview(client, project.id, token, _tu_payload(block.id))).json()

    assert Decimal(body["total_list_value"]) == sum(
        (Decimal(r["list_price"]) for r in body["rows"]), Decimal("0")
    )


# --- #30b: cati turu ---


async def test_preview_roof_floor_son_tur_cati_kati(
    client, db_session, user_factory, project_factory
):
    """Spec §12.4/30b (TU 71): `roof_floor` BIR TUR DAHA uretir, etiketi "Çatı Katı"."""
    project = await project_factory("T9-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (
        await _preview(
            client,
            project.id,
            token,
            _tu_payload(block.id, end_floor=2, roof_floor=True),
        )
    ).json()

    assert body["total_units"] == 9  # 2 kat + cati turu, 3'er slot
    assert [r["floor_label"] for r in body["rows"][-3:]] == ["Çatı Katı"] * 3
    # `{Kat}` jetonu `end_floor + 1`; bu sayi HICBIR sutuna yazilmaz.
    assert [r["floor"] for r in body["rows"][-3:]] == [3, 3, 3]


# --- #30c: kodu NULL olan blok ---


async def test_preview_null_kodlu_blokta_anlik_turetme(
    client, db_session, user_factory, project_factory
):
    """Spec §12.4/30c, plan §0.B (KESINLESMIS): kodu NULL olan canli blokta
    `{Blok}` jetonu blok ADINDAN ANLIK turetilir ve blok satiri GUNCELLENMEZ.

    Backfill migration'i YOKTUR (karar 8). Ikinci bir otorite dogmaz: cagrilan
    fonksiyon kod uretiminin ta kendisidir, blok bir kez duzenlenip kodu
    kalicilastiginda cikti birebir aynidir.
    """
    project = await project_factory("T9-4")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    assert block.code is None
    token = await _login(client, user_factory, "system_admin")

    body = (await _preview(client, project.id, token, _tu_payload(block.id))).json()

    assert [r["unit_no"] for r in body["rows"][:3]] == ["C-1", "C-2", "C-3"]
    await db_session.refresh(block)
    assert block.code is None  # SAKLANMADI


# --- #31: cakisma UYARIDIR, hata degil ---


async def test_preview_cakisma_200_ve_conflict_true(
    client, db_session, user_factory, project_factory
):
    """Spec §5.6 / §12.4/31 (TU 177): "cakisma varsa UYARI verilir".

    Onizlemede cakisma **hata degildir** — kullanici `start_number`'i degistirip
    yeniden onizler (TU 84 ipucu). Blokaj yalniz KAYDETMEDE (`POST …/bulk` → 409).
    """
    project = await project_factory("T9-5")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    await _unit(db_session, project, block, "C-2")
    await _unit(db_session, project, block, "C-5")
    token = await _login(client, user_factory, "system_admin")

    resp = await _preview(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["conflicting_unit_nos"] == ["C-2", "C-5"]
    assert [r["unit_no"] for r in body["rows"] if r["conflict"]] == ["C-2", "C-5"]


# --- #32, #33: HICBIR SEY YAZMAZ ---


async def test_preview_hicbir_satir_yazilmaz(client, db_session, user_factory, project_factory):
    """Spec §12.4/32: oncesi/sonrasi `units` VE `blocks` sayimi ESIT.

    Durum kodu yeterli DEGILDIR: 200 donerken 24 satir yazilmis olabilirdi.
    Sayim tek gercek kanittir (`test_units_bulk.py` atomiklik testiyle ayni
    gerekce). `blocks` da sayilir cunku #30c kodu NULL blogu ANLIK turetiyor —
    turetmenin bir `UPDATE`'e kaymasi tam da bu sayimla yakalanir.
    """
    project = await project_factory("T9-6")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")
    units_before = await _count(db_session, Unit)
    blocks_before = await _count(db_session, Block)

    resp = await _preview(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 200
    assert resp.json()["total_units"] == 24
    assert await _count(db_session, Unit) == units_before
    assert await _count(db_session, Block) == blocks_before


async def test_preview_denetim_yazmaz(client, db_session, user_factory, project_factory):
    """Spec §9 / §12.4/33: onizleme OKUMA ucudur → denetim satiri URETMEZ (P4 T7).

    Sayim MUTLAKTIR (`== 0`), "az" degil: tek bir satir bile "yazan uc denetim
    yazar" kuralini bayraga bagli hâle getirirdi ve denetim bosluklari tam
    olarak orada dogar (spec §5.4/2).
    """
    project = await project_factory("T9-7")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")
    # `login` de bir denetim eylemidir; silinmezse "sifir satir" iddiasi yanlis olur.
    await db_session.execute(delete(AuditLog))

    resp = await _preview(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 200
    assert await _count(db_session, AuditLog) == 0


# --- #33b: kirpma YOK ---


async def test_preview_tum_satirlari_doner(client, db_session, user_factory, project_factory):
    """Spec §5.4: sunucu TUM satirlari doner, 500 bile olsa.

    TU 166 "… 17 unite daha" bir FRONTEND kirpmasidir; sunucu kirpsaydi ekran
    "hangi satir cakisiyor" sorusunu cevaplayamazdi.
    """
    project = await project_factory("T9-8")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    body = (
        await _preview(
            client,
            project.id,
            token,
            {
                "block_id": str(block.id),
                "unit_kind": "apartment",
                "start_floor": 1,
                "end_floor": 25,
                "units_per_floor": 20,
                "numbering": "block_sequence",
            },
        )
    ).json()

    assert body["total_units"] == 500
    assert len(body["rows"]) == 500
    assert body["rows"][-1]["unit_no"] == "C-500"


# --- Yetki ve gorunurluk ---


async def test_preview_requires_full_permission(client, db_session, user_factory, project_factory):
    """Spec §5.4/2: izin `full` KALIR. Onizleme yazma akisinin parcasidir ve
    `view` kullanicisina fiyat uretim kurallarini acmaz."""
    project = await project_factory("T9-9")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, name="C Blok")
    token = await _login_with_access(client, db_session, user_factory, "site_chief")

    resp = await _preview(client, project.id, token, _tu_payload(block.id))

    assert resp.status_code == 403


async def test_preview_foreign_block_returns_404(client, db_session, user_factory, project_factory):
    """IDOR-9 deseni: govdedeki `block_id` baska projenin blogu olabilir → 404."""
    project = await project_factory("T9-10A")
    await _site(db_session, project, code="S-OWN")
    other = await project_factory("T9-10B")
    other_site = await _site(db_session, other, code="S-FOREIGN")
    foreign_block = await _block(db_session, other, other_site, name="C Blok")
    token = await _login(client, user_factory, "system_admin")

    resp = await _preview(client, project.id, token, _tu_payload(foreign_block.id))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Blok bulunamadı"
