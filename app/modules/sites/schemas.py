import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# B6/P1 yer tutucu sozlesmesi TEK yerde tanimlidir (spec §3): kopyalanmaz,
# projects modulunden import edilir.
from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder
from app.modules.sites.models import SectionStatus, SiteStatus

__all__ = [
    "CountPlaceholder",
    "MetricPlaceholder",
    "SectionCreate",
    "SectionListResponse",
    "SectionResponse",
    "SectionStatusCounts",
    "SectionUpdate",
    "SiteCard",
    "SiteCounts",
    "SiteCreate",
    "SiteDetailResponse",
    "SiteListResponse",
    "SiteListTotals",
    "SiteProjectSummary",
    "SiteUpdate",
]


# --- Bolum ---


class SectionResponse(BaseModel):
    """Spec §4.1. "gecikme riski" alani KASITLI olarak yok (spec §3.3): hesabin
    girdisi henuz uretilmedigi icin yer tutucu bile dondurulmez."""

    id: uuid.UUID
    code: str | None
    name: str
    status: SectionStatus
    manager_name: str | None
    start_date: date | None
    end_date: date | None
    sort_order: int
    progress_pct: MetricPlaceholder
    boq_item_count: CountPlaceholder
    budget: MetricPlaceholder
    worker_count: CountPlaceholder


class SectionStatusCounts(BaseModel):
    """Mockup'taki "3 aktif · 2 bekliyor" kirilimi (spec §3.2)."""

    planned: int
    active: int
    completed: int


class SectionListResponse(BaseModel):
    counts: SectionStatusCounts
    items: list[SectionResponse]


# --- Santiye ---


class SiteCard(BaseModel):
    """Spec §4.1 SiteCard. `remaining_days` negatif olabilir (spec §4.2) —
    gecikmeyi kirmizi gostermek frontend'in isi, backend gercegi bastirmaz."""

    id: uuid.UUID
    code: str
    name: str
    status: SiteStatus
    address: str | None
    city: str | None
    city_inherited: bool
    site_manager_name: str | None
    start_date: date | None
    end_date: date | None
    delivery_date: date | None
    remaining_days: int | None
    section_count: int
    worker_count: CountPlaceholder
    progress_pct: MetricPlaceholder


class SiteProjectSummary(BaseModel):
    """Santiye Detay ust satiri: proje adi + isveren (spec §3.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str | None
    employer_name: str | None


class SiteDetailResponse(SiteCard):
    project: SiteProjectSummary
    section_status_counts: SectionStatusCounts
    sections: list[SectionResponse]
    total_progress_payment: MetricPlaceholder
    contract_amount: MetricPlaceholder


class SiteCounts(BaseModel):
    all: int
    active: int
    on_hold: int
    completed: int


class SiteListTotals(BaseModel):
    """Alt KPI seridi — bu dilimde TAMAMI yer tutucu (spec §4.1)."""

    total_progress_payment: MetricPlaceholder
    subcontractor_count: CountPlaceholder
    active_worker_count: CountPlaceholder
    average_margin: MetricPlaceholder


class SiteListResponse(BaseModel):
    counts: SiteCounts
    items: list[SiteCard]
    totals: SiteListTotals


# --- Giris semalari ---


class SiteCreate(BaseModel):
    """`contract_amount` YOK (spec §2.1) — santiye payi BOQ dagitiminin turevidir."""

    # spec §8 acik soru 2, oneri uygulandi: kod zorunlu ama verilmezse ad'dan
    # otomatik turetilir; kullanici sonradan PATCH ile duzeltebilir.
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    status: SiteStatus = SiteStatus.active
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    site_manager_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    delivery_date: date | None = None


class SiteUpdate(BaseModel):
    """`project_id` YOK — santiye baska projeye tasinamaz."""

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    status: SiteStatus | None = None
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    site_manager_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    delivery_date: date | None = None


class SectionCreate(BaseModel):
    """`budget` YOK (spec §2.2) — bolum bedeli BOQ kalemlerinin toplamidir."""

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    # Varsayilan `planned` (spec §2.3): yeni bolum kural olarak planlanmis dogar.
    status: SectionStatus = SectionStatus.planned
    manager_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    sort_order: int = Field(default=0, ge=0)


class SectionUpdate(BaseModel):
    """`site_id` YOK — bolum baska santiyeye tasinamaz."""

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    status: SectionStatus | None = None
    manager_name: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    sort_order: int | None = Field(default=None, ge=0)
