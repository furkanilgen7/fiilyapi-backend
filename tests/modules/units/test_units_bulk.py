"""B8 — toplu unite uretimi (spec §6.3, §7.7).

ATOMIKLIK SINIFI. Kismi yazma SESSIZ VERI HATASIDIR: kullanici 48 uniteden
3'unun atlandigini asla fark etmez. Bu yuzden `test_bulk_conflict_...` testleri
durum koduyla YETINMEZ, istek oncesi/sonrasi `count(*)` esitligini olcer —
plan B8'in acik talebi ve bu davranisin TEK GERCEK KANITIDIR.

Numaralandirma saf fonksiyonlari (`app/modules/units/bulk.py`) DB'siz test edilir:
sira/on ek/kat mantigi bir HTTP istegine ihtiyac duymaz.
"""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.modules.units.bulk import (
    ROOF_FLOOR_LABEL,
    floor_label,
    generate_unit_numbers,
    generate_units,
    total_list_value,
)
from app.modules.units.models import Unit, UnitFacing
from app.modules.units.schemas import (
    UnitBulkCreate,
    UnitBulkSlot,
    UnitKind,
    UnitNumberingPattern,
)
from tests.modules.units.test_units_api import (
    _auth,
    _block,
    _login,
    _login_with_access,
    _site,
    _unit,
)

_ANY_BLOCK = uuid.uuid4()

# TU 107-133 "Kat Sablonu" tablosunun UC SATIRI, mockup'tan BIREBIR. Onizleme
# beklentileri (TU 159-165) bu veriden turedigi icin sayilar burada TEK yerde
# durur; testte tekrar edilirse biri degistiginde digeri sessizce bayatlar.
_TU_SLOTS = (
    UnitBulkSlot(
        sequence=1,
        layout="3+1",
        gross_area_m2=Decimal("148"),
        net_area_m2=Decimal("128"),
        facing=UnitFacing.south,
        list_price=Decimal("1280000"),
    ),
    UnitBulkSlot(
        sequence=2,
        layout="2+1",
        gross_area_m2=Decimal("112"),
        net_area_m2=Decimal("96"),
        facing=UnitFacing.east,
        list_price=Decimal("940000"),
    ),
    UnitBulkSlot(
        sequence=3,
        layout="3+1",
        gross_area_m2=Decimal("148"),
        net_area_m2=Decimal("128"),
        facing=UnitFacing.west,
        list_price=Decimal("1240000"),
    ),
)


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
    """SY 76-99: 2 kat x 12 daire → "1".."24". Sira KAT KAT ilerler.

    KOORDINATOR KARARI (plan §0.C): `sequential` deseni P3.1'de KORUNUR. Mockup
    TU 79'un dort deseninin HICBIRI ciplak sayi uretmiyor (`label_sequence` →
    "Daire 1"), dolayisiyla bu ekran dort desenle uretilemezdi. Enum bes
    degerlidir: dort mockup deseni + `sequential`.
    """
    numbers = generate_unit_numbers(_bulk(start_floor=1, end_floor=2, units_per_floor=12))

    assert numbers == [str(n) for n in range(1, 25)]


def test_prefix_korunur_D1_D4():
    """SY 132-135 REGRESYONU (plan §0.C): `prefix="D"` + `sequential` → D1..D4.

    P3'te bu test `test_sequential_numbering_with_prefix` adiyla vardi; adi
    korunan karari gorunur kilmadigi icin yeniden adlandirildi — davranis
    DEGISMEDI. `prefix` desen ciktisinin ONUNE eklenir ve varsayilani `""`
    oldugu icin mevcut davranis bozulmaz (spec §5.2 son paragrafi).
    """
    numbers = generate_unit_numbers(
        _bulk(start_floor=1, end_floor=1, units_per_floor=4, prefix="D")
    )

    assert numbers == ["D1", "D2", "D3", "D4"]


def test_prefix_dort_desende_de_onune_eklenir():
    """`prefix` desen ciktisinin ONUNE eklenir — dort yeni desende de (spec §5.2)."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=1,
            units_per_floor=2,
            prefix="X",
            numbering=UnitNumberingPattern.block_sequence,
        ),
        block_code="C",
    )

    assert numbers == ["XC-1", "XC-2"]


def test_roof_floor_uretim_sinirina_dahildir():
    """`_MAX_BULK_UNITS` cati turunu DE sayar: saymasaydi kullanici 500 sinirini
    fazladan bir kat kadar sessizce asardi."""
    with pytest.raises(ValidationError) as exc:
        _bulk(start_floor=1, end_floor=25, units_per_floor=20, roof_floor=True)

    assert "Tek seferde en fazla 500 ünite üretilebilir" in str(exc.value)


def test_sequential_numbering_respects_start_number():
    """Blok yarim doldurulmussa uretim kaldigi yerden devam edebilmeli."""
    numbers = generate_unit_numbers(
        _bulk(start_floor=1, end_floor=1, units_per_floor=3, start_number=101)
    )

    assert numbers == ["101", "102", "103"]


def test_floor_sequence_numbering():
    """P3.1 karar 1 (spec §5.2, §11.5): BASA SIFIR YOK.

    P3'te bu test `101,102,201,202` bekliyordu (`_FLOOR_SEQUENCE_WIDTH = 2`
    sabiti). Mockup TU 79 tek hane gosteriyor (`11, 12, 13, 21`) ve mockup
    kazanir (`GOREV-SIRASI.md` §3) — beklenti BILEREK degistirildi, regresyon
    DEGILDIR. Dolgu artik `W = len(str(units_per_floor))`: 2 daire → tek hane.
    """
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=2,
            numbering=UnitNumberingPattern.floor_sequence,
        )
    )

    assert numbers == ["11", "12", "21", "22"]


def test_floor_sequence_numbering_negative_floors():
    """Bodrum katlar (`ge=-5`). Formul HARFI HARFINE uygulanir: kat -1 → "-11".

    P3'te `-101`/`-102` bekleniyordu; karar 1 basa sifiri kaldirdigi icin
    beklenti BILEREK `-11`/`-12` oldu. Alternatif bir bodrum gosterimi
    ("B11") spec'te YOKTUR ve icat EDILMEZ; `prefix` alani bunun icin vardir.
    """
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=-1,
            end_floor=-1,
            units_per_floor=2,
            numbering=UnitNumberingPattern.floor_sequence,
        )
    )

    assert numbers == ["-11", "-12"]


def test_floor_sequence_width_follows_units_per_floor():
    """Spec §12.1/5: dolgu SABIT DEGIL, slot sayisi kadardir.

    P3'te bu test `test_floor_based_numbering_pads_to_two_digits` adiyla
    "sifir dolgusu HER ZAMAN iki hane" diyordu; adi artik kararin TERSINI ima
    ettigi icin yeniden adlandirildi. Ciktisi (`101…112`) ayni kaldi ama
    gerekcesi degisti: iki hane `units_per_floor=12` OLDUGU ICIN cikiyor,
    sabit oldugu icin degil. Tek hane olsaydi kat 1 slot 11 ile kat 11 slot 1
    ayni numarayi alirdi.
    """
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=12,
            numbering=UnitNumberingPattern.floor_sequence,
        )
    )

    assert numbers[:3] == ["101", "102", "103"]
    assert numbers[11:13] == ["112", "201"]


def test_block_sequence_c1_c24():
    """TU 79/159-166: `{Blok}-{Sira}` → C-1 … C-24. BASA SIFIR YOK (karar 1)."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=8,
            units_per_floor=3,
            numbering=UnitNumberingPattern.block_sequence,
        ),
        block_code="C",
    )

    assert numbers == [f"C-{n}" for n in range(1, 25)]


def test_floor_sequence_tek_hane():
    """TU 79: `{Kat}{Sira}` → 11, 12, 13, 21, 22, 23 (3 daire → tek hane)."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=3,
            numbering=UnitNumberingPattern.floor_sequence,
        )
    )

    assert numbers == ["11", "12", "13", "21", "22", "23"]


def test_label_sequence_daire_n():
    """TU 79: `Daire {Sira}` → Daire 1, Daire 2, … Sira GLOBALDIR (kat kat artar)."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=2,
            numbering=UnitNumberingPattern.label_sequence,
        )
    )

    assert numbers == ["Daire 1", "Daire 2", "Daire 3", "Daire 4"]


def test_block_floor_sequence():
    """TU 79: `{Blok}{Kat}{Sira}` → C11, C12, C13. `{Sira}` KAT ICI slottur."""
    numbers = generate_unit_numbers(
        _bulk(
            start_floor=1,
            end_floor=1,
            units_per_floor=3,
            numbering=UnitNumberingPattern.block_floor_sequence,
        ),
        block_code="C",
    )

    assert numbers == ["C11", "C12", "C13"]


def test_kat_etiketi_uretici():
    """Karar 4 (spec §5.3): kat ETIKETI mockup'in kendi sozlugudur."""
    assert floor_label(0) == "Zemin"
    assert floor_label(3) == "3. Kat"
    assert floor_label(-2) == "2. Bodrum"
    assert ROOF_FLOOR_LABEL == "Çatı Katı"


def test_roof_floor_bir_tur_daha_uretir_etiket_cati_kati():
    """TU 71: "Cati Kati" bitis kati SECENEGIDIR → `start..end` turlarindan
    SONRA bir tur daha uretilir ve o turun etiketi "Çatı Katı"dir.

    Numaralandirmadaki `{Kat}` jetonu `end_floor + 1`'dir (spec §5.2) — bu sayi
    YALNIZ uretim icinde yasar, hicbir sutuna yazilmaz.
    """
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=2,
            roof_floor=True,
            numbering=UnitNumberingPattern.floor_sequence,
        )
    )

    assert [u.unit_no for u in units] == ["11", "12", "21", "22", "31", "32"]
    assert [u.floor_label for u in units[-2:]] == [ROOF_FLOOR_LABEL, ROOF_FLOOR_LABEL]
    assert [u.floor for u in units[-2:]] == [3, 3]


def test_fiyat_artisi_TU_bes_satiri_birebir():
    """Spec §5.5 tablosunun BES SATIRI DA — mockup TU 159-165 ile birebir.

    Formul BILESIKTIR: `slot.list_price × (1 + pct/100) ^ (kat - baslangic)`.
    Dogrusal olsaydi C-7 1.318.400 cikardi; mockup 1.318.700 diyor.
    """
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=8,
            units_per_floor=3,
            numbering=UnitNumberingPattern.block_sequence,
            slots=list(_TU_SLOTS),
            floor_price_increase_pct=Decimal("1.5"),
        ),
        block_code="C",
    )
    by_no = {u.unit_no: u for u in units}

    assert by_no["C-1"].list_price == Decimal("1280000.00")
    assert by_no["C-4"].list_price == Decimal("1299200.00")
    assert by_no["C-5"].list_price == Decimal("954100.00")
    assert by_no["C-6"].list_price == Decimal("1258600.00")
    # KARAR 6: 1.318.688 → EN YAKIN 100 ₺ → 1.318.700.
    assert by_no["C-7"].list_price == Decimal("1318700.00")


def test_TU_onizleme_satirlari_slot_alanlarini_tasir():
    """TU 159-165'in fiyat DISI sutunlari: kat, tip, brut/net m², cephe."""
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=8,
            units_per_floor=3,
            numbering=UnitNumberingPattern.block_sequence,
            slots=list(_TU_SLOTS),
            floor_price_increase_pct=Decimal("1.5"),
        ),
        block_code="C",
    )

    assert len(units) == 24
    assert [(u.unit_no, u.floor, u.layout) for u in units[:4]] == [
        ("C-1", 1, "3+1"),
        ("C-2", 1, "2+1"),
        ("C-3", 1, "3+1"),
        ("C-4", 2, "3+1"),
    ]
    assert units[0].floor_label == "1. Kat"
    assert units[1].gross_area_m2 == Decimal("112")
    assert units[1].net_area_m2 == Decimal("96")
    assert [u.facing for u in units[:3]] == [UnitFacing.south, UnitFacing.east, UnitFacing.west]


def test_yuvarlama_en_yakin_100_TL():
    """KARAR 6: `(raw / 100).quantize(0, ROUND_HALF_UP) * 100`, `Decimal` uzerinde.

    Para hesabinda `float` YASAKTIR (P7 K5): 0.1 + 0.2 sinifi bir hata tek bir
    unitede kurusluk degil, 500 unitede birikimli sapma uretir.
    """

    def _rounded(base: str) -> Decimal:
        units = generate_units(
            _bulk(
                units_per_floor=1,
                slots=[UnitBulkSlot(sequence=1, list_price=Decimal(base))],
                floor_price_increase_pct=Decimal("0"),
            )
        )
        return units[0].list_price  # type: ignore[return-value]

    assert _rounded("1000049") == Decimal("1000000.00")  # asagi
    assert _rounded("1000050") == Decimal("1000100.00")  # YARIM → YUKARI (HALF_UP)
    assert _rounded("1000051") == Decimal("1000100.00")  # yukari


def test_artis_yokken_slot_tabani_yuvarlanmaz():
    """KARAR 6'nin SINIRI: artis YOKKEN taban AYNEN yazilir.

    Yuvarlansaydi kullanicinin girdigi 1.234.567 ₺ sessizce 1.234.600 olurdu.
    """
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=2,
            units_per_floor=1,
            slots=[UnitBulkSlot(sequence=1, list_price=Decimal("1234567"))],
        )
    )

    assert [u.list_price for u in units] == [Decimal("1234567.00"), Decimal("1234567.00")]


def test_total_list_value_satirlardan_toplanir():
    """KARAR 5 / onayli sapma §11.6: mockup'in ₺27.264.000 sayisi TESTE KONMAZ.

    TU 146/172'deki toplam mockup'in KENDI verisiyle uzlasmiyor (artissiz
    toplam 27.680.000, %1,5 bilesik ile ~29.177.000 — mockup ikisinin de
    altinda). Kanon: toplam SATIRLARDAN toplanir.
    """
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=8,
            units_per_floor=3,
            numbering=UnitNumberingPattern.block_sequence,
            slots=list(_TU_SLOTS),
            floor_price_increase_pct=Decimal("1.5"),
        ),
        block_code="C",
    )

    assert total_list_value(units) == sum(
        (u.list_price for u in units if u.list_price is not None), Decimal("0")
    )
    assert total_list_value([]) == Decimal("0.00")


def test_slots_bos_birakilirsa_ortak_varsayilanlar_uygulanir():
    """Spec §5.3: `slots` bos birakilabilir → P3'un eski davranisi KORUNUR.

    Mevcut cagiranlar (ve `test_bulk_applies_common_defaults`) kirilmaz.
    """
    units = generate_units(
        _bulk(
            start_floor=1,
            end_floor=1,
            units_per_floor=2,
            layout="3+1",
            gross_area_m2=Decimal("142"),
            list_price=Decimal("1150000"),
        )
    )

    assert [u.layout for u in units] == ["3+1", "3+1"]
    assert [u.gross_area_m2 for u in units] == [Decimal("142"), Decimal("142")]
    assert [u.list_price for u in units] == [Decimal("1150000.00"), Decimal("1150000.00")]
    assert [u.facing for u in units] == [None, None]


def test_slot_count_mismatch():
    """Spec §12.4/37: `len(slots) != units_per_floor` → sema hatasi (422)."""
    with pytest.raises(ValidationError) as exc:
        _bulk(units_per_floor=3, slots=[UnitBulkSlot(sequence=1)])

    assert "Kat şablonu satır sayısı kat başına daire sayısıyla eşleşmiyor" in str(exc.value)


def test_slot_sequence_tekrarli_gecersiz():
    """Spec §12.4/38: `sequence` tekrarli → sema hatasi (422).

    Tekrarli slot sessiz bir numara hatasi uretirdi: `{Sira}` jetonu kat ici
    slot sirasidir ve ayni sira iki kez gelirse ayni numara iki kez dogar.
    """
    with pytest.raises(ValidationError) as exc:
        _bulk(
            units_per_floor=2,
            slots=[UnitBulkSlot(sequence=1), UnitBulkSlot(sequence=1)],
        )

    assert "Kat şablonunda sıra numaraları geçersiz veya tekrarlı" in str(exc.value)


def test_slot_sequence_araligin_disinda_gecersiz():
    """`sequence` 1..units_per_floor araliginda OLMALIDIR — 3 daire icin 5 yok."""
    with pytest.raises(ValidationError) as exc:
        _bulk(
            units_per_floor=2,
            slots=[UnitBulkSlot(sequence=1), UnitBulkSlot(sequence=5)],
        )

    assert "Kat şablonunda sıra numaraları geçersiz veya tekrarlı" in str(exc.value)


def test_slot_net_gt_gross_gecersiz():
    """Spec §5.3: slot alanlari da tekil POST ile AYNI kurala tabidir ve kural
    `guards.ensure_net_le_gross`'tan CAGRILIR, kopyalanmaz."""
    with pytest.raises(Exception) as exc:
        _bulk(
            units_per_floor=1,
            slots=[
                UnitBulkSlot(sequence=1, gross_area_m2=Decimal("100"), net_area_m2=Decimal("120"))
            ],
        )

    assert "Net alan brüt alandan büyük olamaz" in str(exc.value)


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
