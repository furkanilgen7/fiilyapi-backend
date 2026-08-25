"""B8 — toplu ünite üretiminin SAF FONKSİYONLARI (spec §6.3): numaralandırma,
kat etiketi, slot/fiyat artışı ve toplam liste değeri.

Numaralandırma saf fonksiyonları (`app/modules/units/bulk.py`) DB'siz test edilir:
sıra/ön ek/kat mantığı bir HTTP isteğine ihtiyaç duymaz.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali): HTTP ucunun
iddiaları `test_units_bulk_api.py`ye taşındı, paylaşılan yardımcılar
`_units_bulk.py`dedir. Hiçbir testin iddiası değişmedi.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.units.bulk import (
    ROOF_FLOOR_LABEL,
    floor_label,
    generate_unit_numbers,
    generate_units,
    total_list_value,
)
from app.modules.units.models import UnitFacing
from app.modules.units.schemas import (
    UnitBulkSlot,
    UnitNumberingPattern,
)

# TU govdesi TEK yerde durur (`test_units_bulk_preview.py`): T10'un asil iddiasi
# "onizleme ile uretim AYNI govdeden AYNI sonucu verir"dir ve govde kopyalanirsa
# biri degistiginde digeri sessizce bayatlar — iddia da bosa duser.
from ._units_bulk import (
    _TU_SLOTS,
    _bulk,
)


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
