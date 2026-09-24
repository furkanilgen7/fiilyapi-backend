"""Planlama (EV) sirket katalogu + disiplin is kurallari (PLANLAMA-SPEC §3.8 K2/K4, §3.9 B1-9).

Sirket duzeyidir: santiye kapsami YOKTUR (izin kapisi yeter, `access.py`).

## Benzersizlik
Disiplin kodu ve katalogun (disiplin, ad, birim) uclusu once acik SELECT ile
sinanir → `DuplicateError` alanina ozel Turkce metinle (409). DB `UniqueConstraint`
yaris durumu emniyet agi olarak KALIR (`IntegrityError` → 409 genel isleyici).

## Silme
Disiplin yalniz HICBIR EV tablosunda kullanilmiyorsa silinir (B1-9); katalog
kalemi silinmez/arsivlenmez (B1-9) — ucu yoktur.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DuplicateError, NotFoundError, RelatedRecordsExistError
from app.modules.earned_value import guards
from app.modules.earned_value.models import (
    RATE_PRECISION,
    EvBaselineLeaf,
    EvCatalogItem,
    EvDiscipline,
    EvDistribution,
    EvGroupDiscipline,
    EvItemSettings,
    EvRevision,
    EvWindow,
)
from app.modules.earned_value.schemas_catalog import (
    CatalogActual,
    CatalogItemCreate,
    CatalogItemRead,
    CatalogItemUpdate,
    DisciplineCreate,
    DisciplineRef,
    DisciplineUpdate,
)

#: Katalog oran kolonunun kuantumu (Numeric(12,4)) — benimsenen ortalama buna oturur.
_RATE_QUANTUM = Decimal(1).scaleb(-RATE_PRECISION[1])

#: Disiplini "kullanimda" sayan tablolar (B1-9). FK'leri RESTRICT'tir; bu liste
#: 409'u Turkce metinle vermek icindir, DB kisiti ikinci katmandir.
_DISCIPLINE_USERS = (
    EvGroupDiscipline.discipline_id,
    EvCatalogItem.discipline_id,
    EvDistribution.discipline_id,
    EvWindow.discipline_id,
    EvBaselineLeaf.discipline_id,
)


@dataclass(frozen=True)
class CatalogItemRow:
    """Listeleme/yanit icin katalog kalemi + disiplini + turevleri."""

    item: EvCatalogItem
    discipline: EvDiscipline
    used_by_site_count: int
    actual: CatalogActual


# ------------------------------------------------------------------ disiplin


async def list_disciplines(session: AsyncSession) -> list[EvDiscipline]:
    stmt = select(EvDiscipline).order_by(EvDiscipline.sort_order, EvDiscipline.code)
    return list((await session.execute(stmt)).scalars())


async def get_discipline(session: AsyncSession, discipline_id: uuid.UUID) -> EvDiscipline:
    discipline = await session.get(EvDiscipline, discipline_id)
    if discipline is None:
        raise NotFoundError(guards.DISCIPLINE_MISSING)
    return discipline


async def _assert_code_free(
    session: AsyncSession, code: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(EvDiscipline.id).where(EvDiscipline.code == code)
    if exclude_id is not None:
        stmt = stmt.where(EvDiscipline.id != exclude_id)
    if (await session.execute(stmt.limit(1))).first() is not None:
        raise DuplicateError(guards.DISCIPLINE_CODE_TAKEN)


async def create_discipline(session: AsyncSession, data: DisciplineCreate) -> EvDiscipline:
    await _assert_code_free(session, data.code)
    discipline = EvDiscipline(**data.model_dump())
    session.add(discipline)
    await session.flush()
    return discipline


async def update_discipline(
    session: AsyncSession, discipline_id: uuid.UUID, data: DisciplineUpdate
) -> EvDiscipline:
    discipline = await get_discipline(session, discipline_id)
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != discipline.code:
        await _assert_code_free(session, changes["code"], exclude_id=discipline.id)
    for field, value in changes.items():
        setattr(discipline, field, value)
    await session.flush()
    return discipline


async def discipline_in_use(session: AsyncSession, discipline_id: uuid.UUID) -> bool:
    clauses = [exists().where(column == discipline_id) for column in _DISCIPLINE_USERS]
    return bool((await session.execute(select(or_(*clauses)))).scalar_one())


async def delete_discipline(session: AsyncSession, discipline_id: uuid.UUID) -> EvDiscipline:
    """Kullanilmayan disiplini siler; silinen kaydi (denetim metni icin) doner."""
    discipline = await get_discipline(session, discipline_id)
    if await discipline_in_use(session, discipline.id):
        raise RelatedRecordsExistError(guards.DISCIPLINE_IN_USE)
    await session.delete(discipline)
    await session.flush()
    return discipline


# ------------------------------------------------------------------- katalog


def _empty_actual() -> CatalogActual:
    return CatalogActual(avg=None, min=None, max=None, site_count=0, sites=[])


async def catalog_actuals(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> Mapping[uuid.UUID, CatalogActual]:
    """Katalog kalemlerinin GERCEKLESEN birim oranlari (K4) — TEK kaynak.

    Kural (K4): yalniz TAMAMLANMIS santiyeler girer; ortalama MIKTAR AGIRLIKLI
    Σspent / Σqty'dir (santiyeler arasi basit ortalama DEGIL); min/max santiye
    oranlaridir; `sites` ortalamaya giren santiyelerdir.

    ⚠️ B1'de BILEREK BOS doner: gerceklesenin girdisi (kalem × bolum gunluk miktari
    + is koduna dagitilmis saat) saha verisidir ve PLN-B2'de dogar. B3 bu fonksiyonu
    DOLDURUR; imzasi ve donus sekli sabittir, cagiranlar (liste, "gerceklesen standart
    yap") degismez. Bugun her kalem: avg/min/max `None`, `site_count` 0, `sites` [].
    """
    del session  # B3'te okunacak; bugun kullanilmiyor.
    return {item_id: _empty_actual() for item_id in item_ids}


def diff_ratio(actual: CatalogActual, standard: Decimal) -> Decimal | None:
    """(ortalama − standart) ÷ standart; ortalama yoksa `None`. Ham oran, yuvarlamasiz."""
    if actual.avg is None:
        return None
    return (actual.avg - standard) / standard


async def _used_by_site_counts(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Kalemi butcesinde baglamis (`ev_item_settings.catalog_item_id`) DISTINCT santiye."""
    if not item_ids:
        return {}
    stmt = (
        select(EvItemSettings.catalog_item_id, func.count(func.distinct(EvRevision.site_id)))
        .join(EvRevision, EvRevision.id == EvItemSettings.revision_id)
        .where(EvItemSettings.catalog_item_id.in_(item_ids))
        .group_by(EvItemSettings.catalog_item_id)
    )
    return {item_id: count for item_id, count in (await session.execute(stmt)).all()}


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _rows(
    session: AsyncSession, pairs: list[tuple[EvCatalogItem, EvDiscipline]]
) -> list[CatalogItemRow]:
    ids = [item.id for item, _ in pairs]
    counts = await _used_by_site_counts(session, ids)
    actuals = await catalog_actuals(session, ids)
    return [
        CatalogItemRow(
            item=item,
            discipline=discipline,
            used_by_site_count=counts.get(item.id, 0),
            actual=actuals.get(item.id) or _empty_actual(),
        )
        for item, discipline in pairs
    ]


async def list_catalog(
    session: AsyncSession, discipline_id: uuid.UUID | None, q: str | None
) -> list[CatalogItemRow]:
    stmt = select(EvCatalogItem, EvDiscipline).join(
        EvDiscipline, EvDiscipline.id == EvCatalogItem.discipline_id
    )
    if discipline_id is not None:
        stmt = stmt.where(EvCatalogItem.discipline_id == discipline_id)
    if q is not None and q.strip():
        stmt = stmt.where(EvCatalogItem.name.ilike(_like_pattern(q.strip()), escape="\\"))
    stmt = stmt.order_by(EvDiscipline.sort_order, EvDiscipline.code, EvCatalogItem.name)
    pairs = [(item, discipline) for item, discipline in (await session.execute(stmt)).all()]
    return await _rows(session, pairs)


async def _catalog_row(session: AsyncSession, item: EvCatalogItem) -> CatalogItemRow:
    discipline = await get_discipline(session, item.discipline_id)
    return (await _rows(session, [(item, discipline)]))[0]


async def get_catalog_item(session: AsyncSession, item_id: uuid.UUID) -> EvCatalogItem:
    item = await session.get(EvCatalogItem, item_id)
    if item is None:
        raise NotFoundError(guards.CATALOG_ITEM_MISSING)
    return item


async def _assert_item_free(
    session: AsyncSession,
    discipline_id: uuid.UUID,
    name: str,
    uom: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(EvCatalogItem.id).where(
        EvCatalogItem.discipline_id == discipline_id,
        EvCatalogItem.name == name,
        EvCatalogItem.uom == uom,
    )
    if exclude_id is not None:
        stmt = stmt.where(EvCatalogItem.id != exclude_id)
    if (await session.execute(stmt.limit(1))).first() is not None:
        raise DuplicateError(guards.CATALOG_ITEM_TAKEN)


async def create_catalog_item(session: AsyncSession, data: CatalogItemCreate) -> CatalogItemRow:
    # Govde ici varlik referansi: disiplin yoksa 404 (repo kanonu).
    await get_discipline(session, data.discipline_id)
    await _assert_item_free(session, data.discipline_id, data.name, data.uom)
    item = EvCatalogItem(**data.model_dump(), standard_updated_at=datetime.now(UTC))
    session.add(item)
    await session.flush()
    return await _catalog_row(session, item)


async def update_catalog_item(
    session: AsyncSession, item_id: uuid.UUID, data: CatalogItemUpdate
) -> CatalogItemRow:
    item = await get_catalog_item(session, item_id)
    changes = data.model_dump(exclude_unset=True)
    if "discipline_id" in changes:
        await get_discipline(session, changes["discipline_id"])
    key = (
        changes.get("discipline_id", item.discipline_id),
        changes.get("name", item.name),
        changes.get("uom", item.uom),
    )
    if key != (item.discipline_id, item.name, item.uom):
        await _assert_item_free(session, *key, exclude_id=item.id)
    new_rate = changes.get("standard_unit_mhr")
    if new_rate is not None and new_rate != item.standard_unit_mhr:
        item.standard_updated_at = datetime.now(UTC)
    for field, value in changes.items():
        setattr(item, field, value)
    await session.flush()
    return await _catalog_row(session, item)


@dataclass(frozen=True)
class AdoptResult:
    row: CatalogItemRow
    old: Decimal
    new: Decimal


async def adopt_actual(session: AsyncSession, item_id: uuid.UUID) -> AdoptResult:
    """KAT "Gerceklesen standart yap": standart ← gerceklesen ortalama (K4).

    Gerceklesen yoksa 409 — B1'de gerceklesen hic yoktur (`catalog_actuals`), yani
    bu uc B3'e kadar HER ZAMAN 409 doner. Mevcut butceler etkilenmez (oran atama
    aninda kopyalanir, K4).
    """
    item = await get_catalog_item(session, item_id)
    actual = (await catalog_actuals(session, [item.id])).get(item.id)
    if actual is None or actual.avg is None:
        raise ConflictError(guards.CATALOG_NO_ACTUAL)
    old = item.standard_unit_mhr
    new = actual.avg.quantize(_RATE_QUANTUM)
    item.standard_unit_mhr = new
    item.standard_updated_at = datetime.now(UTC)
    await session.flush()
    return AdoptResult(row=await _catalog_row(session, item), old=old, new=new)


def to_read(row: CatalogItemRow) -> CatalogItemRead:
    item = row.item
    return CatalogItemRead(
        id=item.id,
        discipline=DisciplineRef.model_validate(row.discipline),
        name=item.name,
        uom=item.uom,
        standard_unit_mhr=item.standard_unit_mhr,
        default_contractor_type=item.default_contractor_type,
        description=item.description,
        standard_updated_at=item.standard_updated_at,
        used_by_site_count=row.used_by_site_count,
        actual=row.actual,
        diff_pct=diff_ratio(row.actual, item.standard_unit_mhr),
    )
