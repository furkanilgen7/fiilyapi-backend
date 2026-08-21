"""İşveren hakedişi (P7) Pydantic şemaları — okuma/yazma ayrı, `contracts`/`sites`
deseni.

Alan sınırları modeldeki kolon tipleriyle BİREBİR aynıdır (spec §4.1/§4.2):
`description` sınırsız `Text` (form kısıtlamaz); yanıt tarafındaki snapshot
alanları (`code`/`unit`/`group_name`) modeldeki `String(N)` uzunluklarını taşır
— frontend `maxLength`'i buradan okur (spec §10/6).

Pydantic'te duran ve `guards.py`'de TEKRARLANMAYAN kurallar (spec §4.1/§4.2):
satır `quantity >= 0` (OLU 172: 0 meşru — P5 dağılımının aksine), `coefficient
> 0`, `period_month` 1-12 aralığı. `guards.py` yalnız `submit` zorunluluk
kurallarını (§7) ve DB erişimi gereken tutarlılık kurallarının (§6.5) METİN
sabitlerini taşır.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.progress_payments.models import ProgressPaymentStatus

# Enum PAYLAŞILIR (models.py'deki aynı gerekçe): iki hakediş ailesi AYNI rozeti
# aynı tiple yayımlar — S4 simetrisi tip düzeyinde de geçerlidir.
from app.modules.subcontractor_progress_payments.models import QuantitySource

__all__ = [
    "PaymentCalculationBlock",
    "ProgressBlock",
    "ProgressPaymentCreate",
    "ProgressPaymentDetail",
    "ProgressPaymentGroupSummary",
    "ProgressPaymentLineDetail",
    "ProgressPaymentLineInput",
    "ProgressPaymentLinesSave",
    "ProgressPaymentListItem",
    "ProgressPaymentListResponse",
    "ProgressPaymentStatusLiteral",
    "ProgressPaymentSummary",
    "ProgressPaymentUpdate",
    "RefreshPricesResponse",
    "RejectBody",
]

ProgressPaymentStatusLiteral = Literal["draft", "pending_approval", "approved", "paid"]


# --- Yazma şemaları (spec §9.2) ---


class ProgressPaymentLineInput(BaseModel):
    """`PUT …/lines` gövdesindeki tek satır (spec §9.2) — hem POST'un iç içe
    `lines[]`'ında hem `PUT …/lines`'ta kullanılır.

    `quantity >= 0`: OLU 172 `value="0"` kanıtıyla 0 meşru — P5 dağılımının
    "boş hücre `null`, `0` 422" kuralı hakedişe TAŞINMAZ (spec §10/3).
    `coefficient` gönderilmezse `None` kalır: servis katmanı yeni satıra
    hakedişin `default_coefficient`'ını uygular (§4.1), var olan satırın
    katsayısını DEĞİŞTİRMEZ.
    """

    contract_item_id: uuid.UUID
    site_id: uuid.UUID
    quantity: Decimal = Field(ge=0)
    coefficient: Decimal | None = Field(default=None, gt=0)


class ProgressPaymentLinesSave(BaseModel):
    """`PUT …/lines` gövdesi — DEĞİŞTİRME semantiği (spec §9.2/§10-2): gövdede
    olmayan satır SİLİNİR. Boş liste = hakedişin tüm satırlarını temizle."""

    lines: list[ProgressPaymentLineInput] = Field(default_factory=list)


class ProgressPaymentCreate(BaseModel):
    """`POST /projects/{project_id}/progress-payments` gövdesi (spec §9.2).

    Tüm alanlar isteğe bağlıdır (kalıcı karar 4: taslak boş gövdeyle açılabilir,
    `sequence_no`/`status`/snapshot yüzdeler sunucu üretir). Satırlar iç içe ve
    atomik gönderilebilir (`contracts`/`sites` deseninin aynısı).
    """

    period_year: int | None = None
    period_month: int | None = Field(default=None, ge=1, le=12)
    description: str | None = None
    default_coefficient: Decimal | None = Field(default=None, gt=0)
    lines: list[ProgressPaymentLineInput] | None = None


class ProgressPaymentUpdate(BaseModel):
    """`PATCH /progress-payments/{id}` gövdesi — yalnız başlık alanları (spec §9.2).

    `status`/`sequence_no`/satırlar YOK: durum yalnız geçiş uçlarıyla (H6),
    satırlar yalnız `PUT …/lines` (H5) ile değişir. Servis `status != draft`
    ise 409 `INVALID_STATUS_TRANSITION` döner (kural burada TEKRARLANMAZ).
    """

    period_year: int | None = None
    period_month: int | None = Field(default=None, ge=1, le=12)
    description: str | None = None
    default_coefficient: Decimal | None = Field(default=None, gt=0)


class RejectBody(BaseModel):
    """`POST …/reject` gövdesi — 🔴 **OK-1A K2 ile KIRICI biçimde değişti.**

    ## Ne değişti, ne DEĞİŞMEDİ

    * **DEĞİŞTİ:** gerekçe artık ZORUNLUDUR (`str`, `| None` DEĞİL) ve gövdenin
      kendisi de zorunludur. Eski hâli K12'nin ("mockup'ta ret formu yok")
      çıkarımıydı; kullanıcı 2026-08-21'de K2'yi bağladı ve o çıkarımın YERİNE
      GEÇTİ: "Ret gerekçesi ZORUNLU metindir (boş geçilemez)."
    * **DEĞİŞMEDİ:** gerekçenin DEPOLANDIĞI yer. Bu ailede `rejection_reason`
      KOLONU YOKTUR ve AÇILMADI (K2 "zorunlu metin" der, "kolon" demez);
      tek kalıcı iz yine denetim günlüğüdür. Taşeron ailesi kolonu KORUR —
      asimetri bilinçlidir, çünkü orada gerekçe L177 "Revize Gerekli"
      rozetinin ekranda gösterilen açıklamasıdır.

    Boş/yalnız boşluktan oluşan metnin reddi `min_length` ile YAPILMAZ ("   "
    üç karakterdir): kırpma kuralı TEK kopya
    `approvals.service.clean_reject_reason`tadır ve üç evrak ailesi de aynı
    huniden geçer.

    `max_length=500` KORUNDU (H10 denetimi Y3, spec §10/6) ve motorun
    `FREE_TEXT_MAX_LENGTH` tavanına yükseltilmedi: kardeş uç
    (`SubcontractorRejectBody`) da 500'dür ve aynı ekran ailesinde iki farklı
    sınır göstermek kullanıcıya açıklanamaz. Motorun tavanı DIŞ sınır olarak
    yerinde durur.
    """

    reason: str = Field(max_length=500)


# --- Okuma şemaları: liste (spec §9.1) ---


class ProgressPaymentListItem(BaseModel):
    """`GET /progress-payments` satırı (SHK 93-113)."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    sequence_no: int
    period_year: int | None
    period_month: int | None
    description: str | None
    status: ProgressPaymentStatus
    gross_total: Decimal
    net_total: Decimal


class ProgressPaymentListResponse(BaseModel):
    items: list[ProgressPaymentListItem]


# --- Okuma şemaları: detay (spec §9.1, §6.6, §8) ---


class ProgressPaymentLineDetail(BaseModel):
    """E15 96-141 satırı + OLU'nun düzenlenebilir alanları. Türev alanlar
    (`adjusted_unit_price`/`line_total`/`previous_*`/`cumulative_*`) saklanmaz,
    her okuyuşta H2 `calculations` fonksiyonlarıyla hesaplanır (spec §4.2, §6.6).

    `is_price_stale`: `contract_unit_price != kalem.unit_price` iken `True`;
    bağ (`contract_item_id`) koptuysa `None` (spec §5.1 — kalem silinmiş,
    kıyaslanacak canlı fiyat yok).
    """

    id: uuid.UUID
    contract_item_id: uuid.UUID | None
    site_id: uuid.UUID
    code: str = Field(max_length=50)
    description: str
    unit: str = Field(max_length=50)
    contract_unit_price: Decimal
    coefficient: Decimal
    quantity: Decimal
    group_name: str | None = Field(max_length=200)
    sort_order: int
    quantity_source: QuantitySource
    """E15 "Günlük kayıttan" rozetinin kaynağı — SUNUCU damgası, istekten ASLA
    alınmaz (TB4 T1). Taşeron ikizi `SubcontractorProgressPaymentLineRead` ile
    aynı tip ve aynı zorunluluk düzeyindedir (S4 simetrisi)."""
    adjusted_unit_price: Decimal
    line_total: Decimal
    previous_quantity: Decimal
    previous_amount: Decimal
    cumulative_quantity: Decimal
    cumulative_amount: Decimal
    is_price_stale: bool | None


class ProgressPaymentGroupSummary(BaseModel):
    """E15 96-141 grup toplulaştırması (`group_name` üzerinden, spec §6.6)."""

    group_name: str | None
    previous_amount: Decimal
    this_amount: Decimal
    cumulative_amount: Decimal
    contract_amount: Decimal


class PaymentCalculationBlock(BaseModel):
    """E15 151-172 / OLU 179-196 ödeme hesabı (spec §6.2-§6.4) — H2
    `calculations` fonksiyonlarının çıktısı, saklanmaz."""

    gross: Decimal
    vat: Decimal
    advance_deduction: Decimal
    retention: Decimal
    net: Decimal


class ProgressBlock(BaseModel):
    """E15 177-190 sözleşme ilerlemesi (spec §8). Eksik veri → `None` (zarif düşüş)."""

    financial_pct: Decimal | None
    physical_pct: Decimal | None
    duration_pct: Decimal | None


class ProgressPaymentDetail(BaseModel):
    """`GET /progress-payments/{id}` yanıtı — E15 ekranının tamamı (spec §9.1)."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    sequence_no: int
    period_year: int | None
    period_month: int | None
    description: str | None
    status: ProgressPaymentStatus
    vat_pct: Decimal
    advance_pct: Decimal
    retainage_pct: Decimal
    default_coefficient: Decimal
    submitted_at: datetime | None
    approved_at: datetime | None
    approved_by: uuid.UUID | None
    paid_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    lines: list[ProgressPaymentLineDetail]
    groups: list[ProgressPaymentGroupSummary]
    calculation: PaymentCalculationBlock
    progress: ProgressBlock
    dropped_orphan_count: int = 0
    """`PUT …/lines` yanıtında: kalemi silindiği için (`contract_item_id IS NULL`)
    gövdeden adreslenemeyen ve bu kaydetmede DÜŞEN satır sayısı (spec §10/7 —
    zarif düşüş + bildirim, sessiz atlama YOK). Okuma uçlarında (`GET`, `POST`,
    `PATCH`) her zaman `0`'dır: orada düşen satır kavramı yoktur."""


# --- Fiyat tazeleme (spec §9.3) ---


class RefreshPricesResponse(BaseModel):
    refreshed_count: int


# --- Özet (spec §9.6) ---


class ProgressPaymentSummary(BaseModel):
    """`GET /projects/{project_id}/progress-payments/summary` yanıtı (E14
    sekmesi + SHK kartları, spec §9.6). Eksik sözleşme bedeli → `progress_pct`/
    `remaining` `None` (zarif düşüş, §8 deseninin aynısı)."""

    contract_amount: Decimal | None
    cumulative_gross: Decimal
    progress_pct: Decimal | None
    advance_deduction_total: Decimal
    retention_total: Decimal
    net_total: Decimal
    payment_count: int
    pending_count: int
    remaining: Decimal | None
