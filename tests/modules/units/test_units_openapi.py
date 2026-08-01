"""B12 — units/blocks OpenAPI sozlesmesi (spec §7 tablosu).

Bu dosya `openapi.json` URETMEZ; uretilen sema ile spec §7'nin 11 satirlik uc
tablosunun BIREBIR ayni oldugunu dogrular. Frontend `pnpm gen:api` ile bu semadan
istemci uretir — bir uc semadan duserse frontend derlenmeye devam eder ama cagri
canlida 404 verir, o yuzden kapi burada.
"""

from app.main import app

# Spec §7 tablosu, satir sirasi korunarak. (yol, yontem, izin)
SPEC_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("/projects/{project_id}/blocks", "get", "view"),
    ("/projects/{project_id}/blocks", "post", "full"),
    ("/blocks/{block_id}", "patch", "full"),
    # 2026-07-30 kullanici karari: silme YALNIZ sistem yoneticisinde (admin).
    ("/blocks/{block_id}", "delete", "admin"),
    ("/projects/{project_id}/units", "get", "view"),
    ("/projects/{project_id}/units", "post", "full"),
    ("/units/{unit_id}", "patch", "full"),
    ("/units/{unit_id}", "delete", "admin"),
    ("/projects/{project_id}/units/bulk", "post", "full"),
    ("/projects/{project_id}/units/import", "post", "full"),
    ("/projects/{project_id}/units/allocation", "patch", "full"),
)

# Spec §6'daki sema adlari — `gen:api` bunlardan tip uretir.
SPEC_SCHEMAS: tuple[str, ...] = (
    "BlockResponse",
    "BlockListResponse",
    "BlockCreate",
    "BlockUpdate",
    "UnitResponse",
    "UnitListResponse",
    "UnitCreate",
    "UnitUpdate",
    "UnitBulkCreate",
    "UnitImportResult",
    "UnitImportRowReport",
    "UnitImportRowStatus",
    "UnitImportSummary",
    "UnitAllocationRequest",
    "UnitAllocationItem",
    "UnitKindBreakdown",
    "UnitNumberingPattern",
    "UnitKind",
    "UnitOwnerSide",
    "UnitOwnerSideFilter",
    "UnitBlockGroup",
    "UnitSideSummary",
    "UnitTotals",
    "UnitValueBasis",
)


def test_openapi_exposes_all_eleven_endpoints() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    missing = [
        f"{method.upper()} {path}"
        for path, method, _ in SPEC_ENDPOINTS
        if method not in paths.get(path, {})
    ]
    assert not missing, f"OpenAPI semasinda eksik uc: {missing}"


def test_openapi_units_endpoints_are_tagged_units() -> None:
    """Tag kaymasi `gen:api` ciktisini baska bir istemci dosyasina taser."""
    paths = app.openapi()["paths"]
    for path, method, _ in SPEC_ENDPOINTS:
        assert paths[path][method]["tags"] == ["units"], f"{method.upper()} {path}"


def test_openapi_exposes_units_schemas() -> None:
    components = app.openapi()["components"]["schemas"]
    missing = [name for name in SPEC_SCHEMAS if name not in components]
    assert not missing, f"OpenAPI semasinda eksik sema: {missing}"


def test_openapi_import_endpoint_is_multipart() -> None:
    """Spec §7.8: tek alan `file`, multipart/form-data."""
    operation = app.openapi()["paths"]["/projects/{project_id}/units/import"]["post"]
    content = operation["requestBody"]["content"]
    assert "multipart/form-data" in content
