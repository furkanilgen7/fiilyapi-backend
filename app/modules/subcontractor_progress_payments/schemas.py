"""Taşeron hakedişi Pydantic şemaları (T2) — okuma/yazma ayrı.

Alan sınırları modeldeki kolon tipleriyle BİREBİR (spec §2): snapshot alanları
`code`/`unit`/`group_name` modeldeki `String(N)` uzunluklarını taşır, `description`
sınırsız `Text`tir.

Hesap blokları (brüt/KDV/avans/teminat/net) BU DİLİMDE YOKTUR — T3'te
`progress_payments.calculations` yeniden kullanılarak eklenecektir.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.subcontractor_progress_payments.models import (
    QuantitySource,
    SubcontractorPaymentStatus,
)

__all__ = [
    "SubcontractorProgressPaymentCreate",
    "SubcontractorProgressPaymentDetail",
    "SubcontractorProgressPaymentLineRead",
    "SubcontractorProgressPaymentListItem",
    "SubcontractorProgressPaymentListResponse",
    "SubcontractorProgressPaymentUpdate",
]


# --- Yazma şemaları ---


class SubcontractorProgressPaymentCreate(BaseModel):
    """`POST /subcontractor-contracts/{id}/progress-payments` gövdesi.

    `lines[]` YOKTUR (işveren şemasından ayrılan nokta): satırlar sözleşme
    kalemlerinden OTOMATİK yüklenir (O66) ve miktarlar `PUT …/lines` ile
    girilir (T3). Tüm alanlar isteğe bağlıdır — taslak boş gövdeyle açılır.
    """

    period_year: int | None = None
    period_month: int | None = Field(default=None, ge=1, le=12)
    description: str | None = None
    default_coefficient: Decimal | None = Field(default=None, gt=0)
    section_id: uuid.UUID | None = None
    """O58 "Bölüm" seçici — bilgi alanı (spec §8 S2). NULL = "Tüm Bölümler";
    kota/hesaba GİRMEZ, salt etiket/filtredir."""


class SubcontractorProgressPaymentUpdate(BaseModel):
    """`PATCH /subcontractor-progress-payments/{id}` — yalnız başlık alanları.

    `status`/`sequence_no`/satırlar YOK: durum yalnız geçiş uçlarıyla (T4),
    satırlar yalnız `PUT …/lines` (T3) ile değişir. Servis `status != draft`
    ise 409 döner (kural burada TEKRARLANMAZ).
    """

    period_year: int | None = None
    period_month: int | None = Field(default=None, ge=1, le=12)
    description: str | None = None
    default_coefficient: Decimal | None = Field(default=None, gt=0)
    section_id: uuid.UUID | None = None


# --- Okuma şemaları ---


class SubcontractorProgressPaymentLineRead(BaseModel):
    """O72-100 satırı. Şantiye kırılımı YOKTUR — taşeron sözleşmesi zaten tek
    şantiyeye (ya da proje geneline) bağlıdır (spec §2)."""

    id: uuid.UUID
    contract_item_id: uuid.UUID | None
    code: str = Field(max_length=50)
    description: str
    unit: str = Field(max_length=50)
    contract_unit_price: Decimal
    coefficient: Decimal
    quantity: Decimal
    group_name: str | None = Field(default=None, max_length=200)
    sort_order: int
    quantity_source: QuantitySource
    """O87 "Günlük kayıttan" rozetinin kaynağı; `site_diary` dilimi gelene kadar
    HER satır `manual`dır (spec §2)."""


class SubcontractorProgressPaymentListItem(BaseModel):
    """L112-180 liste satırı. Tutar kolonları T3'te (hesap dilimi) eklenecek."""

    id: uuid.UUID
    contract_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    subcontractor_name: str | None
    contract_no: str | None
    sequence_no: int
    period_year: int | None
    period_month: int | None
    description: str | None
    status: SubcontractorPaymentStatus
    section_id: uuid.UUID | None
    created_at: datetime


class SubcontractorProgressPaymentListResponse(BaseModel):
    """`audit`/`users` liste deseninin aynısı: `total` + `limit`/`offset`."""

    items: list[SubcontractorProgressPaymentListItem]
    total: int
    limit: int
    offset: int


class SubcontractorProgressPaymentDetail(BaseModel):
    """`GET /subcontractor-progress-payments/{id}` — O ekranının başlığı + satırları."""

    id: uuid.UUID
    contract_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    subcontractor_name: str | None
    contract_no: str | None
    sequence_no: int
    period_year: int | None
    period_month: int | None
    description: str | None
    status: SubcontractorPaymentStatus
    vat_pct: Decimal
    advance_pct: Decimal
    retainage_pct: Decimal
    default_coefficient: Decimal
    section_id: uuid.UUID | None
    submitted_at: datetime | None
    approved_at: datetime | None
    approved_by: uuid.UUID | None
    paid_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    lines: list[SubcontractorProgressPaymentLineRead]
