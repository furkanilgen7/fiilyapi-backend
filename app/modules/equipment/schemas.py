"""Ekipman kartı şemaları (MK-1 spec §2.1, §4) — T1 iskeleti.

`inventory`/`personnel` üçlüsünün (Create/Update/Response) kardeşi.

## Bu dosyada NE YOK — ve niçin

* **Yakıt kaydı yazma şemaları YOKTUR** (T5).
* **Türev alanlar KART gövdesinde YOKTUR:** kullanım %, maliyet, sapma, tüketim
  rozeti ve toplamlar KOLON DEĞİL TÜREVDİR (K15/K16/K17/K18); özet uçlarının
  şemalarındadır, `EquipmentResponse`a sızmaz.
* **Belge slotu / kira hakedişi alanı YOKTUR:** MK-2'ye devredildi (spec §9).

## 🔴 K11 niçin ŞEMADA değil SERVİSTE denetlenir

`hours`ın sunucu hesabı olduğu kuralı `WorkLogCreate`in bir `model_validator`ına
konsaydı PATCH'te İKİNCİ KEZ yazılmak zorunda kalırdı: kısmi güncellemede kural
gövdeye DEĞİL, gövde ile DB'deki satırın BİRLEŞİMİNE bakar (yalnız `start_time`
gönderen bir PATCH'in `end_time`ı satırdan gelir). İki kopya, biri
güncellenmediğinde POST'ta yasak olanı PATCH'ten geçirirdi. Kural bu yüzden
`service._resolve_hours`ta TEK yerdedir ve K2 ile aynı emsali izler (koşullu
kural DB CHECK'i de şema kuralı da olamaz). Sonuç yine **422**'dir —
`EquipmentValidationError` üzerinden, üstelik Türkçe bir cümleyle.

## Uzunluk tavanları kolon sınırlarıyla BİREBİRDİR

`app.core.text.FREE_TEXT_MAX_LENGTH` yalnız kolonu `Text` olan alanlar içindir
(`status_note`); `String(N)` alanların tavanı N'dir — gevşetilseydi kullanıcı
422 yerine anlaşılmaz bir DB hatası alırdı.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.text import FREE_TEXT_MAX_LENGTH
from app.modules.equipment.consumption import UsageReason
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
    WorkLogType,
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


# --- Çalışma kaydı (M3 · spec §2.2, §4) ---

# `Numeric(6, 2)` — tek kaydın kendi saati de 24'ü aşamaz (DB CHECK'i de aynısını
# söyler). GÜNLÜK toplam tavanı (K12) bundan AYRIDIR ve serviste kilitle ölçülür.
_HOURS = Field(default=None, ge=0, le=24, max_digits=6, decimal_places=2)
_NOTE = Field(default=None, max_length=FREE_TEXT_MAX_LENGTH)


class WorkLogCreate(BaseModel):
    """`POST /equipment/work-logs` — M3 kaydı.

    🔴 **K11:** `hours` gövdede VARDIR ama YALNIZ aralıksız kayıt içindir
    (M3:283 arıza satırı saat basar, aralık basmaz). `start_time`+`end_time`
    verilmişken `hours` göndermek **422**'dir — sunucu hesabının üzerine
    yazılamaz. Kural `service._resolve_hours`ta tek yerdedir (modül docstring'i).

    `site_id` KAYDIN KENDİ şantiyesidir (K9), ekipmanın bugünkü ataması değil:
    makine taşındığında geçmiş aylar geriye dönük başka projeye yazılmasın.
    """

    equipment_id: uuid.UUID
    work_date: date
    site_id: uuid.UUID | None = None
    # K10: arıza kaydında operatör YOKTUR (M3:280) — zorunlu değildir.
    operator_id: uuid.UUID | None = None
    record_type: WorkLogType = WorkLogType.worked
    start_time: time | None = None
    end_time: time | None = None
    hours: Decimal | None = _HOURS
    note: str | None = _NOTE


class WorkLogUpdate(BaseModel):
    """`PATCH /equipment/work-logs/{id}` — kayıt hatası düzeltilebilir.

    Çalışma kaydı MALİ İZ DEĞİLDİR (maliyet ondan TÜREV): hakediş satırının
    aksine düzeltilir ve silinir.

    Alanın GÖNDERİLMEMESİ ile `null` GÖNDERİLMESİ farklıdır (F-İK "touched"
    dersi) ve fark `model_fields_set` ile korunur — aralığı BOŞALTMANIN yolu
    `{"start_time": null, "end_time": null, "hours": …}`tır.
    """

    equipment_id: uuid.UUID | None = None
    work_date: date | None = None
    site_id: uuid.UUID | None = None
    operator_id: uuid.UUID | None = None
    record_type: WorkLogType | None = None
    start_time: time | None = None
    end_time: time | None = None
    hours: Decimal | None = _HOURS
    note: str | None = _NOTE


class WorkLogResponse(BaseModel):
    """Kayıt künyesi. `hours` HER ZAMAN doludur ve HER ZAMAN sunucunundur."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_id: uuid.UUID
    work_date: date
    site_id: uuid.UUID | None
    operator_id: uuid.UUID | None
    record_type: WorkLogType
    start_time: time | None
    end_time: time | None
    hours: Decimal
    note: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime


class WorkLogListResponse(BaseModel):
    """TB3 sayfalama kanonu: `limit ≤ 200`, `total` SÜZÜLMÜŞ kümeyi sayar."""

    items: list[WorkLogResponse]
    total: int
    limit: int
    offset: int


# --- Çalışma özeti (M3 ana tablosu · spec §4) ---


class WorkSummaryRow(BaseModel):
    """M3 tablosunun BİR satırı.

    `cost` ve `usage_pct` AYRI AYRI `null` olabilir (K16): saati bilinen bir
    makinenin bedeli bilinmiyor olabilir. Tek alana sıkıştırılsalardı bilinen
    bir olgu, eksik bir ölçüt yüzünden kaybolurdu.
    """

    equipment_id: uuid.UUID
    equipment_name: str
    site_id: uuid.UUID | None
    hours: Decimal
    usage_pct: Decimal | None
    usage_reason: UsageReason | None
    breakdown_hours: Decimal
    cost: Decimal | None


class WorkSummaryTotals(BaseModel):
    """🔴 K15 — tfoot. **HER ZAMAN satırlardan** toplanır.

    M3'ün kendi tfoot'u (428 saat · ₺124.800 · %69) satırlarıyla TUTARSIZDIR
    (692 · ₺144.200 · %57,7) — mockup'ın aritmetik hatasıdır ve kopyalanmaz
    (TSD `contract_total` TEK KAYNAK emsali, F-P5 K5).

    `cost` bilinmeyen satırı UYDURMA bir 0 ile İÇERMEZ (K16): satır `null`
    kalır, toplam bilinenlerden oluşur. Toplamın kendisi `null` yapılmadı çünkü
    tek bilinmeyen makine yüzünden bütün tabloyu gizlemek kullanıcıyı ekranın
    tamamından ederdi.
    """

    hours: Decimal
    breakdown_hours: Decimal
    cost: Decimal
    usage_pct_avg: Decimal | None


class WorkSummaryWeek(BaseModel):
    """M3:219-243 haftalık kovası.

    `dominant_record_type` SUNUCU DAMGASIDIR (F-P10 kanonu): barın rengini
    istemci kendi eşiğiyle seçseydi iki ekran aynı haftayı farklı boyardı.
    Kayıtsız haftada `null`dur — uydurma bir "çalışıyor" damgası basılmaz.
    """

    index: int
    start_date: date
    end_date: date
    hours: Decimal
    dominant_record_type: WorkLogType | None


class WorkSummaryResponse(BaseModel):
    """`GET /equipment/work-summary` — M3'ün TAMAMI (tablo + tfoot + mini grafik)."""

    year: int
    month: int
    rows: list[WorkSummaryRow]
    totals: WorkSummaryTotals
    weeks: list[WorkSummaryWeek]
