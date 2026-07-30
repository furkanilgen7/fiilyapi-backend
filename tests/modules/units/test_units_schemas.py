"""B2 — units/blocks Pydantic semalari (spec §6.1-6.4)."""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder
from app.modules.units import schemas
from app.modules.units.models import UnitKind, UnitOwnerSide
from app.modules.units.schemas import (
    UnitAllocationItem,
    UnitAllocationRequest,
    UnitBulkCreate,
    UnitCreate,
    UnitKindBreakdown,
    UnitResponse,
    UnitUpdate,
)


def _metric(pending_module: str = "unit_sales") -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _unit(**overrides) -> UnitResponse:
    defaults: dict = {
        "id": uuid.uuid4(),
        "block_id": uuid.uuid4(),
        "block_name": "A Blok",
        "unit_no": "Daire 12",
        "unit_kind": UnitKind.apartment,
        "layout": "3+1",
        "gross_area_m2": Decimal("142.00"),
        "net_area_m2": Decimal("120.00"),
        "list_price": Decimal("1150000.00"),
        "appraisal_value": None,
        "owner_side": None,
        "sort_order": 1,
        "sales_status": _metric(),
        "sale_price": _metric(),
        "buyer_name": _metric(),
        "shareholder": _metric("shareholder_units"),
        "unit_cost": _metric("project_costs"),
    }
    defaults.update(overrides)
    return UnitResponse(**defaults)


# --- turev alanlar ---


def test_unit_price_per_m2_computed():
    """FDS 60-61: liste fiyati ve m² birim fiyat ayni formda yan yana durur."""
    unit = _unit(list_price=Decimal("1150000.00"), gross_area_m2=Decimal("142.00"))
    assert unit.unit_price_per_m2 == Decimal("8098.59")


def test_unit_price_per_m2_none_when_area_missing():
    assert _unit(gross_area_m2=None, net_area_m2=None).unit_price_per_m2 is None


def test_unit_price_per_m2_none_when_area_zero():
    """Sifira bolme yok."""
    unit = _unit(gross_area_m2=Decimal("0.00"), net_area_m2=Decimal("0.00"))
    assert unit.unit_price_per_m2 is None


def test_unit_label_derived():
    """KY 281 / KKP 96: "A Blok · Daire 12"."""
    assert _unit(block_name="A Blok", unit_no="Daire 12").label == "A Blok · Daire 12"


def test_is_landowner_share_derived():
    """KKP 111 "Arsa Sahibinde" durumu `owner_side`'dan turetilir (spec §4.6)."""
    assert _unit(owner_side=UnitOwnerSide.landowner).is_landowner_share is True
    assert _unit(owner_side=UnitOwnerSide.contractor).is_landowner_share is False
    assert _unit(owner_side=None).is_landowner_share is False


def test_unit_kind_breakdown_total():
    """KY 71 / 88: "48 Daire + 4 Dukkan" → 52 unite."""
    assert UnitKindBreakdown(apartment=48, shop=4).total == 52


# --- yazma dogrulamalari ---


def test_unit_create_rejects_negative_price():
    with pytest.raises(ValidationError):
        UnitCreate(
            block_id=uuid.uuid4(),
            unit_no="1",
            unit_kind=UnitKind.apartment,
            list_price=Decimal("-1.00"),
        )


def test_unit_create_rejects_long_unit_no():
    with pytest.raises(ValidationError):
        UnitCreate(block_id=uuid.uuid4(), unit_no="X" * 31, unit_kind=UnitKind.apartment)


def test_unit_update_partial_tracks_unset():
    """ "Gonderilmedi" ile "null yapildi" ayrimi `model_fields_set` ile cozulur."""
    update = UnitUpdate(layout=None)
    assert "layout" in update.model_fields_set
    assert "list_price" not in update.model_fields_set


def test_allocation_request_min_and_max_items():
    with pytest.raises(ValidationError):
        UnitAllocationRequest(items=[])

    over_limit = [
        UnitAllocationItem(unit_id=uuid.uuid4(), owner_side=None)
        for _ in range(schemas._MAX_ALLOCATION_ITEMS + 1)
    ]
    with pytest.raises(ValidationError):
        UnitAllocationRequest(items=over_limit)


def test_bulk_create_rejects_inverted_floor_range():
    with pytest.raises(ValidationError):
        UnitBulkCreate(
            block_id=uuid.uuid4(),
            unit_kind=UnitKind.apartment,
            start_floor=5,
            end_floor=2,
            units_per_floor=2,
        )


def test_bulk_create_rejects_over_limit():
    """51 kat × 10 daire = 510 > _MAX_BULK_UNITS."""
    assert schemas._MAX_BULK_UNITS == 500
    with pytest.raises(ValidationError):
        UnitBulkCreate(
            block_id=uuid.uuid4(),
            unit_kind=UnitKind.apartment,
            start_floor=1,
            end_floor=51,
            units_per_floor=10,
        )


# --- sozlesme ---


def test_decimal_fields_serialize_as_string():
    """Repo deseni: para/olcu alanlari JSON'da string doner, float'a dusmez."""
    dumped = _unit().model_dump(mode="json")
    assert dumped["list_price"] == "1150000.00"
    assert dumped["gross_area_m2"] == "142.00"
    assert dumped["unit_price_per_m2"] == "8098.59"


def test_metric_placeholder_imported_not_redefined():
    """Yer tutucu sozlesmesi TEK yerde tanimlidir (P1); kopyalanmaz."""
    assert schemas.MetricPlaceholder is MetricPlaceholder
    assert schemas.CountPlaceholder is CountPlaceholder
    assert UnitResponse.model_fields["sales_status"].annotation is MetricPlaceholder
