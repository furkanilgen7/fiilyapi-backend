"""ILR-2 — MALI ilerleme: **ONAYLANMIS ISVEREN hakedisinden** proje duzeyinde oran.

🔴 **TASERON hakedisi ILERLEME KAYNAGI DEGILDIR** — o MALIYET tarafidir. Onunla
ilerleme olcmek, ne kadar harcadigini ne kadar ilerledigin sanmaktir. Bu modul
YALNIZ `progress_payments` (isveren) tablosunu okur; `subcontractor_*` hicbir
sorguya girmez.

FORMUL — fizikselle **AYNI AILE**, bu yuzden ikisi karsilastirilabilir:

    mali % = Σ(onaylanmis kumulatif miktar × SOZLESME birim fiyati)
             / Σ(sozlesme kalemi miktari × birim fiyati)

Payda `repository.get_contract_items_total_value` ile ALINIR, KOPYALANMAZ (K3):
`service._progress_block:561` de ayni fonksiyonu cagirir — ikinci bir carpim
yazmak kurus farkli bir "sozlesme bedeli" uretirdi.

🔴 **NICIN BRUT/`contract.amount` DEGIL:** brut tutar fiyat farki katsayisini ve
teminat/avans mahsubunu tasir; fizikselle ayni birimde OLMAZ ve "fiziksel %60 ·
mali %35" karsilastirmasi anlamsizlasirdi. Ikisi de ayni sozlesme fiyatiyla
tartilmis MIKTAR oranidir; aradaki fark yalnizca ONAY gecikmesini gosterir —
yonetimin baktigi sayi tam olarak budur.

KAPSAM: `status ∈ {approved, paid}` (`COMPLETED_STATUSES`). Taslak/beklemedeki
hakedis GIRMEZ — `lines.completed_totals` bu suzgeci zaten tek yerde tutar.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.progress import weighted_pct
from app.modules.progress_payments import lines, repository

_ZERO = Decimal("0")


async def financial_for_project(session: AsyncSession, project_id: uuid.UUID) -> Decimal | None:
    """Projenin MALI ilerlemesi. Sozlesme kalemi yoksa yuzde YOKTUR (`None`).

    Hakedis hic yoksa sonuc `0.00`'dir — "bilinmiyor" DEGIL, GERCEKTEN sifir:
    sozlesme kalemleri vardir, onaylanmis hakedis yoktur.
    """
    totals = await lines.completed_totals(session, project_id)
    item_ids = list({contract_item_id for contract_item_id, _ in totals})
    items = await repository.get_employer_items_by_ids(session, item_ids)

    numerator = _ZERO
    for (contract_item_id, _site_id), (quantity, _amount) in totals.items():
        item = items.get(contract_item_id)
        if item is None:
            # Kalemi silinmis satir: `totals_from_payments` zaten `None` kalem
            # kimligini atlar; burada olusabilecek tek hâl kalemin ARADA
            # silinmesidir — ONAYLI SAPMA, ayni gerekce (spec §6.5 notu).
            continue
        numerator += quantity * item.unit_price

    denominator = await repository.get_contract_items_total_value(session, project_id)
    return weighted_pct(numerator, denominator)
