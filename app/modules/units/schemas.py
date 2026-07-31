import enum
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, computed_field, model_validator

# Yer tutucu sozlesmesi TEK yerde tanimlidir (B6/P1, spec §6): kopyalanmaz,
# projects modulunden import edilir (BOQ `schemas.py:8` deseninin aynisi).
from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder
from app.modules.units.models import (
    BlockGroundUsage,
    BlockParkingType,
    BlockRoofType,
    BlockStatus,
    UnitKind,
    UnitOwnerSide,
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
    "UnitCreate",
    "UnitImportResult",
    "UnitImportRowError",
    "UnitKind",
    "UnitKindBreakdown",
    "UnitListResponse",
    "UnitNumberingPattern",
    "UnitOwnerSide",
    "UnitOwnerSideFilter",
    "UnitResponse",
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
_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


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

    apartment: int = 0
    shop: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        return self.apartment + self.shop


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
    # --- ileri dilim yer tutuculari ---
    sales_status: MetricPlaceholder  # P8 (KY 276, KKP 92)
    sale_price: MetricPlaceholder  # P8 (KY 275)
    buyer_name: MetricPlaceholder  # P8 (KY 277)
    shareholder: MetricPlaceholder  # P9 (KKP 91)
    unit_cost: MetricPlaceholder  # P10 (FDS 62)

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
    sold: CountPlaceholder  # P8 (KKP 163)
    reserved: CountPlaceholder  # P8
    listed: CountPlaceholder  # P8


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
    sold_units: CountPlaceholder  # P8 (KY 88, 264)
    reserved_units: CountPlaceholder  # P8 (KY 265)
    available_units: CountPlaceholder  # P8 (KY 266)
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


class UnitCreate(BaseModel):
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


class UnitUpdate(BaseModel):
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


class UnitAllocationItem(BaseModel):
    """KKP 25 "Paylasimi Kaydet". `owner_side=None` atamayi kaldirir (spec §5.3)."""

    unit_id: uuid.UUID
    owner_side: UnitOwnerSide | None


class UnitAllocationRequest(BaseModel):
    items: list[UnitAllocationItem] = Field(min_length=1, max_length=_MAX_ALLOCATION_ITEMS)


# --- Toplu uretim (kullanici karari, mockup yok — spec §6.3) ---


class UnitNumberingPattern(str, enum.Enum):
    sequential = "sequential"  # 1, 2, 3, ... N     — SY 76-99 deseni
    floor_based = "floor_based"  # 101, 102, 201, 202


class UnitBulkCreate(BaseModel):
    block_id: uuid.UUID
    unit_kind: UnitKind
    start_floor: int = Field(ge=-5, le=100)  # bodrum katlar icin negatif serbest
    end_floor: int = Field(ge=-5, le=100)
    units_per_floor: int = Field(ge=1, le=20)
    numbering: UnitNumberingPattern = UnitNumberingPattern.sequential
    prefix: str = Field(default="", max_length=10)  # "D" → D1..D4 (SY 132-135)
    start_number: int = Field(default=1, ge=0)  # sequential icin baslangic (SY 76 "1")
    # Uretilen TUM unitelere uygulanacak ortak varsayilanlar.
    layout: str | None = Field(default=None, max_length=20)
    gross_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    net_area_m2: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    list_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    appraisal_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)

    @model_validator(mode="after")
    def _validate_range(self) -> "UnitBulkCreate":
        if self.end_floor < self.start_floor:
            raise ValueError("Bitiş katı başlangıç katından küçük olamaz")
        total = (self.end_floor - self.start_floor + 1) * self.units_per_floor
        if total > _MAX_BULK_UNITS:
            raise ValueError(f"Tek seferde en fazla {_MAX_BULK_UNITS} ünite üretilebilir")
        return self


# --- Excel ice aktarma (kullanici karari, mockup yok — spec §6.4) ---


class UnitImportRowError(BaseModel):
    row: int  # Excel satir numarasi (baslik = 1, veri 2'den baslar)
    column: str | None
    message: str


class UnitImportResult(BaseModel):
    created: int
    blocks_created: int
    errors: list[UnitImportRowError]  # basarili sonucta bos
