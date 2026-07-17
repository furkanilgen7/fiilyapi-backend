import enum
import uuid
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db


class AccessLevel(str, enum.Enum):
    """Erişim seviyesi. Sıralıdır: none < view < draft < request < approve < full < admin.

    full silmeyi KAPSAMAZ — silme yalnızca admin seviyesindedir (spec §5.0).
    """

    none = "none"
    view = "view"
    draft = "draft"
    request = "request"
    approve = "approve"
    full = "full"
    admin = "admin"


class Scope(str, enum.Enum):
    """Veri kapsamı — aktörün modül içinde hangi kayıtları görebildiği."""

    all = "all"
    own = "own"
    project = "project"
    finance = "finance"
    stock = "stock"
    limited = "limited"


_LEVEL_ORDER: dict[AccessLevel, int] = {
    AccessLevel.none: 0,
    AccessLevel.view: 1,
    AccessLevel.draft: 2,
    AccessLevel.request: 3,
    AccessLevel.approve: 4,
    AccessLevel.full: 5,
    AccessLevel.admin: 6,
}


def satisfies(actual: AccessLevel, required: AccessLevel) -> bool:
    """actual seviyesi, required seviyesini karşılıyor mu?"""
    return _LEVEL_ORDER[actual] >= _LEVEL_ORDER[required]


def require_permission(module_key: str, min_level: AccessLevel):
    """Uç için asgari yetki kapısı.

    Kullanımı:
        @router.post(
            "/x", dependencies=[require_permission("progress_payments", AccessLevel.draft)]
        )

    İzin satırı yoksa erişim reddedilir (varsayılan kapalı).
    """
    # Fonksiyon içi import kasıtlı: app.core.deps -> app.modules.users.models ->
    # app.modules.roles.models -> app.core.permissions döngüsünü kırar.
    # Modül seviyesine taşıma.
    from app.core.deps import get_current_user
    from app.modules.users.models import User

    async def _check(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        # Fonksiyon içi import kasıtlı: app.core.permissions <-> app.modules.roles
        # arasındaki döngüsel import'u kırar. Modül seviyesine taşıma.
        from app.modules.roles.repository import get_permission

        permission = await get_permission(session, user.role_id, module_key)
        if permission is None or not satisfies(permission.access_level, min_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok"
            )

    return Depends(_check)


class Deletable(Protocol):
    """Silinebilirliği değerlendirilecek kaydın taşıması gereken asgari alanlar."""

    created_by: uuid.UUID
    is_draft: bool


def can_delete(actor_id: uuid.UUID, level: AccessLevel, record: Deletable) -> bool:
    """Spec §5.0 silme kuralı.

    admin seviyesi her şeyi siler. Bunun dışında yalnızca taslak istisnası geçerlidir:
    kaydı aktör oluşturmuş + kayıt hâlâ taslak + aktörün en az draft seviyesi var.
    """
    if satisfies(level, AccessLevel.admin):
        return True

    return record.created_by == actor_id and record.is_draft and satisfies(level, AccessLevel.draft)
