"""İK-3 T5 — SGK bildirimi (ozet + damga).

Oran tablosu ucları kardes dosyadadir (`rates.py`); ikisi de T5'tir ama
sorumluluklari ayridir: burasi BILDIRIM, orasi hesabin GIRDISI.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.audit import messages
from app.modules.payroll import guards, schemas, sgk
from app.modules.payroll.service.core import (
    _lines_with_names,
    _lock_period,
    get_period,
    rates_by_source,
)

# --- T5: SGK bildirimi + oran tablosu + Excel ------------------------------
#
# ## SGK özeti neden `summary.py`de DEĞİL de `sgk.py`de?
#
# İkisi FARKLI SORULARA cevap verir ve tabanları da farklıdır: BY kartları
# ÖDEME ile MALİYETİ ayırır, SGK ekranı ise BİLDİRİM tabanını kullanır (taşeron
# DAHİL, oran seti olmayan satır HARİÇ). Tek fonksiyona sıkıştırılsaydı bir
# ekranın kuralını değiştirmek ötekini sessizce bozardı.
#
# ## Excel ikinci bir okuma yolu AÇMAZ
#
# `GET .../export` dönem detayını `get_period_detail` ile — ekran ucuyla AYNI
# çağrıdan — alır ve yalnızca biçimlendirir. İkinci bir sorgu yazılsaydı dosya
# ile ekran zamanla ayrışır ve hangisinin doğru olduğu tartışılırdı.


async def sgk_summary(
    session: AsyncSession, period_id: uuid.UUID
) -> schemas.PayrollSgkSummaryResponse:
    """`GET /payroll/periods/{id}/sgk-summary` — SGK **55-95** (spec §5).

    Görünmeyen dönem var olmayanla AYNI 404'ü alır. Okuma ucudur: kilit ALMAZ
    (yazma yollarının aksine) ve denetim YAZMAZ.

    🔴 Hesabın tamamı `sgk.py`dedir ve o da `compute.rate_share`e dayanır —
    burada tek bir çarpma bile yapılmaz.
    """
    period = await get_period(session, period_id)
    lines = [line for line, _ in await _lines_with_names(session, [period.id])]
    ozet = sgk.build_sgk_summary(lines, await rates_by_source(session, period.year))
    return schemas.PayrollSgkSummaryResponse(
        period_id=period.id,
        year=period.year,
        month=period.month,
        sgk_submitted_at=period.sgk_submitted_at,
        **vars(ozet),
    )


async def submit_sgk(
    session: AsyncSession, period_id: uuid.UUID
) -> tuple[schemas.PayrollSgkSubmitResult, str]:
    """`POST /payroll/periods/{id}/sgk-submit` — YALNIZ `sgk_submitted_at` damgası.

    * **Dış sistem entegrasyonu YOKTUR** (spec §1): ne HTTP isteği, ne kuyruk,
      ne dosya gönderimi. SGK 44'ün düğmesi bir ELLE İŞARETLEMEDİR.
    * **Tekrar damgalama 409** (idempotent DEĞİL): damga bir OLAYIN zamanıdır ve
      SGK 46'daki son bildirim tarihiyle karşılaştırılır. Sessizce yeniden
      yazılsaydı geç kalınmış bir bildirim ikinci bir tıklamayla zamanında
      yapılmış gibi görünürdü. `/pay`in "ikinci ödeme 409" kuralıyla aynı aile.
    * **Dönem DURUMU ön koşul DEĞİLDİR** ve bu bir eksiklik değil bir karardır:
      SGK 44-47 banner'ı bildirimin beklediğini söylerken BY 61 aynı dönemin
      bordrosunun HÂLÂ onay beklediğini yazar — mockup bildirimin ödeme
      onayından ÖNCE yapılabildiğini gösteriyor. Onay şartı koymak mockup'ın
      çizdiği durumu imkânsız kılardı (WORKFLOW §3: icat yasağı).

    🔴 **EŞİK = KİLİT (WORKFLOW §4):** dönem `FOR UPDATE` ile ve DAMGA
    DENETİMİNDEN ÖNCE okunur; sıra tüm uçlardaki gibi dönem → satır (burada
    satır tarafı yoktur). Kilitsiz iki eşzamanlı istek aynı `None` damgayı okur
    ve İKİSİ DE geçerdi.
    """
    period = await _lock_period(session, period_id)
    if period.sgk_submitted_at is not None:
        raise ConflictError(guards.SGK_ALREADY_SUBMITTED)

    period.sgk_submitted_at = datetime.now(UTC)
    await session.flush()
    return (
        schemas.PayrollSgkSubmitResult(
            period_id=period.id, sgk_submitted_at=period.sgk_submitted_at
        ),
        messages.payroll_sgk_submitted(period.year, period.month),
    )
