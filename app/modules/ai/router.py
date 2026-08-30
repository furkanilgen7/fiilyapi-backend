"""`GET /ai/tools` · `GET /ai/context` (AI-0b T6).

Akış YOK · model YOK · panel YOK · `POST /ai/chat` YOK — hepsi AI-1'in işidir.

Kapı: `require_permission("ai", AccessLevel.view)`. 🔴 `ai:full` diye bir şey
YOKTUR: yazma kapısı seviyede değil `SYSTEM_ADMIN_KEY` rol anahtarındadır
(spec §6.1 / T4), bu yüzden anlamlı seviye kümesi `{none, view}`tir.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.ai import guards
from app.modules.ai.actor import aktor_baglami
from app.modules.ai.audit import record_ai_turn
from app.modules.ai.loop import ajan_turu, tur_ozeti
from app.modules.ai.providers.base import AiOlay
from app.modules.ai.providers.factory import (
    SaglayiciYapilandirilmadi,
    SaglayiciYok,
    saglayici_kur,
)
from app.modules.ai.readplane import build_read_plane
from app.modules.ai.schemas import (
    AiChatRequest,
    AiContextResponse,
    AiToolListResponse,
    AiToolRead,
)
from app.modules.ai.stream import SSE_BASLIKLARI, sse_akisi
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


# --------------------------------------------------------------------------- #
# AI-1 — `POST /ai/chat` (SSE)
# --------------------------------------------------------------------------- #

#: Okuma düzlemi **bir kez** kurulur: `build_read_plane` 342 rota bağlamını gezer
#: ve her istekte yeniden kurmak turun önüne ölçülebilir bir gecikme koyardı.
#: 🔴 Modül düzeyinde kurulamaz — `build_read_plane` `app.main`i import eder ve
#: `main` bu router'ı import eder (döngü). Bu yüzden tembel.
_okuma_duzlemi: FastAPI | None = None


def okuma_duzlemi() -> FastAPI:
    global _okuma_duzlemi
    if _okuma_duzlemi is None:
        _okuma_duzlemi = build_read_plane()
    return _okuma_duzlemi


def _bearer(request: Request) -> str:
    """İsteğin **kendi** access token'ı (T1: AI'ın kendi kimliği YOKTUR).

    `get_current_user` bu isteği zaten doğruladı; buradaki iş token'ın **ham**
    hâlini okuma düzlemine taşımaktır. 🔴 Değer hiçbir günlüğe, prompta, araç
    argümanına ya da hata metnine yazılmaz (B24).
    """
    ham = request.headers.get("authorization") or ""
    return ham[7:] if ham.lower().startswith("bearer ") else ""


@router.post(
    "/chat",
    dependencies=[_VIEW],
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Sunucu-gönderimli olay akışı (SSE).",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        503: {"description": "AI sağlayıcısı yapılandırılmadı ya da tanınmıyor."},
    },
)
async def ai_chat_endpoint(
    request: Request,
    govde: AiChatRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Tek bir kullanıcı mesajı için ajan turunu akıtır.

    Kapı: `ai:view` (`_VIEW`). 🔴 `ai:full` diye bir şey YOKTUR.

    🔴 Sağlayıcı yapılandırılmamışsa **503 + dürüst mesaj** döner, genel bir 500
    DEĞİL: "sistem hatası" cümlesi operatörü yanlış yerde arattırır. Hata akış
    BAŞLAMADAN verilir; yarısı akmış bir yanıtın içine hata gömmek, istemciye
    "cevap geldi ama eksik" hissi verirdi.
    """
    try:
        saglayici = saglayici_kur()
    except (SaglayiciYapilandirilmadi, SaglayiciYok) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    bearer = _bearer(request)
    ai_session_id = uuid.uuid4()
    istemci_ip = request.client.host if request.client else None
    # 🔴 ORM nesnesi DEĞİL, düz UUID kapatılır. Akış gövdesi `get_db` bağımlılığı
    # sökülDÜKTEN sonra koşar; `SessionLocal` bugün `expire_on_commit=False`
    # olduğu için `user.id` şu an güvenli, ama bu bir YAPILANDIRMA ayrıntısıdır
    # ve bir gün değişirse hata ancak canlıda, denetim satırı sessizce
    # düşerken görünürdü. Bağı burada kesiyoruz.
    kullanici_id = user.id

    async def _olaylar() -> AsyncIterator[AiOlay]:
        """Turu koşar ve **her hâlde** özet denetim satırını yazar."""
        gorulen: list[AiOlay] = []
        istemci = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=okuma_duzlemi(), raise_app_exceptions=True),
            base_url="http://ai-okuma",
        )
        try:
            async for olay in ajan_turu(
                kayit=REGISTRY,
                saglayici=saglayici,
                okuma_duzlemi_istemcisi=istemci,
                bearer=bearer,
                kullanici_mesaji=govde.mesaj,
                ai_session_id=ai_session_id,
            ):
                gorulen.append(olay)
                yield olay
        finally:
            await istemci.aclose()
            # 🔴 `finally`: akış istemci tarafından koparılsa bile tur bir iz
            # bırakır. İz bırakmayan bir AI turu, atfedilemez bir turdur.
            await record_ai_turn(
                user_id=kullanici_id,
                detail=f"{tur_ozeti(gorulen)} · oturum: {ai_session_id}",
                ip_address=istemci_ip,
            )

    return StreamingResponse(
        sse_akisi(_olaylar()),
        media_type="text/event-stream",
        headers=SSE_BASLIKLARI,
    )
