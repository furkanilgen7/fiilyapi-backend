"""Dağıtılmış/kalan miktarın TEK KAYNAĞI (TB4 · B2, spec §1 B2).

P5'ten devreden borç: "kalan" iki ayrı yerde, İKİ FARKLI kümeden toplanıyordu:

* **aşım kontrolü** (`distribution._assert_within_contract_quantity`) —
  `repository.list_boq_items_for_sites` ile **projenin şantiyelerinden** gelen
  satırlar, `(contract_item_id, site_id)` çiftinde tekilleştirilmiş,
* **göstergeler** (`distribution._to_distribution_item` ve
  `service.to_item_response`) — `contract_item_id` üzerinden **TÜM** BOQ
  satırları (`list_distributed_boq_items` / `sum_distributed_quantities`),
  satırın şantiyesi hangi projede olursa olsun ve aynı çiftin birden çok
  satırı varsa hepsi.

İki küme normalde aynı sonucu verir; ayrıştıkları an (kaleme bağlı bir BOQ
satırı projenin dışındaki bir şantiyede kalmışsa — şantiye devri) gösterge
"kalan 0" derken kota kontrolü hâlâ yer olduğunu sanıyordu, yani ekran ile
kapı çelişiyordu.

Karar (spec §1 B2): **aşım kontrolünün kümesi OTORİTEDİR** — kota neyi sayıyorsa
gösterge de onu sayar. Bu modül o kümeyi tek yerde tanımlar; hem kapılar hem
göstergeler buradan geçer.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqItem
from app.modules.contracts import repository
from app.modules.sites import repository as sites_repository

AllocationKey = tuple[uuid.UUID, uuid.UUID]  # (contract_item_id, site_id)


def index_allocations(boq_rows: Iterable[BoqItem]) -> dict[AllocationKey, BoqItem]:
    """Otorite küme: dağıtım matrisinin (kalem, şantiye) hücreleri.

    Bağsız (`contract_item_id IS NULL`) satırlar dağıtım değildir, elenir.
    Aynı hücreye düşen birden çok satır varsa İLKİ kazanır — kaynak sorgu
    (`repository.list_boq_items_for_sites`) `id`'ye göre sıralı olduğu için
    seçim deterministiktir. Hücre tekilliği kotanın tanımıdır: yazma yolu bir
    hücreye tek satır açar, ikinci satır (BOQ ekranından `code` düzenlenerek
    doğabilir) kotayı ikinci kez harcamış sayılmaz.
    """
    indexed: dict[AllocationKey, BoqItem] = {}
    for row in boq_rows:
        if row.contract_item_id is None:
            continue
        indexed.setdefault((row.contract_item_id, row.site_id), row)
    return indexed


def distributed_totals(
    allocations: dict[AllocationKey, BoqItem],
    *,
    exclude: set[AllocationKey] | None = None,
) -> dict[uuid.UUID, Decimal]:
    """Sözleşme kalemi başına dağıtılmış toplam.

    `exclude`: gövdenin yeniden tanımladığı hücreler — yazma yolunda mevcut
    değerleri sayılmaz (yerlerine gövdedeki miktar geçer).
    """
    totals: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for key, row in allocations.items():
        if exclude is not None and key in exclude:
            continue
        totals[key[0]] += row.quantity
    return dict(totals)


async def load_allocations(
    session: AsyncSession, project_id: uuid.UUID
) -> dict[AllocationKey, BoqItem]:
    """Projenin şantiyelerindeki dağıtım hücreleri (iki sorgu, N+1 YOK)."""
    sites = await sites_repository.list_sites_for_project(session, project_id)
    rows = await repository.list_boq_items_for_sites(session, [site.id for site in sites])
    return index_allocations(rows)


async def load_distributed_totals(
    session: AsyncSession, project_id: uuid.UUID
) -> dict[uuid.UUID, Decimal]:
    return distributed_totals(await load_allocations(session, project_id))
