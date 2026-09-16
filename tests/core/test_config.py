import pytest

from app.core.config import Settings

_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
_TEST_DB_URL = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"


def test_production_with_default_jwt_secret_raises() -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            jwt_secret="dev-only-change-me",
            database_url=_DB_URL,
            test_database_url=_TEST_DB_URL,
        )


def test_production_with_real_secret_succeeds() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="x-test-secret",
        database_url=_DB_URL,
        test_database_url=_TEST_DB_URL,
    )

    assert settings.environment == "production"


def test_development_with_default_jwt_secret_succeeds() -> None:
    settings = Settings(
        environment="development",
        jwt_secret="dev-only-change-me",
        database_url=_DB_URL,
        test_database_url=_TEST_DB_URL,
    )

    assert settings.environment == "development"


def test_ortam_degiskeni_HIC_VERILMEZSE_production_sayilir(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔴 FAIL-CLOSED VARSAYILAN (altyapi-fail-closed, kayıt 4).

    Üstteki üç test de `environment`i AÇIKÇA geçiriyor; "değişken hiç gelmezse ne olur"
    sorusu bugüne kadar hiç sorulmadı. Cevap fail-OPEN'dı: `ENVIRONMENT` eksik ya da
    yanlış yazılmışsa koruma SESSİZCE kapanır ve gerçek token'lar herkese açık depodaki
    `dev-only-change-me` ile imzalanır (`app/core/config.py:6`).

    `_env_file=None` ŞART: yoksa yerel `.env:4` sızar ve `development` yapar.
    """
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            jwt_secret="dev-only-change-me",
            database_url=_DB_URL,
            test_database_url=_TEST_DB_URL,
        )
