import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.projects.models import Project, ProjectType

# Gorunurluk suzgeci P1'DEN GELIR (spec §8): kopya bir erisim mantigi YAZILMAZ.
# Iki ayri suzgec zamanla ayrisir ve ayrisan taraf sessiz bir yetki sizintisi
# olur. Ayni desen P2 `sites/service.py:15` ve P4 `boq/service.py`'de de var.
from app.modules.projects.service import visible_projects
from app.modules.units import repository
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from app.modules.units.schemas import (
    BlockListResponse,
    BlockResponse,
    CountPlaceholder,
    MetricPlaceholder,
    UnitBlockGroup,
    UnitKindBreakdown,
    UnitListResponse,
    UnitOwnerSideFilter,
    UnitResponse,
    UnitSideSummary,
    UnitTotals,
    UnitValueBasis,
)
from app.modules.users.models import User

# 404 GOVDESI DE AYIRT EDICI OLMAMALIDIR (P2 `sites/service.py` dersi): gorunmeyen
# proje ile var olmayan proje ayni mesaji doner, aksi hâlde elinde UUID olan
# kullanici kaydin var oldugunu ve baskasina ait oldugunu ayirt edebilirdi.
_PROJECT_MISSING = "Proje bulunamadı"

# Spec §6.1: bu dilimde YAZILMAYAN turev alanlarin bagli oldugu modul anahtarlari.
# Kullaniciya gosterilecek metin degil, B6 yer tutucu sozlesmesindeki anahtardir.
_UNIT_SALES = "unit_sales"
_SHAREHOLDER_UNITS = "shareholder_units"
_PROJECT_COSTS = "project_costs"

_MONEY = Decimal("0.01")
_HUNDRED = Decimal("100")

# Taraf ozetlerinin SABIT sirasi (spec §5.3): ucu de her zaman doner, unite
# olmasa bile. Ekran "henuz paylasilmadi" durumunu `None` grubundan basar.
_SIDE_ORDER: tuple[UnitOwnerSide | None, ...] = (
    UnitOwnerSide.contractor,
    UnitOwnerSide.landowner,
    None,
)

# Spec §4.4: toplamlarin hangi sutundan hesaplandigi proje tipine baglidir.
_VALUE_BASIS_BY_TYPE = {
    ProjectType.kat_karsiligi: UnitValueBasis.appraisal_value,
    ProjectType.kendi_yatirim: UnitValueBasis.list_price,
    ProjectType.taahhut: UnitValueBasis.list_price,
}


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def _sum(values: list[Decimal | None]) -> Decimal:
    """NULL'lar 0 SAYILIR (spec §6.1) ve toplama Decimal ile yapilir — float ASLA."""
    return _quantize_money(sum((value for value in values if value is not None), Decimal("0")))


def _counts(units: list[Unit]) -> UnitKindBreakdown:
    return UnitKindBreakdown(
        apartment=sum(1 for u in units if u.unit_kind is UnitKind.apartment),
        shop=sum(1 for u in units if u.unit_kind is UnitKind.shop),
    )


def _basis_value(unit: Unit, basis: UnitValueBasis) -> Decimal | None:
    if basis is UnitValueBasis.appraisal_value:
        return unit.appraisal_value
    return unit.list_price


def to_block(block: Block, site_name: str, units: list[Unit]) -> BlockResponse:
    return BlockResponse(
        id=block.id,
        name=block.name,
        site_id=block.site_id,
        site_name=site_name,
        sort_order=block.sort_order,
        counts=_counts(units),
    )


def to_unit(unit: Unit, block_name: str) -> UnitResponse:
    """Satis alanlari (KY 275-277, KKP 91-92) P8/P9/P10'un isidir ve yer tutucu
    doner — `units`'te saklanmaz (spec §4.6)."""
    return UnitResponse(
        id=unit.id,
        block_id=unit.block_id,
        block_name=block_name,
        unit_no=unit.unit_no,
        unit_kind=unit.unit_kind,
        layout=unit.layout,
        gross_area_m2=unit.gross_area_m2,
        net_area_m2=unit.net_area_m2,
        list_price=unit.list_price,
        appraisal_value=unit.appraisal_value,
        owner_side=unit.owner_side,
        sort_order=unit.sort_order,
        sales_status=_metric(_UNIT_SALES),
        sale_price=_metric(_UNIT_SALES),
        buyer_name=_metric(_UNIT_SALES),
        shareholder=_metric(_SHAREHOLDER_UNITS),
        unit_cost=_metric(_PROJECT_COSTS),
    )


def _average(total: Decimal, count: int) -> Decimal | None:
    """Sifira bolme YOK: unitesi olmayan kumede ortalama `None`'dir, 0 degil."""
    if count == 0:
        return None
    return _quantize_money(total / Decimal(count))


def _side_summary(
    side: UnitOwnerSide | None, units: list[Unit], basis: UnitValueBasis, project_total: int
) -> UnitSideSummary:
    """KK 116-122 / KKP 161-168 tfoot toplami.

    `share_pct` ADET oranidir (spec §5.2): sozlesmedeki yuzde (P1) ile birebir
    tutmak ZORUNDA DEGILDIR ve sapma DOGRULANMAZ, yalnizca raporlanir.
    """
    selected = [u for u in units if u.owner_side is side]
    total_value = _sum([_basis_value(u, basis) for u in selected])
    share_pct = (
        _quantize_money(Decimal(len(selected)) * _HUNDRED / Decimal(project_total))
        if project_total
        else None
    )
    return UnitSideSummary(
        side=side,
        counts=_counts(selected),
        total_value=total_value,
        average_value=_average(total_value, len(selected)),
        share_pct=share_pct,
        sold=_count(_UNIT_SALES),
        reserved=_count(_UNIT_SALES),
        listed=_count(_UNIT_SALES),
    )


def _totals(units: list[Unit], basis: UnitValueBasis) -> UnitTotals:
    """Spec §7.4: toplamlar SUZGECTEN ETKILENMEZ — cagiran daima projenin TUM
    unitelerini verir (P1 `list_projects_overview` kuralinin birebir tekrari)."""
    total_value = _sum([_basis_value(u, basis) for u in units])
    return UnitTotals(
        counts=_counts(units),
        value_basis=basis,
        total_value=total_value,
        average_value=_average(total_value, len(units)),
        total_list_price=_sum([u.list_price for u in units]),
        total_appraisal_value=_sum([u.appraisal_value for u in units]),
        total_gross_area_m2=_sum([u.gross_area_m2 for u in units]),
        sides=[_side_summary(side, units, basis, len(units)) for side in _SIDE_ORDER],
        sold_units=_count(_UNIT_SALES),
        reserved_units=_count(_UNIT_SALES),
        available_units=_count(_UNIT_SALES),
        sales_revenue=_metric(_UNIT_SALES),
        average_sale_price=_metric(_UNIT_SALES),
    )


# --- Gorunurluk (spec §8) ---


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = _PROJECT_MISSING
) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


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
    await _visible_project(session, actor, project_id)
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
    project = await _visible_project(session, actor, project_id)
    blocks, by_block, units = await _blocks_with_units(session, project_id)
    basis = _VALUE_BASIS_BY_TYPE[project.project_type]

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
    return UnitListResponse(totals=_totals(units, basis), blocks=groups)
