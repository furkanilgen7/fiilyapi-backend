"""Blok/unite okuma uclari ve TEKIL yazma uclari (spec §7.1-§7.6, §7.9).

Toplu yollar (`bulk`, `import`, `allocation`) `batch.py`'dedir; ortak korkuluklar
ve Turkce hata metinleri `guards.py`'de, saf toplama/sunum `summary.py`'dedir.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RelatedRecordsExistError
from app.modules.sites import repository as sites_repository

# Gorunurluk suzgeci P1'DEN GELIR (spec §8): kopya bir erisim mantigi YAZILMAZ.
# `guards` uzerinden yeniden disa acilir — mevcut cagiranlar `service.visible_projects`
# adini kullanir ve bu ad korunur.
from app.modules.units import guards, repository
from app.modules.units.guards import visible_projects
from app.modules.units.models import Block, Unit, UnitKind
from app.modules.units.schemas import (
    BlockCreate,
    BlockListResponse,
    BlockResponse,
    BlockUpdate,
    UnitBlockGroup,
    UnitCreate,
    UnitListResponse,
    UnitOwnerSideFilter,
    UnitResponse,
    UnitUpdate,
)
from app.modules.units.summary import VALUE_BASIS_BY_TYPE, to_block, to_unit, totals
from app.modules.users.models import User

__all__ = [
    "block_response",
    "create_block",
    "create_unit",
    "delete_block",
    "delete_unit",
    "list_blocks",
    "list_units",
    "to_block",
    "to_unit",
    "unit_response",
    "update_block",
    "update_unit",
    "visible_projects",
]


# --- Okuma uclari (spec §7.1, §7.4) ---


async def _blocks_with_units(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[tuple[Block, str]], dict[uuid.UUID, list[Unit]], list[Unit]]:
    """Bloklar + unitelerin bloklara dagilmis hâli + duz unite listesi.

    Uniteler TEK sorguda cekilir (repository notu); dagitim Python'dadir.
    """
    blocks = await repository.list_blocks_for_project(session, project_id)
    units = await repository.list_units_for_project(session, project_id)
    by_block: dict[uuid.UUID, list[Unit]] = {block.id: [] for block, _ in blocks}
    for unit in units:
        by_block.setdefault(unit.block_id, []).append(unit)
    return blocks, by_block, units


async def list_blocks(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> BlockListResponse:
    """Spec §7.1. Blok seciciler (unite formu, toplu uretim formu) bu ucu kullanir."""
    await guards.visible_project(session, actor, project_id)
    blocks, by_block, _ = await _blocks_with_units(session, project_id)
    return BlockListResponse(
        blocks=[to_block(block, site_name, by_block[block.id]) for block, site_name in blocks]
    )


def _matches(unit: Unit, kind: UnitKind | None, owner_side: UnitOwnerSideFilter | None) -> bool:
    if kind is not None and unit.unit_kind is not kind:
        return False
    if owner_side is None:
        return True
    if owner_side is UnitOwnerSideFilter.unassigned:
        return unit.owner_side is None
    return unit.owner_side is not None and unit.owner_side.value == owner_side.value


async def list_units(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    *,
    block_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    kind: UnitKind | None = None,
    owner_side: UnitOwnerSideFilter | None = None,
) -> UnitListResponse:
    """Spec §7.4. Suzgecler YALNIZ listeyi daraltir; `totals` daima projenin
    tamamini sayar. `site_id` suzgeci blok uzerinden calisir — `units`'te
    `site_id` sutunu YOKTUR (spec §4.0). Unitesi olmayan blok listede KALIR."""
    project = await guards.visible_project(session, actor, project_id)
    blocks, by_block, units = await _blocks_with_units(session, project_id)
    basis = VALUE_BASIS_BY_TYPE[project.project_type]

    selected = [
        (block, site_name)
        for block, site_name in blocks
        if (block_id is None or block.id == block_id)
        and (site_id is None or block.site_id == site_id)
    ]
    groups = [
        UnitBlockGroup(
            block=to_block(block, site_name, by_block[block.id]),
            units=[
                to_unit(unit, block.name)
                for unit in by_block[block.id]
                if _matches(unit, kind, owner_side)
            ],
        )
        for block, site_name in selected
    ]
    return UnitListResponse(totals=totals(units, basis), blocks=groups)


# --- Yanit zarflari ---


async def block_response(session: AsyncSession, block: Block) -> BlockResponse:
    site = await sites_repository.get_site(session, block.site_id)
    units = await repository.list_units_for_block(session, block.id)
    # `site` None olamaz: `site_id` NOT NULL + FK. Kosul yalnizca tip
    # daraltmasi icindir, sessiz bir dusus degil.
    return to_block(block, site.name if site is not None else "", units)


async def unit_response(session: AsyncSession, unit: Unit) -> UnitResponse:
    block = await repository.get_block(session, unit.block_id)
    # `block` None olamaz: `block_id` NOT NULL + FK. Kosul yalnizca tip
    # daraltmasi icindir, sessiz bir dusus degil.
    return to_unit(unit, block.name if block is not None else "")


# --- Blok yazma uclari (spec §7.2, §7.3) ---


async def create_block(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: BlockCreate
) -> Block:
    project = await guards.visible_project(session, actor, project_id)
    site = await guards.resolve_site(session, project.id, data.site_id)
    await guards.ensure_block_name_unique(session, project.id, data.name)
    block = Block(
        project_id=project.id, site_id=site.id, name=data.name, sort_order=data.sort_order
    )
    session.add(block)
    await session.flush()
    await session.refresh(block)
    return block


async def update_block(
    session: AsyncSession, actor: User, block_id: uuid.UUID, data: BlockUpdate
) -> Block:
    """Spec §7.3. `site_id` degistirilebilir (blok yanlis santiyeye acilmissa);

    yeni santiye AYNI projede olmali, degilse **404** (spec §4.5 son paragrafi ve
    plan B5 test 13). Spec §7.3'un hata listesinde bu durum icin "422" yaziyor —
    §4.5 ve plan 404 dedigi icin 404 uygulanmistir.
    """
    block, project = await guards.visible_block(session, actor, block_id)
    updates = data.model_dump(exclude_unset=True)
    if updates.get("site_id") is not None:
        site = await guards.resolve_site(session, project.id, updates["site_id"])
        updates["site_id"] = site.id
    else:
        # `site_id: null` gonderimi sutunu bosaltamaz (NOT NULL) — yok sayilir.
        updates.pop("site_id", None)
    if updates.get("name") is not None:
        await guards.ensure_block_name_unique(session, project.id, updates["name"], block.id)
    for field, value in updates.items():
        if value is not None:
            setattr(block, field, value)
    await session.flush()
    await session.refresh(block)
    return block


# --- Unite yazma uclari (spec §7.5, §7.6, §3.3) ---


async def create_unit(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: UnitCreate
) -> Unit:
    """Spec §7.5. `taahhut` projede unite tanimlamak SERBEST (§3.3 — kisit icat
    edilmez); iki fiyat sutunu da her tipte kabul edilir (§4.4)."""
    project = await guards.visible_project(session, actor, project_id)
    block = await guards.block_in_project(session, project, data.block_id)
    guards.ensure_owner_side_allowed(project, data.owner_side)
    guards.ensure_net_le_gross(data.gross_area_m2, data.net_area_m2)
    await guards.ensure_unit_no_unique(session, block.id, data.unit_no)
    unit = Unit(
        project_id=project.id,
        block_id=block.id,
        unit_no=data.unit_no,
        unit_kind=data.unit_kind,
        layout=data.layout,
        gross_area_m2=data.gross_area_m2,
        net_area_m2=data.net_area_m2,
        list_price=data.list_price,
        appraisal_value=data.appraisal_value,
        owner_side=data.owner_side,
        sort_order=data.sort_order,
    )
    session.add(unit)
    await session.flush()
    await session.refresh(unit)
    return unit


async def update_unit(
    session: AsyncSession, actor: User, unit_id: uuid.UUID, data: UnitUpdate
) -> Unit:
    """Spec §7.6. `exclude_unset` ayrimi kritiktir: GONDERILMEYEN alan degismez,
    `null` GONDERILEN alan bosalir (P1/P2/P4 deseni).

    Kurallar birlesmis (mevcut + gonderilen) deger uzerinde yeniden calisir:
    yalniz `net_area_m2` gonderen bir istek, mevcut `gross_area_m2` ile
    karsilastirilmazsa DB CHECK'ine duser ve kullanici anlamsiz bir 409 gorur.
    """
    unit, project = await guards.visible_unit(session, actor, unit_id)
    updates = data.model_dump(exclude_unset=True)

    target_block_id = unit.block_id
    if "block_id" in updates and updates["block_id"] is not None:
        target_block_id = (await guards.block_in_project(session, project, updates["block_id"])).id
    updates.pop("block_id", None)  # NOT NULL: `null` gonderimi sutunu bosaltamaz

    owner_side = updates["owner_side"] if "owner_side" in updates else unit.owner_side
    guards.ensure_owner_side_allowed(project, owner_side)
    gross = updates["gross_area_m2"] if "gross_area_m2" in updates else unit.gross_area_m2
    net = updates["net_area_m2"] if "net_area_m2" in updates else unit.net_area_m2
    guards.ensure_net_le_gross(gross, net)

    target_unit_no = updates.get("unit_no") or unit.unit_no
    if target_block_id != unit.block_id or target_unit_no != unit.unit_no:
        await guards.ensure_unit_no_unique(session, target_block_id, target_unit_no, unit.id)

    unit.block_id = target_block_id
    for field, value in updates.items():
        # NOT NULL sutunlar `null` ile bosaltilamaz; nullable olanlar bosaltilir.
        if value is None and field in ("unit_no", "unit_kind", "sort_order"):
            continue
        setattr(unit, field, value)
    await session.flush()
    await session.refresh(unit)
    return unit


# --- Silme uclari (spec §7.9) — VERI KAYBI SINIFI ---


async def delete_unit(session: AsyncSession, actor: User, unit_id: uuid.UUID) -> None:
    """Spec §7.9. Unite silme KOSULSUZDUR: P3'te uniteye baglanan hicbir tablo
    yoktur (spec §1.3). P8 (satis) geldiginde satisi olan unite icin korkuluk
    O DILIMDE eklenecektir — bugun var olmayan bir bag icin kontrol yazilmaz.

    Gorunurluk yine yukari cozumlenir: gorunmeyen projenin unitesi 404'tur ve
    var olmayan unite ile ayni mesaji verir (IDOR-6/IDOR-7).
    """
    unit, _ = await guards.visible_unit(session, actor, unit_id)
    await session.delete(unit)
    await session.flush()


async def delete_block(session: AsyncSession, actor: User, block_id: uuid.UUID) -> None:
    """Spec §7.9. CASCADE YOKTUR — bu fonksiyonun tek isi cascade'i ENGELLEMEKTIR.

    Blokta en az bir unite varsa silme 409 ile reddedilir. Uc katman birden
    korur ve UCU DE bilincli olarak yerinde birakilmistir:

    1. Buradaki `block_has_units` on kontrolu — kullaniciya Turkce, eyleme
       donuk mesaj verir ("once uniteleri silin").
    2. `units.block_id` uzerindeki `ON DELETE RESTRICT` (B1, spec §4.2) — servis
       atlanirsa DB reddeder; `IntegrityError → 409` handler'i yaris-durumu agidir.
    3. Modelde `relationship(cascade=...)` TANIMLI DEGIL — ORM'in kendiliginden
       unite silecek bir yolu yoktur.

    Mesajda unite ADEDI VERILMEZ (spec §7.9): kullanici sayiyi zaten GET ile
    goruyor, hata govdesi gorunurluk disi bilgi tasimaz.
    """
    block, _ = await guards.visible_block(session, actor, block_id)
    if await repository.block_has_units(session, block.id):
        raise RelatedRecordsExistError(guards.BLOCK_HAS_UNITS)
    await session.delete(block)
    await session.flush()
