"""K4 katalog gerçekleşeni — tamamlanmış şantiye, miktar ağırlıklı.

Kurgu (conftest `baseline` + `saha_gunu`): I1 "Beton" katalog "Beton"a bağlı (aktif revizyon).
Gün 05.05: I1 Bölümsüz 5 m3 · Ali 9 sa direct l:I1:none · Veli 8 sa prorata i:I1 → i:I1
spent_cum = 17, qty_cum = 5 → oran 3,4 a-s/m3. Şantiye TAMAMLANINCA ortalamaya girer.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.earned_value import catalog_service
from app.modules.earned_value.models import EvItemSettings, EvRevision, RevisionStatus
from app.modules.sites.models import SiteStatus

from .test_day_allocation import _body, _day

D = Decimal


async def _link_and_allocate(client, saha, seeded_db, santiye, boq, katalog, saha_gunu) -> None:  # noqa: ANN001
    from sqlalchemy import select

    active = (
        await seeded_db.execute(
            select(EvRevision).where(
                EvRevision.site_id == santiye.id, EvRevision.status == RevisionStatus.ACTIVE
            )
        )
    ).scalar_one()
    seeded_db.add(
        EvItemSettings(
            revision_id=active.id,
            boq_item_id=boq["i1"].id,
            is_direct=True,
            catalog_item_id=katalog["beton"].id,
        )
    )
    await seeded_db.flush()
    body = _body(boq, saha_gunu["ali"], saha_gunu["veli"])
    assert (
        await client.put(_day(santiye, "/allocation"), headers=saha, json=body)
    ).status_code == 200


async def test_active_site_does_not_feed_catalog(
    client, saha, seeded_db, santiye, boq, katalog, baseline, saha_gunu
) -> None:
    await _link_and_allocate(client, saha, seeded_db, santiye, boq, katalog, saha_gunu)
    actual = (await catalog_service.catalog_actuals(seeded_db, [katalog["beton"].id]))[
        katalog["beton"].id
    ]
    assert actual.site_count == 0  # şantiye aktif → girmez


async def test_completed_site_feeds_quantity_weighted_actual(
    client, saha, seeded_db, santiye, boq, katalog, baseline, saha_gunu
) -> None:
    await _link_and_allocate(client, saha, seeded_db, santiye, boq, katalog, saha_gunu)
    santiye.status = SiteStatus.completed
    await seeded_db.flush()
    actual = (await catalog_service.catalog_actuals(seeded_db, [katalog["beton"].id]))[
        katalog["beton"].id
    ]
    assert actual.site_count == 1
    assert actual.avg == D(17) / D(5)
    assert (actual.min, actual.max) == (D(17) / D(5), D(17) / D(5))
    assert (actual.sites[0].qty, actual.sites[0].rate) == (D(5), D(17) / D(5))
    other = (await catalog_service.catalog_actuals(seeded_db, [katalog["tugla"].id]))[
        katalog["tugla"].id
    ]
    assert other.site_count == 0  # bağı olmayan katalog kalemi etkilenmez


async def test_budget_suggestions_carry_recent_completed_site_actual(
    client, saha, admin, seeded_db, santiye, boq, katalog, baseline, saha_gunu
) -> None:
    """Bütçe öneri popover'ı: aday katalog kaleminin "son 3 şantiye gerçekleşen"i (K4)."""
    await _link_and_allocate(client, saha, seeded_db, santiye, boq, katalog, saha_gunu)
    url = f"/sites/{santiye.id}/earned-value/budget/items/{boq['i1'].id}/suggestions"
    before = (await client.get(url, headers=admin)).json()
    beton = str(katalog["beton"].id)
    [row] = [r for r in before["recent_actuals"] if r["catalog_item_id"] == beton]
    assert (row["site_count"], row["avg"]) == (0, None)  # aktif şantiye girmez
    santiye.status = SiteStatus.completed
    await seeded_db.flush()
    after = (await client.get(url, headers=admin)).json()
    [row] = [r for r in after["recent_actuals"] if r["catalog_item_id"] == beton]
    assert (row["site_count"], D(row["avg"])) == (1, D(17) / D(5))
    assert after["history"] == []  # kullanılmaz alan boş kalır


async def test_recent_site_actuals_keeps_newest_three(monkeypatch) -> None:
    import uuid
    from datetime import date

    from app.modules.earned_value import actuals

    cid = uuid.uuid4()

    def site(name: str, end: date | None) -> actuals.SiteItemActual:
        return actuals.SiteItemActual(uuid.uuid4(), name, end, D(1), D(2))

    rows = [
        site("eski", date(2024, 1, 1)),
        site("tarihsiz", None),
        site("yeni", date(2026, 1, 1)),
        site("orta", date(2025, 1, 1)),
        site("orta2", date(2025, 6, 1)),
    ]

    async def fake(_session, ids):  # noqa: ANN001, ANN202
        return {i: rows for i in ids}

    monkeypatch.setattr(actuals, "completed_site_actuals", fake)
    got = await actuals.recent_site_actuals(None, [cid])  # type: ignore[arg-type]
    assert [s.site_name for s in got[cid]] == ["yeni", "orta2", "orta"]
