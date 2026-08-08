import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.projects.models import PriceIndexType, ProjectStatus, ProjectType

# VKN/TCKN: 10 veya 11 haneli rakam (spec §3.2). Mesaj Turkce ve alana ozel.
_TAX_NUMBER_PATTERN = re.compile(r"^\d{10,11}$")
_TAX_NUMBER_MESSAGE = "VKN 10 veya 11 haneli rakam olmalıdır."


# --- İşveren (employers) şemaları (spec §3.1, §3.2) ---


class EmployerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_number: str | None = Field(default=None, max_length=11)
    contact_person: str | None = Field(default=None, max_length=200)

    @field_validator("tax_number")
    @classmethod
    def _validate_tax_number(cls, value: str | None) -> str | None:
        if value is not None and not _TAX_NUMBER_PATTERN.fullmatch(value):
            raise ValueError(_TAX_NUMBER_MESSAGE)
        return value


class EmployerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    tax_number: str | None
    contact_person: str | None
    is_active: bool


class EmployerListResponse(BaseModel):
    items: list[EmployerResponse]


# --- Sözleşme okuma yanıtı (spec §3.3, §5.4) ---


class ProjectContractResponse(BaseModel):
    """Detay/liste yanıtında sözleşme (spec §2.4). Yalnız okuma; giriş `ProjectContractInput`."""

    model_config = ConfigDict(from_attributes=True)

    contract_no: str | None
    signature_date: date | None
    amount: Decimal | None
    advance_pct: Decimal
    retainage_pct: Decimal
    vat_pct: Decimal
    late_penalty_daily: Decimal | None
    has_price_escalation: bool
    index_type: PriceIndexType | None
    base_index_value: Decimal | None


class ProjectBudgetLines(BaseModel):
    """Dört bütçe kalemi okuma yanıtı (spec §3.3). Toplam `budget` ayrı alanda durur."""

    material: Decimal
    labor: Decimal
    subcontractor: Decimal
    overhead: Decimal


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
    # employer_name anlık görüntüsü KALIR (spec §2.3): join'siz okunur, kırılmasın.
    employer_name: str | None
    # B6: işveren/sözleşme ilişki nesneleri + bütçe kalemleri + taslak bayrağı (ekleme,
    # kırıcı değil). Taslakta employer/contract None olabilir; alanlar sözleşmede kalır.
    employer: EmployerResponse | None
    contract: ProjectContractResponse | None
    budget_lines: ProjectBudgetLines
    is_draft: bool
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
    # B6: taslak sekmesi sayacı (spec §5.4). completed ve diğer sayaçlar aynen kalır.
    draft: int


class ProjectListResponse(BaseModel):
    counts: ProjectCounts
    items: list[ProjectListItem]


# --- Giris semalari ---


class ProjectInvestmentInput(BaseModel):
    sales_target: Decimal | None = Field(default=None, ge=0)
    land_cost: Decimal | None = Field(default=None, ge=0)


class ShareholderInput(BaseModel):
    """P9 spec §4.1: `id` OPSIYONELDIR ve satirin KIMLIGINI korur.

    id verilirse mevcut satir yerinde guncellenir (`units.shareholder_id` bagi
    ayakta kalir); verilmezse yeni satirdir. id'siz eski govdeler geriye uyumlu
    calisir. Bilinmeyen ya da baska projeye ait id sessizce yeni satira DONMEZ,
    422 verir (bkz. `service._merge_shareholders`).
    """

    id: uuid.UUID | None = None
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


class ProjectContractInput(BaseModel):
    """İşveren sözleşmesi girişi (spec §2.4, §3.3). Yalnız `taahhut` projelerinde.

    Yüzdeler alan düzeyinde 0..100 (§3.6 kural 6). `has_price_escalation=true` iken
    endeks alanlarının zorunluluğu (kural 5) ve endeks kapalıyken NULL olması
    (ck_contract_escalation) servis + DB CHECK ile denetlenir.
    """

    contract_no: str | None = Field(default=None, max_length=100)
    signature_date: date | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    advance_pct: Decimal = Field(default=Decimal("20"), ge=0, le=100)
    retainage_pct: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    vat_pct: Decimal = Field(default=Decimal("20"), ge=0, le=100)
    late_penalty_daily: Decimal | None = Field(default=None, ge=0)
    has_price_escalation: bool = True
    index_type: PriceIndexType | None = None
    base_index_value: Decimal | None = Field(default=None, ge=0)


class ProjectBudgetInput(BaseModel):
    """Dört bütçe kalemi (spec §3.3). Toplam `budget`'i servis hesaplar; istemci `budget` yok."""

    material: Decimal = Field(default=Decimal("0"), ge=0)
    labor: Decimal = Field(default=Decimal("0"), ge=0)
    subcontractor: Decimal = Field(default=Decimal("0"), ge=0)
    overhead: Decimal = Field(default=Decimal("0"), ge=0)


class ProjectSiteInput(BaseModel):
    """Satır içi şantiye (spec §3.4). Kod verilmezse P2 türeticisi çalışır (B5)."""

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=50)
    site_manager_name: str | None = Field(default=None, max_length=200)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)


class ProjectCreate(BaseModel):
    # code artik OPSIYONEL: bossa sunucu PRJ-{YYYY}-{NNN} uretir (spec §3.5).
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    project_type: ProjectType
    status: ProjectStatus = ProjectStatus.active
    category: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    parcel: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=300)
    start_date: date | None = None
    end_date: date | None = None
    # employer_name gövdeden KALDIRILDI (spec §3.3): serbest metin işveren yolu kapandı.
    employer_id: uuid.UUID | None = None
    contract: ProjectContractInput | None = None
    budget_lines: ProjectBudgetInput = Field(default_factory=ProjectBudgetInput)
    sites: list[ProjectSiteInput] = Field(default_factory=list)
    is_draft: bool = False
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
