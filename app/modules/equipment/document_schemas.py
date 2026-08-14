"""Ekipman belgesi şemaları (MK-2 T4, spec §2.3/§4) — M2:134-159 slotları.

`content` (bytea) HİÇBİR yanıt şemasında YOKTUR: liste/detay uçları yalnız
künyeyi taşır, baytlara erişim indirme ucunun `StreamingResponse`'udur
(`documents`/T3 kanonu — künye ile bayt AYNI yanıtta seyahat ETMEZ).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


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
    valid_until: date | None
    created_at: datetime


class EquipmentDocumentListResponse(BaseModel):
    items: list[EquipmentDocumentResponse]


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
