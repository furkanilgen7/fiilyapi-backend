import app.core.db as db_module
from app.core.config import Settings

_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
_TEST_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"


def _settings(**overrides) -> Settings:
    base = {"database_url": _DB_URL, "test_database_url": _TEST_DB_URL}
    base.update(overrides)
    return Settings(**base)


def test_timeout_defaults() -> None:
    settings = _settings()
    assert settings.db_connect_timeout == 10
    assert settings.db_command_timeout == 30


def test_build_engine_passes_timeouts_to_connect_args(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return "ENGINE"

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)

    result = db_module.build_engine(_settings(db_connect_timeout=7, db_command_timeout=42))

    assert result == "ENGINE"
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["connect_args"] == {"timeout": 7, "command_timeout": 42}
