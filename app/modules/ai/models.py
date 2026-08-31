"""AI araç denetimi — `ai_tool_calls` (AI-0b T4, spec §2.2 KATMAN 6, GRAFT-1).

Bu tablo `audit_log`un **ikizi değildir** ve onun yerine geçmez:

* `audit_log` bir **ürün olayını** kaydeder ("hakediş onaylandı"). `record_audit`
  isteğin kendi session'ına yazar, **commit etmez** (docstring birebir: "COMMIT
  ETMEZ, `flush()` bile çağırmaz") ve `get_db` istisnada `rollback()` eder.
* `ai_tool_calls` bir **erişim izini** kaydeder ("bu kullanıcı bu aracı bu
  çözülmüş yolla çağırdı"). Araç patlarsa ya da istek session'ı geri alınırsa
  iz **KALMAK ZORUNDADIR** — aksi hâlde korkuluk kendi kaydını siler (S7).
  Bu yüzden yazımı `app/modules/ai/audit.py` **ayrı bir session** ile yapar.

🔴 **"Okumalar denetlenmez" bir HAYALET ATIFTIR.** Depoda 16 dosya bu cümleyi
*"WORKFLOW kuralı"* diye anar ama kök `WORKFLOW.md`de böyle bir kural YOKTUR
(ölçüldü, AI-0b). AI'ın okuma izini tutması bu yüzden bir kuralı çiğnemek değil,
**bilinçli bir sapmadır** ve gerekçesi S8'dir: AI, kullanıcının kendi bearer'ıyla
140 GET ucuna erişebilir; bu erişimin izi hiçbir yerde yoksa atfedilebilirlik
sıfırdır.

## Neden İKİ SATIR, tek `call_id`

`http_status` ve `latency_ms` ancak araç koştuktan **sonra** bilinir; ama denetim
satırı araç **koşmadan önce** yazılmak zorundadır (yoksa patlayan araç iz
bırakmaz). `audit_log` disiplininde UPDATE **yoktur** — bu tablo o disiplini
devralır. Çözüm: `started` satırı + `finished` satırı, ortak `call_id`.

## Neden `origin` ve `ai_session_id` istemciden ALINMAZ (S24)

`audit_log.ip_address` istemcinin `X-Forwarded-For`una güvenir (ölçüldü:
`core/ratelimit.py::client_ip` ilk girdiye koşulsuz güvenir). Bu tabloda
atfedilebilirlik başlıktan türetilmez: `origin` sunucuda set edilir ve
`ai_session_id` sunucunun ürettiği tur kimliğidir.

## Kolon adları İNGİLİZCE (spec'ten bilinçli sapma)

Spec §2.2 `cozulmus_yol` yazar. Bu depoda **1037 `mapped_column`un hiçbiri
Türkçe değildir** (ölçüldü); tek bir Türkçe kolon adı şema genelinde bir
istisna açardı. Python tarafındaki tanımlayıcılar (AI-0a deseni) Türkçe
kalır, **DB kolonları İngilizce**.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, desc, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiToolDecision(str, enum.Enum):
    """Huninin (`ToolRegistry.invoke`) verdiği karar — spec §2.2 KATMAN 6.

    Proje geneli deseni (`str, enum.Enum`) korunur; StrEnum'a geçiş `__str__`
    davranışını değiştirir (bkz. `AuditAction` notu / pyproject UP042).
    """

    allowed = "allowed"
    denied_permission = "denied_permission"
    denied_unknown_tool = "denied_unknown_tool"
    denied_write_role = "denied_write_role"
    denied_budget = "denied_budget"


class AiToolCallPhase(str, enum.Enum):
    """`started` araç **koşmadan önce**, `finished` sonuç bilindiğinde yazılır."""

    started = "started"
    finished = "finished"


class AiToolCallOrigin(str, enum.Enum):
    """Kaydı kimin ürettiği — **sunucuda** set edilir, istemciden ALINMAZ (S24)."""

    ai = "ai"
    human = "human"


class AiToolCall(Base):
    """Değiştirilemez AI araç erişim izi.

    Yalnız INSERT ve SELECT yapılır: bu tablo için UPDATE/DELETE ucu, servis
    fonksiyonu ya da repository yardımcısı **YOKTUR** (`audit_log` disiplini).
    """

    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        Index("ix_ai_tool_calls_occurred_at", desc("occurred_at")),
        Index("ix_ai_tool_calls_user_id", "user_id"),
        # Bir çağrının iki satırı bu indeksle buluşur (`started` + `finished`).
        Index("ix_ai_tool_calls_call_id", "call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: İki satırı bağlayan çağrı kimliği. UNIQUE **DEĞİLDİR** — tam olarak iki
    #: satır paylaşır.
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phase: Mapped[AiToolCallPhase] = mapped_column(
        Enum(AiToolCallPhase, name="ai_tool_call_phase"), nullable=False
    )
    # ON DELETE SET NULL: kullanıcı silinince erişim izi silinmez (`audit_log` emsali).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: AI-0b'de her zaman NULL: `ai_conversations` tablosu bu dilimde AÇILMAZ
    #: (§9-A3 kararı şemadan önce gelir). FK **yoktur** — olmayan bir tabloya
    #: FK yazılamaz ve ileride eklenmesi ayrı bir migration'ın işidir.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: AI-0b'de NULL: sağlayıcı katmanı bu dilimde YOK (kapsam dışı).
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: 🔴 ŞABLON DEĞİL ÇÖZÜLMÜŞ yol (S27). `/projects/{project_id}` yazılırsa
    #: tablo yalan söyler ve bu dilimin tüm meselesi atfedilebilirliktir.
    #: Reddedilen çağrılarda (yol hiç kurulamadı) NULL olabilir.
    resolved_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Aracın beyan ettiği kapı modülleri. İKİ kapılı uçlar vardır (ölçüldü: 2
    #: operasyon), bu yüzden ÇOĞUL.
    module_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[AiToolDecision] = mapped_column(
        Enum(AiToolDecision, name="ai_tool_decision"), nullable=False
    )
    origin: Mapped[AiToolCallOrigin] = mapped_column(
        Enum(AiToolCallOrigin, name="ai_tool_call_origin"), nullable=False
    )
    ai_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: `finished` satırında dolar.
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------- #
# AI-CHAT-2 / K2 — sohbet saklama
# --------------------------------------------------------------------------- #
#
# 🔴 **KULLANICI KARARI (A3, 2026-08-30): SORU + ÖZET SAKLANIR, ARAÇ SONUÇ
# GÖVDELERİ HİÇ SAKLANMAZ.**
#
# | saklanır | saklanmaz |
# |---|---|
# | kullanıcının sorusu | araç sonuç **gövdeleri** (bordro satırı, TCKN, personel) |
# | modelin cevap **metni** | yapısal bloklar (metrik kartı, stok listesi) |
# | araç **çağrı adları** | araç argümanları |
# | zarf **hâlleri** (`Ok`/`Restricted`…) | `veri` alanının kendisi |
#
# 🔴 **DÜRÜST SONUÇ:** geçmiş bir sohbet açıldığında metrik kartları ve varlık
# listeleri **yeniden çizilemez** — verisi yok. Bu bir kusur değil, kararın
# bedelidir; ekran bunu açıkça söyler ("kartlar saklanmadı, özet gösteriliyor")
# ve sessizce boş kart BASMAZ.
#
# 🔴 **SAHİPLİK:** bir kullanıcı başkasının sohbetini listeleyemez/okuyamaz.
# Kapı repository'de (`WHERE user_id = :actor`) ve bekçisi kapıya ÇARPAN bir
# testtir (`test_aichat2_sohbet.py::test_KIKIZ1_...`). 404 döner, 403 değil:
# S14'ün "görünmeyen-var-olan ile var-olmayan BAYT BAYT AYNI" kuralı.


class AiMessageRole(str, enum.Enum):
    """🔴 İKİ üye. `arac` rolü BURADA YOKTUR — araç sonucu saklanmıyor (A3)."""

    kullanici = "kullanici"
    asistan = "asistan"


class AiConversation(Base):
    """Bir sohbet. **Sahibine** bağlıdır ve başkası okuyamaz."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        # Listeleme her zaman "benim sohbetlerim, yeniden eskiye".
        Index("ix_ai_conversations_user_updated", "user_id", desc("updated_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: 🔴 `SET NULL` DEĞİL `CASCADE` — `ai_tool_calls`tan bilinçli SAPMA.
    #: Orada iz **atfedilebilirlik** için yaşar; burada içerik kullanıcının kendi
    #: sorularıdır. Sahipsiz kalan bir sohbet hiçbir kapının arkasında değildir
    #: ama kullanıcının metnini taşımaya devam ederdi.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: İlk sorudan türetilir ve KIRPILIR. Modelden başlık İSTENMEZ: ikinci bir
    #: model çağrısı turun maliyetini ve gecikmesini iki katına çıkarırdı.
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiMessage(Base):
    """Bir mesaj. 🔴 Araç sonuç **gövdesi** taşıyan hiçbir kolon YOKTUR."""

    __tablename__ = "ai_messages"
    __table_args__ = (Index("ix_ai_messages_conversation", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[AiMessageRole] = mapped_column(
        Enum(AiMessageRole, name="ai_message_role"), nullable=False
    )
    #: Kullanıcının sorusu ya da modelin cevap METNİ. Araç gövdesi ASLA.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: Çağrılan araçların ADLARI — argümanları değil, sonuçları değil.
    tool_names: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    #: Zarf HÂLLERİ (`Ok` · `Restricted` · `Truncated` …) — `veri` alanı yok.
    #: 🔴 `tool_names` ile aynı sırada ve aynı uzunlukta; ikisi bir ÇİFTTİR ve
    #: ayrışırsa iz yalan söyler (bekçisi var).
    tool_states: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    #: `TurSebebi` değeri. 🔴 `bitti`/`filtrelendi` AYRI TUTULUR (§5-30): ikisi
    #: aynı ekrana düşerse panel "cevap bu" der ve YALAN SÖYLER.
    finish_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Mockup'ın "09:42 · 1,8 sn" damgasının `sn` yarısı.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
