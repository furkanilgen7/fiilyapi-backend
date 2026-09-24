"""Planlama (EV) uclari — settings_router. Kapilar ve kapsam: `access.py`.

Santiye EV ayarlari (AYP ekrani; PLANLAMA-SPEC §3.8 K1/K5/K6/K19/K25): tek GET +
tek PUT. Kapi: okuma `VIEW`, yazma `WRITE` (draft — saha muhendisi dahil, B1-8).
Kapsam: `access.visible_site` — gorunmeyen santiye ile olmayan santiye AYNI 404.

`GET` `record_audit` CAGIRMAZ; PUT TEK `settings_saved` satiri yazar.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import ConflictError
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.earned_value import audit_messages, settings_service
from app.modules.earned_value.access import VIEW, WRITE, visible_site
from app.modules.earned_value.guards import SITE_COMPLETED_READ_ONLY
from app.modules.earned_value.schemas_settings import SettingsRead, SettingsSave
from app.modules.sites.models import SiteStatus
from app.modules.users.models import User

router = APIRouter(tags=["earned-value"], responses=COMMON_ERROR_RESPONSES)

_User = Annotated[User, Depends(get_current_user)]
_Session = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/sites/{site_id}/earned-value/settings", response_model=SettingsRead, dependencies=[VIEW]
)
async def get_settings_endpoint(site_id: uuid.UUID, user: _User, session: _Session) -> SettingsRead:
    """Santiyenin EV ayarlari. Satir yoksa sabit varsayilanlar, `is_default` = true (K1)."""
    await visible_site(session, user, site_id)
    return await settings_service.get_settings(session, site_id)


@router.put(
    "/sites/{site_id}/earned-value/settings", response_model=SettingsRead, dependencies=[WRITE]
)
async def save_settings_endpoint(
    request: Request, site_id: uuid.UUID, data: SettingsSave, user: _User, session: _Session
) -> SettingsRead:
    """TAM DEGISTIRME: govde santiyenin ayar kumesinin TAMAMIDIR.

    ⚠️ Govdede gecmeyen tatil ve pacal metrik SILINIR. Baslangic/bitis tarihi alan
    DEGILDIR (K7); "her n. haftanin X gunu" kurali YOKTUR (S5). Yanit guncel GET govdesi.
    """
    context = await visible_site(session, user, site_id)
    # §3.10 F0-8: tamamlanmis santiyenin ayarlari SALT OKUNUR. 409 (durum engeli, alan
    # degil) — `ConflictError` emsali.
    if context.site.status is SiteStatus.completed:
        raise ConflictError(SITE_COMPLETED_READ_ONLY)
    result = await settings_service.save_settings(session, site_id, data, user)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=audit_messages.settings_saved(context.project.name, context.site.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return result
