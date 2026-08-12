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
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.personnel import guards
from app.modules.personnel.models import Gender, MaritalStatus, PaymentMethod, WageType
from app.modules.site_diary.models import WorkerSource

_FREE_LABEL_MAX = 150


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


# --- İK-1 T3: belge alt-kaynağı (spec §2, §3, §5 K5) -----------------------


class PersonnelDocumentCreate(BaseModel):
    """Belge takip kaydı — `type_id` XOR `free_label` (tam biri, spec §2).

    XOR pydantic'te BURADA da doğrulanır (giriş katmanı 422): `model_validator`
    "tam biri" kuralını uygular. Servis (`guards.TYPE_XOR_LABEL`) ile DB CHECK
    ikinci ve üçüncü katlardır — biri düşse öteki tutar (WORKFLOW savunma
    derinliği).

    `document_id` BC arşiv künyesine bağdır (opsiyonel; dosyasız takip meşru,
    spec §2). Görünürlük denetimi SERVİSTEDİR (IDOR) — pydantic yalnız biçime bakar.
    """

    type_id: uuid.UUID | None = None
    free_label: str | None = Field(default=None, max_length=_FREE_LABEL_MAX)
    valid_until: date | None = None
    issued_at: date | None = None
    note: str | None = None
    document_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _type_xor_label(self) -> "PersonnelDocumentCreate":
        has_type = self.type_id is not None
        has_label = bool(self.free_label and self.free_label.strip())
        if has_type == has_label:
            raise ValueError(guards.TYPE_XOR_LABEL)
        return self


class PersonnelDocumentUpdate(BaseModel):
    """Kısmi güncelleme (spec §3). `type_id`/`free_label` DEĞİŞMEZ — belgenin

    KİMLİĞİ (hangi tip/etiket) sabittir; yanlış tiple açılan kayıt silinip yeniden
    açılır. Yalnız künye alanları ve BC bağı güncellenir. `document_id`
    gönderildiğinde görünürlük denetimi serviste yapılır (create ile aynı IDOR
    korkuluğu); `null` göndermek bağı çözer (dosyasız takibe döner) ve meşrudur.

    `exclude_unset` ile "gönderilmedi" ≠ "null gönderildi" ayrımı korunur.
    """

    valid_until: date | None = None
    issued_at: date | None = None
    note: str | None = None
    document_id: uuid.UUID | None = None


class PersonnelDocumentResponse(BaseModel):
    """Belge kaydı + tip künyesi (JOIN'li, N+1 yok) + TÜREV durum (spec §2, §3).

    `status` ve `days_left` kolon DEĞİL, `status.derive_document_status` ile
    hesaplanır (tek kaynak). `type_name`/`is_mandatory`/`validity_months` katalog
    tipinden gelir ve serbest etiketli kayıtta None'dur.
    """

    id: uuid.UUID
    personnel_id: uuid.UUID
    type_id: uuid.UUID | None
    type_name: str | None
    is_mandatory: bool | None
    validity_months: int | None
    free_label: str | None
    document_id: uuid.UUID | None
    issued_at: date | None
    valid_until: date | None
    note: str | None
    # TÜREV alanlar (kolon değil) — `status.py` tek kaynağından.
    status: str
    days_left: int | None
    created_at: datetime
    updated_at: datetime
