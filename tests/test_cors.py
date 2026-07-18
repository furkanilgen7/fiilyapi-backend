from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.config import Settings
from app.main import _configure_cors

_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
_TEST_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"


def _settings(**overrides) -> Settings:
    base = {"database_url": _DB_URL, "test_database_url": _TEST_DB_URL}
    base.update(overrides)
    return Settings(**base)


def test_cors_origin_list_parses_and_trims() -> None:
    settings = _settings(cors_origins="https://a.co, https://b.co ,, https://c.co ")
    assert settings.cors_origin_list == ["https://a.co", "https://b.co", "https://c.co"]


def test_cors_origin_list_empty_by_default() -> None:
    assert _settings().cors_origin_list == []


def test_configure_cors_adds_middleware_when_origins_present() -> None:
    app = FastAPI()
    _configure_cors(app, _settings(cors_origins="https://a.co"))
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_configure_cors_skips_when_no_origins() -> None:
    app = FastAPI()
    _configure_cors(app, _settings(cors_origins=""))
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
