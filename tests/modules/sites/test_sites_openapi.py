"""T16 — `openapi.json` sozlesmesi: spec §7'nin SEKIZ ucu ve genisleyen govdeler.

Frontend sozlesmeyi bu semadan uretir (`gen:api`). Bir uc ya da alan semadan
duserse hata BACKEND testlerinde degil, frontend derlemesinde -- veya daha kotusu
CALISMA ZAMANINDA -- ortaya cikar. Bu dosya o mesafeyi kapatir.

Sema uygulamayi import ederek uretilir; dosya (`openapi.json`) gitignore'ludur ve
COMMIT EDILMEZ (plan §0.8), bu yuzden test dosyaya degil `app.openapi()` ciktisina
bakar.
"""

from app.main import app

# Spec §7 tablosu, satir satir. Bu liste DARALTILAMAZ.
SPEC_ENDPOINTS = (
    ("/projects/{project_id}/sites", "post"),
    ("/projects/{project_id}/sites", "get"),
    ("/sites/{site_id}", "get"),
    ("/sites/{site_id}", "patch"),
    ("/sites/{site_id}", "delete"),
    ("/sites/{site_id}/sections", "post"),
    ("/sections/{section_id}", "patch"),
    ("/sections/{section_id}", "delete"),
)

# T2'nin 22 kolonundan API GOVDESINE giren alanlar (sekiz tesis `facilities`
# grubunda toplandigi icin ayri sayilmaz, §4.1).
NEW_SITE_FIELDS = (
    "site_manager_user_id",
    "safety_officer_user_id",
    "safety_officer_is_outsourced",
    "neighborhood",
    "parcel",
    "gps_coordinates",
    "land_area_m2",
    "construction_area_m2",
    "floor_info",
    "budget",
    "electricity_subscription_no",
    "water_subscription_no",
    "planned_worker_count",
    "is_draft",
)
FACILITY_KEYS = (
    "closed_warehouse",
    "open_storage",
    "cold_storage",
    "site_office",
    "canteen",
    "dormitory",
    "changing_room_wc",
    "infirmary",
)


def _schema() -> dict:
    return app.openapi()


def _resolve(schema: dict, node: dict) -> dict:
    """`$ref` zincirini `components.schemas` uzerinden tek adim cozer."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[1]
        return schema["components"]["schemas"][name]
    return node


def _request_properties(schema: dict, path: str, method: str) -> dict:
    body = schema["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]
    return _resolve(schema, body)["properties"]


def _response_properties(schema: dict, path: str, method: str, status: str = "200") -> dict:
    body = schema["paths"][path][method]["responses"][status]["content"]["application/json"][
        "schema"
    ]
    return _resolve(schema, body)["properties"]


def test_openapi_exposes_all_eight_site_endpoints():
    """Spec §7'nin sekiz satiri -- IKI DELETE DAHIL -- semada."""
    schema = _schema()

    missing = [
        (path, method)
        for path, method in SPEC_ENDPOINTS
        if method not in schema["paths"].get(path, {})
    ]

    assert missing == [], missing


def test_delete_endpoints_declare_204_without_body():
    schema = _schema()

    for path in ("/sites/{site_id}", "/sections/{section_id}"):
        responses = schema["paths"][path]["delete"]["responses"]
        assert "204" in responses, (path, sorted(responses))
        assert "content" not in responses["204"], responses["204"]


def test_site_create_body_carries_every_new_field():
    schema = _schema()

    properties = _request_properties(schema, "/projects/{project_id}/sites", "post")

    for field in NEW_SITE_FIELDS:
        assert field in properties, field
    assert "sections" in properties
    assert "facilities" in properties
    # Turevler sozlesmeye SIZMAZ (§3.6, §3.5).
    assert "duration_days" not in properties
    assert "latitude" not in properties and "longitude" not in properties


def test_site_update_body_carries_every_new_field():
    schema = _schema()

    properties = _request_properties(schema, "/sites/{site_id}", "patch")

    for field in NEW_SITE_FIELDS:
        assert field in properties, field
    # PATCH proje/bolum tasimaz (§7.3).
    assert "project_id" not in properties
    assert "sections" not in properties


def test_facilities_group_is_a_nested_object_of_eight_booleans():
    schema = _schema()
    properties = _request_properties(schema, "/projects/{project_id}/sites", "post")

    facilities = _resolve(schema, properties["facilities"])

    assert set(FACILITY_KEYS) == set(facilities["properties"])
    # Duz `has_*` kolonlari API sozlesmesine SIZMAZ (§4.1).
    assert not any(key.startswith("has_") for key in properties)


def test_site_response_exposes_new_fields_and_draft_counter():
    schema = _schema()

    card = _response_properties(schema, "/projects/{project_id}/sites", "get")
    detail = _response_properties(schema, "/sites/{site_id}", "get")

    counts = _resolve(schema, card["counts"])
    assert "draft" in counts["properties"]
    items = _resolve(schema, card["items"]["items"])
    for field in NEW_SITE_FIELDS:
        assert field in items["properties"], field
        assert field in detail, field
    assert "facilities" in items["properties"]


def test_section_contract_carries_manager_user_id():
    schema = _schema()

    created = _response_properties(schema, "/sites/{site_id}/sections", "post", "201")
    create_body = _request_properties(schema, "/sites/{site_id}/sections", "post")
    update_body = _request_properties(schema, "/sections/{section_id}", "patch")

    assert "manager_user_id" in created
    assert "manager_user_id" in create_body
    assert "manager_user_id" in update_body
    # "Tahmini Bedel" yer tutucudur, saklanmaz (§3.4).
    assert "estimated_amount" not in created


def test_preparation_is_a_site_status_value():
    schema = _schema()

    properties = _request_properties(schema, "/projects/{project_id}/sites", "post")
    status_schema = _resolve(schema, properties["status"])

    assert "preparation" in status_schema["enum"]
