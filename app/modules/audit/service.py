import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    action: AuditAction,
    detail: str,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> None:
    """Denetim satirini request-session'a ekler.

    COMMIT ETMEZ, `flush()` bile cagirmaz: commit'i `get_db` bagimliligi sahiplenir.
    Boylece denetim satiri asil islemle ayni transaction'a girer — islem geri
    alinirsa denetim satiri da yazilmaz (atomiklik, bkz. tasarim §2.3).
    """
    session.add(
        AuditLog(
            action=action,
            detail=detail,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
        )
    )
