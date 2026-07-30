import uuid
from datetime import date
from decimal import Decimal

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
    "SiteFacilities",
    "SiteFacilitiesInput",
    "SiteListResponse",
    "SiteListTotals",
    "SiteProjectSummary",
    "SiteSectionInput",
    "SiteUpdate",
]


# --- Tesisler (spec §4.1) ---


class SiteFacilitiesInput(BaseModel):
    """Mockup 153-155 (depo) + 161-165 (tesis). DB'de 8 DUZ Boolean kolon (§4).

    API'de GRUPLU, DB'de duz: grup, mockup'taki gorsel kumelenmeyi tasir; duz
    kolonlar ise sorgulanabilir ve indekslenebilir kalir (§4.2, JSONB DEGIL).

    Sekizinin de varsayilani `False` — mockup'taki on-isaretler ORNEK VERIDIR,
    varsayilan degildir (§14.2, karar 2026-07-30).
    """

    closed_warehouse: bool = False
    open_storage: bool = False
    cold_storage: bool = False
    site_office: bool = False
    canteen: bool = False
    changing_room_wc: bool = False
    dormitory: bool = False
    infirmary: bool = False


class SiteFacilities(SiteFacilitiesInput):
    """Cikis karsiligi — girisle AYNI sekiz alan (§6.2). Ayri sinif, cunku
    giris/cikis sozlesmeleri zamanla ayrisabilir; bugun ayrisma yok."""


# --- Bolum ---


class SectionResponse(BaseModel):
    """Spec §4.1. "gecikme riski" alani KASITLI olarak yok (spec §3.3): hesabin
    girdisi henuz uretilmedigi icin yer tutucu bile dondurulmez."""

    id: uuid.UUID
    code: str | None
    name: str
    status: SectionStatus
    # §6.2 TEK ekleme. `manager_name` anlik goruntusu KALIR: kullanici silinse
    # (FK `SET NULL`) bile liste ekrani ve denetim kirilmaz.
    manager_user_id: uuid.UUID | None = None
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

    # --- Santiye formu genislemesi (§6.2). YALNIZ EKLEME yapildi: yukaridaki
    # P2 alanlarinin hicbiri kaldirilmadi/yeniden adlandirilmadi, aksi hâlde
    # P2 frontend'i kirilirdi. Hicbirinin varsayilani YOKTUR: eksik birakan bir
    # donusturucu sessizce degil, ValidationError ile patlamalidir.
    is_draft: bool
    site_manager_user_id: uuid.UUID | None
    safety_officer_user_id: uuid.UUID | None
    safety_officer_name: str | None
    safety_officer_is_outsourced: bool
    neighborhood: str | None
    parcel: str | None
    gps_coordinates: str | None
    land_area_m2: Decimal | None
    construction_area_m2: Decimal | None
    floor_info: str | None
    budget: Decimal | None
    facilities: SiteFacilities
    electricity_subscription_no: str | None
    water_subscription_no: str | None
    planned_worker_count: int | None


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
    # §5.2: taslaklar durum sayaclarindan DUSULMEZ (durumlari ne ise o sayilir);
    # yalnizca bu sayac ayrica artar. `ProjectCounts.draft` deseni.
    draft: int


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


class SiteSectionInput(BaseModel):
    """Form ici bolum satiri (mockup 119-124).

    P2 `SectionCreate`'in YERINE GECMEZ; onun yaninda durur ve ayni `Section`
    modelini yazar. Iki alan bilincli olarak YOKTUR:

    * `estimated_amount` — "Tahmini Bedel" yer tutucudur, saklanmaz (§3.4).
      Govdede gelirse Pydantic onu sessizce yok sayar.
    * `sort_order` — sira govdeden gelmez, dizideki sirasindan atanir (0,1,2...).
    """

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    manager_user_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None


class SiteCreate(BaseModel):
    """Mockup "Şantiye Ekle" formunun tam govdesi (spec §6.1).

    `contract_amount` YOK (spec §2.1) — santiye payi BOQ dagitiminin turevidir.
    `duration_days` YOK (§3.6) — sure turevdir. `latitude`/`longitude` YOK (§3.5).
    """

    # --- kimlik (mockup 63-73) ---
    name: str = Field(min_length=1, max_length=150)
    # Bossa SNT-{YYYY}-{NNN} uretilir (§3.2); kullanici PATCH ile duzeltebilir.
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: SiteStatus = SiteStatus.active
    site_manager_user_id: uuid.UUID | None = None
    safety_officer_user_id: uuid.UUID | None = None
    safety_officer_is_outsourced: bool = False
    # --- konum & alan (mockup 76-88) ---
    city: str | None = Field(default=None, max_length=100)
    neighborhood: str | None = Field(default=None, max_length=150)
    parcel: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=300)
    # BICIM DOGRULAMASI YOK (§3.5): yalniz uzunluk sinirlanir.
    gps_coordinates: str | None = Field(default=None, max_length=50)
    land_area_m2: Decimal | None = Field(default=None, ge=0)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)
    # Serbest metin ("2 bodrum + 10 normal") — sayi DEGIL (mockup 86).
    floor_info: str | None = Field(default=None, max_length=100)
    # --- takvim & butce (mockup 91-99) ---
    start_date: date | None = None
    end_date: date | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    # --- tesisler (mockup 147-174) ---
    facilities: SiteFacilitiesInput = Field(default_factory=SiteFacilitiesInput)
    electricity_subscription_no: str | None = Field(default=None, max_length=50)
    water_subscription_no: str | None = Field(default=None, max_length=50)
    planned_worker_count: int | None = Field(default=None, ge=0)
    # --- bolumler + taslak (mockup 102-144, 226) ---
    sections: list[SiteSectionInput] = Field(default_factory=list)
    is_draft: bool = False
    # P2/P1.1a mirasi — mockup'ta yok ama sozlesmede KALIR: `site_manager_user_id`
    # doluysa servis `users.full_name`i bunun uzerine yazar.
    site_manager_name: str | None = Field(default=None, max_length=200)
    delivery_date: date | None = None


class SiteUpdate(BaseModel):
    """`project_id` YOK — santiye baska projeye tasinamaz.
    `sections` YOK — bolumler mevcut P2 uclariyla yonetilir (§7.3).

    Tum alanlar istege bagli; "gonderilmedi" ile "null yapildi" ayrimi
    `model_fields_set`/`exclude_unset` ile korunur.
    """

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: SiteStatus | None = None
    site_manager_user_id: uuid.UUID | None = None
    safety_officer_user_id: uuid.UUID | None = None
    safety_officer_is_outsourced: bool | None = None
    city: str | None = Field(default=None, max_length=100)
    neighborhood: str | None = Field(default=None, max_length=150)
    parcel: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=300)
    gps_coordinates: str | None = Field(default=None, max_length=50)
    land_area_m2: Decimal | None = Field(default=None, ge=0)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)
    floor_info: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    budget: Decimal | None = Field(default=None, ge=0)
    facilities: SiteFacilitiesInput | None = None
    electricity_subscription_no: str | None = Field(default=None, max_length=50)
    water_subscription_no: str | None = Field(default=None, max_length=50)
    planned_worker_count: int | None = Field(default=None, ge=0)
    is_draft: bool | None = None
    site_manager_name: str | None = Field(default=None, max_length=200)
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
