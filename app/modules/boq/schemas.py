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
    "BoqItemCreate",
    "BoqItemResponse",
    "BoqItemUpdate",
    "BoqListResponse",
    "BoqTotals",
]

_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


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
