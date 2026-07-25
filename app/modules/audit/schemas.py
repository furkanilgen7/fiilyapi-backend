"""Denetim gunlugu okuma semalari (plan Task 4).

Yalnizca okuma: bu modulde audit satirini olusturan/degistiren bir sema YOKTUR.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.audit.models import AuditAction


class AuditActorRead(BaseModel):
    """Denetim satirini yapan kullanici.

    `role_name` ZORUNLUDUR: ekranin kullanici hucresi ad + rol adini birlikte gosterir.
    """

    id: uuid.UUID
    full_name: str
    role_name: str


class AuditItem(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    action: AuditAction
    detail: str
    # asyncpg INET sutununu IPv4Address/IPv6Address olarak dondurur; router bu alani
    # str() ile metne cevirerek verir (aksi halde serilestirme patlar).
    ip_address: str | None = None
    # None → aktorsuz kayit (sistem/otomatik). Sunum karari frontend'indir.
    actor: AuditActorRead | None = None


class AuditListResponse(BaseModel):
    items: list[AuditItem]
    total: int
    limit: int
    offset: int
