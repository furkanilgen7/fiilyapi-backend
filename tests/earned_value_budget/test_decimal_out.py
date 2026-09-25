"""PLN-B3.1 — EV yanıtlarında Decimal ÜSTEL yazılmaz ("0E+7" sözleşme kusuru) · bekçiler.

Kusur (ölçüldü): pydantic Decimal'i `str()` ile yazar → `Decimal('0E+7')` → `"0E+7"`; kendi
OpenAPI desenimiz (`E` yok) ve frontend `DECIMAL_PATTERN`i reddeder, sıfır "—" görünürdü.
B1 bütçe `share`, önizleme `required_people`, B3 rapor/panel `progress_pct_*`.

1. YAPISAL: EV uçlarının yanıt modellerinin çekirdek şemasındaki HER `decimal` düğümü
   `decimal_out.plain_decimal` serileştiricisini taşır (yeni alan çıplak Decimal'le
   eklenirse kırmızı) — negatif kontrolle (bekçi kör değil).
2. DAVRANIŞ: üstel değerler sabit gösterime açılır, ölçek korunur, python modu Decimal kalır.
3. GOLDEN: hiçbir golden dosyasında üstel sayı dizesi yok.
OpenAPI şemasının DEĞİŞMEDİĞİ `tests/contract/test_openapi_contract_baseline.py`de.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.modules.earned_value.decimal_out import EvDecimal, plain_decimal
from app.modules.earned_value.schemas_reports import PanelKpi

EXPONENT = re.compile(r"^-?\d+(\.\d+)?[eE][+-]?\d+$")
GOLDENS = [
    *(Path(__file__).parent / "golden").glob("*.json"),
    *(Path(__file__).parents[1] / "modules" / "earned_value" / "golden").glob("*.json"),
]


def _ev_response_models() -> list[object]:
    """EV modülünün BEŞ router'ındaki her ucun yanıt modeli (app.routes tembel sarmalanır)."""
    from app.modules.earned_value import (
        catalog_router,
        day_router,
        report_router,
        router,
        settings_router,
    )

    models = []
    for module in (router, day_router, settings_router, report_router, catalog_router):
        for route in module.router.routes:
            model = getattr(route, "response_model", None)
            if model is not None:  # sınıf ya da `list[X]` gibi genel tip
                models.append(model)
    return models


def _bare_decimals(schema: object, path: str = "$") -> list[str]:
    """Çekirdek şemada JSON serileştiricisi `plain_decimal` OLMAYAN decimal düğümleri."""
    out: list[str] = []
    if isinstance(schema, dict):
        if schema.get("type") == "decimal":
            ser = schema.get("serialization") or {}
            if ser.get("function") is not plain_decimal:
                out.append(path)
        for k, v in schema.items():
            out += _bare_decimals(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            out += _bare_decimals(v, f"{path}[{i}]")
    return out


def test_every_ev_response_decimal_uses_plain_serializer() -> None:
    models = _ev_response_models()
    assert len(models) >= 20, "EV yanıt modeli bulunamadı — bekçi kör"
    bare = {repr(m): _bare_decimals(TypeAdapter(m).core_schema) for m in models}
    assert {n: p for n, p in bare.items() if p} == {}


def test_guard_detects_bare_decimal_negative_control() -> None:
    class Bare(BaseModel):
        good: EvDecimal
        bad: Decimal

    missing = _bare_decimals(Bare.__pydantic_core_schema__)
    assert len(missing) == 1 and ".bad." in missing[0], missing


def test_exponent_values_serialize_as_fixed_notation() -> None:
    kpi = PanelKpi(
        budget_mhr=Decimal("225.0000000"),
        earned_day=Decimal("1E-7"),
        earned_cum=Decimal("1E+2"),
        spent_day=None,
        progress_pct_cum=Decimal("0E+7"),
        planned_pct_cum=Decimal("-0E-3"),
        variance=Decimal("-1.5E-8"),
        status=None,
        pf_cum=None,
        pf_week=None,
        pf_cum_band=None,
        pf_week_band=None,
        timesheet_total_day=Decimal("17.00"),
        undistributed_day=None,
    )
    data = json.loads(kpi.model_dump_json())
    assert (data["earned_day"], data["earned_cum"], data["progress_pct_cum"]) == (
        "0.0000001",
        "100",
        "0",
    )
    assert data["variance"] == "-0.000000015"
    assert data["budget_mhr"] == "225.0000000" and data["timesheet_total_day"] == "17.00"
    assert data["spent_day"] is None
    assert not any(isinstance(v, str) and EXPONENT.match(v) for v in data.values())
    assert kpi.model_dump()["progress_pct_cum"] == Decimal("0E+7")  # python modu Decimal


def test_constrained_alias_still_validates() -> None:
    from app.modules.earned_value.schemas_settings import Band

    adapter = TypeAdapter(Band)
    assert adapter.validate_python("0.950") == Decimal("0.950")
    with pytest.raises(ValidationError):
        adapter.validate_python("0.9501")  # decimal_places=3 kısıtı korunur


def _strings(v: object) -> list[str]:
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return [v] if isinstance(v, str) else []


def test_goldens_have_no_exponent_numbers() -> None:
    assert len(GOLDENS) >= 4
    hits = {
        p.name: [s for s in _strings(json.loads(p.read_text())) if EXPONENT.match(s)]
        for p in GOLDENS
    }
    assert {n: h for n, h in hits.items() if h} == {}
