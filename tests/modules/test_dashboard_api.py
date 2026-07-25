from decimal import Decimal

from app.modules.dashboard.schemas import (
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)


def test_metric_placeholder_defaults_to_unavailable():
    metric = MetricPlaceholder(pending_module="progress_payments")

    assert metric.available is False
    assert metric.value is None
    assert metric.pending_module == "progress_payments"


def test_pending_approvals_placeholder_has_zero_count():
    placeholder = PendingApprovalsPlaceholder(pending_module="approvals")

    assert placeholder.available is False
    assert placeholder.count == 0
    assert placeholder.items == []


def test_summary_serializes_decimal_project_fields():
    summary = DashboardSummaryResponse(
        role_name="Patron",
        active_project_count=1,
        projects=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "code": "GK-A",
                "name": "Güneşkent A-Blok",
                "status": "active",
                "budget": Decimal("1500000.00"),
                "progress_pct": Decimal("42.50"),
            }
        ],
        portfolio=MetricPlaceholder(pending_module="progress_payments"),
        receivables=MetricPlaceholder(pending_module="invoicing"),
        average_margin=MetricPlaceholder(pending_module="progress_payments"),
        pending_approvals=PendingApprovalsPlaceholder(pending_module="approvals"),
        risks=ListPlaceholder(pending_module="inventory"),
    )

    dumped = summary.model_dump(mode="json")

    assert dumped["projects"][0]["budget"] == "1500000.00"
    assert dumped["risks"]["available"] is False
    assert dumped["risks"]["items"] == []
