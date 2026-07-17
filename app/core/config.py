from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
    test_database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    environment: str = "development"

    @model_validator(mode="after")
    def _reddet_prod_ortaminda_varsayilan_jwt_secret(self) -> "Settings":
        """Production ortamında varsayılan JWT secret'ı ile açılışı engeller.

        Aksi halde, ortam değişkeni eksik geldiğinde uygulama sessizce ayakta kalır ve
        herkese açık, bilinen bir string ile gerçek token'lar imzalanmaya başlar.
        """
        if self.environment == "production" and self.jwt_secret == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "Production ortamında varsayılan JWT_SECRET kullanılamaz; "
                "gerçek bir gizli anahtar tanımlayın."
            )
        return self


settings = Settings()
