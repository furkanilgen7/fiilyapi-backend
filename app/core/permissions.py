from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.db import get_db
from app.core.deps import get_current_user
from app.modules.roles.repository import get_permission
from app.modules.users.models import User


def require_permission(module_key: str, min_level: AccessLevel):
    """Uç için asgari yetki kapısı.

    Kullanımı:
        @router.post(
            "/x", dependencies=[require_permission("progress_payments", AccessLevel.draft)]
        )

    İzin satırı yoksa erişim reddedilir (varsayılan kapalı).
    """

    async def _check(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        permission = await get_permission(session, user.role_id, module_key)
        if permission is None or not satisfies(permission.access_level, min_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok"
            )

    return Depends(_check)
