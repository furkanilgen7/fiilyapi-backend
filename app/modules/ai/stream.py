"""`AiOlay` → `text/event-stream` (AI-1).

SSE seçildi, WebSocket değil: akış **tek yönlü** (sunucu → tarayıcı), araya
Next.js BFF giriyor ve tarayıcı tarafında yeniden bağlanma ücretsiz. WebSocket
BFF'te ikinci bir protokol yükseltmesi ve ayrı bir kimlik yolu isterdi.

## Kare biçimi

    event: <ad>
    data: {"...": ...}

`data` **tek satırdır**: JSON dizgileri ham satır sonu taşıyamaz, dolayısıyla
çok satırlı `data:` sarmalamasına gerek yoktur. Bu, ayrıştırıcıyı da basit
tutar.

## 🔴 Ön yorum satırı (`: ...`) TAMPONLAMAYA KARŞI

Ters vekiller (nginx, Railway'in yönlendiricisi) ilk baytı görene kadar yanıtı
tutabilir. Akış başlar başlamaz gönderilen yorum satırı, `Content-Type` ve
başlıkların **hemen** akmasını sağlar. ⚠️ Bu bir garanti DEĞİLDİR: Railway'in
tamponlama davranışı bu dilimde **ölçülmedi** (canlıya bağlanmak kapsam
dışıydı). Ölçülene kadar bu satır bir önlemdir, kanıt değil.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator

from app.modules.ai.providers.base import AiOlay

#: Akış başında gönderilen yorum karesi. SSE'de `:` ile başlayan satır yorumdur
#: ve istemci onu **olay saymaz**.
ON_YORUM: bytes = b": fiil-ai akis acildi\n\n"

#: 🔴 Ters vekile "bu yaniti tamponlama" demenin taşınabilir yolu.
SSE_BASLIKLARI: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # nginx'e özel ama zararsız; Railway/Vercel yığınlarında da tanınır.
    "X-Accel-Buffering": "no",
}


def sse_kodla(olay: AiOlay) -> bytes:
    """Tek olayı bir SSE karesine çevirir."""
    govde = dataclasses.asdict(olay)
    return (
        f"event: {olay.olay_adi}\ndata: {json.dumps(govde, ensure_ascii=False, default=str)}\n\n"
    ).encode()


async def sse_akisi(olaylar: AsyncIterator[AiOlay]) -> AsyncIterator[bytes]:
    """Olay akışını SSE bayt akışına çevirir; ön yorumu **ilk** gönderir."""
    yield ON_YORUM
    async for olay in olaylar:
        yield sse_kodla(olay)
