"""Sözleşmeler (P5) Pydantic şemaları — okuma/yazma ayrı, `boq`/`sites` deseni.

Alan uzunluk sınırları modeldeki `String(N)` ile BİREBİR aynıdır (spec §3.2-§3.6):
frontend `maxLength`'i buradan okur, uyuşmazlık sessiz 422 üretir.

Pydantic'te duran ve `guards.py`'de tekrarlanmayan kurallar (spec §10): ad boş
olamaz, tutarlar `>= 0`, `quantity > 0`, yüzdeler 0-100, `payment_term_days >= 0`.

Kapsam dışı alanlar (spec §2.2) yanıt şemalarında AÇIKÇA yer alır: hakediş →
`progress_payment_summary: None`, milestone → `milestones: None`, belgeler →
`documents: None`, artı `pending_modules: list[str]` sabiti.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

# Serbest metin tavanı (TB4 S3) `boq` ailesiyle PAYLAŞILIR — tek kaynak.
from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.contracts.models import ContractStatus, PaymentPeriod

# İşveren hakediş özeti P7'de GERÇEK veriye bağlandı (spec §9.6): E14 127-147
# kartı artık yer tutucu değil, hesaplanmış özettir. Yön TEK taraflıdır
# (`contracts` → `progress_payments`); şema importu döngü YARATMAZ çünkü
# `progress_payments.schemas` yalnız kendi modellerini okur.
from app.modules.progress_payments.schemas import ProgressPaymentSummary

# `PriceIndexType` sözleşme kolonunun kendi enum'udur (`projects.models`) —
# okuma şemasında yeniden tanımlanmaz (T5).
from app.modules.projects.models import PriceIndexType

# KDV kümesi ({1, 10, 20}) `units.schemas`ten GELİR (`sales.schemas` ile aynı
# gerekçe): oran yasayla değişen TEK bir listedir, üç modülde üç kopya olamaz.
from app.modules.units.schemas import RequiredVatRate, VatRate

__all__ = [
    "ContractAllocationInput",
    "ContractDistributionAllocation",
    "ContractDistributionGroup",
    "ContractDistributionItem",
    "ContractDistributionResponse",
    "ContractDistributionSave",
    "ContractDistributionSite",
    "ContractDistributionSiteItem",
    "ContractDistributionSiteSummary",
    "ContractListItem",
    "ContractListResponse",
    "ContractSummary",
    "ContractType",
    "EmployerContractDetail",
    "EmployerContractGroupCreate",
    "EmployerContractGroupItems",
    "EmployerContractGroupResponse",
    "EmployerContractGroupUpdate",
    "EmployerContractItemCreate",
    "EmployerContractItemResponse",
    "EmployerContractItemsResponse",
    "EmployerContractItemUpdate",
    "SubcontractorContractCreate",
    "SubcontractorContractDetail",
    "SubcontractorContractItemCreate",
    "SubcontractorContractItemGroup",
    "SubcontractorContractItemResponse",
    "SubcontractorContractItemsLoadResponse",
    "SubcontractorContractItemUpdate",
    "SubcontractorContractListItem",
    "SubcontractorContractListResponse",
    "SubcontractorContractUpdate",
    "SubcontractorCreate",
    "SubcontractorListResponse",
    "SubcontractorResponse",
    "SubcontractorUpdate",
]

_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


ContractType = Literal["employer", "subcontractor"]


# --- Birleşik liste (spec §6.1) ---


class ContractSummary(BaseModel):
    """`SZL` 34-38 üst KPI şeridi.

    `progress_payment_total` (P7/H9, spec §9.6): listelenen sözleşmelerin
    KÜMÜLATİF BRÜT (`approved|paid`) hakediş toplamı — artık `MetricPlaceholder`
    DEĞİL düz `Decimal`. TH-SUM dilimiyle İKİ sekmede de doludur: işveren tarafı
    `progress_payments`, taşeron tarafı `subcontractor_progress_payments`
    üzerinden hesaplanır; liste ucu artık iki dalda da değer döner ve hakedişi
    olmayan küme `0.00`'dır (bilinmiyor değil, gerçekten sıfır). Alan tipi
    `Decimal | None` KALIR — şema uyumluluğu için (frontend typecheck'i bu
    dilimde kırılmaz), varsayılanı hâlâ `None`'dır.

    ⚠️ **Frontend için kırıcı değişiklik** (spec §10/4): alan artık
    `{available, value, pending_module}` sarmalayıcısı değildir; `gen:api`
    yenilenmeden tüketilemez.
    """

    total_amount: Decimal
    active_count: int
    progress_payment_total: Decimal | None = None
    expiring_this_month_count: int


class ContractListItem(BaseModel):
    """`SZL` 44-51 satırı. `title`/`counterparty_name` işveren/taşeron için farklı
    kaynaklardan servis tarafından doldurulur (spec §6.1 alan eşlemesi)."""

    id: uuid.UUID
    title: str
    contract_no: str | None
    counterparty_name: str | None
    amount: Decimal
    start_date: date | None
    end_date: date | None
    progress_pct: Decimal | None = None
    """§8 finansal ilerleme: `kümülatif brüt / bedel × 100` (P7/H9, spec §9.6).

    İşveren sözleşmesinde gerçek değer; bedel yok/sıfır ise `None`. Taşeron
    sözleşmesinde her zaman `None` (ayrı dilim, spec §1.2). Kırıcı değişiklik:
    eskiden `MetricPlaceholder` sarmalayıcısıydı (spec §10/4).
    """
    status: ContractStatus
    is_draft: bool


class ContractListResponse(BaseModel):
    summary: ContractSummary
    items: list[ContractListItem]


# --- İşveren sözleşmesi: gruplar + kalemler (spec §3.2, `BoqGroup`/`BoqItem` birebiri) ---


class EmployerContractGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int = Field(default=0, ge=0)


class EmployerContractGroupUpdate(BaseModel):
    """`project_id` YOK — grup başka projeye taşınamaz (`BoqGroupUpdate` deseni)."""

    name: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    sort_order: int | None = Field(default=None, ge=0)


class EmployerContractGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int


class EmployerContractItemCreate(BaseModel):
    group_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str = Field(min_length=1, max_length=50)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    sort_order: int = Field(default=0, ge=0)


class EmployerContractItemUpdate(BaseModel):
    """`project_id` YOK. `group_id` verilirse aynı proje kontrolü servis
    katmanında tekrarlanır (`BoqItemUpdate` deseni)."""

    group_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)


class EmployerContractItemResponse(BaseModel):
    """`POZ` tablo satırı. `distributed_quantity`/`remaining_quantity` türevdir,
    servis `boq_items.contract_item_id` bağlarından hesaplar (spec §3.3, §6.2)."""

    id: uuid.UUID
    group_id: uuid.UUID
    code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    sort_order: int
    distributed_quantity: Decimal
    remaining_quantity: Decimal


class EmployerContractGroupItems(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    items: list[EmployerContractItemResponse]


class EmployerContractItemsResponse(BaseModel):
    """`GET /projects/{project_id}/contract/items` yanıtı (spec §6.2)."""

    groups: list[EmployerContractGroupItems]


# --- İşveren sözleşmesi detayı (`E14` başlığı, spec §6.2) ---


class EmployerContractDetail(BaseModel):
    """`E14` başlığı. Sözleşmenin kendi alanları için YENİ yazma ucu AÇILMAZ
    (spec §6.2) — bu yalnız okuma şemasıdır.

    Kapsam dışı (spec §2.2): milestone takvimi (P11), belgeler (kalıcı karar
    8) — ikisi de burada AÇIKÇA `None` döner. Hakediş özeti (P7) artık kapsam
    dışı DEĞİL (P7/H9): `progress_payment_summary` ZORUNLUDUR, `None` döndürmez.
    """

    project_id: uuid.UUID
    contract_no: str | None
    signature_date: date | None
    amount: Decimal | None
    advance_pct: Decimal
    retainage_pct: Decimal
    vat_pct: Decimal
    late_penalty_daily: Decimal | None
    has_price_escalation: bool
    index_type: PriceIndexType | None
    """T5 (spec §6 ek task, P7 bulgusu): fiyat farkı endeks tipi additive olarak
    okuma ucuna eklendi — sözleşmenin yazma yolu bu dilimde DEĞİŞMEZ
    (`PATCH /projects/{id}` nested `contract`'ında kalır). Fiyat farkı kapalıyken
    (`has_price_escalation=false`) model kısıtı gereği daima `None`."""
    status: ContractStatus
    # Tarihler `projects.start_date`/`end_date`'ten okunur (spec §3.1 — ikinci
    # bir tarih kaynağı açılmaz).
    start_date: date | None
    end_date: date | None
    employer_name: str | None
    contractor_name: str | None
    items_total: Decimal
    items_total_diff: Decimal
    advance_amount: Decimal
    progress_payment_summary: ProgressPaymentSummary
    """E14 127-147 "Hakediş Özeti" kartı — P7/H9'da GERÇEK veriye bağlandı
    (spec §9.6). ZORUNLU alan (H9 denetim O2): tek üretici
    `contracts.service.get_employer_contract_detail`, sözleşme varlığı zaten
    bu şemaya ulaşmanın ön şartı (yoksa 404) ve `progress_payments_summary.
    build_summary` HER yolda dolu bir gövde döner (hakediş yoksa sıfırlarla) —
    `None` gelen bir dal yoktur, bu yüzden şema da `None`'a izin vermez."""
    milestones: None = None
    documents: None = None
    pending_modules: list[str] = Field(default_factory=lambda: ["project_schedule", "documents"])
    """`progress_payments` bu listeden ÇIKTI (P7/H9): modül artık yazıldı ve
    `progress_payment_summary` gerçek veri taşıyor."""


# --- Poz dağılımı (spec §6.3, `POZ` ekranı) ---


class ContractAllocationInput(BaseModel):
    """`quantity=None` gönderilmesi kaldırma anlamına gelir (spec §6.3 adım 1)."""

    contract_item_id: uuid.UUID
    site_id: uuid.UUID
    quantity: Decimal | None = Field(default=None, gt=0)


class ContractDistributionSave(BaseModel):
    """`PUT .../contract/distribution` gövdesi — ekranın tamamı tek istekte."""

    allocations: list[ContractAllocationInput] = Field(default_factory=list)


class ContractDistributionSite(BaseModel):
    """`POZ` 82-83 dağıtım kolon başlığı."""

    id: uuid.UUID
    name: str


class ContractDistributionAllocation(BaseModel):
    site_id: uuid.UUID
    quantity: Decimal
    boq_item_id: uuid.UUID


class ContractDistributionItem(BaseModel):
    id: uuid.UUID
    code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    allocations: list[ContractDistributionAllocation]
    remaining_quantity: Decimal


class ContractDistributionGroup(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int
    items: list[ContractDistributionItem]


class ContractDistributionSiteItem(BaseModel):
    """`site_summaries[]` içindeki kalem satırı (`POZ` 168-187)."""

    code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class ContractDistributionSiteSummary(BaseModel):
    site_id: uuid.UUID
    site_name: str
    items: list[ContractDistributionSiteItem]
    total_amount: Decimal


class ContractDistributionResponse(BaseModel):
    """`GET .../contract/distribution` yanıtı — `POZ` ekranının gerektirdiği kadarı."""

    sites: list[ContractDistributionSite]
    groups: list[ContractDistributionGroup]
    undistributed_item_count: int
    undistributed_item_names: list[str]
    site_summaries: list[ContractDistributionSiteSummary]
    distributed_item_count: int
    total_item_count: int


# --- Taşeron kartoteksi (spec §3.4, `Employer` deseninin birebiri) ---


class SubcontractorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tax_number: str | None = Field(default=None, max_length=11)
    contact_person: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    # category enum DEĞİL, String — sunucu FORM 82'deki listeyi zorlamaz (spec §3.4).
    category: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class SubcontractorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_number: str | None = Field(default=None, max_length=11)
    contact_person: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class SubcontractorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    tax_number: str | None
    contact_person: str | None
    phone: str | None
    email: str | None
    category: str | None
    is_active: bool


class SubcontractorListResponse(BaseModel):
    items: list[SubcontractorResponse]


# --- Taşeron sözleşmesi kalemleri (spec §3.6) ---


class SubcontractorContractItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str = Field(min_length=1, max_length=50)
    quantity: Decimal = Field(gt=0)
    # NULL bilinçli (spec §3.6): işverenden yüklenen kalem fiyatsız gelir;
    # "girilmedi" ile "0 TL" ayrımı korunur.
    unit_price: Decimal | None = Field(default=None, ge=0)
    # `None` = "istemci göndermedi" (İÇ İÇE yazma yolunda satır sırasına göre
    # otomatik atanır); bilinçli `0` bundan AYIRT edilmeli — `int = 0` iken
    # ikisi ayrışamazdı (dal geneli son inceleme, falsy `or` tuzağı).
    sort_order: int | None = Field(default=None, ge=0)
    source_contract_item_id: uuid.UUID | None = None


class SubcontractorContractItemUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=FREE_TEXT_MAX_LENGTH)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)


class SubcontractorContractItemGroup(BaseModel):
    """Grup başlığı `source_contract_item_id` → `employer_contract_items.group_id`
    üzerinden TÜRER; ayrı grup tablosu açılmaz (spec §3.6)."""

    id: uuid.UUID
    name: str


class SubcontractorContractItemResponse(BaseModel):
    """`FORM`/`TSD` kalem satırı. `line_total` türevdir, saklanmaz — `unit_price`
    NULL olan satır toplama 0 katkı verir (spec §3.6)."""

    id: uuid.UUID
    contract_id: uuid.UUID
    source_contract_item_id: uuid.UUID | None
    code: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal | None
    sort_order: int
    # Bağsız kalemler `group: null` ile döner (spec §3.6).
    group: SubcontractorContractItemGroup | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_total(self) -> Decimal:
        if self.unit_price is None:
            return Decimal("0")
        return _quantize_money(self.quantity * self.unit_price)


class SubcontractorContractItemsLoadResponse(BaseModel):
    """`POST .../items/load-from-employer` yanıtı (spec §6.5) — idempotent

    kopyalamanın kaç kalem yazdığını/atladığını bildirir.
    """

    created_count: int
    skipped_count: int


# --- Taşeron sözleşmesi (spec §3.5) ---


class SubcontractorContractCreate(BaseModel):
    """`FORM` gövdesi. Kalemler İÇ İÇE ve atomik gönderilebilir (spec §6.5,
    `sites` + bölümler deseninin aynısı)."""

    site_id: uuid.UUID | None = None
    subcontractor_id: uuid.UUID | None = None
    work_category: str | None = Field(default=None, max_length=100)
    contract_no: str | None = Field(default=None, max_length=100)
    signature_date: date | None = None
    is_notarized: bool = False
    start_date: date | None = None
    end_date: date | None = None
    late_penalty_daily: Decimal | None = Field(default=None, ge=0)
    advance_pct: Decimal = Field(default=Decimal("10"), ge=0, le=100)
    retainage_pct: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    # Taşeron hakedişi spec §8 S1: hakediş oluşturmada snapshot'lanır.
    vat_pct: RequiredVatRate = Decimal("20")
    payment_period: PaymentPeriod = PaymentPeriod.monthly
    payment_term_days: int = Field(default=30, ge=0)
    materials_by_contractor: bool = False
    subcontractor_files_own_sgk: bool = False
    vat_withholding: bool = False
    status: ContractStatus = ContractStatus.active
    is_draft: bool = False
    items: list[SubcontractorContractItemCreate] = Field(default_factory=list)


class SubcontractorContractUpdate(BaseModel):
    """`project_id` YOK — sözleşme başka projeye taşınamaz. `items` YOK — kalemler
    ayrı uçlarla yönetilir (spec §6.5). Tüm alanlar isteğe bağlı (kısmi PATCH)."""

    site_id: uuid.UUID | None = None
    subcontractor_id: uuid.UUID | None = None
    work_category: str | None = Field(default=None, max_length=100)
    contract_no: str | None = Field(default=None, max_length=100)
    signature_date: date | None = None
    is_notarized: bool | None = None
    start_date: date | None = None
    end_date: date | None = None
    late_penalty_daily: Decimal | None = Field(default=None, ge=0)
    advance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    retainage_pct: Decimal | None = Field(default=None, ge=0, le=100)
    vat_pct: VatRate = None
    payment_period: PaymentPeriod | None = None
    payment_term_days: int | None = Field(default=None, ge=0)
    materials_by_contractor: bool | None = None
    subcontractor_files_own_sgk: bool | None = None
    vat_withholding: bool | None = None
    status: ContractStatus | None = None
    is_draft: bool | None = None


class SubcontractorContractDetail(BaseModel):
    """`TSD` başlığı + bağlantı zinciri + kalemler + türev toplam (spec §6.5).

    Kapsam dışı (spec §2.2): hakediş özeti (P7), belgeler (kalıcı karar 8) —
    burada AÇIKÇA `None` döner.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None
    subcontractor_id: uuid.UUID | None
    subcontractor_name: str | None
    work_category: str | None
    contract_no: str | None
    signature_date: date | None
    is_notarized: bool
    start_date: date | None
    end_date: date | None
    late_penalty_daily: Decimal | None
    advance_pct: Decimal
    retainage_pct: Decimal
    vat_pct: Decimal
    payment_period: PaymentPeriod
    payment_term_days: int
    materials_by_contractor: bool
    subcontractor_files_own_sgk: bool
    vat_withholding: bool
    status: ContractStatus
    is_draft: bool
    items: list[SubcontractorContractItemResponse]
    contract_total: Decimal
    items_missing_price: int
    progress_payment_summary: None = None
    documents: None = None
    pending_modules: list[str] = Field(
        default_factory=lambda: ["subcontractor_progress_payments", "documents"]
    )
    """⚠️ Buradaki yer tutucu **TAŞERON** hakedişidir, işveren hakedişi DEĞİL —
    P7 yalnız işveren tarafını yazdı. Anahtar bu yüzden spec §1.2'nin adıyla
    (`subcontractor_progress_payments`) YENİDEN ADLANDIRILDI; listeden
    ÇIKARILMADI: taşeron hakedişi hâlâ ayrı ve yazılmamış bir dilimdir."""


# --- Taşeron sözleşmesi seçim listesi (TB2 U1) ---


class SubcontractorContractListItem(BaseModel):
    """`GET /subcontractor-contracts` satırı — hakediş açma akışının seçim adımı.

    Bilinçli olarak DAR: bedel/hakediş türevleri TAŞIMAZ (onlar birleşik
    `/contracts?type=subcontractor` ucunun işidir). Proje/şantiye adları
    JOIN'den gelir (`repository.list_subcontractor_contract_rows`), satır başına
    ek sorgu YOKTUR.
    """

    id: uuid.UUID
    contract_no: str | None
    subcontractor_name: str | None
    work_category: str | None
    project_id: uuid.UUID
    project_name: str
    site_id: uuid.UUID | None
    site_name: str | None
    """`site_id` NULL ise (proje geneli sözleşme, K4) ad da NULL'dır."""
    status: ContractStatus
    is_draft: bool


class SubcontractorContractListResponse(BaseModel):
    """TB3 T2: `subcontractor_progress_payments` liste deseninin aynısı —

    `items` + `total`/`limit`/`offset`. Alanlar ADDITIVE: öğe gövdesi TB2'deki
    hâliyle birebir aynıdır, mevcut tüketici (F-TH seçim adımı) kırılmaz.
    """

    items: list[SubcontractorContractListItem]
    total: int
    limit: int
    offset: int
