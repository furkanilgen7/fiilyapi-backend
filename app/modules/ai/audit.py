"""`record_tool_call()` — AI araç erişim izi. **AYRI session, ÖNCE commit** (T5/S7).

## Neden `record_audit` KULLANILAMAZ (ölçüldü)

`audit/service.py::record_audit` docstring'i birebir şunu der: *"COMMIT ETMEZ,
`flush()` bile çağırmaz"*. Ve `core/db.py::get_db` istisnada `rollback()` eder.
Yani araç patlarsa korkuluk **kendi kaydını siler** — geriye "hiçbir şey
olmamış" gibi görünen bir DB kalır. Bu tam olarak S7'dir.

`record_audit`ın imzası DEĞİŞTİRİLMEZ: çağrı yüzeyi **105 çağrı / 33 dosya**
(app/) + 5 çağrı / 1 dosya (tests/) olarak ölçüldü. Bir korkuluk uğruna 110
çağrıyı elden geçirmek, korkuluğun kendisinden daha büyük bir risktir.

## FAIL-CLOSED

Denetim yazılamazsa **araç KOŞMAZ**. `record_tool_call` istisnayı yutmaz;
çağıran (`ToolRegistry.invoke`) onu `ToolError("denetim_yazilamadi")`ya çevirir
ve handler'a **hiç dokunmaz**. Bu, B6b'nin ölçtüğü davranıştır.

## İki satır, tek `call_id`

`http_status`/`latency_ms` ancak sonra bilinir ve `audit_log` disiplininde
UPDATE yoktur. `started` satırı araç **koşmadan önce**, `finished` satırı sonuç
bilindiğinde yazılır; ikisi `call_id` ile buluşur.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.db import SessionLocal
from app.modules.ai.models import (
    AiToolCall,
    AiToolCallOrigin,
    AiToolCallPhase,
    AiToolDecision,
)


async def record_tool_call(
    *,
    call_id: uuid.UUID,
    phase: AiToolCallPhase,
    user_id: uuid.UUID | None,
    tool_name: str,
    module_keys: Sequence[str],
    arguments: Mapping[str, Any],
    decision: AiToolDecision,
    resolved_path: str | None = None,
    conversation_id: uuid.UUID | None = None,
    ai_session_id: uuid.UUID | None = None,
    provider: str | None = None,
    model: str | None = None,
    http_status: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Tek bir denetim satırını **kendi session'ında** yazar ve COMMIT eder.

    🔴 `SessionLocal` (ANA, yazılabilir motor) kullanılır — `AiSessionLocal`
    DEĞİL. Salt-okunur oturum bu INSERT'i PostgreSQL düzeyinde reddederdi ve
    denetim hiç yazılamazdı. Bu, `ai/**` içinde `SessionLocal(` kullanan **tek**
    dosyadır (S15 bekçisinin adıyla tanıdığı istisna).

    ⚠️ `origin` her zaman `ai`: bu tabloya yalnız AI hattı yazar. Alan
    istemciden ALINMAZ (S24) ve parametresi de yoktur — parametre olsaydı
    ileride bir çağıran onu `human` yapabilirdi ve iz yalan söylerdi.
    """
    async with SessionLocal() as session:
        session.add(
            AiToolCall(
                call_id=call_id,
                phase=phase,
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider,
                model=model,
                tool_name=tool_name,
                resolved_path=resolved_path,
                module_keys=list(module_keys),
                arguments=dict(arguments),
                decision=decision,
                origin=AiToolCallOrigin.ai,
                ai_session_id=ai_session_id,
                http_status=http_status,
                latency_ms=latency_ms,
                error=error,
            )
        )
        await session.commit()
