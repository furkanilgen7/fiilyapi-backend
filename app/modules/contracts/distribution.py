"""Poz Dağılımı okuma ucu (task C7, spec §6.3 GET kısmı, `POZ` mockup).

`GET /projects/{project_id}/contract/distribution` — bir işveren sözleşmesi
pozunun projenin şantiyelerine nasıl bölündüğünü gösteren matris. Salt okuma:
hiçbir şey yazmaz, `record_audit` çağırmaz (okuma uçları denetim günlüğüne
yazmaz — task brief kararı).

İki katmanlı koruma `contracts/service.py`'nin aynısı: router'daki `_VIEW`
YETKİYİ verir, burada yeniden kullanılan `service._visible_project` KAPSAMI
belirler — görünmeyen projenin dağılımı asla dönmez, görünmeyen kayıt ile
var olmayan kayıt AYNI 404 gövdesini verir.

Sorgu sayısı (N+1 YOK, task brief kısıtı):
1. `visible_projects` (service._visible_project içinde, mevcut desen)
2. `list_sites_for_project` — projenin şantiyeleri
3. `list_employer_groups` — gruplar
4. gruplar `.items` erişilince `lazy="selectin"` tetiklenir — TÜM grupların
   kalemleri TEK ek sorguda (C1'in tanımı)
5. `list_distributed_boq_items` — TÜM kalemlere bağlı BOQ satırları TEK `IN`
   sorgusunda

Toplam: kalem/şantiye sayısından BAĞIMSIZ, sabit sayıda sorgu.
"""

import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.boq.models import BoqItem
from app.modules.contracts import repository
from app.modules.contracts.guards import CONTRACT_MISSING
from app.modules.contracts.models import EmployerContractItem
from app.modules.contracts.schemas import (
    ContractDistributionAllocation,
    ContractDistributionGroup,
    ContractDistributionItem,
    ContractDistributionResponse,
    ContractDistributionSite,
    ContractDistributionSiteItem,
    ContractDistributionSiteSummary,
)
from app.modules.contracts.service import _visible_project
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Site
from app.modules.users.models import User

_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _allocations_by_item(boq_items: list[BoqItem]) -> dict[uuid.UUID, list[BoqItem]]:
    grouped: dict[uuid.UUID, list[BoqItem]] = defaultdict(list)
    for boq_item in boq_items:
        # `contract_item_id IS NULL` satırlar zaten `list_distributed_boq_items`
        # filtresiyle elenmiştir (spec §3.3) — burada yine de güvence için atlanır.
        if boq_item.contract_item_id is None:
            continue
        grouped[boq_item.contract_item_id].append(boq_item)
    return grouped


def _to_distribution_item(
    item: EmployerContractItem, allocations: list[BoqItem]
) -> ContractDistributionItem:
    distributed_total = sum((row.quantity for row in allocations), Decimal("0"))
    return ContractDistributionItem(
        id=item.id,
        code=item.code,
        description=item.description,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        allocations=[
            ContractDistributionAllocation(
                site_id=row.site_id, quantity=row.quantity, boq_item_id=row.id
            )
            for row in allocations
        ],
        remaining_quantity=item.quantity - distributed_total,
    )


def _site_summaries(
    sites: list[Site],
    items: list[EmployerContractItem],
    allocations_by_item: dict[uuid.UUID, list[BoqItem]],
) -> list[ContractDistributionSiteSummary]:
    """`POZ` 168-187: şantiye başına dağıtılmış kalemler + tutar.

    Spec §3.3: `total_amount` **sözleşme kaleminin** birim fiyatıyla hesaplanır,
    BOQ satırının değil — ikisi normalde aynıdır ama sözleşme otoritedir.
    """
    items_by_id = {item.id: item for item in items}
    summaries: list[ContractDistributionSiteSummary] = []
    for site in sites:
        site_items: list[ContractDistributionSiteItem] = []
        for contract_item_id, allocations in allocations_by_item.items():
            item = items_by_id.get(contract_item_id)
            if item is None:
                continue
            for row in allocations:
                if row.site_id != site.id:
                    continue
                site_items.append(
                    ContractDistributionSiteItem(
                        code=item.code,
                        description=item.description,
                        quantity=row.quantity,
                        unit_price=item.unit_price,
                        amount=_quantize_money(row.quantity * item.unit_price),
                    )
                )
        total_amount = _quantize_money(sum((row.amount for row in site_items), Decimal("0")))
        summaries.append(
            ContractDistributionSiteSummary(
                site_id=site.id,
                site_name=site.name,
                items=site_items,
                total_amount=total_amount,
            )
        )
    return summaries


async def build_distribution(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ContractDistributionResponse:
    project = await _visible_project(session, actor, project_id)
    if project.contract is None:
        raise NotFoundError(CONTRACT_MISSING)

    sites = await sites_repository.list_sites_for_project(session, project_id)
    groups = await repository.list_employer_groups(session, project_id)
    all_items = [item for group in groups for item in group.items]
    item_ids = [item.id for item in all_items]

    boq_rows = await repository.list_distributed_boq_items(session, item_ids)
    allocations_by_item = _allocations_by_item(boq_rows)

    undistributed_items = [item for item in all_items if not allocations_by_item.get(item.id)]

    return ContractDistributionResponse(
        sites=[ContractDistributionSite(id=site.id, name=site.name) for site in sites],
        groups=[
            ContractDistributionGroup(
                id=group.id,
                name=group.name,
                sort_order=group.sort_order,
                items=[
                    _to_distribution_item(item, allocations_by_item.get(item.id, []))
                    for item in group.items
                ],
            )
            for group in groups
        ],
        undistributed_item_count=len(undistributed_items),
        undistributed_item_names=[item.description for item in undistributed_items],
        site_summaries=_site_summaries(sites, all_items, allocations_by_item),
        distributed_item_count=len(all_items) - len(undistributed_items),
        total_item_count=len(all_items),
    )
