"""`GET /ai/tools` · `GET /ai/context` (AI-0b T6).

Akış YOK · model YOK · panel YOK · `POST /ai/chat` YOK — hepsi AI-1'in işidir.

Kapı: `require_permission("ai", AccessLevel.view)`. 🔴 `ai:full` diye bir şey
YOKTUR: yazma kapısı seviyede değil `SYSTEM_ADMIN_KEY` rol anahtarındadır
(spec §6.1 / T4), bu yüzden anlamlı seviye kümesi `{none, view}`tir.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.ai import conversations, guards
from app.modules.ai.actor import aktor_baglami
from app.modules.ai.audit import record_ai_turn
from app.modules.ai.loop import ajan_turu, tur_ozeti
from app.modules.ai.providers.base import (
    AiOlay,
    AracSonuclandi,
    MetinParcasi,
    TurBitti,
)
from app.modules.ai.providers.factory import (
    SaglayiciYapilandirilmadi,
    SaglayiciYok,
    saglayici_kur,
)
from app.modules.ai.readplane import build_read_plane
from app.modules.ai.schemas import (
    AiChatRequest,
    AiContextResponse,
    AiConversationDetail,
    AiConversationListResponse,
    AiConversationRead,
    AiMessageRead,
    AiToolListResponse,
    AiToolRead,
)
from app.modules.ai.stream import SSE_BASLIKLARI, sse_akisi
from app.modules.ai.tools.catalog import REGISTRY
from app.modules.users.models import User

logger = logging.getLogger(__name__)

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
    session: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Tek bir kullanıcı mesajı için ajan turunu akıtır.

    Kapı: `ai:view` (`_VIEW`). 🔴 `ai:full` diye bir şey YOKTUR.

    🔴 Sağlayıcı yapılandırılmamışsa **503 + dürüst mesaj** döner, genel bir 500
    DEĞİL: "sistem hatası" cümlesi operatörü yanlış yerde arattırır. Hata akış
    BAŞLAMADAN verilir; yarısı akmış bir yanıtın içine hata gömmek, istemciye
    "cevap geldi ama eksik" hissi verirdi.
    """
    # 🔴 SAHİPLİK KAPISI **SAĞLAYICIDAN ÖNCE**. Sıra bir tercih değil bir
    # KISITTIR ve bekçisi kapıya çarparak bulundu: kapı `saglayici_kur()`dan
    # SONRA koşarken, sağlayıcı yapılandırılmamış bir sistemde başkasının
    # sohbetine yazma denemesi 503 alıyordu — yani "reddedildi" gibi görünüyordu
    # ama REDDEDEN ŞEY KAPI DEĞİLDİ. Sağlayıcı yapılandırıldığı gün kapı sessizce
    # açılırdı. Bekçi: `test_aichat2_sohbet.py::test_KIKIZ1_..._MESAJ_EKLENEMEZ`.
    conversation_id = await conversations.turu_baslat(
        session,
        user_id=user.id,
        conversation_id=govde.conversation_id,
        soru=govde.mesaj,
    )
    if conversation_id is None:
        # 403 DEĞİL 404: "bu var ama senin değil" bir varlık sızıntısıdır (S14).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=guards.BULUNAMADI)

    try:
        saglayici = saglayici_kur()
    except (SaglayiciYapilandirilmadi, SaglayiciYok) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    bearer = _bearer(request)
    ai_session_id = uuid.uuid4()
    istemci_ip = request.client.host if request.client else None
    # 🔴 ORM nesnesi DEĞİL, düz UUID kapatılır. `SessionLocal` bugün
    # `expire_on_commit=False` olduğu için `user.id` güvenlidir, ama bu bir
    # YAPILANDIRMA ayrıntısıdır: ayar değişirse öznitelik erişimi async bir
    # lazy-load'a düşer ve hata ancak canlıda görünürdü. Bağı burada kesiyoruz.
    #
    # ⚠️ Eski yorum bunu *"akış gövdesi `get_db` bağımlılığı sökülDÜKTEN sonra
    # koşar"* diye gerekçelendiriyordu; o cümle ÖLÇÜLDÜ ve YANLIŞ (aşağı bak).
    # Gerekçe yanlıştı, önlem doğru: düz UUID kapatmak yine de doğrudur.
    kullanici_id = user.id

    # 🔴 SOHBET, AKIŞ BAŞLAMADAN KALICI OLMAK ZORUNDADIR (AI-SOHBET-FIX).
    #
    # `turu_baslat` yalnız `flush()` eder: sohbet ve kullanıcı mesajı bu isteğin
    # AÇIK ama COMMIT EDİLMEMİŞ transaction'ında durur. Aşağıdaki akış gövdesi
    # ise `cevabi_sakla`yı **ayrı bir session'da** koşturur ve ayrı bir session
    # commit edilmemiş bir satırı GÖREMEZ.
    #
    # 🔴 SIRA ÖLÇÜLDÜ ve bu dosyanın eski varsayımının TERSİ çıktı: FastAPI'nin
    # `yield` bağımlılıkları akış gövdesi BİTTİKTEN SONRA sökülür. Yani
    # `get_db`nin commit'i `cevabi_sakla`dan SONRA gelir — çok geç. Canlıda her
    # turda olan tam olarak buydu:
    #     ForeignKeyViolationError: ai_messages_conversation_id_fkey
    #     → istisna `get_db`ye kaçtı → ROLLBACK → sohbet VE kullanıcı mesajı
    #       birlikte kayboldu (canlı sayım: ai_conversations 0 · ai_messages 0,
    #       oysa ai_tool_calls 16 — çünkü o zaten kendi session'ında commit eder).
    #
    # 🔴 `get_db`nin GENEL DAVRANIŞI DEĞİŞMEZ: commit burada, bu uçta, akış
    # sınırının geçildiği noktada çağrılır. `get_db` temiz çıkışta yine commit
    # eder (boş transaction üzerinde zararsız), istisnada yine rollback eder.
    #
    # 🔴 YERİ ÜÇ KISITLA ÇAKILIDIR, tercih değildir:
    #   · sahiplik kapısından SONRA → 404 yolu geride hiçbir iz bırakmaz;
    #   · sağlayıcı kurulumundan SONRA → 503 yolu kullanıcının geçmişine
    #     cevapsız, boş bir sohbet YAZMAZ;
    #   · `user.id` okunDUKTAN sonra → yukarıdaki `expire_on_commit` bağı
    #     bugün teorik kalır, commit ondan önce gelseydi YÜK TAŞIRDI.
    await session.commit()

    basladi = time.monotonic()

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
            # 🔴 §5-33: gövde `get_db` SÖKÜLDÜKTEN sonra koşar; cevap kendi
            # yazılabilir session'ında saklanır. `conversation_id` istemciden
            # DEĞİL, sahiplik kapısından geçmiş dönüşten gelir.
            #
            # 🔴 Saklanan: cevap METNİ + araç ADLARI + zarf HÂLLERİ.
            #    Saklanmayan: araç sonuç GÖVDELERİ ve yapısal bloklar (A3).
            araclar = [o for o in gorulen if isinstance(o, AracSonuclandi)]
            bitis = next((o for o in reversed(gorulen) if isinstance(o, TurBitti)), None)
            # 🔴 SAKLAMA BİR YAN ETKİDİR — YANIT YOLUNU ÇÖKERTEMEZ.
            #
            # Burası bir `StreamingResponse` gövdesinin `finally`sidir: yanıt
            # BAŞLIKLARI ÇOKTAN GİTMİŞTİR. Buradan kaçan bir istisna kullanıcıya
            # bir hata sayfası göstermez, iki ayrı hasar üretir:
            #   1. Starlette `RuntimeError: Caught handled exception, but
            #      response already started.` fırlatır — bağlantı yarıda kopar,
            #      kullanıcı akan cevabını KAYBEDER;
            #   2. istisna `get_db`ye ulaşır ve onu ROLLBACK'e sürükler — yani
            #      saklanamayan asistan cevabı, saklanabilmiş SORUYU da yanında
            #      götürür. Canlıda ölçülen zincir buydu.
            #
            # 🔴 SESSİZCE YUTULMAZ: `logger.exception` tam traceback'i yazar ve
            # `conversation_id` + oturum kimliği ile iz sürülebilir kalır. Turun
            # denetim satırı (`record_ai_turn`) zaten yukarıda yazıldı; yani
            # "hiç olmamış gibi" bir hâl mümkün değildir.
            try:
                await conversations.cevabi_sakla(
                    conversation_id=conversation_id,
                    metin="".join(o.metin for o in gorulen if isinstance(o, MetinParcasi)),
                    tool_names=[o.arac_adi for o in araclar],
                    tool_states=[o.hal for o in araclar],
                    finish_reason=bitis.sebep.value if bitis else None,
                    duration_ms=int((time.monotonic() - basladi) * 1000),
                )
            except Exception:  # noqa: BLE001 — gerekçe yukarıdaki iki maddedir
                logger.exception(
                    "AI asistan cevabı saklanamadı (conversation_id=%s · oturum=%s). "
                    "Kullanıcının cevabı akmaya devam etti; kayıp YALNIZ geçmiştedir.",
                    conversation_id,
                    ai_session_id,
                )

    return StreamingResponse(
        sse_akisi(_olaylar()),
        media_type="text/event-stream",
        headers=SSE_BASLIKLARI,
    )


# --------------------------------------------------------------------------- #
# AI-CHAT-2 / K2 — sohbet geçmişi uçları
# --------------------------------------------------------------------------- #
#
# 🔴 Kapı İKİ KATLIDIR ve alt kat üstünü İKAME ETMEZ:
#   1. `ai:view` — AI'ı kullanabilir misin (`_VIEW`).
#   2. `WHERE user_id = :actor` — **senin** sohbetin mi (`conversations.py`).
# `ai:view` olan herkes AI'ı kullanabilir; bu, başkasının sorularını okumak
# DEĞİLDİR. Bekçisi kapıya ÇARPAN bir testtir (K-IKIZ1).


@router.get("/conversations", response_model=AiConversationListResponse, dependencies=[_VIEW])
async def list_ai_conversations_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiConversationListResponse:
    """Aktörün **kendi** sohbetleri, yeniden eskiye (mockup sol sütunu)."""
    satirlar, toplam = await conversations.sohbetlerim(
        session, user_id=user.id, limit=limit, offset=offset
    )
    return AiConversationListResponse(
        items=[
            AiConversationRead(
                id=k.id,
                title=k.title,
                created_at=k.created_at,
                updated_at=k.updated_at,
                message_count=n,
            )
            for k, n in satirlar
        ],
        total=toplam,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AiConversationDetail,
    dependencies=[_VIEW],
)
async def get_ai_conversation_endpoint(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AiConversationDetail:
    """Tek bir sohbet + mesajları. 🔴 Başkasınınki **404** (403 DEĞİL, S14)."""
    sohbet = await conversations.sohbetim(session, user_id=user.id, conversation_id=conversation_id)
    if sohbet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=guards.BULUNAMADI)
    mesajlar = await conversations.mesajlarim(
        session, user_id=user.id, conversation_id=conversation_id
    )
    return AiConversationDetail(
        id=sohbet.id,
        title=sohbet.title,
        created_at=sohbet.created_at,
        updated_at=sohbet.updated_at,
        messages=[
            AiMessageRead(
                id=m.id,
                role=m.role.value,
                content=m.content,
                created_at=m.created_at,
                tool_names=list(m.tool_names or []),
                tool_states=list(m.tool_states or []),
                finish_reason=m.finish_reason,
                duration_ms=m.duration_ms,
            )
            for m in (mesajlar or [])
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_VIEW],
)
async def delete_ai_conversation_endpoint(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Kendi sohbetini siler. Mesajlar FK CASCADE ile gider.

    🔴 Bu uç bir **KVKK gereğidir**, süs değil: kullanıcı kendi sorularını
    silebilmelidir. `ai_tool_calls` izi SİLİNMEZ — o tablo atfedilebilirlik
    için değişmezdir ve içinde araç sonuç gövdesi yoktur.
    """
    if not await conversations.sohbet_sil(
        session, user_id=user.id, conversation_id=conversation_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=guards.BULUNAMADI)
