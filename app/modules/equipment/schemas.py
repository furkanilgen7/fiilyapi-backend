"""Ekipman kartı şemaları (MK-1 spec §2.1, §4) — T1 iskeleti.

`inventory`/`personnel` üçlüsünün (Create/Update/Response) kardeşi.

## Bu dosyada NE YOK — ve niçin

* **Çalışma ve yakıt kaydı yazma şemaları YOKTUR** (T3/T4). Onların gövdesi
  K11'in sunucu hesabına bağlıdır (`hours` istemciden GELMEZ) ve şemayı
  uçlarından önce yazmak, o kuralı iki yerde tarif etme riski taşır.
* **Türev alanlar YOKTUR:** kullanım %, maliyet, sapma, tüketim rozeti ve
  toplamlar KOLON DEĞİL TÜREVDİR (K15/K16/K17/K18); özet uçlarının
  şemalarındadır, kart gövdesine sızmaz.
* **Belge slotu / kira hakedişi alanı YOKTUR:** MK-2'ye devredildi (spec §9).

## Uzunluk tavanları kolon sınırlarıyla BİREBİRDİR

`app.core.text.FREE_TEXT_MAX_LENGTH` yalnız kolonu `Text` olan alanlar içindir
(`status_note`); `String(N)` alanların tavanı N'dir — gevşetilseydi kullanıcı
422 yerine anlaşılmaz bir DB hatası alırdı.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.equipment.models import (
    DEFAULT_MONTHLY_CAPACITY_HOURS,
    EquipmentCategory,
    EquipmentFinancing,
    EquipmentFuelType,
    EquipmentMaintenancePeriod,
    EquipmentNormUnit,
    EquipmentOwnership,
    EquipmentRatePeriod,
    EquipmentStatus,
)

# Model `String(200)`/`String(100)`/`String(30)` — şema ile DB sınırı AYNI.
_NAME = Field(min_length=1, max_length=200)
_SHORT_TEXT = Field(default=None, max_length=100)
_PLATE = Field(default=None, max_length=30)
_STATUS_NOTE = Field(default=None, max_length=FREE_TEXT_MAX_LENGTH)

# Para alanları `Numeric(18, 2)`; negatif bedel hiçbir okumada anlamlı değildir.
_MONEY = Field(default=None, ge=0, max_digits=18, decimal_places=2)
# K5: norm tüketim SAYIDIR ve pozitiftir — 0 norm, sapma hesabını sıfıra bölerdi.
_NORM = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class EquipmentCreate(BaseModel):
    """`POST /equipment` — M2 formunun gövdesi.

    `purchase_amount` BURADA isteğe bağlıdır ve bu bir eksiklik DEĞİLDİR (K2):
    kural `ownership == owned` iken zorunluluk şeklindedir ve SERVİStedir (422).
    Şemaya konsaydı kiralık makine hiç kaydedilemezdi.
    """

    name: str = _NAME
    category: EquipmentCategory
    brand: str | None = _SHORT_TEXT
    model: str | None = _SHORT_TEXT
    serial_no: str | None = _SHORT_TEXT
    plate_no: str | None = _PLATE
    model_year: int | None = Field(default=None, ge=1900, le=2200)
    ownership: EquipmentOwnership = EquipmentOwnership.owned
    purchase_amount: Decimal | None = _MONEY
    purchase_date: date | None = None
    depreciation_years: int | None = Field(default=None, gt=0, le=100)
    supplier_id: uuid.UUID | None = None
    financing: EquipmentFinancing | None = None
    market_value: Decimal | None = _MONEY
    rate_amount: Decimal | None = _MONEY
    rate_period: EquipmentRatePeriod | None = None
    # K4: NULL = "Depoda (Atanmadı)". `warehouse_id` YOKTUR — bilinçli.
    site_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    status: EquipmentStatus = EquipmentStatus.working
    status_note: str | None = _STATUS_NOTE
    status_expected_date: date | None = None
    fuel_type: EquipmentFuelType | None = None
    norm_consumption: Decimal | None = _NORM
    norm_unit: EquipmentNormUnit | None = None
    maintenance_period: EquipmentMaintenancePeriod | None = None
    # K7: VERİDİR. 0 verilebilir (kullanım % `null` döner, K16) ama negatif olamaz.
    monthly_capacity_hours: int = Field(default=DEFAULT_MONTHLY_CAPACITY_HOURS, ge=0)
    # K8: yalnız bir işaret; hiçbir yan etki tetiklemez.
    is_company_asset: bool = True
    is_active: bool = True


class EquipmentUpdate(BaseModel):
    """`PATCH /equipment/{id}` — TÜM alanlar isteğe bağlı.

    Alanın GÖNDERİLMEMESİ ile `null` GÖNDERİLMESİ farklıdır ve fark
    `model_fields_set` ile korunur (F-İK dersi: dokunulmamış bir seçici
    sunucudaki değeri EZMEMELİDİR).

    Kullanımdan kaldırma YOLU budur (`is_active: false`) — DELETE ucu yoktur.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: EquipmentCategory | None = None
    brand: str | None = _SHORT_TEXT
    model: str | None = _SHORT_TEXT
    serial_no: str | None = _SHORT_TEXT
    plate_no: str | None = _PLATE
    model_year: int | None = Field(default=None, ge=1900, le=2200)
    ownership: EquipmentOwnership | None = None
    purchase_amount: Decimal | None = _MONEY
    purchase_date: date | None = None
    depreciation_years: int | None = Field(default=None, gt=0, le=100)
    supplier_id: uuid.UUID | None = None
    financing: EquipmentFinancing | None = None
    market_value: Decimal | None = _MONEY
    rate_amount: Decimal | None = _MONEY
    rate_period: EquipmentRatePeriod | None = None
    site_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    status: EquipmentStatus | None = None
    status_note: str | None = _STATUS_NOTE
    status_expected_date: date | None = None
    fuel_type: EquipmentFuelType | None = None
    norm_consumption: Decimal | None = _NORM
    norm_unit: EquipmentNormUnit | None = None
    maintenance_period: EquipmentMaintenancePeriod | None = None
    monthly_capacity_hours: int | None = Field(default=None, ge=0)
    is_company_asset: bool | None = None
    is_active: bool | None = None


class EquipmentResponse(BaseModel):
    """Kart künyesi — M1 kartının veri tabanı.

    **Kullanım % / maliyet / son bakım ALANI YOKTUR:** hepsi çalışma ve yakıt
    kayıtlarından TÜREVDİR (K15/K18) ve özet uçlarından gelir. Buraya konsaydı
    liste her çizilişte hareket tablosunu tarardı.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: EquipmentCategory
    brand: str | None
    model: str | None
    serial_no: str | None
    plate_no: str | None
    model_year: int | None
    ownership: EquipmentOwnership
    purchase_amount: Decimal | None
    purchase_date: date | None
    depreciation_years: int | None
    supplier_id: uuid.UUID | None
    financing: EquipmentFinancing | None
    market_value: Decimal | None
    rate_amount: Decimal | None
    rate_period: EquipmentRatePeriod | None
    site_id: uuid.UUID | None
    operator_id: uuid.UUID | None
    status: EquipmentStatus
    status_note: str | None
    status_expected_date: date | None
    fuel_type: EquipmentFuelType | None
    norm_consumption: Decimal | None
    norm_unit: EquipmentNormUnit | None
    maintenance_period: EquipmentMaintenancePeriod | None
    monthly_capacity_hours: int
    is_company_asset: bool
    is_active: bool
    created_at: datetime


class EquipmentListResponse(BaseModel):
    """`personnel`/`inventory` liste deseni: `total` + `limit`/`offset`
    (TB3 sayfalama kanonu, `limit ≤ 200`)."""

    items: list[EquipmentResponse]
    total: int
    limit: int
    offset: int


class EquipmentSummaryResponse(BaseModel):
    """`GET /equipment/summary` — M1'in dört KPI kartı.

    🔴 **K21:** mockup ÜÇ durum rozeti çiziyor (Çalışıyor/Arızalı/Bakımda) ama
    sunucu DÖRDÜNÜ verir; `idle` basılmazsa sayaçların toplamı filoyu vermez ve
    "sunucu mockup'tan fazla veri verebilir, eksik veremez" kuralı çiğnenirdi.
    Hangisinin ekrana basılacağı frontend dilimin kararıdır.

    `monthly_cost` **cari ayın çalışma maliyeti toplamıdır** ve SATIRLARDAN
    türer (K15) — M1'in ₺124K'sı mockup'ın kendi aritmetik hatasıdır,
    kopyalanmaz. Bedeli bilinmeyen makine toplama uydurma bir `0` ile GİRMEZ
    (K16, gerekçe `service.summarize`).
    """

    model_config = ConfigDict(from_attributes=True)

    working: int
    broken: int
    maintenance: int
    idle: int
    monthly_cost: Decimal
