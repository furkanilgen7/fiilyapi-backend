"""Denetim gunlugu okuma ucu (plan Task 4).

Yalnizca okuma ucu tanimlanir; audit satirlari `record_audit` ile yazma uclarinda
uretilir. Bu tablo icin UPDATE/DELETE ucu YOKTUR.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.audit import repository
from app.modules.audit.models import AuditAction
from app.modules.audit.repository import AuditRow
from app.modules.audit.schemas import AuditActorRead, AuditItem, AuditListResponse

router = APIRouter(prefix="/audit-log", tags=["audit"], responses=COMMON_ERROR_RESPONSES)


def _to_item(row: AuditRow) -> AuditItem:
    entry, actor, role = row
    return AuditItem(
        id=entry.id,
        occurred_at=entry.occurred_at,
        action=entry.action,
        detail=entry.detail,
        # asyncpg INET'i IPv4Address/IPv6Address dondurur — metne cevrilmeden serilestirilemez.
        ip_address=str(entry.ip_address) if entry.ip_address is not None else None,
        actor=(
            AuditActorRead(
                id=actor.id, full_name=actor.full_name, role_name=role.name if role else ""
            )
            if actor is not None
            else None
        ),
    )


@router.get(
    "",
    response_model=AuditListResponse,
    dependencies=[require_permission("settings", AccessLevel.view)],
)
async def list_audit_log_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    date_from: Annotated[
        date | None, Query(description="YYYY-MM-DD — o gunun 00:00'indan itibaren (UTC, dahil)")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="YYYY-MM-DD — o gunun sonuna kadar (UTC, dahil)")
    ] = None,
    q: Annotated[str | None, Query(description="Detay metni veya aktor adinda kismi arama")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditListResponse:
    """Filtrelenebilir/sayfalanabilir denetim gunlugu listesi (`occurred_at DESC`)."""
    filters = {
        "actor_user_id": actor_user_id,
        "action": action,
        "date_from": date_from,
        "date_to": date_to,
        "q": q,
    }
    rows = await repository.list_audit_entries(session, limit=limit, offset=offset, **filters)
    total = await repository.count_audit_entries(session, **filters)
    return AuditListResponse(
        items=[_to_item(row) for row in rows], total=total, limit=limit, offset=offset
    )
