"""Unite listesinin SAF sunum/toplama cekirdegi (spec §6.1, §5.2, §7.4).

Servisten AYRI tutulur ki "24 unitenin toplami ne eder", "taraf yuzdesi nasil
hesaplanir" sorulari veritabanina, oturuma ve yetkiye dokunmadan test
edilebilsin (`bulk.py` ile ayni gerekce). Burada `AsyncSession` YOKTUR ve
olmamalidir: bu modul yalnizca ORM nesnelerini semalara cevirir.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.modules.projects.models import ProjectType
from app.modules.units.models import Block, Unit, UnitKind, UnitOwnerSide
from app.modules.units.schemas import (
    BlockResponse,
    CountPlaceholder,
    MetricPlaceholder,
    UnitKindBreakdown,
    UnitResponse,
    UnitSideSummary,
    UnitTotals,
    UnitValueBasis,
)

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
VALUE_BASIS_BY_TYPE = {
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
        # Blok formu (BE) — 13 alan aynen doner; `estimated_unit_count`
        # BlockResponse'ta TUREVDIR ve burada hesaplanmaz (spec §3.3).
        code=block.code,
        basement_floor_count=block.basement_floor_count,
        floor_count=block.floor_count,
        roof_type=block.roof_type,
        units_per_floor=block.units_per_floor,
        ground_floor_usage=block.ground_floor_usage,
        shop_count=block.shop_count,
        construction_area_m2=block.construction_area_m2,
        elevator_count=block.elevator_count,
        parking_type=block.parking_type,
        estimated_delivery_date=block.estimated_delivery_date,
        status=block.status,
        notes=block.notes,
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


def totals(units: list[Unit], basis: UnitValueBasis) -> UnitTotals:
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
