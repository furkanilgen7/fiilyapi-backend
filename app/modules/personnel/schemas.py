"""Personel şemaları — puantaj spec §2, §3.

`customers/schemas.py` üçlüsünün (Create/Update/Response) kardeşi. Kaynak/taşeron
uyuşması burada DEĞİL `guards.py`de doğrulanır: PATCH kısmi gövde gönderir, kural
ancak DB'deki kayıtla BİRLEŞTİRİLMİŞ değerler üzerinde anlamlıdır.

**İK alanı YOKTUR** (spec §1, §5): belge / izin / SGK / bordro / ücret alanı bu
şemalara EKLENMEZ — bu dilim yalnız puantajın ihtiyaç duyduğu asgari personel
kaydını açar.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

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


class PersonnelUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    trade: str | None = Field(default=None, max_length=100)
    source: WorkerSource | None = None
    subcontractor_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # Pasifleştirme YOLU: DELETE ucu yoktur (spec §3), çıkarma bu bayrakla yapılır.
    is_active: bool | None = None


class PersonnelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    trade: str | None
    source: WorkerSource
    subcontractor_id: uuid.UUID | None
    user_id: uuid.UUID | None
    is_active: bool


class PersonnelListResponse(BaseModel):
    """`audit`/`users` liste deseninin aynısı: `total` + `limit`/`offset`."""

    items: list[PersonnelResponse]
    total: int
    limit: int
    offset: int
