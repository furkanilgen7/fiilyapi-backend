"""Günlük poz satırlarının ve işçi kırılımının TEK yazma yolu (T3; spec §2).

## ⚠️ Semantik: DEĞİŞTİRME (replace) — iki gövdede de aynı

`PUT /diary/{entry_id}/lines` gövdesi ekranın TAMAMIDIR: gövdede geçmeyen satır
**SİLİNİR**. `PATCH /diary/{entry_id}` içindeki `worker_counts[]` de aynı kuraldadır.
Taşeron `subcontractor_progress_payments/lines.py` deseninin birebiri.

## Taşeron modülünden İKİ FARK (bilinçli)

1. **Kota YOK.** Günlük kayıt bir TAAHHÜT değil bir GÖZLEMDİR: "bugün BOQ
   miktarından fazlasını yaptım" fiziksel olarak mümkündür ve günlük onu
   engellemez; tavan denetimi hakediş katmanının işidir.
2. **Katsayı YOK.** ₺ katkısı KATSAYISIZ `quantity × unit_price`tır (spec §2) —
   fiyat farkı katsayısı hakedişin işidir, günlüğün değil.

## Sıra — ÖNCE TÜM DOĞRULAMALAR, SONRA TEK YAZMA

`_resolve` hiçbir şey YAZMAZ, uygulama hiçbir şey DOĞRULAMAZ: ikinci satırda
patlayan istek birincisini session'a eklemiş OLMAMALIDIR (kısmi yazma yok).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, SiteValidationError
from app.modules.boq.models import BoqItem
from app.modules.site_diary import guards, repository
from app.modules.site_diary.models import SiteDiaryEntry, SiteDiaryLine, SiteDiaryWorkerCount
from app.modules.site_diary.schemas import SiteDiaryLineInput, SiteDiaryWorkerCountInput


@dataclass(frozen=True)
class _ResolvedLine:
    """Doğrulaması BİTMİŞ satır planı — henüz hiçbir şey yazılmadı."""

    item: BoqItem
    quantity: Decimal


async def _resolve(
    session: AsyncSession, entry: SiteDiaryEntry, inputs: list[SiteDiaryLineInput]
) -> list[_ResolvedLine]:
    """Gövde-içi çift → poz-şantiye sahipliği. **Hiçbir yazma YAPMAZ.**

    Sorgu satır başına DEĞİL gövdenin tamamı için TEK kez koşar (N+1 yok).
    """
    items = await repository.get_boq_items_by_ids(
        session, [entry_input.boq_item_id for entry_input in inputs]
    )

    seen: set[uuid.UUID] = set()
    resolved: list[_ResolvedLine] = []
    for line_input in inputs:
        if line_input.boq_item_id in seen:
            # Kismi UQ `uq_site_diary_lines_boq_item` ihlali GOVDE ICINDE yakalanir;
            # `IntegrityError` emniyet agi olarak kalir.
            raise DuplicateError(guards.DUPLICATE_LINE)
        seen.add(line_input.boq_item_id)

        item = items.get(line_input.boq_item_id)
        if item is None or item.site_id != entry.site_id:
            # Var OLMAYAN poz ile BASKA santiyenin pozu AYNI 422'yi alir
            # (IDOR yuzeyi: kimlik varligi sizdirilmaz).
            raise SiteValidationError(guards.LINE_ITEM_MISMATCH)
        resolved.append(_ResolvedLine(item=item, quantity=line_input.quantity))
    return resolved


def _new_line(plan: _ResolvedLine) -> SiteDiaryLine:
    """Snapshot DÖRTLÜSÜ yalnız BOQ kaleminden kopyalanır — istekten ASLA.

    Mevcut satırın snapshot'ı DONMUŞTUR (yeniden kopyalanmaz): bir günün kaydı
    o gün geçerli olan fiyatı taşır, BOQ sonradan güncellenirse geçmiş gün
    kendiliğinden değişmemelidir.
    """
    return SiteDiaryLine(
        boq_item_id=plan.item.id,
        code=plan.item.code,
        description=plan.item.description,
        unit=plan.item.unit,
        unit_price=plan.item.unit_price,
        quantity=plan.quantity,
    )


async def apply_lines(
    session: AsyncSession, entry: SiteDiaryEntry, inputs: list[SiteDiaryLineInput]
) -> int:
    """Gövdeyi kayda uygular (DEĞİŞTİRME semantiği); düşen bağı-kopmuş satır
    sayısını döner.

    Var olan satır KORUNUR (kimliği ve snapshot'ı ile), yalnız `quantity`
    güncellenir. Bağı kopmuş satır (`boq_item_id IS NULL`) gövdeden ADRESLENEMEZ,
    bu yüzden ilk kaydetmede düşer — kaçınılmaz ama SESSİZ değil: sayısı
    döndürülür ve yanıtın `dropped_orphan_count` alanıyla bildirilir.
    """
    existing = {line.boq_item_id: line for line in entry.lines if line.boq_item_id is not None}
    dropped_orphan_count = sum(1 for line in entry.lines if line.boq_item_id is None)
    resolved = await _resolve(session, entry, inputs)

    # --- Buradan itibaren yazma; dogrulama YOK (yukaridaki sira kisiti). ---
    new_lines: list[SiteDiaryLine] = []
    for plan in resolved:
        line = existing.get(plan.item.id)
        if line is None:
            line = _new_line(plan)
        else:
            line.quantity = plan.quantity
        new_lines.append(line)
    entry.lines = new_lines
    await session.flush()
    return dropped_orphan_count


def apply_worker_counts(entry: SiteDiaryEntry, inputs: list[SiteDiaryWorkerCountInput]) -> None:
    """`PATCH` gövdesindeki `worker_counts[]` — DEĞİŞTİRME semantiği.

    Satır kimliği (`trade`, `source`) İKİLİSİDİR: UQ (entry_id, trade, source)
    ihlali `IntegrityError`a DÜŞMEDEN, gövde içinde 409 olur (kullanıcı "Veri
    bütünlüğü hatası" değil NE YAPACAĞINI görür). Aynı meslek FARKLI kaynakla
    meşrudur (GK418-430) — çakışan yalnız ÜÇLÜNÜN tamamıdır.

    `trade` kırpılması Pydantic katmanındadır (`SiteDiaryWorkerCountInput`):
    çakışma kontrolü KIRPILMIŞ değer üzerinden koşar, yoksa " Kalıpçı" gövdede
    çakışmadan geçip DB'de UQ'ya takılırdı.
    """
    seen: set[tuple[str, str]] = set()
    for row_input in inputs:
        key = (row_input.trade, row_input.source.value)
        if key in seen:
            raise DuplicateError(guards.DUPLICATE_WORKER_COUNT)
        seen.add(key)

    existing = {(row.trade, row.source.value): row for row in entry.worker_counts}
    new_rows: list[SiteDiaryWorkerCount] = []
    for row_input in inputs:
        row = existing.get((row_input.trade, row_input.source.value))
        if row is None:
            row = SiteDiaryWorkerCount(
                trade=row_input.trade, source=row_input.source, count=row_input.count
            )
        else:
            row.count = row_input.count
        new_rows.append(row)
    entry.worker_counts = new_rows
