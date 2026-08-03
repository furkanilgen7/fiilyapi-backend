"""Şantiye günlüğü Pydantic şemaları (T2) — okuma/yazma ayrı.

Alan sınırları modeldeki kolon tipleriyle BİREBİR (spec §2): `code`/`unit`
`String(50)`, `trade` `String(100)`, `description`/`work_done` sınırsız `Text`.

Türevler (satır ₺ katkısı, satır toplamı, işçi toplamı) yalnız OKUMA şemalarında
yaşar — kolon açılmaz (spec §2).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.site_diary.models import DiaryStatus, Weather, WorkerSource

__all__ = [
    "SiteDiaryEntryCreate",
    "SiteDiaryEntryDetail",
    "SiteDiaryEntryListItem",
    "SiteDiaryEntryListResponse",
    "SiteDiaryEntryUpdate",
    "SiteDiaryLineRead",
    "SiteDiaryWorkerCountRead",
]

# `ck_site_diary_entries_temperature_range` ile BİREBİR: DB CHECK'i son savunmadır
# ama kullanıcıya "Veri bütünlüğü hatası" der; alan hatası burada yakalanınca 422
# gövdesi hangi alanın yanlış olduğunu söyler.
_TEMP_MIN = Decimal("-60")
_TEMP_MAX = Decimal("60")


# --- Yazma şemaları ---


class SiteDiaryEntryCreate(BaseModel):
    """`POST /sites/{site_id}/diary` gövdesi.

    `lines[]` YOKTUR (bilinçli): satır iskeleti şantiyenin BOQ pozlarından
    OTOMATİK üretilir — GK'de satır ekle/sil yoktur, liste BOQ'dan gelir.
    Miktar girişi `PUT …/lines` ile yapılır (T3).

    `worker_counts[]` de YOKTUR: işçi kırılımının yazma semantiği T3'ündür.

    `status` YOKTUR: kayıt her zaman `draft` doğar, `submit` ucu (T4) gönderir.

    `entry_date` DIŞINDA her alan isteğe bağlıdır — taslak yarım doldurulabilir,
    zorunluluk kuralları `submit` katmanındadır (model docstring'i).
    """

    entry_date: date
    section_id: uuid.UUID | None = None
    weather: Weather | None = None
    temperature_c: Decimal | None = Field(default=None, ge=_TEMP_MIN, le=_TEMP_MAX)
    work_done: str | None = None
    chief_note: str | None = None
    safety_meeting_held: bool = False
    ppe_checked: bool = False
    has_incident: bool = False
    incident_note: str | None = None


class SiteDiaryEntryUpdate(BaseModel):
    """`PATCH /diary/{entry_id}` — yalnız BAŞLIK alanları, yalnız `draft` kayıtta.

    `status` alanı YOKTUR: durum yalnız geçiş uçlarıyla (T4) değişir; gövdeden
    kabul edilseydi `submit`in damgası ve doğrulamaları atlanabilirdi. Gövdeye
    yazılan bilinmeyen alan `extra="forbid"` ile 422'dir — sessizce yutulup
    "güncelledim" demek, kullanıcıya yalan söylemektir.

    `entry_date` DEĞİŞTİRİLEBİLİR (yanlış güne açılmış kayıt düzeltilebilsin);
    hedef gün doluysa servis 409 döner.
    """

    model_config = {"extra": "forbid"}

    entry_date: date | None = None
    section_id: uuid.UUID | None = None
    weather: Weather | None = None
    temperature_c: Decimal | None = Field(default=None, ge=_TEMP_MIN, le=_TEMP_MAX)
    work_done: str | None = None
    chief_note: str | None = None
    safety_meeting_held: bool | None = None
    ppe_checked: bool | None = None
    has_incident: bool | None = None
    incident_note: str | None = None


# --- Okuma şemaları ---


class SiteDiaryLineRead(BaseModel):
    """GK212-230 satırı — poz snapshot'ı + o günkü miktar.

    Kümülatif miktar (GK229) bu dilimde YOKTUR: aylık toplamlar `summary` ucunun
    (T4) işidir ve tek bir günün detayında kümülatif göstermek, iki farklı
    kaynaktan iki farklı sayı üretme riskidir.
    """

    id: uuid.UUID
    boq_item_id: uuid.UUID | None
    code: str = Field(max_length=50)
    description: str
    unit: str = Field(max_length=50)
    unit_price: Decimal
    quantity: Decimal
    line_amount: Decimal
    """GK230 ₺ katkısı = `quantity × unit_price`, KATSAYISIZ (spec §2): fiyat
    farkı katsayısı hakediş katmanının işidir, günlüğün değil. TÜREV — kolon yok."""


class SiteDiaryWorkerCountRead(BaseModel):
    """GK418-430 işçi kırılımı satırı. Yazma semantiği T3'tedir."""

    id: uuid.UUID
    trade: str = Field(max_length=100)
    source: WorkerSource
    count: int


class SiteDiaryEntryListItem(BaseModel):
    """GK "Son Kayıtlar" satırı — durum + işçi toplamı + satır ₺ toplamı.

    Üç alanın da kolonu YOKTUR (spec §2); listede taşınmalarının nedeni ekranın
    kayıt başına ayrı bir detay isteği atmak zorunda kalmamasıdır.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    project_id: uuid.UUID
    entry_date: date
    section_id: uuid.UUID | None
    weather: Weather | None
    has_incident: bool
    status: DiaryStatus
    worker_total: int
    lines_total: Decimal
    created_by: uuid.UUID
    created_at: datetime


class SiteDiaryEntryListResponse(BaseModel):
    """`audit`/`users` liste deseninin aynısı: `total` + `limit`/`offset`."""

    items: list[SiteDiaryEntryListItem]
    total: int
    limit: int
    offset: int


class SiteDiaryEntryDetail(BaseModel):
    """`GET /diary/{entry_id}` — GK'nin tek gün görünümü."""

    id: uuid.UUID
    site_id: uuid.UUID
    project_id: uuid.UUID
    entry_date: date
    section_id: uuid.UUID | None
    weather: Weather | None
    temperature_c: Decimal | None
    work_done: str | None
    chief_note: str | None
    safety_meeting_held: bool
    ppe_checked: bool
    has_incident: bool
    incident_note: str | None
    status: DiaryStatus
    submitted_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    lines: list[SiteDiaryLineRead]
    worker_counts: list[SiteDiaryWorkerCountRead]
    lines_total: Decimal
    worker_total: int
