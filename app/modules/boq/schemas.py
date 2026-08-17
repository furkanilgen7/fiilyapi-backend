import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, computed_field

# Serbest metin tavani (TB4 S3) `contracts` ailesiyle PAYLASILIR — tek kaynak.
from app.core.text import FREE_TEXT_MAX_LENGTH

# Yer tutucu sozlesmesi TEK yerde tanimlidir (B6/P1, spec §3/§5.1): kopyalanmaz,
# projects modulunden import edilir (plan T2 notu).
from app.modules.projects.schemas import MetricPlaceholder

__all__ = [
    "MetricPlaceholder",
    "BoqGroupCreate",
    "BoqGroupResponse",
    "BoqGroupUpdate",
    "BoqItemAllocation",
    "BoqItemAllocationInput",
    "BoqItemAllocationsReplace",
    "BoqItemAllocationsResponse",
    "BoqItemCreate",
    "BoqItemResponse",
    "BoqItemUpdate",
    "BoqListResponse",
    "BoqTotals",
]

_MONEY = Decimal("0.01")

#: Miktar hassasiyeti — `boq_items.quantity` / `boq_item_section_allocations.quantity`
#: kolonlarinin `Numeric(14, 3)` olcegiyle BIREBIR. Govdeden gelen miktar YAZILMADAN
#: ONCE bu olcege cekilir: kontrol edilen sayi ile SAKLANAN sayi ayrisirsa toplam
#: invarianti (K3) DB'nin yuvarlamasi kadar kacak verir.
_QUANTITY = Decimal("0.001")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(_QUANTITY, rounding=ROUND_HALF_UP)


# --- Okuma semalari ---


class BoqItemResponse(BaseModel):
    """Spec §5.1 poz kalemi satiri. `amount` turevdir, saklanmaz — quantity *
    unit_price, para hassasiyetine (0.01) yuvarlanir. `progress_pct` hakediş
    (P7) yer tutucusudur (spec §3.2)."""

    id: uuid.UUID
    code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    progress_pct: MetricPlaceholder
    sort_order: int
    # --- BOQ-SEC (K6) — MEVCUT alanlarin hicbiri degismedi, ikisi EKLENDI ---
    #
    # 🔴 IKI ANLAM TUZAGI: `section_id` suzgeciyle okundugunda `quantity` O BOLUME
    # tahsis edilen miktardir (poz toplami DEGIL, K5) — ama asagidaki iki alan HER
    # ZAMAN pozun GERCEK santiye kotasi uzerinden turer. Yani suzulmus yanitta
    # `unallocated_quantity != quantity - allocated_quantity`'dir ve bu bir kusur
    # degil tanimdir. Mockup'in "Santiye Kotasi" sutunu (BoqAssignmentCard.tsx:17)
    # suzulmus yanitta `allocated_quantity + unallocated_quantity`den okunur.
    allocated_quantity: Decimal
    unallocated_quantity: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> Decimal:
        return _quantize_money(self.quantity * self.unit_price)


class BoqGroupResponse(BaseModel):
    """Spec §5.1 grup satiri. `group_total` turevdir: kalem tutarlarinin toplami."""

    id: uuid.UUID
    name: str
    sort_order: int
    items: list[BoqItemResponse]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def group_total(self) -> Decimal:
        return _quantize_money(sum((item.amount for item in self.items), Decimal("0")))


class BoqTotals(BaseModel):
    """Spec §5.1 ust KPI seridi. `grand_total` GERCEK deger, geri kalani yer
    tutucu (sozlesme/hakediş bu dilimde yazilmiyor)."""

    contract_total: MetricPlaceholder
    realized_total: MetricPlaceholder
    remaining_total: MetricPlaceholder
    revision_total: MetricPlaceholder
    grand_total: Decimal
    grand_progress_pct: MetricPlaceholder


class BoqListResponse(BaseModel):
    totals: BoqTotals
    groups: list[BoqGroupResponse]


# --- Yazma semalari ---


class BoqGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int = Field(default=0, ge=0)


class BoqGroupUpdate(BaseModel):
    """`site_id` YOK — grup baska santiyeye tasinamaz (spec §3.3 invariant 4)."""

    name: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int | None = Field(default=None, ge=0)


class BoqItemCreate(BaseModel):
    group_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str = Field(min_length=1, max_length=50)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    sort_order: int = Field(default=0, ge=0)


class BoqItemAllocationInput(BaseModel):
    """Tek tahsis satiri (BOQ-SEC K4).

    `quantity` STRICT pozitiftir: sifir tahsis bir satir olarak TUTULMAZ (K1
    `CHECK`i ile ayni kural) — "bu bolumden cikar" demenin yolu satiri govdeden
    DUSURMEKTIR, sifir yazmak degil.
    """

    section_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class BoqItemAllocationsReplace(BaseModel):
    """`PUT /boq/items/{item_id}/allocations` govdesi — TAM KUME DEGISTIRME.

    🔴 `allocations` ZORUNLUDUR (varsayilani YOKTUR): alan hic gonderilmezse ya
    da `null` gecilirse istek 422 alir. Bu ucta "dokunma" anlami YOKTUR; bos
    dizi `[]` "hepsini kaldir" demektir ve eksik alani sessizce ona ya da
    "degistirme"ye yorumlamak, kullanicinin niyetini SUNUCUNUN uydurmasi olurdu.
    """

    allocations: list[BoqItemAllocationInput]


class BoqItemAllocation(BaseModel):
    """Yaziladan SONRAKI tahsis satiri. `section_name` UI icindir (mockup F131-211).

    Bu sema santiye BOQ listesinde BASILMAZ (K6): her kalem icin tahsis listesi
    donmek N+1 acar ve liste ekraninin ihtiyaci olan sey zaten `allocated_quantity`
    ozetidir.
    """

    section_id: uuid.UUID
    section_name: str
    quantity: Decimal


class BoqItemAllocationsResponse(BaseModel):
    item: BoqItemResponse
    allocations: list[BoqItemAllocation]


class BoqItemUpdate(BaseModel):
    """`site_id` YOK (spec §3.3 invariant 4). `group_id` verilirse ayni santiye
    kontrolu servis katmaninda tekrarlanir (spec §3.3 invariant 1)."""

    group_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
