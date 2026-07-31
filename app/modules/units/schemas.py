import enum
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, computed_field, model_validator

# Yer tutucu sozlesmesi TEK yerde tanimlidir (B6/P1, spec §6): kopyalanmaz,
# projects modulunden import edilir (BOQ `schemas.py:8` deseninin aynisi).
from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder
from app.modules.units.guards import (
    INVALID_VAT_RATE,
    SLOT_COUNT_MISMATCH,
    SLOT_SEQUENCE_INVALID,
    ensure_net_le_gross,
)
from app.modules.units.models import (
    BlockGroundUsage,
    BlockParkingType,
    BlockRoofType,
    BlockStatus,
    UnitFacing,
    UnitKind,
    UnitOwnerSide,
    UnitParkingRight,
    UnitSalesStatus,
)

__all__ = [
    "BlockCreate",
    "BlockGroundUsage",
    "BlockParkingType",
    "BlockRoofType",
    "BlockStatus",
    "BlockListResponse",
    "BlockResponse",
    "BlockUpdate",
    "CountPlaceholder",
    "MetricPlaceholder",
    "UnitAllocationItem",
    "UnitAllocationRequest",
    "UnitBlockGroup",
    "UnitBulkCreate",
    "UnitBulkPreview",
    "UnitBulkPreviewRow",
    "UnitBulkSlot",
    "UnitCreate",
    "UnitFacing",
    "UnitImportResult",
    "UnitImportRowError",
    "UnitKind",
    "UnitKindBreakdown",
    "UnitListResponse",
    "UnitNumberingPattern",
    "UnitOwnerSide",
    "UnitOwnerSideFilter",
    "UnitParkingRight",
    "UnitResponse",
    "UnitSalesStatus",
    "UnitSideSummary",
    "UnitTotals",
    "UnitUpdate",
    "UnitValueBasis",
]

# Modul duzeyi sabitler — sihirli sayi birakilmaz (spec §6.2, §7.8).
# KKP'de 42 unite var; 500 makul ust sinirdir ve tek istekte sinirsiz satir
# yazilmasini engeller.
_MAX_ALLOCATION_ITEMS = 500
_MAX_BULK_UNITS = 500
_MAX_IMPORT_BYTES = 2 * 1024 * 1024
_MAX_IMPORT_ROWS = 1000

_LABEL_SEPARATOR = " · "

# KARAR 9: KDV listesi (%1 / %10 / %20) KODDA SABITTIR (UE 93). Sutun
# `Numeric(5,2)` serbest kalir ve DB CHECK yalniz `0..100` der — kumeyi burasi
# zorlar. Gerekce: KDV yasayla degisen bir listedir; gun gelip %8 eklenirse
# migration degil, BU SATIR degisir (spec §4.2).
_ALLOWED_VAT_RATES = (Decimal("1"), Decimal("10"), Decimal("20"))
_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _check_vat_rate(value: Decimal | None) -> Decimal | None:
    if value is not None and value not in _ALLOWED_VAT_RATES:
        raise ValueError(INVALID_VAT_RATE)
    return value


# `Create` ve `Update` AYNI kurala tabidir; iki ayri validator zamanla ayrisir.
VatRate = Annotated[
    Decimal | None,
    Field(default=None, ge=0, max_digits=5, decimal_places=2),
    AfterValidator(_check_vat_rate),
]


class UnitValueBasis(str, enum.Enum):
    """Toplamlarin hangi sutundan hesaplandigi (spec §4.4).

    `kat_karsiligi` → `appraisal_value`, digerleri → `list_price`. Yanitta ACIKCA
    bildirilir ki ekran hangi sutunu gosterdigini tahmin etmek zorunda kalmasin.
    """

    list_price = "list_price"
    appraisal_value = "appraisal_value"


class UnitOwnerSideFilter(str, enum.Enum):
    """`GET .../units` sorgu suzgeci (spec §7.4).

    `UnitOwnerSide`'in kendisi KULLANILAMAZ: atanmamis uniteleri (NULL) secmek
    icin ucuncu bir deger gerekir ve bu deger sutunda saklanan bir durum degil,
    yalnizca sorgu dilidir — modele sizmasi yanlis olurdu.
    """

    contractor = "contractor"
    landowner = "landowner"
    unassigned = "unassigned"


# --- Okuma semalari ---


class UnitKindBreakdown(BaseModel):
    """KY 71 "48 Daire + 4 Dukkan", KK 121, SY 104. `total` turevdir: iki sayacin
    toplami saklanmaz, yoksa zamanla kayabilir."""

    apartment: int = 0  # KY 71 "48 Daire"
    shop: int = 0  # KY 71 "4 Dukkan"
    # UE 74 (spec §4.3). KARAR 13: ekran ETIKETLERI DEGISMEZ — KY 71 / KK 72 /
    # SY 74 hâlâ "Daire + Dukkan" der; uc yeni sayac sifirsa ekranda GORUNMEZ.
    office: int = 0
    warehouse: int = 0
    parking: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return self.apartment + self.shop + self.office + self.warehouse + self.parking


class BlockResponse(BaseModel):
    id: uuid.UUID
    name: str  # KY 281 "A Blok"
    site_id: uuid.UUID
    site_name: str  # blok basliginda santiye gosterilebilsin diye (join)
    sort_order: int
    counts: UnitKindBreakdown  # SY 74 "A Blok — 24 Daire"
    # --- Blok formu (BE), spec §3.1 ---
    code: str | None  # BE 71
    basement_floor_count: int | None  # BE 78
    floor_count: int | None  # BE 79
    roof_type: BlockRoofType | None  # BE 80
    units_per_floor: int | None  # BE 81
    ground_floor_usage: BlockGroundUsage | None  # BE 82
    shop_count: int | None  # BE 83
    construction_area_m2: Decimal | None  # BE 84
    elevator_count: int | None  # BE 85
    parking_type: BlockParkingType | None  # BE 86
    estimated_delivery_date: date | None  # BE 100
    status: BlockStatus | None  # BE 101
    notes: str | None  # BE 102

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_unit_count(self) -> int | None:
        """BE 90-93: "8 kat × 3 daire + 2 dükkan" = 26 (spec §3.3).

        SAKLANMAZ: saklansaydi uc girdiden biri degistiginde sessizce bayatlardi.
        Uc girdi de bossa **None** doner — 0 "hesaplandi ve sifir" der ve bu
        yanlis bilgidir. `counts` (GERCEK unite adedi) ile karistirilmamalidir:
        biri plan, digeri gercektir ve ikisi bilerek ayri alanlardir.
        """
        if self.floor_count is None and self.units_per_floor is None and self.shop_count is None:
            return None
        return (self.floor_count or 0) * (self.units_per_floor or 0) + (self.shop_count or 0)


class UnitResponse(BaseModel):
    """KY 271-274 ve KKP 86-90 sutunlari. Satis alanlari (KY 275-277, KKP 91-92)
    P8'in isidir ve yer tutucu doner — `units`'te saklanmaz (spec §4.6)."""

    id: uuid.UUID
    block_id: uuid.UUID
    block_name: str
    unit_no: str
    unit_kind: UnitKind
    layout: str | None  # KY 272 "Tip"
    gross_area_m2: Decimal | None
    net_area_m2: Decimal | None
    list_price: Decimal | None  # KY 274 "Liste Fiyati"
    appraisal_value: Decimal | None  # KKP 89 "Rayic Deger"
    owner_side: UnitOwnerSide | None  # KKP 90 "Sahip"
    sort_order: int
    # --- Unite formu (UE), spec §4.1 ---
    floor: str | None  # UE 66 — METIN (karar 4)
    facing: UnitFacing | None  # UE 78
    balcony_area_m2: Decimal | None  # UE 79
    bathroom_count: int | None  # UE 80
    parking_right: UnitParkingRight | None  # UE 81
    min_sale_price: Decimal | None  # UE 92
    vat_rate: Decimal | None  # UE 93
    # UE 94 — ARTIK YER TUTUCU DEGIL (kullanici karari 2, spec §4.4). P8
    # geldiginde OTOMATIKLESECEK ve elle giris kilitlenecektir.
    sales_status: UnitSalesStatus | None
    # --- ileri dilim yer tutuculari ---
    sale_price: MetricPlaceholder  # P8 (KY 275)
    buyer_name: MetricPlaceholder  # P8 (KY 277)
    shareholder: MetricPlaceholder  # P9 (KKP 91)
    # KARAR 3: maliyet ELLE GIRILMEZ, kolon ACILMAZ (spec §4.5) — ileride Is
    # Kalemleri/satinalmadan hesaplanacak. Maliyet yoksa kâr da yoktur.
    unit_cost: MetricPlaceholder  # UE 91 / FDS 62
    expected_profit: MetricPlaceholder  # UE 97-99

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        return f"{self.block_name}{_LABEL_SEPARATOR}{self.unit_no}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unit_price_per_m2(self) -> Decimal | None:
        """FDS 61. Tabani HER ZAMAN `list_price`'tir: FDS 60-61 ikisini ayni
        formda yan yana gosterir; `appraisal_value` birim fiyati mockup'ta yok."""
        if self.list_price is None or not self.gross_area_m2:
            return None
        return _quantize_money(self.list_price / self.gross_area_m2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_landowner_share(self) -> bool:
        return self.owner_side is UnitOwnerSide.landowner


class UnitSideSummary(BaseModel):
    """KK 116-122 / 150-156, KKP 161-168 tfoot toplamlari."""

    side: UnitOwnerSide | None  # None = henuz atanmamis (spec §5.3)
    counts: UnitKindBreakdown
    total_value: Decimal  # value_basis sutununun toplami (NULL'lar 0 sayilir)
    average_value: Decimal | None  # KK 121 "Ortalama ₺1,32M"
    share_pct: Decimal | None  # turev adet orani (spec §5.2)
    # P3'te yer tutucuydular; `totals`'taki sayaclarla AYNI veriden (`sales_status`
    # sutunu) beslendikleri icin onlarla birlikte GERCEK sayaca dondular (spec
    # §8.2). Ayri kalsalardi ekran proje toplaminda "34 satildi" gorup taraf
    # tablosunda "veri yok" basardi. GERCEKLESEN satis TUTARI hâlâ P8'indir ve
    # `UnitTotals.sales_revenue` yer tutucu KALIR — durum sutunu acildi diye
    # ciro uydurulmaz.
    sold: int  # KKP 163
    reserved: int
    listed: int  # `closed` (Satisa Kapali) SAYILMAZ: bos olsa bile satista degil


class UnitTotals(BaseModel):
    counts: UnitKindBreakdown  # KKP 67, KY 71/88
    value_basis: UnitValueBasis  # spec §4.4
    total_value: Decimal  # KKP 69 "Toplam Deger"
    average_value: Decimal | None  # KY 168 "Ort. ₺927K"
    # Iki sutun da AYRICA doner ki ekran ihtiyaci olani sorgusuz alabilsin.
    total_list_price: Decimal
    total_appraisal_value: Decimal
    total_gross_area_m2: Decimal  # KKP 68'in (insaat alani) YERINE GECMEZ
    sides: list[UnitSideSummary]  # contractor / landowner / atanmamis
    # KY 258-259 "34 satildi · 5 rezerve · 13 bos", KKP 161-163 tfoot kirilimi.
    # DORT deger de her zaman doner (sifir olsa bile): eksik anahtar, ekranda
    # "veri yok" ile "sifir" ayrimini kaybettirirdi (spec §8.2).
    by_sales_status: dict[UnitSalesStatus, int]
    # P3'te yer tutucuydular; `sales_status` sutunu acildigi icin GERCEK sayaca
    # dondular (spec §8.2). `available` = `listed` — `closed` (Satisa Kapali)
    # bos olsa bile SATISTA DEGILDIR.
    sold_units: int  # KY 88, 264
    reserved_units: int  # KY 265
    available_units: int  # KY 266
    # YER TUTUCU KALIR: GERCEKLESEN satis tutari hâlâ P8'in verisidir — durum
    # sutunu acildi diye ciro uydurulmaz.
    sales_revenue: MetricPlaceholder  # P8 (KY 93)
    average_sale_price: MetricPlaceholder  # P8 (KY 267)


class UnitBlockGroup(BaseModel):
    """SY 74 / 104 blok basliklari. Unitesi olmayan blok da doner (bos `units`
    ile): yeni acilan blok ekranda gorunmezse kullanici kaydettigini goremez."""

    block: BlockResponse
    units: list[UnitResponse]


class UnitListResponse(BaseModel):
    totals: UnitTotals
    blocks: list[UnitBlockGroup]


class BlockListResponse(BaseModel):
    blocks: list[BlockResponse]


# --- Yazma semalari ---


class _BlockFormFields(BaseModel):
    """BE formunun 13 alani — `Create` ve `Update` icin TEK kopya (spec §3.1).

    KARAR 11: **HICBIRI ZORUNLU DEGILDIR.** Mockup'taki kirmizi `*` (BE 79
    `floor_count`) yalniz UI ipucudur; ne DB'de `NOT NULL`, ne burada
    zorunluluk dogurur — taslak destegi (Kalici Karar 4) bunu gerektirir.

    `code` bos birakilirsa serviste URETILIR (BE 71 ipucu, spec §3.2).
    """

    code: str | None = Field(default=None, max_length=20)
    basement_floor_count: int | None = Field(default=None, ge=0)
    floor_count: int | None = Field(default=None, ge=0)
    roof_type: BlockRoofType | None = None
    units_per_floor: int | None = Field(default=None, ge=0)
    ground_floor_usage: BlockGroundUsage | None = None
    shop_count: int | None = Field(default=None, ge=0)
    construction_area_m2: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    elevator_count: int | None = Field(default=None, ge=0)
    parking_type: BlockParkingType | None = None
    estimated_delivery_date: date | None = None
    status: BlockStatus | None = None
    # `Text` degil: sinirsiz metin frontend'de `maxLength` konamamasina ve
    # sessiz 422 sinifina yol acar (spec §3.1).
    notes: str | None = Field(default=None, max_length=500)


# Servis, 13 alani TEK TEK YAZMAK yerine bu kumeyi kullanir: yeni bir alan
# eklendiginde `Create` ile yazma yolunun ayrisma ihtimali kalmaz.
BLOCK_FORM_FIELDS = frozenset(_BlockFormFields.model_fields)


class BlockCreate(_BlockFormFields):
    name: str = Field(min_length=1, max_length=50)
    # Tek santiyeli projede opsiyoneldir, otomatik atanir (spec §4.5): mockup'ta
    # santiye secici yoktur (KY 38 / KK 39 tekil "📍 Santiye" girdisi).
    site_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0)


class BlockUpdate(_BlockFormFields):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    site_id: uuid.UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class _UnitFormFields(BaseModel):
    """UE formunun 8 yeni alani — `Create` ve `Update` icin TEK kopya (§4.1).

    KARAR 11: **HICBIRI ZORUNLU DEGILDIR.** UE 66 (`floor`) ve UE 94
    (`sales_status`) mockup'ta kirmizi `*` tasir; bu YALNIZ UI ipucudur. Excel
    ice aktarma `Kat` sutununu zorunlu tutmuyor — zorunlu yapilsaydi ice aktarma
    KENDI KENDINI kirardi.

    KARAR 2: `min_sale_price <= list_price` BURADA DA zorlanmaz; ne
    `model_validator`, ne DB CHECK, ne servis (spec §4.1).
    """

    floor: str | None = Field(default=None, max_length=20)  # UE 66 — METIN
    facing: UnitFacing | None = None  # UE 78
    balcony_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    bathroom_count: int | None = Field(default=None, ge=0)  # UE 80
    parking_right: UnitParkingRight | None = None  # UE 81
    min_sale_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    vat_rate: VatRate = None  # UE 93 — kume {1, 10, 20} (karar 9)


# Servis, yeni alanlari TEK TEK YAZMAK yerine bu kumeyi kullanir.
UNIT_FORM_FIELDS = frozenset(_UnitFormFields.model_fields) | {"sales_status"}


class UnitCreate(_UnitFormFields):
    block_id: uuid.UUID
    unit_no: str = Field(min_length=1, max_length=30)
    unit_kind: UnitKind
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    owner_side: UnitOwnerSide | None = None
    sort_order: int = Field(default=0, ge=0)
    # UE 94'te "Satışta (Boş)" `selected` gelir → sunucu VARSAYILANI `listed`.
    # Varsayilan ZORUNLULUK DEGILDIR (karar 11).
    sales_status: UnitSalesStatus | None = UnitSalesStatus.listed


class UnitUpdate(_UnitFormFields):
    """TUM alanlar opsiyoneldir; "gonderilmedi" ile "null yapildi" ayrimi servis
    katmaninda `model_fields_set` ile cozulur (P1/P2/P4 deseni)."""

    block_id: uuid.UUID | None = None
    unit_no: str | None = Field(default=None, min_length=1, max_length=30)
    unit_kind: UnitKind | None = None
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    owner_side: UnitOwnerSide | None = None
    sort_order: int | None = Field(default=None, ge=0)
    # Kullanici karari 2: satis durumu BUGUN elle degistirilebilir (spec §4.4).
    sales_status: UnitSalesStatus | None = None


class UnitAllocationItem(BaseModel):
    """KKP 25 "Paylasimi Kaydet". `owner_side=None` atamayi kaldirir (spec §5.3)."""

    unit_id: uuid.UUID
    owner_side: UnitOwnerSide | None


class UnitAllocationRequest(BaseModel):
    items: list[UnitAllocationItem] = Field(min_length=1, max_length=_MAX_ALLOCATION_ITEMS)


# --- Toplu uretim (kullanici karari, mockup yok — spec §6.3) ---


class UnitNumberingPattern(str, enum.Enum):
    """TU 79'un DORT deseni + korunan `sequential` (plan §0.C, koordinator karari).

    Mockup dort desen listeliyor ama hicbiri CIPLAK SAYI uretmiyor
    (`label_sequence` → "Daire 1"). SY 76-99/132-135 ekrani ciplak sayi ve
    `prefix + sayi` (D1..D4) uretiyor ve bu ekran bugun CALISIYOR — dort desene
    indirgemek onu sessizce kirardi. Bu yuzden enum BES degerlidir.

    `floor_based` → `floor_sequence` olarak yeniden ADLANDIRILDI: davranisi
    karar 1 ile zaten degisti (basa sifir kalkti), eski ad yeni davranisi
    yanlis tarif ediyordu.
    """

    sequential = "sequential"  # 1, 2, 3, ... N          — SY 76-99
    block_sequence = "block_sequence"  # C-1, C-2, C-3   — TU 79 `{Blok}-{Sira}`
    floor_sequence = "floor_sequence"  # 11, 12, 13, 21  — TU 79 `{Kat}{Sira}`
    label_sequence = "label_sequence"  # Daire 1, Daire 2 — TU 79 `Daire {Sira}`
    block_floor_sequence = "block_floor_sequence"  # C11, C12 — TU 79 `{Blok}{Kat}{Sira}`


class UnitBulkSlot(BaseModel):
    """TU 107-133 "Kat Sablonu" tablosunun BIR satiri. Her katta tekrarlanir (TU 94).

    Ortak varsayilanlardan (bir alt siniftaki `layout`/`gross_area_m2`/…) farki:
    ortak varsayilan TUM uretilen uniteye ayni degeri verir, slot ise KAT ICI
    her daireye ayrisik deger verir (TU 96-133 uc farkli oda tipi/m²/cephe/fiyat
    gosteriyor ve mevcut uc bunu HIC karsilayamiyordu, spec §5.1).
    """

    sequence: int = Field(ge=1, le=20)  # TU 98 "Sira"
    layout: str | None = Field(default=None, max_length=20)  # TU 99
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    facing: UnitFacing | None = None  # TU 102
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    # TU 104 "Maliyet" sutunu BILEREK YOKTUR — kullanici karari 3 (spec §4.5):
    # maliyet elle girilmez, kolon acilmaz.


class UnitBulkCreate(BaseModel):
    block_id: uuid.UUID
    unit_kind: UnitKind
    start_floor: int = Field(ge=-5, le=100)  # bodrum katlar icin negatif serbest
    end_floor: int = Field(ge=-5, le=100)
    # TU 71: "Bitis Kati" seceneklerinden biri "Cati Kati"dir. `end_floor` tam
    # sayi oldugu icin bu secenek AYRI bir bayrakla tasinir (karar 4, spec §5.3).
    roof_floor: bool = False
    units_per_floor: int = Field(ge=1, le=20)
    numbering: UnitNumberingPattern = UnitNumberingPattern.sequential
    prefix: str = Field(default="", max_length=10)  # "D" → D1..D4 (SY 132-135)
    start_number: int = Field(default=1, ge=0)  # global sira baslangici (TU 84, SY 76)
    slots: list[UnitBulkSlot] = Field(default_factory=list, max_length=20)  # TU 96-133
    floor_price_increase_pct: Decimal | None = Field(  # TU 138 "Kat basina %1.5"
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    # Uretilen TUM unitelere uygulanacak ortak varsayilanlar. `slots` BOS
    # birakilirsa bunlar uygulanir (P3 davranisi KORUNUR, spec §5.3).
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)

    @model_validator(mode="after")
    def _validate_range(self) -> "UnitBulkCreate":
        """DOGRULAMA TEK YERDEDIR (burada); `bulk.py` saf kalir ve kural
        KOPYALANMAZ — ayni kurali iki yerde tutmak zamanla ayrisir (spec §6.3).
        """
        if self.end_floor < self.start_floor:
            raise ValueError("Bitiş katı başlangıç katından küçük olamaz")
        # Cati turu de sinira DAHILDIR: sayilmasaydi kullanici 500 sinirini
        # fazladan bir kat kadar sessizce asardi.
        rounds = self.end_floor - self.start_floor + 1 + (1 if self.roof_floor else 0)
        if rounds * self.units_per_floor > _MAX_BULK_UNITS:
            raise ValueError(f"Tek seferde en fazla {_MAX_BULK_UNITS} ünite üretilebilir")
        if self.slots:
            if len(self.slots) != self.units_per_floor:
                raise ValueError(SLOT_COUNT_MISMATCH)
            sequences = {slot.sequence for slot in self.slots}
            if len(sequences) != len(self.slots) or max(sequences) > self.units_per_floor:
                raise ValueError(SLOT_SEQUENCE_INVALID)
            for slot in self.slots:
                # Tekil POST ile AYNI kural: `guards`tan CAGRILIR, kopyalanmaz.
                ensure_net_le_gross(slot.gross_area_m2, slot.net_area_m2)
        return self


class UnitBulkPreviewRow(BaseModel):
    """TU 151-156 onizleme tablosunun BIR satiri (spec §5.4).

    `floor` ile `floor_label` AYRI alanlardir ve birlestirilmemelidir (karar 4):
    `floor` uretim turunun SAYISIDIR (TU 152 1/2/3 basiyor, numaralandirmanin
    girdisi), `floor_label` ise uniteye YAZILACAK metindir ("1. Kat", "Zemin",
    "Çatı Katı"). Tek alana indirilseydi ekran ya sayiyi ya etiketi kaybederdi.
    """

    unit_no: str  # TU 151
    floor: int  # TU 152
    floor_label: str  # karar 4 — `units.floor` sutununa yazilacak deger
    layout: str | None  # TU 153 "Tip"
    gross_area_m2: Decimal | None  # TU 154 "Brut/Net m²"
    net_area_m2: Decimal | None
    facing: UnitFacing | None  # TU 155
    list_price: Decimal | None  # TU 156
    conflict: bool  # TU 177 — cakisma UYARIDIR, hata degil (spec §5.6)


class UnitBulkPreview(BaseModel):
    """AYRI UC'un yaniti (spec §5.4) — `UnitListResponse` ile birlestirilemez.

    Ortada `id`'si olan unite yoktur, `totals` projenin tamamini sayar, `blocks`
    gruplari MEVCUT kayitlardir. Tek uca `dry_run` bayragi konsaydi
    `response_model` iki seklin BIRLESIMINE (`Union`) zorlanir ve `gen:api`
    ciktisinda her iki alan da `optional` gorunerek istemci tarafinda sessiz
    `undefined` sinifi dogardi.
    """

    total_units: int  # TU 73, 146, 171
    total_list_value: Decimal  # TU 146, 172 — SATIRLARDAN toplanir (karar 5)
    conflicting_unit_nos: list[str]  # TU 177
    # TUM satirlar doner, 500 bile olsa: TU 166 "… 17 unite daha" bir FRONTEND
    # kirpmasidir. Sunucu kirpsaydi ekran "hangi satir cakisiyor" sorusunu
    # cevaplayamazdi (spec §5.4).
    rows: list[UnitBulkPreviewRow]  # TU 159-165


# --- Excel ice aktarma (kullanici karari, mockup yok — spec §6.4) ---


class UnitImportRowError(BaseModel):
    row: int  # Excel satir numarasi (baslik = 1, veri 2'den baslar)
    column: str | None
    message: str


class UnitImportResult(BaseModel):
    created: int
    blocks_created: int
    errors: list[UnitImportRowError]  # basarili sonucta bos
