"""Ekipman belgesi şemaları (MK-2 T4, spec §2.3/§4) — M2:134-159 slotları.

`content` (bytea) HİÇBİR yanıt şemasında YOKTUR: liste/detay uçları yalnız
künyeyi taşır, baytlara erişim indirme ucunun `StreamingResponse`'udur
(`documents`/T3 kanonu — künye ile bayt AYNI yanıtta seyahat ETMEZ).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

DOCUMENT_NO_MAX_LENGTH = 100
"""K1 — `equipment_documents.document_no` kolonuyla AYNI tavan (emsal:
`contract_no` / `serial_no` / `invoice_no`). Tek yerde tanımlıdır."""


class EquipmentDocumentTypeResponse(BaseModel):
    """`GET /equipment/document-types` — altı sabit slot (CRUD ucu YOK)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    name: str
    is_required: bool
    sort_order: int


class EquipmentDocumentTypeListResponse(BaseModel):
    items: list[EquipmentDocumentTypeResponse]


class EquipmentDocumentResponse(BaseModel):
    """`GET /equipment/{id}/documents` satırı — bayt YOK, yalnız künye."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    equipment_id: uuid.UUID
    type_id: uuid.UUID
    type_code: str
    type_name: str
    filename: str
    mime_type: str
    size_bytes: int
    document_no: str | None
    issued_at: date | None
    valid_until: date | None
    note: str | None
    created_at: datetime


class EquipmentDocumentListResponse(BaseModel):
    items: list[EquipmentDocumentResponse]


class EquipmentDocumentUpdate(BaseModel):
    """`PATCH /equipment/documents/{id}` — KAPSAM DAR (K2).

    Yalnız DÖRT künye alanı güncellenir: `document_no` · `issued_at` · `note` ·
    `valid_until`. Dosyanın kendisi (`content`/`filename`/`mime_type`/
    `size_bytes`) ve belgenin KİMLİĞİ (`type_id`) DEĞİŞMEZ — yanlış tiple ya da
    yanlış dosyayla açılan kayıt silinip yeniden yüklenir
    (`PersonnelDocumentUpdate` emsalinin birebiri). Gövdeye bu alanlar
    gönderilse bile Pydantic onları YOK SAYAR.

    `exclude_unset` ile "gönderilmedi" ≠ "null gönderildi" ayrımı korunur:
    gönderilmeyen alana DOKUNULMAZ, açıkça `null` gönderilen alan TEMİZLENİR.
    """

    document_no: str | None = Field(default=None, max_length=DOCUMENT_NO_MAX_LENGTH)
    issued_at: date | None = None
    note: str | None = None
    valid_until: date | None = None


class EquipmentExpiringDocument(BaseModel):
    """K7 — 30 gün içinde süresi dolacak belge (özet listesi)."""

    id: uuid.UUID
    equipment_id: uuid.UUID
    equipment_name: str
    type_name: str
    valid_until: date
    days_left: int


class EquipmentExpiredDocument(BaseModel):
    """K7 — süresi çoktan dolmuş belge (özet listesi)."""

    id: uuid.UUID
    equipment_id: uuid.UUID
    equipment_name: str
    type_name: str
    valid_until: date
    days_overdue: int


class EquipmentDocumentsSummaryResponse(BaseModel):
    """`GET /equipment/documents/summary` — K7 üç sayaç + iki liste.

    `missing` YALNIZ zorunlu (`is_required=true`) tipler üzerinden sayılır
    (İK-1'in `missing` semantiğinin birebiri) ve YALNIZ AKTİF (`is_active=true`)
    ekipmanı kapsar — kullanımdan kaldırılmış (pasif) bir ekipmanın eksik
    belgesi hiçbir sayaca girmez.
    """

    expiring_soon: int
    expired: int
    missing: int
    expiring_documents: list[EquipmentExpiringDocument]
    expired_documents: list[EquipmentExpiredDocument]
