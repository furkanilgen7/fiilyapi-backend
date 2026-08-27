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

    🔴 Govdesi YOKTUR: toplu hâle DELEGE eder (K3). Iki ayri gövde, zamanla
    tek proje ile liste ekraninin farkli "%" basmasi demekti.
    """
    return (await financial_for_projects(session, [project_id]))[project_id]


async def financial_for_projects(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal | None]:
    """TOPLU mali ilerleme — proje KARTLARI icin (N+1 yasagi, `cost_cards.py`).

    Hakedisler `repository.list_completed_payments_by_projects` ile TEK sorguda
    gelir (H4 denetimi O1'in cozumu); toplama `lines.totals_from_payments` ile
    yapilir — toplama kuralinin ikinci kopyasi ACILMAZ (K3).
    """
    if not project_ids:
        return {}
    grouped = await repository.list_completed_payments_by_projects(session, project_ids)

    item_ids: set[uuid.UUID] = set()
    per_project: dict[uuid.UUID, dict[tuple[uuid.UUID, uuid.UUID | None], tuple[Decimal, Decimal]]]
    per_project = {}
    for project_id, payments in grouped.items():
        totals = lines.totals_from_payments(payments)
        per_project[project_id] = totals
        item_ids.update(contract_item_id for contract_item_id, _ in totals)

    items = await repository.get_employer_items_by_ids(session, list(item_ids))
    denominators = await repository.get_contract_items_total_by_projects(session, project_ids)

    sonuc: dict[uuid.UUID, Decimal | None] = {}
    for project_id in project_ids:
        numerator = _ZERO
        for (contract_item_id, _site_id), (quantity, _amount) in per_project.get(
            project_id, {}
        ).items():
            item = items.get(contract_item_id)
            if item is not None:
                numerator += quantity * item.unit_price
        sonuc[project_id] = weighted_pct(numerator, denominators.get(project_id, _ZERO))
    return sonuc
