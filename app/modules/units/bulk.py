"""Toplu unite uretiminin SAF cekirdegi (spec §5.2, §5.3, §5.5).

Servisten AYRI tutulur ki numaralandirma ve fiyat uretimi DB'siz, HTTP'siz test
edilebilsin: "24 daire hangi numaralari ve hangi fiyatlari alir" sorusu bir
veritabanina ihtiyac duymaz ve oraya karisirsa yalnizca entegrasyon testiyle
dogrulanabilir hâle gelir.

Burada DOGRULAMA YOKTUR: kat araligi, uretim siniri (`_MAX_BULK_UNITS`) ve kat
sablonu kurallari `UnitBulkCreate`'in `model_validator`'undadir (spec §5.3) —
ayni kurali iki yerde tutmak zamanla ayrisir.

PARA HESABINDA KAYAN NOKTA YASAKTIR (P7 K5 dersi): tum carpim ve yuvarlama
`Decimal` uzerindedir. Tek bir kayan nokta donusumu 500 unitede birikimli sapma
uretir.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.units.models import UnitFacing
from app.modules.units.schemas import UnitBulkCreate, UnitBulkSlot, UnitNumberingPattern

__all__ = [
    "ROOF_FLOOR_LABEL",
    "GeneratedUnit",
    "floor_label",
    "generate_unit_numbers",
    "generate_units",
    "total_list_value",
]

# Kat etiketi sozlugu — mockup'in KENDI sozlugudur (TU 70/71, UE 66, BE 78).
_GROUND_FLOOR_LABEL = "Zemin"
ROOF_FLOOR_LABEL = "Çatı Katı"
_UPPER_FLOOR_SUFFIX = ". Kat"
_BASEMENT_SUFFIX = ". Bodrum"

# TU 79 `Daire {Sira}` deseninin sabit on eki.
_UNIT_LABEL_PREFIX = "Daire "
_BLOCK_SEPARATOR = "-"

_MONEY = Decimal("0.01")
_HUNDRED = Decimal("100")
# KARAR 6 (spec §5.5): kat artisi uygulanan fiyat EN YAKIN 100 ₺'ye yuvarlanir.
# Mockup'in tek veri noktasi (C-7: 1.318.688 → 1.318.700) bununla uyumludur.
_PRICE_ROUNDING_STEP = Decimal("100")


@dataclass(frozen=True)
class GeneratedUnit:
    """Uretilecek TEK unite — henuz hicbir yere yazilmamis hâli.

    Onizleme ucu (spec §5.4) ve gercek uretim AYNI listeyi kullanir: onizleme
    otoriter degil, TEKRARLANABILIR bir hesaptir (TU 182 "Onizlemeyi Yenile").
    """

    unit_no: str
    floor: int  # uretim turunun SAYISI — TU 152 bunu basar, sutuna YAZILMAZ
    floor_label: str  # uniteye YAZILACAK metin: "1. Kat" / "Zemin" / "Çatı Katı"
    layout: str | None
    gross_area_m2: Decimal | None
    net_area_m2: Decimal | None
    facing: UnitFacing | None
    list_price: Decimal | None


def floor_label(floor: int) -> str:
    """Kat SAYISINI mockup'in kat ETIKETINE cevirir (karar 4, spec §5.3).

    Cati turunun etiketi bu fonksiyondan gelmez (`ROOF_FLOOR_LABEL`): cati bir
    sayi degil, TU 71'de "Bitis Kati" seceneklerinden biridir.
    """
    if floor == 0:
        return _GROUND_FLOOR_LABEL
    if floor > 0:
        return f"{floor}{_UPPER_FLOOR_SUFFIX}"
    return f"{-floor}{_BASEMENT_SUFFIX}"


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _slot_width(units_per_floor: int) -> int:
    """KARAR 1 (spec §5.2, §11.5): dolgu SABIT DEGIL, slot sayisi kadardir.

    P3'te dolgu SABIT iki haneydi ve modul basindaki yorum "1. kat 1. daire
    101'dir, 11 degil" diyordu. Mockup TU 79 tek hane gosteriyor (`11, 12, 13, 21`) ve
    TU 159-165 `C-1 … C-7` (`C-01` degil) — mockup kazanir. Sabit ve onu
    aciklayan yorum KALDIRILDI; birakilsaydi bir sonraki okuyan kodu
    "regresyon" sanip geri alirdi.

    Cakisma yine de korunur: 10-20 daire icin W=2 doner, aksi hâlde kat 1 slot
    11 ile kat 11 slot 1 ayni numarayi alirdi.
    """
    return len(str(units_per_floor))


def _unit_no(
    data: UnitBulkCreate,
    block_code: str,
    *,
    floor: int,
    slot: int,
    index: int,
    width: int,
) -> str:
    """TU 79'un dort deseni + korunan `sequential` (spec §5.2, plan §0.C).

    `{Sira}` jetonu IKI FARKLI ANLAM tasir ve karistirilmasi sessiz numara
    hatasi uretir:
      * `sequential` / `block_sequence` / `label_sequence` → uretim boyunca
        artan GLOBAL sira (`index`; TU 159-165: C-1…C-7 kat degisse de artiyor)
      * `floor_sequence` / `block_floor_sequence` → KAT ICI slot sirasi
        (`slot`; 11, 12, 13 → sonra 21)
    """
    number = data.start_number + index
    if data.numbering is UnitNumberingPattern.block_sequence:
        body = f"{block_code}{_BLOCK_SEPARATOR}{number}"
    elif data.numbering is UnitNumberingPattern.label_sequence:
        body = f"{_UNIT_LABEL_PREFIX}{number}"
    elif data.numbering is UnitNumberingPattern.floor_sequence:
        body = f"{floor}{slot:0{width}d}"
    elif data.numbering is UnitNumberingPattern.block_floor_sequence:
        body = f"{block_code}{floor}{slot:0{width}d}"
    else:
        body = str(number)
    return f"{data.prefix}{body}"


def _price(base: Decimal | None, pct: Decimal | None, exponent: int) -> Decimal | None:
    """`base × (1 + pct/100) ^ exponent`, EN YAKIN 100 ₺ (karar 6, spec §5.5).

    Artis BILESIKTIR, dogrusal degil — mockup C-7 bunu kanitliyor (dogrusal
    olsaydi 1.318.400 cikardi, mockup 1.318.700 diyor).

    Yuvarlama YALNIZ artis hesabina girer: `pct is None` iken slot tabani AYNEN
    yazilir, aksi hâlde kullanicinin girdigi 1.234.567 ₺ sessizce 1.234.600
    olurdu (karar 6'nin sinirI).
    """
    if base is None:
        return None
    if pct is None:
        return _quantize_money(base)
    raw = base * (Decimal(1) + pct / _HUNDRED) ** exponent
    stepped = (raw / _PRICE_ROUNDING_STEP).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return _quantize_money(stepped * _PRICE_ROUNDING_STEP)


def _slots(data: UnitBulkCreate) -> list[UnitBulkSlot]:
    """Kat sablonu; BOS birakilmissa ortak varsayilanlardan TEK slot kumesi kurar.

    Boylece P3'un davranisi (tum unitelere ayni varsayilanlar) tek kod yolundan
    korunur — geriye donuk uyum icin ikinci bir uretim dali acilmaz (spec §5.3).
    `facing` ortak varsayilanlarda YOKTUR: TU cepheyi yalniz slot satirinda
    veriyor ve mockup'ta olmayan bir alan icat edilmez.
    """
    if data.slots:
        return sorted(data.slots, key=lambda slot: slot.sequence)
    return [
        UnitBulkSlot(
            sequence=sequence,
            layout=data.layout,
            gross_area_m2=data.gross_area_m2,
            net_area_m2=data.net_area_m2,
            list_price=data.list_price,
        )
        for sequence in range(1, data.units_per_floor + 1)
    ]


def generate_units(data: UnitBulkCreate, block_code: str = "") -> list[GeneratedUnit]:
    """Uretilecek uniteleri SIRAYLA dondurur (spec §5.2, §5.3, §5.5).

    `block_code` `{Blok}` jetonunun karsiligidir; kodu **NULL** olan blokta
    cagiran `codes.effective_block_code` ile ANLIK turetir ve SAKLAMAZ (karar 8).

    Cati turu (`roof_floor`) `start_floor…end_floor` turlarindan SONRA bir tur
    daha uretir. O turda iki farkli sayi is basindadir ve karistirilmamalidir:
    numaralandirmadaki `{Kat}` jetonu `end_floor + 1`, fiyat artisi ussu ise
    `end_floor − start_floor + 1`'dir. Ikisi de yalniz uretim icinde yasar.
    """
    slots = _slots(data)
    width = _slot_width(data.units_per_floor)
    rounds: list[tuple[int, str, int]] = [
        (floor, floor_label(floor), floor - data.start_floor)
        for floor in range(data.start_floor, data.end_floor + 1)
    ]
    if data.roof_floor:
        rounds.append((data.end_floor + 1, ROOF_FLOOR_LABEL, data.end_floor - data.start_floor + 1))

    units: list[GeneratedUnit] = []
    for floor, label, exponent in rounds:
        for slot in slots:
            units.append(
                GeneratedUnit(
                    unit_no=_unit_no(
                        data,
                        block_code,
                        floor=floor,
                        slot=slot.sequence,
                        index=len(units),
                        width=width,
                    ),
                    floor=floor,
                    floor_label=label,
                    layout=slot.layout,
                    gross_area_m2=slot.gross_area_m2,
                    net_area_m2=slot.net_area_m2,
                    facing=slot.facing,
                    list_price=_price(slot.list_price, data.floor_price_increase_pct, exponent),
                )
            )
    return units


def generate_unit_numbers(data: UnitBulkCreate, block_code: str = "") -> list[str]:
    """`generate_units`'in yalniz numaralarini isteyen cagiranlar icin.

    AYRI bir uretim yolu DEGILDIR — ayni saf fonksiyondan turer, boylece
    numaralar iki yerde ayrisamaz.
    """
    return [unit.unit_no for unit in generate_units(data, block_code)]


def total_list_value(units: list[GeneratedUnit]) -> Decimal:
    """TU 146/172 "Toplam Liste Degeri" — SATIRLARDAN toplanir (karar 5).

    Mockup'in `₺27.264.000` sayisi KANON DEGILDIR ve hedeflenmez: kendi
    verisiyle uzlasmiyor (artissiz toplam 27.680.000, %1,5 bilesik artisla
    ~29.177.000 — mockup ikisinin de altinda). Onayli sapma §11.6.
    """
    return _quantize_money(
        sum((unit.list_price for unit in units if unit.list_price is not None), Decimal("0"))
    )
