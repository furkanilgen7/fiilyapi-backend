"""Denetim gunlugu okuma sorgulari (plan Task 4).

Yalnizca SELECT: bu tablo icin UPDATE/DELETE yardimcisi YOKTUR (degistirilemezlik).
"""

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.roles.models import Role
from app.modules.users.models import User

# ILIKE deseninde joker anlami tasiyan karakterler; kullanici girdisinde duz karakter
# olarak aranmalari icin escape edilir.
_LIKE_ESCAPE = "\\"

AuditRow = tuple[AuditLog, User | None, Role | None]


def _escape_like(term: str) -> str:
    return (
        term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _filters(
    *,
    actor_user_id: uuid.UUID | None,
    action: AuditAction | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
) -> list[ColumnElement[bool]]:
    """Opsiyonel filtreleri AND'lenecek kosullara cevirir.

    Tarih sinirlari UTC'de gun-dahil yorumlanir: `date_from` o gunun 00:00:00'i,
    `date_to` o gunun 23:59:59.999999'u. Boylece `date_to=bugun` bugunun kayitlarini
    kirpmaz. (`occurred_at` timestamptz oldugu icin karsilastirma tz-farkindadir.)
    """
    conditions: list[ColumnElement[bool]] = []
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if action is not None:
        conditions.append(AuditLog.action == action)
    if date_from is not None:
        conditions.append(AuditLog.occurred_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        conditions.append(AuditLog.occurred_at <= datetime.combine(date_to, time.max, tzinfo=UTC))
    term = (q or "").strip()
    if term:
        pattern = f"%{_escape_like(term)}%"
        conditions.append(
            or_(
                AuditLog.detail.ilike(pattern, escape=_LIKE_ESCAPE),
                User.full_name.ilike(pattern, escape=_LIKE_ESCAPE),
            )
        )
    return conditions


async def list_audit_entries(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
) -> list[AuditRow]:
    """Filtreli/sirali denetim satirlarini aktor ve rolüyle birlikte TEK sorguda doner.

    Aktor ve rol `outerjoin` ile ayni sorguda gelir — satir basina ek sorgu (N+1) YOK.
    `limit=None` tum eslesen kayitlari doner (export ucu icin).
    """
    stmt = (
        select(AuditLog, User, Role)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Role, User.role_id == Role.id)
        .where(
            *_filters(
                actor_user_id=actor_user_id,
                action=action,
                date_from=date_from,
                date_to=date_to,
                q=q,
            )
        )
        .order_by(AuditLog.occurred_at.desc())
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1], row[2]) for row in result.all()]


async def count_audit_entries(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
) -> int:
    """Ayni filtrelerle toplam kayit sayisi — `total` sayfadan degil filtreden etkilenir."""
    stmt = (
        select(func.count())
        .select_from(AuditLog)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .where(
            *_filters(
                actor_user_id=actor_user_id,
                action=action,
                date_from=date_from,
                date_to=date_to,
                q=q,
            )
        )
    )
    return (await session.execute(stmt)).scalar_one()
