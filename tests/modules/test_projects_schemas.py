from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.projects.schemas import (
    CountPlaceholder,
    MetricPlaceholder,
    ProjectCreate,
    ProjectLandShareInput,
    ProjectUpdate,
)


def test_metric_placeholder_defaults_to_unavailable():
    metric = MetricPlaceholder(pending_module="progress_payments")
    assert metric.available is False
    assert metric.value is None


def test_count_placeholder_defaults_to_unavailable():
    counter = CountPlaceholder(pending_module="timesheet")
    assert counter.available is False
    assert counter.count is None


def test_land_share_input_rejects_pct_not_summing_to_100():
    with pytest.raises(ValidationError):
        ProjectLandShareInput(
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("70.00"),
            owner_share_pct=Decimal("45.00"),
        )


def test_land_share_input_accepts_valid_pcts():
    data = ProjectLandShareInput(
        landowner_name="Yılmaz Ailesi",
        our_share_pct=Decimal("55.00"),
        owner_share_pct=Decimal("45.00"),
        shareholders=[{"name": "A. Yılmaz", "share_pct": Decimal("60.00")}],
    )
    assert data.shareholders[0].name == "A. Yılmaz"


def test_project_create_minimal_taahhut():
    data = ProjectCreate(code="GK-C", name="Güneşkent C-Blok", project_type="taahhut")
    assert data.status.value == "active"
    assert data.investment is None
    assert data.land_share is None


def test_project_create_code_is_optional():
    """B4: code opsiyonel, boşsa sunucu üretir (spec §3.5)."""
    data = ProjectCreate(name="Kodsuz", project_type="taahhut")
    assert data.code is None
    assert data.is_draft is False
    # employer_name gövdeden kaldırıldı.
    assert "employer_name" not in ProjectCreate.model_fields
    # budget_lines varsayılanı sıfır dört kalem.
    assert data.budget_lines.material == Decimal("0")
    assert data.sites == []


def test_contract_input_defaults():
    from app.modules.projects.schemas import ProjectContractInput

    contract = ProjectContractInput()
    assert contract.advance_pct == Decimal("20")
    assert contract.retainage_pct == Decimal("5")
    assert contract.vat_pct == Decimal("20")
    assert contract.has_price_escalation is True


def test_contract_input_rejects_pct_over_100():
    from app.modules.projects.schemas import ProjectContractInput

    with pytest.raises(ValidationError):
        ProjectContractInput(vat_pct=Decimal("150"))


def test_project_update_has_no_project_type_field():
    """Tip is modelidir, PATCH ile degistirilemez (spec §3.5)."""
    assert "project_type" not in ProjectUpdate.model_fields
