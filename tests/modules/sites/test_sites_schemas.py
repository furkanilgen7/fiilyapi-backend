"""Task 4 — santiye/bolum semalari (spec §4.1)."""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.projects.schemas import CountPlaceholder, MetricPlaceholder
from app.modules.sites import schemas as sites_schemas
from app.modules.sites.schemas import (
    SectionCreate,
    SectionResponse,
    SectionUpdate,
    SiteCard,
    SiteCreate,
    SiteUpdate,
)


def test_placeholders_are_reused_from_projects_module():
    """Spec §3: MetricPlaceholder/CountPlaceholder KOPYALANMAZ, import edilir."""
    assert sites_schemas.MetricPlaceholder is MetricPlaceholder
    assert sites_schemas.CountPlaceholder is CountPlaceholder


def _card_kwargs() -> dict:
    return {
        "id": uuid.uuid4(),
        "code": "A-BLOK",
        "name": "A-Blok Şantiyesi",
        "status": "active",
        "address": "Kuyubaşı Mah.",
        "city": "Ankara",
        "city_inherited": False,
        "site_manager_name": "Sercan Öztürk",
        "start_date": "2025-03-01",
        "end_date": "2026-12-31",
        "delivery_date": None,
        "remaining_days": 157,
        "section_count": 5,
        "worker_count": CountPlaceholder(pending_module="timesheet"),
        "progress_pct": MetricPlaceholder(pending_module="progress_payments"),
    }


def test_site_card_serializes_placeholder_fields():
    card = SiteCard(**_card_kwargs())
    dumped = card.model_dump()

    assert dumped["worker_count"] == {
        "available": False,
        "count": None,
        "pending_module": "timesheet",
    }
    assert dumped["progress_pct"] == {
        "available": False,
        "value": None,
        "pending_module": "progress_payments",
    }
    assert dumped["remaining_days"] == 157
    assert dumped["city_inherited"] is False


def test_site_card_accepts_negative_remaining_days():
    """Spec §4.2: gecikme NEGATIF doner, kirpilmaz."""
    card = SiteCard(**{**_card_kwargs(), "remaining_days": -42})
    assert card.remaining_days == -42


def test_site_card_accepts_null_remaining_days():
    card = SiteCard(**{**_card_kwargs(), "remaining_days": None})
    assert card.remaining_days is None


def test_section_response_carries_four_placeholders():
    section = SectionResponse(
        id=uuid.uuid4(),
        code=None,
        name="Kat 6-10 Kaba İnşaat",
        status="active",
        manager_name="Sercan Öztürk",
        start_date="2026-01-01",
        end_date="2026-09-30",
        sort_order=2,
        progress_pct=MetricPlaceholder(pending_module="progress_payments"),
        boq_item_count=CountPlaceholder(pending_module="boq"),
        budget=MetricPlaceholder(pending_module="boq"),
        worker_count=CountPlaceholder(pending_module="timesheet"),
    )

    assert section.boq_item_count.pending_module == "boq"
    assert section.budget.pending_module == "boq"
    assert section.progress_pct.available is False


def test_section_response_has_no_delay_risk_field():
    """Spec §3.3: "3 gecikme riski" ne gercek ne yer tutucu olarak DONMEZ."""
    assert "delay_risk_count" not in SectionResponse.model_fields
    assert "delay_risk" not in SectionResponse.model_fields


def test_site_has_no_contract_amount_input():
    """Spec §2.1: santiyeye elle sozlesme bedeli girilemez."""
    assert "contract_amount" not in SiteCreate.model_fields
    assert "contract_amount" not in SiteUpdate.model_fields


def test_section_has_no_budget_input():
    """Spec §2.2: bolum bedeli BOQ turevidir, elle girilmez."""
    assert "budget" not in SectionCreate.model_fields
    assert "budget" not in SectionUpdate.model_fields


def test_site_create_defaults():
    data = SiteCreate(name="A-Blok Şantiyesi")
    assert data.code is None  # servis ad'dan turetir (spec §8 acik soru 2)
    assert data.status.value == "active"
    assert data.city is None


def test_section_create_defaults_to_planned():
    data = SectionCreate(name="Kat 6-10")
    assert data.status.value == "planned"
    assert data.sort_order == 0


def test_site_create_rejects_blank_name():
    with pytest.raises(ValidationError):
        SiteCreate(name="")


def test_updates_are_fully_optional():
    assert SiteUpdate().model_dump(exclude_unset=True) == {}
    assert SectionUpdate().model_dump(exclude_unset=True) == {}


def test_section_update_cannot_move_section_between_sites():
    assert "site_id" not in SectionUpdate.model_fields


def test_site_update_cannot_move_site_between_projects():
    assert "project_id" not in SiteUpdate.model_fields
