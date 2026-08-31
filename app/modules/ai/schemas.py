"""`GET /ai/tools` ve `GET /ai/context` yanıt şemaları (AI-0b T6).

Bu iki uç **akış içermez, model çağırmaz, panel beslemez**. `GET /ai/tools`
aynı zamanda **canlı doğrulama aracıdır**: iki farklı rolle çağrılıp listelerin
FARKLI geldiği ölçülür.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AiToolRead(BaseModel):
    """Aktörün görebildiği bir araç. 🔴 `ucler` ve `kapilar` YAYINLANMAZ.

    Uç listesi bir iç uygulama detayıdır; yayınlamak istemciye "şu yolu çağır"
    fikri verirdi ve `navigate_to`nun kapalı-enum kararını (S22) dolanırdı.
    """

    ad: str
    aciklama: str
    kapsam: str
    kume: str


class AiToolListResponse(BaseModel):
    items: list[AiToolRead]
    total: int


class AiContextResponse(BaseModel):
    """S14'ün korkuluğu: AI sınırını **bilerek** çağırsın.

    `/auth/me` kapsam taşımaz; AI sınırını bilmeden çağırır ve 404'ü yalana
    çevirir. Bu uç `permissions` + görünür araç sicili + yetki dışı modülleri
    birlikte verir.
    """

    user_id: uuid.UUID
    role_key: str
    permissions: dict[str, str]
    #: Aktörün görebildiği araç adları — prompt'un ürettiğiyle AYNI küme (B8).
    arac_adlari: list[str]
    #: 🔴 Yetkisi olmadığı için düşen modüller ADIYLA (S9-c).
    yetkisiz_moduller: list[str]
    #: 🔴 `visible_project_ids` bu dilimde **YOKTUR**: onu üretmek
    #: `projects.repository`yi çağırmayı gerektirirdi ve bu uç `ai` modülünün
    #: kapısıyla korunuyor, `projects`ınkiyle değil — yani `projects:none` olan
    #: bir rol proje kimliklerini buradan sızdırabilirdi. Kullanıcı proje
    #: kümesini `projeleri_listele` aracıyla, kendi kapısından geçerek öğrenir.
    proje_kimlikleri_notu: str


class AiChatRequest(BaseModel):
    """`POST /ai/chat` gövdesi.

    🔴 `conversation_id` AI-CHAT-2'de AÇILDI (§9-A3 kararı kapandı: soru + özet
    saklanır, araç sonuç gövdeleri saklanmaz). **İSTEĞE BAĞLIDIR**: verilmezse
    yeni bir sohbet açılır. Başkasına ait bir kimlik verilirse **404** döner —
    403 DEĞİL, çünkü 403 "bu var ama senin değil" der (S14 varlık sızıntısı).

    🔴 `model` / `provider` / `temperature` alanları YOKTUR: sağlayıcı ve model
    **sunucu** yapılandırmasıdır. İstemcinin model seçebilmesi, maliyeti ve veri
    işleyicisini istemciye devretmek olurdu.
    """

    mesaj: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# AI-CHAT-2 / K2 — sohbet saklama şemaları
# --------------------------------------------------------------------------- #

#: 🔴 Ekranda DÜRÜSTÇE basılır. Geçmiş bir sohbet açıldığında metrik kartları ve
#: varlık listeleri **yeniden çizilemez**: araç sonuç gövdeleri saklanmıyor (A3).
#: Sessizce boş kart basmak, kullanıcıya "veri yoktu" yalanını söylerdi.
BLOKLAR_SAKLANMADI = (
    "Bu sohbetin kartları saklanmadı; yalnız sorular, cevap metni ve araç "
    "izlerinin özeti gösteriliyor. Araç sonuçları (bordro satırı, personel "
    "verisi gibi) HİÇ SAKLANMAZ."
)


class AiConversationRead(BaseModel):
    """Sol sütundaki sohbet kartı (mockup 70-118)."""

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    #: Mockup'ın "4 mesaj · 09:42" satırının ilk yarısı. `COUNT`la ölçülür,
    #: `len(items)` ile DEĞİL: liste sayfalanır, sayaç sayfalanmaz.
    message_count: int


class AiConversationListResponse(BaseModel):
    items: list[AiConversationRead]
    total: int


class AiMessageRead(BaseModel):
    """🔴 Araç sonuç GÖVDESİ taşıyan alan YOKTUR ve olmayacaktır (A3)."""

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    #: Yalnız ADLAR. Argümanlar ve sonuçlar saklanmadı.
    tool_names: list[str]
    #: Zarf HÂLLERİ (`Ok` · `Restricted` · `Truncated` …), `tool_names` ile
    #: aynı sırada ve aynı uzunlukta.
    tool_states: list[str]
    #: 🔴 `bitti` ile `filtrelendi` AYRI (§5-30). Panel ikisini aynı cümleye
    #: düşürürse "cevap bu" der ve yalan söyler.
    finish_reason: str | None
    duration_ms: int | None


class AiConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[AiMessageRead]
    #: 🔴 Kararın bedeli EKRANDA yazar; sessizce boş kart basılmaz.
    bloklar_saklanmadi_notu: str = BLOKLAR_SAKLANMADI
