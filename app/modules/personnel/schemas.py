"""Personel şemaları — puantaj spec §2, §3 + İK-1 kart genişlemesi (spec §1, §5).

`customers/schemas.py` üçlüsünün (Create/Update/Response) kardeşi. Kaynak/taşeron
uyuşması + TCKN + taslak/yayın zorunluluğu burada DEĞİL `guards.py`/`service.py`de
doğrulanır: PATCH kısmi gövde gönderir, kurallar ancak DB'deki kayıtla
BİRLEŞTİRİLMİŞ değerler üzerinde anlamlıdır.

**İK-1 (spec §1, §5 K3):** yeni kart kolonları eklendi ve HEPSİ Create'te
OPSİYONELdir — zorunluluk taslak-farkındalıklıdır (yayında `service` katmanında
zorlanır). `is_draft` Create'te varsayılan `True` (mockup "Taslak" ile "Personeli
Kaydet" iki ayrı buton; yayın akışı `is_draft=false` gönderir). Foto/vergi no
AÇILMADI (spec §5 K2/K6); belge alt-kaynağı şeması T3'ün işidir.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.personnel.models import Gender, MaritalStatus, PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource


class PersonnelCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    # Meslek SERBEST METİN (spec §7 S5) — katalog tablosu YOK, diary `trade` deseni.
    trade: str | None = Field(default=None, max_length=100)
    source: WorkerSource
    subcontractor_id: uuid.UUID | None = None
    # Login ŞART DEĞİL: işçiler `users` kaydı olmadan da puantaja girer (spec §2).
    user_id: uuid.UUID | None = None
    is_active: bool = True

    # --- İK-1 kart alanları (PE 51-118) — HEPSİ opsiyonel (spec §5 K3) --------
    tc_no: str | None = Field(default=None, max_length=11)
    birth_date: date | None = None
    gender: Gender | None = None
    marital_status: MaritalStatus | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    hire_date: date | None = None
    wage_type: WageType | None = None
    wage_amount: Decimal | None = Field(default=None, ge=0)
    payment_method: PaymentMethod | None = None
    iban: str | None = Field(default=None, max_length=34)
    sgk_no: str | None = Field(default=None, max_length=20)
    assigned_project_id: uuid.UUID | None = None
    assigned_section_id: uuid.UUID | None = None
    # Taslak varsayılan (mockup "Taslak" butonu); yayın akışı açıkça `false` gönderir.
    is_draft: bool = True


class PersonnelUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    trade: str | None = Field(default=None, max_length=100)
    source: WorkerSource | None = None
    subcontractor_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # Pasifleştirme YOLU: DELETE ucu yoktur (spec §3), çıkarma bu bayrakla yapılır.
    is_active: bool | None = None

    # --- İK-1 kart alanları — kısmi gönderim (spec §5 K3) --------------------
    tc_no: str | None = Field(default=None, max_length=11)
    birth_date: date | None = None
    gender: Gender | None = None
    marital_status: MaritalStatus | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    hire_date: date | None = None
    wage_type: WageType | None = None
    wage_amount: Decimal | None = Field(default=None, ge=0)
    payment_method: PaymentMethod | None = None
    iban: str | None = Field(default=None, max_length=34)
    sgk_no: str | None = Field(default=None, max_length=20)
    assigned_project_id: uuid.UUID | None = None
    assigned_section_id: uuid.UUID | None = None
    is_draft: bool | None = None


class PersonnelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    trade: str | None
    source: WorkerSource
    subcontractor_id: uuid.UUID | None
    user_id: uuid.UUID | None
    is_active: bool

    # --- İK-1 kart alanları ---------------------------------------------------
    tc_no: str | None
    birth_date: date | None
    gender: Gender | None
    marital_status: MaritalStatus | None
    phone: str | None
    email: str | None
    address: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    hire_date: date | None
    wage_type: WageType | None
    wage_amount: Decimal | None
    payment_method: PaymentMethod | None
    iban: str | None
    sgk_no: str | None
    assigned_project_id: uuid.UUID | None
    assigned_section_id: uuid.UUID | None
    is_draft: bool


class PersonnelListResponse(BaseModel):
    """`audit`/`users` liste deseninin aynısı: `total` + `limit`/`offset`."""

    items: list[PersonnelResponse]
    total: int
    limit: int
    offset: int
