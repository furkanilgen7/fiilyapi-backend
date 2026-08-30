"""`GET /ai/tools` · `GET /ai/context` (AI-0b T6).

Akış YOK · model YOK · panel YOK · `POST /ai/chat` YOK — hepsi AI-1'in işidir.

Kapı: `require_permission("ai", AccessLevel.view)`. 🔴 `ai:full` diye bir şey
YOKTUR: yazma kapısı seviyede değil `SYSTEM_ADMIN_KEY` rol anahtarındadır
(spec §6.1 / T4), bu yüzden anlamlı seviye kümesi `{none, view}`tir.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.ai import guards
from app.modules.ai.actor import aktor_baglami
from app.modules.ai.schemas import AiContextResponse, AiToolListResponse, AiToolRead
from app.modules.ai.tools.catalog import REGISTRY
from app.modules.users.models import User

router = APIRouter(prefix="/ai", tags=["ai"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(guards.PERMISSION_MODULE, guards.MIN_LEVEL)

#: 🔴 Bu uç `permissions` yayınlar ama bir yetki **YÜKSELTMEZ**: içerik zaten
#: `/auth/me`nin aynısıdır ve aktör kendi rolünü okur.
_PROJE_KIMLIKLERI_NOTU = (
    "Görünür proje kimlikleri bu uçtan YAYINLANMAZ. Bu uç `ai` kapısıyla "
    "korunuyor, `projects` kapısıyla değil; proje kimliklerini buraya koymak "
    "`projects:none` olan bir role kimlik sızdırırdı. Proje kümesi "
    "`projeleri_listele` aracıyla, kendi kapısından geçerek öğrenilir."
)


@router.get("/tools", response_model=AiToolListResponse, dependencies=[_VIEW])
async def list_ai_tools_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiToolListResponse:
    """Aktörün **görebildiği** araçlar (Kapı A'nın yayınlanmış hâli).

    Canlı doğrulama: iki farklı rolle çağrılıp listelerin FARKLI geldiği
    ölçülür. Aynı gelirse Kapı A hiçbir şey yapmıyordur.
    """
    actor = await aktor_baglami(session, user)
    araclar = REGISTRY.katalog(actor)
    return AiToolListResponse(
        items=[
            AiToolRead(ad=s.ad, aciklama=s.aciklama, kapsam=s.kapsam.value, kume=s.kume.value)
            for s in araclar
        ],
        total=len(araclar),
    )


@router.get("/context", response_model=AiContextResponse, dependencies=[_VIEW])
async def get_ai_context_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiContextResponse:
    """AI'ın sınırı — S14'ün korkuluğu."""
    actor = await aktor_baglami(session, user)
    return AiContextResponse(
        user_id=actor.user_id,
        role_key=actor.role_key,
        permissions={k: v.value for k, v in actor.permissions.items()},
        arac_adlari=[s.ad for s in REGISTRY.katalog(actor)],
        yetkisiz_moduller=REGISTRY.dusurulen_moduller(actor),
        proje_kimlikleri_notu=_PROJE_KIMLIKLERI_NOTU,
    )
