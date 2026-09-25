"""K4 katalog gerceklesenleri — TAMAMLANMIS santiyelerin is tipi (L3) birim oranlari.

Kaynak: her tamamlanmis + aktif baseline'li santiyede motor (`ev_input` → takvim sonunda
`compute_daily_report`) · is tipinin katalog bagi = aktif revizyonun `ev_item_settings
.catalog_item_id`i. Ortalama MIKTAR AGIRLIKLI (Σspent_cum / Σqty_cum); min/max santiye
oranlari; karma birimli is tipi (qty None) ya da miktarsiz is tipi ortalamaya GIRMEZ.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.earned_value.engine import compute_daily_report
from app.modules.earned_value.ev_input import build_site_input
from app.modules.earned_value.models import EvItemSettings
from app.modules.sites.models import Site, SiteStatus

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class SiteItemActual:
    site_id: uuid.UUID
    site_name: str
    end_date: date | None
    qty: Decimal
    spent: Decimal

    @property
    def rate(self) -> Decimal:
        return self.spent / self.qty


async def completed_site_actuals(
    session: AsyncSession, catalog_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[SiteItemActual]]:
    wanted = set(catalog_ids)
    out: dict[uuid.UUID, list[SiteItemActual]] = {c: [] for c in wanted}
    if not wanted:
        return out
    sites = (
        await session.execute(select(Site).where(Site.status == SiteStatus.completed))
    ).scalars()
    for site in sites:
        site_input = await build_site_input(session, site.id, site.end_date or today())
        if site_input is None:
            continue
        links = (
            await session.execute(
                select(EvItemSettings.boq_item_id, EvItemSettings.catalog_item_id).where(
                    EvItemSettings.revision_id == site_input.revision.id,
                    EvItemSettings.catalog_item_id.in_(wanted),
                )
            )
        ).all()
        if not links:
            continue
        report = compute_daily_report(site_input.inp, site_input.inp.calendar.end_date)
        for item_id, catalog_id in links:
            m = report.nodes.get(f"i:{item_id}")
            if m is None or not m.qty_cum:
                continue
            out[catalog_id].append(
                SiteItemActual(site.id, site.name, site.end_date, m.qty_cum, m.spent_cum)
            )
    return out


RECENT_SITES = 3  # K4 butce onerisi: "son 3 santiye gerceklesen"


async def recent_site_actuals(
    session: AsyncSession, catalog_ids: Iterable[uuid.UUID], limit: int = RECENT_SITES
) -> dict[uuid.UUID, list[SiteItemActual]]:
    """Katalog kalemi basina bitis tarihi EN YENI `limit` tamamlanmis santiye (tarihsiz sona)."""
    per_item = await completed_site_actuals(session, catalog_ids)
    return {
        cid: sorted(sites, key=lambda s: (s.end_date is not None, s.end_date), reverse=True)[:limit]
        for cid, sites in per_item.items()
    }
