from decimal import Decimal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "dev-only-change-me"


def _asyncpg_url(url: str) -> str:
    """Düz `postgresql://` / `postgres://` URL'sini asyncpg sürücüsüne çevirir.

    Uygulama motoru ve alembic `create_async_engine` kullanır; bu da `postgresql+asyncpg://`
    şeması bekler. Railway/Heroku'nun sağladığı `DATABASE_URL` düz `postgresql://` (bazen
    `postgres://`) olduğundan, normalize edilmezse açılışta senkron sürücü (psycopg2)
    aranır — kurulu değildir — ve uygulama sessizce çöker.
    """
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
    test_database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    environment: str = "development"

    # Kullaniciya donuk TUM zaman ve gun sinirlarinin saat dilimi (IANA adi). Tek sirketli
    # bir Turk ERP'si oldugu icin varsayilan TR'dir: "bugun"/"bu ay" filtreleri ve Excel
    # ciktisindaki saatler bu dilimde yorumlanir. Bkz. `app/core/timezone.py`.
    display_timezone: str = "Europe/Istanbul"

    # Veritabanı bağlantı/komut zaman aşımları (saniye). Asılı bir sorgu ya da bağlantı
    # canlıda tek instance'ı kilitlemesin diye asyncpg'ye açıkça sınır veriyoruz.
    db_connect_timeout: int = 10
    db_command_timeout: int = 30

    # CORS izin listesi (virgülle ayrılmış origin'ler). Boşsa CORS middleware eklenmez
    # (dev'de kırmaz). BFF deseni nedeniyle tarayıcı backend'e doğrudan gitmez; bu
    # savunma-derinliğidir. Wildcard `*` + credentials ASLA birlikte kullanılmaz.
    cors_origins: str = ""

    # Kaba-kuvvet denemelerine karşı IP başına login/refresh hız sınırı (slowapi biçimi).
    login_rate_limit: str = "10/minute"
    refresh_rate_limit: str = "20/minute"

    # İlk sistem yöneticisi bootstrap'ı (opsiyonel). İkisi de doluysa ve DB'de hiç kullanıcı
    # yoksa açılışta bu hesap oluşturulur; aksi halde bootstrap atlanır. Kullanıcı oluşturma
    # ucu admin yetkisi istediğinden ilk kurulumdaki tavuk-yumurta sorununu bu çözer.
    admin_email: str = ""
    admin_password: str = ""

    # Sirket logosu DB'de bytea saklanir (object storage yok). Yukleme sinirlari + marka
    # varsayilanlari config'ten gelir (hardcode degil).
    logo_max_bytes: int = 1_048_576  # 1 MB
    allowed_logo_content_types: str = "image/png,image/jpeg,image/svg+xml,image/webp"
    default_brand_color: str = "#2563eb"
    default_accent_color: str = "#2563eb"
    default_vat_rate: Decimal = Decimal("20.00")

    # Belge arşivi (belge çekirdeği spec §4 / §7 S5). v1'de baytlar DB'de bytea
    # olarak durur (`document_blobs`), object storage YOK — sınır bu yüzden
    # config'ten gelir, hardcode DEĞİLDİR.
    # 50 MB: mockup'ta 48 MB'lık bir ZIP var (E12), tavan onun hemen üstünde.
    document_max_bytes: int = 50 * 1024 * 1024
    # GENİŞ beyaz liste (spec §4): zip + heic dahil. `allowed_logo_content_types`
    # deseniyle aynı — virgülle ayrılmış env dizesi, kümeye `..._set` ile çevrilir.
    # UZANTI listesidir (MIME değil): mockup dosya adına göre tip ikonu basıyor ve
    # dwg gibi tiplerin güvenilir tek bir MIME'i yok.
    allowed_document_extensions: str = "pdf,doc,docx,xls,xlsx,csv,dwg,jpg,jpeg,png,heic,zip"

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _normalize_pg_driver(cls, value: str) -> str:
        return _asyncpg_url(value)

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

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins`'i temizlenmiş origin listesine çevirir (boşları atar)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_logo_content_type_set(self) -> set[str]:
        """Izin verilen logo MIME tiplerini kume olarak dondurur."""
        return {t.strip() for t in self.allowed_logo_content_types.split(",") if t.strip()}

    @property
    def allowed_document_extension_set(self) -> set[str]:
        """İzin verilen belge uzantılarını küçük harfe indirgenmiş küme olarak döndürür.

        Baştaki nokta tolere edilir (`.pdf` == `pdf`) — env'i yazan kişinin
        biçim tercihi beyaz listeyi sessizce boşaltmamalı.
        """
        return {
            ext.strip().lstrip(".").lower()
            for ext in self.allowed_document_extensions.split(",")
            if ext.strip().lstrip(".")
        }


settings = Settings()
