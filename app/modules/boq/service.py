import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq import repository
from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.boq.schemas import (
    BoqGroupResponse,
    BoqItemResponse,
    BoqListResponse,
    BoqTotals,
    MetricPlaceholder,
)

# Gorunurluk suzgeci P2'DEN GELIR (plan T3 notu): site->proje cozumu kopyalanmaz,
# `sites.service._visible_site` yeniden kullanilir. Ayni desen zaten
# `projects.service`'in `sites.service._unique_code`/`derive_code`'u yeniden
# kullanmasinda var (bkz. app/modules/projects/service.py).
from app.modules.sites.service import _visible_site
from app.modules.users.models import User

# Spec §3.2/§5.1: bu dilimde YAZILMAYAN turev alanlarin bagli oldugu modul
# anahtarlari. Kullaniciya gosterilecek metin degil, B6 sozlesmesindeki
# pending_module anahtaridir.
_CONTRACTS = "contracts"
_PROGRESS_PAYMENTS = "progress_payments"

_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def to_item(item: BoqItem) -> BoqItemResponse:
    return BoqItemResponse(
        id=item.id,
        code=item.code,
        description=item.description,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        progress_pct=_metric(_PROGRESS_PAYMENTS),
        sort_order=item.sort_order,
    )


def to_group(group: BoqGroup) -> BoqGroupResponse:
    return BoqGroupResponse(
        id=group.id,
        name=group.name,
        sort_order=group.sort_order,
        items=[to_item(item) for item in group.items],
    )


def _totals(groups: list[BoqGroupResponse]) -> BoqTotals:
    """Spec §5.1: `grand_total` GERCEK (gruplarin toplami), geri kalani yer
    tutucu. Toplama Decimal ile yapilir (float ASLA); bos BOQ "0.00" doner."""
    grand_total = _quantize_money(sum((group.group_total for group in groups), Decimal("0")))
    return BoqTotals(
        contract_total=_metric(_CONTRACTS),
        realized_total=_metric(_PROGRESS_PAYMENTS),
        remaining_total=_metric(_PROGRESS_PAYMENTS),
        revision_total=_metric(_CONTRACTS),
        grand_total=grand_total,
        grand_progress_pct=_metric(_PROGRESS_PAYMENTS),
    )


async def get_boq_for_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> BoqListResponse:
    """Spec §5.1 okuma yolu. Gorunmeyen santiye 404 doner (P2 §5.2 deseni),
    403 degil — varligin kendisi sizdirilmaz."""
    site, _ = await _visible_site(session, actor, site_id)
    groups = [to_group(group) for group in await repository.list_groups_for_site(session, site.id)]
    return BoqListResponse(totals=_totals(groups), groups=groups)
