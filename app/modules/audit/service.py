import ipaddress
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditAction, AuditLog


def _normalize_ip(value: str | None) -> str | None:
    """Gecerli bir IP metnini normalize eder; gecersizse `None` doner.

    `ip_address` kolonu INET'tir ve gecersiz metin insert'i `DataError` ile dusurur.
    Audit satiri asil islemle AYNI transaction'da oldugu icin bu, ISLEMIN kendisini de
    geri alir; ustelik deger `X-Forwarded-For` uzerinden istemcinin kontrolundedir.
    Bu yuzden dogrulama tek huniden (bu fonksiyon) gecer: denetim alani bos kalir,
    islem korunur.
    """
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


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
            ip_address=_normalize_ip(ip_address),
        )
    )
