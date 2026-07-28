import uuid
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.projects.models import ProjectStatus, ProjectType

# --- B6 yer tutucu deseni (dashboard spec §2.3; bu ekran icin spec §5.3) ---


class MetricPlaceholder(BaseModel):
    """Veri kaynagi henuz yazilmamis tek degerli alan. Sahte rakam yerine durust bos durum."""

    available: bool = False
    value: Decimal | None = None
    pending_module: str


class CountPlaceholder(BaseModel):
    """Veri kaynagi henuz yazilmamis sayac alani ("48 isci", "3 hissedar" gibi)."""

    available: bool = False
    count: int | None = None
    pending_module: str


# --- Tip kartlari (spec §5.3) ---


class ContractingCard(BaseModel):
    """Taahhut karti — sozlesme bedeli/isveren ustte gercek, gerisi bos durum."""

    spent: MetricPlaceholder
    physical_progress: MetricPlaceholder
    final_progress_payment: MetricPlaceholder
    worker_count: CountPlaceholder
    subcontractor_count: CountPlaceholder


class InvestmentCard(BaseModel):
    sales_target: Decimal | None
    land_cost: Decimal | None
    sold_amount: MetricPlaceholder
    sales_ratio: MetricPlaceholder
    unit_summary: CountPlaceholder
    total_cost: MetricPlaceholder
    estimated_profit: MetricPlaceholder
    margin: MetricPlaceholder


class ShareholderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    share_pct: Decimal


class LandShareCard(BaseModel):
    landowner_name: str
    our_share_pct: Decimal
    owner_share_pct: Decimal
    land_cost: Decimal  # daima 0 — tanim geregi, saklanmaz (spec §3.3)
    contract_no: str | None
    notary_date: date | None
    land_area_m2: Decimal | None
    construction_area_m2: Decimal | None
    delivery_date: date | None
    daily_penalty: Decimal | None
    guarantee_amount: Decimal | None
    shareholder_count: int
    shareholders: list[ShareholderResponse]
    our_unit_count: CountPlaceholder
    owner_unit_count: CountPlaceholder
    our_share_value: MetricPlaceholder
    construction_cost: MetricPlaceholder
    estimated_profit: MetricPlaceholder
    margin: MetricPlaceholder
    construction_progress: MetricPlaceholder


# --- Liste/detay yanitlari ---


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    project_type: ProjectType
    category: str | None
    city: str | None
    status: ProjectStatus
    start_date: date | None
    end_date: date | None
    contract_no: str | None
    contract_amount: Decimal | None
    employer_name: str | None
    budget: Decimal
    progress_pct: Decimal
    contracting: ContractingCard | None
    investment: InvestmentCard | None
    land_share: LandShareCard | None


class ProjectDetailResponse(ProjectListItem):
    # P2 eklemesi (spec §1): GERCEK deger, yer tutucu degil — sayacin girdisi
    # (sites tablosu) P2'de yazildi. P1 sozlesmesine ekleme, kirici degisiklik degil.
    site_count: int


class ProjectCounts(BaseModel):
    all: int
    taahhut: int
    kendi_yatirim: int
    kat_karsiligi: int
    completed: int


class ProjectListResponse(BaseModel):
    counts: ProjectCounts
    items: list[ProjectListItem]


# --- Giris semalari ---


class ProjectInvestmentInput(BaseModel):
    sales_target: Decimal | None = Field(default=None, ge=0)
    land_cost: Decimal | None = Field(default=None, ge=0)


class ShareholderInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    share_pct: Decimal = Field(gt=0, le=100)


class ProjectLandShareInput(BaseModel):
    landowner_name: str = Field(min_length=1, max_length=200)
    our_share_pct: Decimal = Field(gt=0, lt=100)
    owner_share_pct: Decimal = Field(gt=0, lt=100)
    contract_no: str | None = Field(default=None, max_length=100)
    notary_date: date | None = None
    land_area_m2: Decimal | None = Field(default=None, ge=0)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)
    delivery_date: date | None = None
    daily_penalty: Decimal | None = Field(default=None, ge=0)
    guarantee_amount: Decimal | None = Field(default=None, ge=0)
    shareholders: list[ShareholderInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _pct_total_must_be_100(self) -> Self:
        if self.our_share_pct + self.owner_share_pct != 100:
            msg = "Pay yüzdelerinin toplamı 100 olmalıdır"
            raise ValueError(msg)
        return self


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    project_type: ProjectType
    status: ProjectStatus = ProjectStatus.active
    category: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    contract_no: str | None = Field(default=None, max_length=100)
    contract_amount: Decimal | None = Field(default=None, ge=0)
    employer_name: str | None = Field(default=None, max_length=200)
    investment: ProjectInvestmentInput | None = None
    land_share: ProjectLandShareInput | None = None


class ProjectUpdate(BaseModel):
    """project_type YOK — tip PATCH ile degistirilemez (spec §3.5)."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    status: ProjectStatus | None = None
    category: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    contract_no: str | None = Field(default=None, max_length=100)
    contract_amount: Decimal | None = Field(default=None, ge=0)
    employer_name: str | None = Field(default=None, max_length=200)
    investment: ProjectInvestmentInput | None = None
    land_share: ProjectLandShareInput | None = None
