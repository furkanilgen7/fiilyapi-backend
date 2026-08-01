"""B12 — units/blocks OpenAPI sozlesmesi (spec §7 tablosu).

Bu dosya `openapi.json` URETMEZ; uretilen sema ile spec §7'nin uc tablosunun
BIREBIR ayni oldugunu dogrular. Frontend `pnpm gen:api` ile bu semadan istemci
uretir — bir uc semadan duserse frontend derlenmeye devam eder ama cagri
canlida 404 verir, o yuzden kapi burada.

P3.1 T17: tablo 11 → **14** uc. Uc yeni uc (`bulk/preview`, `import/validate`,
`import/template`) da bu kapidan gecer — "onizleme/dogrulama zaten okuma ucu"
diye kapinin disinda birakmak, `gen:api` ciktisinda sessizce eksik bir istemci
fonksiyonu uretirdi.
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
    # P3.1'in UC yeni ucu (spec §7 tablosu 12-14, §6.2/§6.7).
    ("/projects/{project_id}/units/bulk/preview", "post", "full"),
    ("/projects/{project_id}/units/import/validate", "post", "full"),
    # Tek `view` ucu: bos sablon proje verisi tasimaz (§6.2 karari, §12.6/I6).
    ("/projects/{project_id}/units/import/template", "get", "view"),
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
    # P3.1 T8/T9: kat sablonu (slot) + onizleme zarfi.
    "UnitBulkSlot",
    "UnitBulkPreview",
    "UnitBulkPreviewRow",
    "UnitImportResult",
    # P3.1 T13: dogrulama (dry-run) zarfi — `UnitImportResult`'tan AYRI sema.
    "UnitImportValidation",
    "UnitImportRowReport",
    "UnitImportRowStatus",
    "UnitImportSummary",
    "UnitAllocationRequest",
    "UnitAllocationItem",
    "UnitKindBreakdown",
    "UnitNumberingPattern",
    "UnitKind",
    # P3.1 T6: `UnitResponse.sales_status` yer tutucudan GERCEK enum'a dondu;
    # `facing` YENI alandir. Ikisi de `gen:api` icin sema olarak gorunmelidir.
    "UnitSalesStatus",
    "UnitFacing",
    "UnitOwnerSide",
    "UnitOwnerSideFilter",
    "UnitBlockGroup",
    "UnitSideSummary",
    "UnitTotals",
    "UnitValueBasis",
)


def test_openapi_exposes_all_fourteen_endpoints() -> None:
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


def test_spec_endpoint_table_has_fourteen_rows() -> None:
    """Tablonun KENDISI de iddiadir: bir uc eklenip tabloya yazilmazsa yukaridaki
    "eksik uc" testi onu goremez (var olmayan bir seyi arayamaz)."""
    assert len(SPEC_ENDPOINTS) == 14


def test_openapi_import_endpoints_are_multipart() -> None:
    """Spec §7.8 + §6.2: `import` ve `validate` multipart'tir ve `file` disinda
    `site_id` (EI 61) ile `include_warnings` (EI 192) alanlarini da kabul eder —
    `gen:api` bunlari gormezse frontend santiye secimini gonderemez."""
    paths = app.openapi()["paths"]
    for path in (
        "/projects/{project_id}/units/import",
        "/projects/{project_id}/units/import/validate",
    ):
        content = paths[path]["post"]["requestBody"]["content"]
        assert "multipart/form-data" in content, path
        schema_ref = content["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
        fields = app.openapi()["components"]["schemas"][schema_ref]["properties"]
        assert {"file", "site_id", "include_warnings"} <= set(fields), path


def test_openapi_template_endpoint_declares_xlsx_response() -> None:
    """Spec §6.7. `gen:api` yaniti ikili olarak isaretlemelidir; JSON sanirsa
    istemci dosyayi cozmeye calisir ve bozuk bir `.xlsx` iner."""
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    operation = app.openapi()["paths"]["/projects/{project_id}/units/import/template"]["get"]
    assert xlsx in operation["responses"]["200"]["content"]
