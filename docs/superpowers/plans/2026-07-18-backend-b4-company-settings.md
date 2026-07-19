# Backend B4 — Şirket Bilgileri + Kullanıcı Tercihleri Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tek-şirket bilgilerini (okuma + güncelleme + DB'de bytea logo) ve kullanıcı-başına self-service tercihleri (görünüm + bildirim kanalları) sağlayan `company` ve `settings` modüllerini eklemek; frontend F5 Ayarlar ekranlarını besleyecek uçları açmak.

**Architecture:** Modüler FastAPI; iki yeni modül (`company`, `settings`) `models · schemas · repository · service · router` iskeletini izler. Şirket **yazma** uçları `require_permission("settings", AccessLevel.full)` ile kapılıdır (seed'de yalnızca `system_admin`). Şirket **okuma** ve tüm tercih uçları yalnızca `get_current_user` ister; her kullanıcı yalnızca kendi tercihini okur/yazar. Şirket tek satırdır (`only_row` UNIQUE + CHECK ile zorlanır) ve okuma yolunda get-or-create ile garanti edilir; ayrıca açılışta `bootstrap.ensure_company()` çağrılır. Logo object storage olmadığından DB'de `bytea` saklanır ve ayrı bir uçtan stream edilir.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · Pydantic v2 + pydantic-settings · pytest + pytest-asyncio + httpx

**Spec:** `docs/superpowers/specs/2026-07-17-temel-modul-design.md` (§4.1 tablolar, §6.3 Ayarlar, §8 B4, §9 ödünçler) ve tasarım dokümanı `docs/superpowers/specs/2026-07-18-backend-b4-company-settings-design.md`. Çelişki hâlinde spec kazanır.

## Global Constraints

- **Repo:** Tüm yollar `/Users/furkanilgen/Documents/Projeler/insaat/backend` köküne görelidir. Frontend ayrı repo — bu planda ona dokunulmaz.
- **Yürütme ortamı:** PATH'te `python` YOK. Her komutta `.venv/bin/python`, `.venv/bin/alembic`, `.venv/bin/ruff` kullan. Docker/lokal DB yok; DB Railway'de (bulut). Testler uzak DB'ye bağlandığından yavaştır — her task'ta yalnızca FOCUSED testler; tam suite yalnızca faz sonunda.
- **Dil:** Kod, değişken ve fonksiyon adları İngilizce. Kullanıcıya dönen hata mesajları Türkçe. Commit mesajlarında Türkçe diakritik kullanma (ör. "sirket", "tercih").
- **Çok şirketlilik yok.** Hiçbir tabloya `company_id` eklenmez (spec §9.1). `company` tek satırdır.
- **Yetki:** `role.key` üzerinden, ASLA `role.name`. `require_permission` tek yetki kapısı; saf domain `app/core/access.py`, kapı `app/core/permissions.py`. Seviye sırası `none < view < draft < request < approve < full < admin`.
- **Yetki eşiği:** Şirket **okuma** (`GET /company`, `GET /company/logo`) → yalnızca `get_current_user`. Şirket **yazma** (`PUT /company`, `POST/DELETE /company/logo`) → `require_permission("settings", AccessLevel.full)`. Tercihler (görünüm + bildirim) → yalnızca `get_current_user`, daima kendi `user.id`.
- **Tema kısıtı:** `theme` DB enum'u `light`/`dark`/`system` içerir ama v1 yazma şeması yalnızca `light` kabul eder (aksi 422: "Koyu tema henuz aktif degil"). Spec §9: koyu tema pasif.
- **Yanıt gövdesi:** Parola, `password_hash`, token veya `logo_data` bytea'sı HİÇBİR JSON yanıt modelinde yer almaz. Logo yalnızca `GET /company/logo`'dan ikili olarak döner.
- **Config:** Sabit değerler hardcode değil `app/core/config.py` Settings'ten: `logo_max_bytes`, `allowed_logo_content_types`, `default_brand_color`, `default_accent_color`, `default_vat_rate`.
- **Dosya boyutu:** Tek dosya 400 satırı geçmemeli; geçiyorsa böl.
- **Migration:** Tek additive migration (3 tablo + 4 enum). Yeni PG enum tipleri `downgrade()` içinde AÇIKÇA düşürülür (`sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`). Migration ASLA dev DB'de denenmez; yalnızca `TEST_DATABASE_URL`. Canlıda additive + geriye dönük uyumlu olmalı.
- **Test:** Her task TDD — önce başarısız test, sonra minimal implementasyon. Faz sonunda kapsam ≥ %85, `ruff` temiz.
- **Commit:** Her task sonunda commit. Format `<type>: <açıklama>` (feat, fix, refactor, test, chore, docs). Branch: `feat/b4-company-settings` (zaten oluşturuldu ve checkout'lu).

---

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `app/core/config.py` | Logo/marka/KDV config alanları eklenir + `allowed_logo_content_type_set` property. |
| `app/core/bootstrap.py` | `ensure_company()` eklenir (tek satır garanti). |
| `app/main.py` | Lifespan'de `ensure_company()` çağrısı; `company_router` + `settings_router` kaydı. |
| `app/modules/company/__init__.py` | Boş paket işareti. |
| `app/modules/company/models.py` | `Company` (bytea logo + `only_row` singleton koruması). |
| `app/modules/company/schemas.py` | `CompanyRead` (logo bytes HARİÇ + `has_logo`/`logo_url`), `CompanyUpdate`. |
| `app/modules/company/repository.py` | `get_or_create_singleton`, `set_logo`, `clear_logo`. |
| `app/modules/company/service.py` | `get_company`, `update_company`, `set_logo`, `clear_logo`. |
| `app/modules/company/router.py` | `GET/PUT /company`, `POST/GET/DELETE /company/logo`. |
| `app/modules/settings/__init__.py` | Boş paket işareti. |
| `app/modules/settings/constants.py` | `NOTIFICATION_EVENTS` kataloğu + `NOTIFICATION_EVENT_KEYS`. |
| `app/modules/settings/models.py` | `UserPreferences`, `NotificationPref` + enum'lar (`UILocale`, `UICurrency`, `UIDensity`, `UITheme`). |
| `app/modules/settings/schemas.py` | `PreferencesRead`, `PreferencesUpdate`, `NotificationPrefItem`, `NotificationPrefsUpdate`. |
| `app/modules/settings/repository.py` | `get_preferences`, `upsert_preferences`, `list_notification_prefs`, `upsert_notification_pref`. |
| `app/modules/settings/service.py` | `get_preferences`, `update_preferences`, `get_notifications`, `update_notifications`. |
| `app/modules/settings/router.py` | `GET/PUT /settings/preferences`, `GET/PUT /settings/notifications`. |
| `alembic/env.py` | `company` + `settings` model import'ları eklenir. |
| `alembic/versions/*` | 1 yeni migration: `company` + `user_preferences` + `notification_prefs` tabloları + 4 enum. |
| `tests/conftest.py` | `company` + `settings` model import'ları (create_all için). |
| `tests/modules/test_company_settings_models.py` | Model default + singleton CHECK + config testleri (Task 1). |
| `tests/modules/test_company_api.py` | Şirket okuma/yazma uçları (Task 2). |
| `tests/modules/test_company_logo.py` | Logo yükle/getir/sil (Task 3). |
| `tests/modules/test_preferences_api.py` | Görünüm tercihleri self-service (Task 4). |
| `tests/modules/test_notifications_api.py` | Bildirim tercihleri self-service (Task 5). |

---

## Task 1: Şema temeli — config + 3 model + tek migration

**Files:**
- Modify: `app/core/config.py`
- Create: `app/modules/company/__init__.py`, `app/modules/company/models.py`
- Create: `app/modules/settings/__init__.py`, `app/modules/settings/models.py`
- Modify: `app/core/bootstrap.py` (ensure_company), `app/main.py` (lifespan çağrısı)
- Modify: `alembic/env.py`, `tests/conftest.py` (model import'ları)
- Create: `alembic/versions/<yeni>_b4_company_settings_tablolari.py`
- Test: `tests/modules/test_company_settings_models.py`

**Interfaces:**
- Produces:
  - `app.modules.company.models.Company` (ORM); alanlar: `id, only_row, name, tax_number, tax_office, trade_registry_no, kep_address, phone, email, website, address, logo_data, logo_content_type, logo_filename, brand_color, gib_integration_code, earsiv_portal, default_vat_rate, auto_einvoice, created_at, updated_at`.
  - `app.modules.settings.models.UserPreferences` (PK `user_id`), `NotificationPref` (UNIQUE `user_id, event_key`).
  - Enum'lar `UILocale{tr,en}`, `UICurrency{TRY,USD,EUR}`, `UIDensity{comfortable,normal,compact}`, `UITheme{light,dark,system}`.
  - `settings.logo_max_bytes: int`, `settings.allowed_logo_content_type_set: set[str]`, `settings.default_brand_color/default_accent_color: str`, `settings.default_vat_rate: Decimal`.
  - `app.core.bootstrap.ensure_company()`.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_company_settings_models.py
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings as app_settings
from app.modules.company.models import Company
from app.modules.settings.models import NotificationPref, UserPreferences


def test_logo_and_brand_config_defaults():
    assert app_settings.logo_max_bytes == 1_048_576
    assert "image/png" in app_settings.allowed_logo_content_type_set
    assert "image/svg+xml" in app_settings.allowed_logo_content_type_set
    assert app_settings.default_brand_color == "#2563eb"
    assert str(app_settings.default_vat_rate) == "20.00"


async def test_company_defaults(db_session):
    company = Company()
    db_session.add(company)
    await db_session.flush()
    assert company.only_row is True
    assert company.brand_color == "#2563eb"
    assert str(company.default_vat_rate) == "20.00"
    assert company.auto_einvoice is False
    assert company.logo_data is None


async def test_company_is_singleton(db_session):
    db_session.add(Company())
    await db_session.flush()
    db_session.add(Company())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_preferences_defaults(db_session, user_factory):
    user = await user_factory(email="pref@t.co", password="parola1234", role_key="patron")
    prefs = UserPreferences(user_id=user.id)
    db_session.add(prefs)
    await db_session.flush()
    assert prefs.locale.value == "tr"
    assert prefs.currency.value == "TRY"
    assert prefs.density.value == "normal"
    assert prefs.theme.value == "light"
    assert prefs.accent_color == "#2563eb"


async def test_notification_pref_unique(db_session, user_factory):
    user = await user_factory(email="notif@t.co", password="parola1234", role_key="patron")
    db_session.add(NotificationPref(user_id=user.id, event_key="vat_due_soon", email=True, in_app=True, sms=False))
    await db_session.flush()
    db_session.add(NotificationPref(user_id=user.id, event_key="vat_due_soon", email=False, in_app=False, sms=False))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_settings_models.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.company` / config alanları yok.

- [ ] **Step 3: Config alanlarını ekle**

```python
# app/core/config.py — importlara ekle:
from decimal import Decimal
```

```python
# app/core/config.py — Settings sınıfı içine (admin_password'dan sonra) ekle:

    # Sirket logosu DB'de bytea saklanir (object storage yok). Yukleme sinirlari + marka
    # varsayilanlari config'ten gelir (hardcode degil).
    logo_max_bytes: int = 1_048_576  # 1 MB
    allowed_logo_content_types: str = "image/png,image/jpeg,image/svg+xml,image/webp"
    default_brand_color: str = "#2563eb"
    default_accent_color: str = "#2563eb"
    default_vat_rate: Decimal = Decimal("20.00")
```

```python
# app/core/config.py — Settings sınıfı içine, cors_origin_list property'sinin yanına ekle:

    @property
    def allowed_logo_content_type_set(self) -> set[str]:
        """Izin verilen logo MIME tiplerini kume olarak dondurur."""
        return {t.strip() for t in self.allowed_logo_content_types.split(",") if t.strip()}
```

- [ ] **Step 4: Company modelini oluştur**

```python
# app/modules/company/__init__.py
```
(boş dosya)

```python
# app/modules/company/models.py
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Company(Base):
    """Tek satirlik sirket bilgisi (spec §4.1). Cok-sirketlilik yok.

    Tekillik `only_row` uzerindeki UNIQUE + `only_row IS TRUE` CHECK ile zorlanir:
    ikinci satir eklenirse UNIQUE ihlali olur.
    """

    __tablename__ = "company"
    __table_args__ = (CheckConstraint("only_row IS TRUE", name="company_single_row"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    only_row: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", unique=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_office: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trade_registry_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kep_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="#2563eb", server_default="#2563eb"
    )
    gib_integration_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    earsiv_portal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("20.00"), server_default="20.00"
    )
    auto_einvoice: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 5: Settings modellerini oluştur**

```python
# app/modules/settings/__init__.py
```
(boş dosya)

```python
# app/modules/settings/models.py
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UILocale(str, enum.Enum):
    tr = "tr"
    en = "en"


class UICurrency(str, enum.Enum):
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


class UIDensity(str, enum.Enum):
    comfortable = "comfortable"
    normal = "normal"
    compact = "compact"


class UITheme(str, enum.Enum):
    light = "light"
    dark = "dark"
    system = "system"


class UserPreferences(Base):
    """Kullanici-basina gorunum tercihleri (spec §4.1). Self-service."""

    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[UILocale] = mapped_column(
        Enum(UILocale, name="ui_locale"), nullable=False, default=UILocale.tr, server_default="tr"
    )
    currency: Mapped[UICurrency] = mapped_column(
        Enum(UICurrency, name="ui_currency"),
        nullable=False,
        default=UICurrency.TRY,
        server_default="TRY",
    )
    date_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DD.MM.YYYY", server_default="DD.MM.YYYY"
    )
    density: Mapped[UIDensity] = mapped_column(
        Enum(UIDensity, name="ui_density"),
        nullable=False,
        default=UIDensity.normal,
        server_default="normal",
    )
    theme: Mapped[UITheme] = mapped_column(
        Enum(UITheme, name="ui_theme"),
        nullable=False,
        default=UITheme.light,
        server_default="light",
    )
    accent_color: Mapped[str] = mapped_column(
        String(20), nullable=False, default="#2563eb", server_default="#2563eb"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NotificationPref(Base):
    """Kullanici-basina olay kanal tercihi (spec §4.1). v1'de gonderim yok, yalnizca kayit."""

    __tablename__ = "notification_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_key: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 6: `env.py` ve `conftest.py`'ye model import'larını ekle**

`alembic/env.py` — mevcut model import'larının yanına:
```python
from app.modules.company import models as company_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
```

`tests/conftest.py` — mevcut model import'larının yanına (böylece `Base.metadata.create_all` yeni tabloları kurar):
```python
from app.modules.company import models as company_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
```

- [ ] **Step 7: Model + config testinin geçtiğini doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_settings_models.py -v`
Expected: PASS (5 test). `_create_schema` fixture'ı tabloları modelden kurar.

- [ ] **Step 8: `ensure_company` bootstrap'ı ekle**

```python
# app/core/bootstrap.py — importlara ekle:
from app.modules.company.models import Company
```

```python
# app/core/bootstrap.py — dosyanın sonuna ekle:
async def ensure_company() -> None:
    """DB'de sirket satiri yoksa bos tek satiri olusturur (spec §4.1: tek sirket).

    Idempotent: satir varsa hicbir sey yapmaz. GET /company okuma yolunda da get-or-create
    vardir; bu bootstrap yalnizca ilk istegin yazma yapmamasi icin sicak-baslatmadir.
    """
    async with SessionLocal() as session:
        existing = await session.scalar(select(func.count()).select_from(Company))
        if existing:
            return
        session.add(Company())
        await session.commit()
        logger.info("Bos sirket satiri olusturuldu.")
```

- [ ] **Step 9: `main.py` lifespan'de `ensure_company` çağır**

```python
# app/main.py — importlara ekle:
from app.core.bootstrap import ensure_company, ensure_first_admin
```

```python
# app/main.py — lifespan içinde ensure_first_admin try/except bloğunun ardına ekle:
    try:
        await ensure_company()
    except Exception:
        logger.exception("Sirket bootstrap'i basarisiz oldu")
```

- [ ] **Step 10: Migration yaz**

```bash
.venv/bin/alembic revision -m "b4 company settings tablolari"
```
Üretilen dosyayı düzenle — `down_revision = "1c788f666c43"` (mevcut head) ve gövde:

```python
def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("only_row", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("tax_number", sa.String(length=50), nullable=True),
        sa.Column("tax_office", sa.String(length=100), nullable=True),
        sa.Column("trade_registry_no", sa.String(length=100), nullable=True),
        sa.Column("kep_address", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("logo_data", sa.LargeBinary(), nullable=True),
        sa.Column("logo_content_type", sa.String(length=100), nullable=True),
        sa.Column("logo_filename", sa.String(length=255), nullable=True),
        sa.Column("brand_color", sa.String(length=20), server_default="#2563eb", nullable=False),
        sa.Column("gib_integration_code", sa.String(length=100), nullable=True),
        sa.Column("earsiv_portal", sa.String(length=255), nullable=True),
        sa.Column("default_vat_rate", sa.Numeric(precision=5, scale=2), server_default="20.00", nullable=False),
        sa.Column("auto_einvoice", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("only_row IS TRUE", name="company_single_row"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("only_row"),
    )
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("locale", sa.Enum("tr", "en", name="ui_locale"), server_default="tr", nullable=False),
        sa.Column("currency", sa.Enum("TRY", "USD", "EUR", name="ui_currency"), server_default="TRY", nullable=False),
        sa.Column("date_format", sa.String(length=20), server_default="DD.MM.YYYY", nullable=False),
        sa.Column("density", sa.Enum("comfortable", "normal", "compact", name="ui_density"), server_default="normal", nullable=False),
        sa.Column("theme", sa.Enum("light", "dark", "system", name="ui_theme"), server_default="light", nullable=False),
        sa.Column("accent_color", sa.String(length=20), server_default="#2563eb", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "notification_prefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("event_key", sa.String(length=100), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("sms", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),
    )
    op.create_index(op.f("ix_notification_prefs_user_id"), "notification_prefs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_prefs_user_id"), table_name="notification_prefs")
    op.drop_table("notification_prefs")
    op.drop_table("user_preferences")
    op.drop_table("company")
    # Bos-kolonlu drop_table enum'u otomatik dusurmez — acikca dusur (DuplicateObject korumasi).
    sa.Enum(name="ui_locale").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_currency").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_density").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ui_theme").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 11: Migration zincirini `TEST_DATABASE_URL`'de doğrula**

Run: `DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade head && DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic downgrade -1 && DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade head`
Expected: hatasız (ASLA dev DB'de değil). Zincir kirliyse önce TEST DB şemasını sıfırla (`DROP SCHEMA public CASCADE; CREATE SCHEMA public`), sonra tekrar dene.

- [ ] **Step 12: ruff + odaklı testi tekrar çalıştır**

Run: `.venv/bin/ruff check app/modules/company app/modules/settings app/core/config.py app/core/bootstrap.py && .venv/bin/python -m pytest tests/modules/test_company_settings_models.py -v`
Expected: ruff temiz, testler PASS.

- [ ] **Step 13: Commit**

```bash
git add app/modules/company/__init__.py app/modules/company/models.py \
        app/modules/settings/__init__.py app/modules/settings/models.py \
        app/core/config.py app/core/bootstrap.py app/main.py \
        alembic/env.py alembic/versions/ tests/conftest.py \
        tests/modules/test_company_settings_models.py
git commit -m "feat: b4 sema temeli - company + preferences + notification tablolari"
```

---

## Task 2: Şirket okuma/yazma (`GET/PUT /company`)

**Files:**
- Create: `app/modules/company/schemas.py`, `app/modules/company/repository.py`, `app/modules/company/service.py`, `app/modules/company/router.py`
- Modify: `app/main.py` (router kaydı)
- Test: `tests/modules/test_company_api.py`

**Interfaces:**
- Consumes: `Company` (Task 1), `require_permission` / `AccessLevel` (`app.core.permissions` / `app.core.access`), `get_current_user` (`app.core.deps`), `get_db` (`app.core.db`), `settings` (`app.core.config`).
- Produces:
  - `repository.get_or_create_singleton(session) -> Company`
  - `service.get_company(session) -> Company`; `service.update_company(session, data: CompanyUpdate) -> Company`
  - `schemas.CompanyRead.from_model(company) -> CompanyRead`; `schemas.CompanyUpdate`
  - Router `company_router` (prefix `/company`).

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_company_api.py
async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"})
    return resp.json()["access_token"]


async def test_get_company_any_authenticated_user(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")  # settings=none ama okuma serbest
    resp = await client.get("/company", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_logo"] is False
    assert body["logo_url"] == "/company/logo"
    assert body["brand_color"] == "#2563eb"
    assert "logo_data" not in body


async def test_get_company_requires_auth(client, seeded_db):
    resp = await client.get("/company")
    assert resp.status_code == 401


async def test_update_company_as_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put(
        "/company",
        json={"name": "FIIL Yapi A.S.", "tax_number": "1234567890", "default_vat_rate": "10.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "FIIL Yapi A.S."
    # kalicilik: yeniden oku
    again = await client.get("/company", headers={"Authorization": f"Bearer {token}"})
    assert again.json()["tax_number"] == "1234567890"
    assert again.json()["default_vat_rate"] == "10.00"


async def test_update_company_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "accounting")  # settings=none
    resp = await client.put("/company", json={"name": "X"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_update_company_invalid_brand_color(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put("/company", json={"brand_color": "mavi"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


async def test_update_company_invalid_email(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put("/company", json={"email": "gecersiz"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


async def test_update_company_vat_out_of_range(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.put("/company", json={"default_vat_rate": "150.00"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_api.py -v`
Expected: FAIL (404/ImportError — `/company` yok).

- [ ] **Step 3: Schemas yaz**

```python
# app/modules/company/schemas.py
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.company.models import Company

_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class CompanyUpdate(BaseModel):
    """Kismi guncelleme — tum alanlar opsiyonel. Gonderilmeyen alan degismez."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    tax_number: str | None = Field(default=None, max_length=50)
    tax_office: str | None = Field(default=None, max_length=100)
    trade_registry_no: str | None = Field(default=None, max_length=100)
    kep_address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    website: str | None = Field(default=None, max_length=255)
    address: str | None = None
    brand_color: str | None = Field(default=None, pattern=_HEX_COLOR)
    gib_integration_code: str | None = Field(default=None, max_length=100)
    earsiv_portal: str | None = Field(default=None, max_length=255)
    default_vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    auto_einvoice: bool | None = None


class CompanyRead(BaseModel):
    """Sirket okuma modeli. Logo bytea'si ASLA burada donmez; yalnizca has_logo + logo_url."""

    id: uuid.UUID
    name: str | None
    tax_number: str | None
    tax_office: str | None
    trade_registry_no: str | None
    kep_address: str | None
    phone: str | None
    email: str | None
    website: str | None
    address: str | None
    brand_color: str
    gib_integration_code: str | None
    earsiv_portal: str | None
    default_vat_rate: Decimal
    auto_einvoice: bool
    has_logo: bool
    logo_url: str

    @classmethod
    def from_model(cls, company: Company) -> "CompanyRead":
        return cls(
            id=company.id,
            name=company.name,
            tax_number=company.tax_number,
            tax_office=company.tax_office,
            trade_registry_no=company.trade_registry_no,
            kep_address=company.kep_address,
            phone=company.phone,
            email=company.email,
            website=company.website,
            address=company.address,
            brand_color=company.brand_color,
            gib_integration_code=company.gib_integration_code,
            earsiv_portal=company.earsiv_portal,
            default_vat_rate=company.default_vat_rate,
            auto_einvoice=company.auto_einvoice,
            has_logo=company.logo_data is not None,
            logo_url="/company/logo",
        )
```

- [ ] **Step 4: Repository yaz**

```python
# app/modules/company/repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company.models import Company


async def get_or_create_singleton(session: AsyncSession) -> Company:
    """Tek sirket satirini dondurur; yoksa bos satir olusturur (spec §4.1)."""
    company = await session.scalar(select(Company).limit(1))
    if company is None:
        company = Company()
        session.add(company)
        await session.flush()
    return company
```

- [ ] **Step 5: Service yaz**

```python
# app/modules/company/service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.company import repository
from app.modules.company.models import Company
from app.modules.company.schemas import CompanyUpdate


async def get_company(session: AsyncSession) -> Company:
    return await repository.get_or_create_singleton(session)


async def update_company(session: AsyncSession, data: CompanyUpdate) -> Company:
    company = await repository.get_or_create_singleton(session)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await session.flush()
    return company
```

- [ ] **Step 6: Router yaz**

```python
# app/modules/company/router.py
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.company import service
from app.modules.company.schemas import CompanyRead, CompanyUpdate
from app.modules.users.models import User

router = APIRouter(prefix="/company", tags=["company"], responses=COMMON_ERROR_RESPONSES)


@router.get("", response_model=CompanyRead)
async def get_company_endpoint(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    company = await service.get_company(session)
    return CompanyRead.from_model(company)


@router.put(
    "",
    response_model=CompanyRead,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def update_company_endpoint(
    data: CompanyUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyRead:
    company = await service.update_company(session, data)
    return CompanyRead.from_model(company)
```

- [ ] **Step 7: Router'ı kaydet**

```python
# app/main.py — importlara ekle:
from app.modules.company.router import router as company_router
```
```python
# app/main.py — include_router bloğuna ekle (auth_router yanına):
app.include_router(company_router)
```

- [ ] **Step 8: Testin geçtiğini doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_api.py -v`
Expected: PASS (7 test).

- [ ] **Step 9: ruff + commit**

Run: `.venv/bin/ruff check app/modules/company`
Expected: temiz.
```bash
git add app/modules/company/ app/main.py tests/modules/test_company_api.py
git commit -m "feat: sirket okuma/yazma uclari (settings full kapisi)"
```

---

## Task 3: Şirket logosu (`POST/GET/DELETE /company/logo`)

**Files:**
- Modify: `app/modules/company/repository.py`, `app/modules/company/service.py`, `app/modules/company/router.py`
- Test: `tests/modules/test_company_logo.py`

**Interfaces:**
- Consumes: Task 2 çıktıları, `settings.logo_max_bytes`, `settings.allowed_logo_content_type_set`, `NotFoundError` (`app.core.errors`).
- Produces:
  - `repository.set_logo(session, content_type, filename, data) -> Company`; `repository.clear_logo(session) -> Company`
  - `service.set_logo(...) -> Company`; `service.clear_logo(session) -> Company`
  - Router uçları `POST /company/logo`, `GET /company/logo`, `DELETE /company/logo`.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_company_logo.py
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # kucuk sahte PNG govdesi


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"})
    return resp.json()["access_token"]


async def test_upload_and_fetch_logo(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    up = await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up.status_code == 200
    assert up.json()["has_logo"] is True

    got = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/png")
    assert got.content == _PNG


async def test_upload_logo_invalid_content_type(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.gif", _PNG, "image/gif")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_upload_logo_too_large(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    big = b"0" * (1_048_576 + 1)
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.png", big, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413


async def test_get_logo_when_none(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")
    resp = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_upload_logo_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_delete_logo(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    await client.post(
        "/company/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    deleted = await client.delete("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 204
    got = await client.get("/company/logo", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 404
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_logo.py -v`
Expected: FAIL (404 — logo uçları yok).

- [ ] **Step 3: Repository'ye logo fonksiyonları ekle**

```python
# app/modules/company/repository.py — sona ekle:
async def set_logo(
    session: AsyncSession, content_type: str, filename: str | None, data: bytes
) -> Company:
    company = await get_or_create_singleton(session)
    company.logo_data = data
    company.logo_content_type = content_type
    company.logo_filename = filename
    await session.flush()
    return company


async def clear_logo(session: AsyncSession) -> Company:
    company = await get_or_create_singleton(session)
    company.logo_data = None
    company.logo_content_type = None
    company.logo_filename = None
    await session.flush()
    return company
```

- [ ] **Step 4: Service'e logo fonksiyonları ekle**

```python
# app/modules/company/service.py — sona ekle:
async def set_logo(
    session: AsyncSession, content_type: str, filename: str | None, data: bytes
) -> Company:
    return await repository.set_logo(session, content_type, filename, data)


async def clear_logo(session: AsyncSession) -> Company:
    return await repository.clear_logo(session)
```

- [ ] **Step 5: Router'a logo uçlarını ekle**

```python
# app/modules/company/router.py — importları güncelle:
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.core.config import settings
from app.core.errors import NotFoundError
```
```python
# app/modules/company/router.py — mevcut uçların ardına ekle:
@router.post(
    "/logo",
    response_model=CompanyRead,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def upload_logo_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> CompanyRead:
    if file.content_type not in settings.allowed_logo_content_type_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Desteklenmeyen logo bicimi (izinli: PNG, JPEG, SVG, WEBP)",
        )
    content = await file.read()
    if len(content) > settings.logo_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo boyutu cok buyuk (en fazla 1 MB)",
        )
    company = await service.set_logo(session, file.content_type, file.filename, content)
    return CompanyRead.from_model(company)


@router.get("/logo")
async def get_logo_endpoint(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    company = await service.get_company(session)
    if company.logo_data is None:
        raise NotFoundError("Logo yuklenmemis")
    return Response(
        content=company.logo_data,
        media_type=company.logo_content_type or "application/octet-stream",
    )


@router.delete(
    "/logo",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("settings", AccessLevel.full)],
)
async def delete_logo_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.clear_logo(session)
```

- [ ] **Step 6: Testin geçtiğini doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_company_logo.py -v`
Expected: PASS (6 test).

- [ ] **Step 7: ruff + commit**

Run: `.venv/bin/ruff check app/modules/company`
Expected: temiz.
```bash
git add app/modules/company/ tests/modules/test_company_logo.py
git commit -m "feat: sirket logosu yukle/getir/sil (DB bytea, tip+boyut dogrulama)"
```

---

## Task 4: Görünüm tercihleri — self-service (`GET/PUT /settings/preferences`)

**Files:**
- Create: `app/modules/settings/schemas.py`, `app/modules/settings/repository.py`, `app/modules/settings/service.py`, `app/modules/settings/router.py`
- Modify: `app/main.py` (router kaydı)
- Test: `tests/modules/test_preferences_api.py`

**Interfaces:**
- Consumes: `UserPreferences` + enum'lar (Task 1), `get_current_user`, `get_db`.
- Produces:
  - `repository.get_preferences(session, user_id) -> UserPreferences | None`; `repository.upsert_preferences(session, user_id, values: dict) -> UserPreferences`
  - `service.get_preferences(session, user) -> PreferencesRead`; `service.update_preferences(session, user, data: PreferencesUpdate) -> PreferencesRead`
  - `schemas.PreferencesRead`, `schemas.PreferencesUpdate`
  - `settings_router` (prefix `/settings`).

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_preferences_api.py
async def _login(client, user_factory, email: str, role_key: str = "patron") -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    return resp.json()["access_token"]


async def test_get_preferences_defaults_when_no_row(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "a@t.co")
    resp = await client.get("/settings/preferences", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["locale"] == "tr"
    assert body["currency"] == "TRY"
    assert body["theme"] == "light"


async def test_update_preferences_upsert(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "b@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"locale": "en", "currency": "USD", "density": "compact"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    again = await client.get("/settings/preferences", headers={"Authorization": f"Bearer {token}"})
    assert again.json()["locale"] == "en"
    assert again.json()["currency"] == "USD"
    assert again.json()["density"] == "compact"


async def test_update_preferences_dark_theme_rejected(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "c@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"theme": "dark"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_update_preferences_invalid_currency(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "d@t.co")
    resp = await client.put(
        "/settings/preferences",
        json={"currency": "GBP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_preferences_are_per_user(client, user_factory, seeded_db):
    token_a = await _login(client, user_factory, "u1@t.co")
    token_b = await _login(client, user_factory, "u2@t.co")
    await client.put(
        "/settings/preferences",
        json={"locale": "en"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get("/settings/preferences", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_b.json()["locale"] == "tr"  # B kullanicisi etkilenmedi
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_preferences_api.py -v`
Expected: FAIL (404/ImportError).

- [ ] **Step 3: Schemas yaz**

```python
# app/modules/settings/schemas.py
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.settings.models import UICurrency, UIDensity, UILocale, UITheme

_HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: UILocale
    currency: UICurrency
    date_format: str
    density: UIDensity
    theme: UITheme
    accent_color: str


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: UILocale | None = None
    currency: UICurrency | None = None
    date_format: str | None = Field(default=None, max_length=20)
    density: UIDensity | None = None
    theme: UITheme | None = None
    accent_color: str | None = Field(default=None, pattern=_HEX_COLOR)

    @field_validator("theme")
    @classmethod
    def _only_light_theme(cls, value: UITheme | None) -> UITheme | None:
        # Spec §9: v1'de yalnizca acik tema aktif; koyu/sistem pasif.
        if value is not None and value is not UITheme.light:
            raise ValueError("Koyu tema henuz aktif degil")
        return value
```

- [ ] **Step 4: Repository yaz**

```python
# app/modules/settings/repository.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.models import NotificationPref, UserPreferences


async def get_preferences(session: AsyncSession, user_id: uuid.UUID) -> UserPreferences | None:
    return await session.get(UserPreferences, user_id)


async def upsert_preferences(
    session: AsyncSession, user_id: uuid.UUID, values: dict
) -> UserPreferences:
    prefs = await session.get(UserPreferences, user_id)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id, **values)
        session.add(prefs)
    else:
        for field, value in values.items():
            setattr(prefs, field, value)
    await session.flush()
    return prefs


async def list_notification_prefs(
    session: AsyncSession, user_id: uuid.UUID
) -> list[NotificationPref]:
    result = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id == user_id)
    )
    return list(result.scalars().all())


async def upsert_notification_pref(
    session: AsyncSession,
    user_id: uuid.UUID,
    event_key: str,
    email: bool,
    in_app: bool,
    sms: bool,
) -> NotificationPref:
    existing = await session.scalar(
        select(NotificationPref).where(
            NotificationPref.user_id == user_id, NotificationPref.event_key == event_key
        )
    )
    if existing is None:
        existing = NotificationPref(
            user_id=user_id, event_key=event_key, email=email, in_app=in_app, sms=sms
        )
        session.add(existing)
    else:
        existing.email = email
        existing.in_app = in_app
        existing.sms = sms
    await session.flush()
    return existing
```

- [ ] **Step 5: Service yaz (preferences kısmı)**

```python
# app/modules/settings/service.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings import repository
from app.modules.settings.models import UICurrency, UIDensity, UILocale, UITheme, UserPreferences
from app.modules.settings.schemas import PreferencesRead, PreferencesUpdate
from app.modules.users.models import User


def _default_preferences() -> PreferencesRead:
    return PreferencesRead(
        locale=UILocale.tr,
        currency=UICurrency.TRY,
        date_format="DD.MM.YYYY",
        density=UIDensity.normal,
        theme=UITheme.light,
        accent_color="#2563eb",
    )


async def get_preferences(session: AsyncSession, user: User) -> PreferencesRead:
    prefs = await repository.get_preferences(session, user.id)
    if prefs is None:
        return _default_preferences()
    return PreferencesRead.model_validate(prefs)


async def update_preferences(
    session: AsyncSession, user: User, data: PreferencesUpdate
) -> PreferencesRead:
    values = data.model_dump(exclude_unset=True)
    prefs: UserPreferences = await repository.upsert_preferences(session, user.id, values)
    return PreferencesRead.model_validate(prefs)
```

- [ ] **Step 6: Router yaz (preferences kısmı)**

```python
# app/modules/settings/router.py
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.modules.settings import service
from app.modules.settings.schemas import PreferencesRead, PreferencesUpdate
from app.modules.users.models import User

router = APIRouter(prefix="/settings", tags=["settings"], responses=COMMON_ERROR_RESPONSES)


@router.get("/preferences", response_model=PreferencesRead)
async def get_preferences_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesRead:
    return await service.get_preferences(session, user)


@router.put("/preferences", response_model=PreferencesRead)
async def update_preferences_endpoint(
    data: PreferencesUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesRead:
    return await service.update_preferences(session, user, data)
```

- [ ] **Step 7: Router'ı kaydet**

```python
# app/main.py — importlara ekle:
from app.modules.settings.router import router as settings_router
```
```python
# app/main.py — include_router bloğuna ekle:
app.include_router(settings_router)
```

- [ ] **Step 8: Testin geçtiğini doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_preferences_api.py -v`
Expected: PASS (5 test).

- [ ] **Step 9: ruff + commit**

Run: `.venv/bin/ruff check app/modules/settings`
Expected: temiz.
```bash
git add app/modules/settings/ app/main.py tests/modules/test_preferences_api.py
git commit -m "feat: gorunum tercihleri self-service (light-only tema kapisi)"
```

---

## Task 5: Bildirim tercihleri — self-service (`GET/PUT /settings/notifications`)

**Files:**
- Create: `app/modules/settings/constants.py`
- Modify: `app/modules/settings/schemas.py`, `app/modules/settings/service.py`, `app/modules/settings/router.py`
- Test: `tests/modules/test_notifications_api.py`

**Interfaces:**
- Consumes: Task 4 çıktıları, `repository.list_notification_prefs`, `repository.upsert_notification_pref` (Task 4'te tanımlandı).
- Produces:
  - `constants.NOTIFICATION_EVENTS: list[dict]`, `constants.NOTIFICATION_EVENT_KEYS: set[str]`, `constants.NOTIFICATION_LABELS: dict[str, str]`
  - `schemas.NotificationPrefItem`, `schemas.NotificationPrefUpdateItem`, `schemas.NotificationPrefsUpdate`
  - `service.get_notifications(session, user) -> list[NotificationPrefItem]`; `service.update_notifications(session, user, data) -> list[NotificationPrefItem]`
  - Router uçları `GET/PUT /settings/notifications`.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_notifications_api.py
from app.modules.settings.constants import NOTIFICATION_EVENTS


async def _login(client, user_factory, email: str, role_key: str = "patron") -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    return resp.json()["access_token"]


async def test_get_notifications_returns_full_catalog(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n1@t.co")
    resp = await client.get("/settings/notifications", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(NOTIFICATION_EVENTS)
    assert {item["event_key"] for item in body} == {e["event_key"] for e in NOTIFICATION_EVENTS}
    assert all("label" in item for item in body)


async def test_update_notification_overrides_default(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n2@t.co")
    key = NOTIFICATION_EVENTS[0]["event_key"]
    resp = await client.put(
        "/settings/notifications",
        json={"items": [{"event_key": key, "email": False, "in_app": False, "sms": True}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    again = await client.get("/settings/notifications", headers={"Authorization": f"Bearer {token}"})
    row = next(i for i in again.json() if i["event_key"] == key)
    assert row["email"] is False and row["in_app"] is False and row["sms"] is True


async def test_update_notification_unknown_event_rejected(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "n3@t.co")
    resp = await client.put(
        "/settings/notifications",
        json={"items": [{"event_key": "bilinmeyen_olay", "email": True, "in_app": True, "sms": False}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_notifications_are_per_user(client, user_factory, seeded_db):
    token_a = await _login(client, user_factory, "n4@t.co")
    token_b = await _login(client, user_factory, "n5@t.co")
    key = NOTIFICATION_EVENTS[0]["event_key"]
    await client.put(
        "/settings/notifications",
        json={"items": [{"event_key": key, "email": True, "in_app": True, "sms": True}]},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    resp_b = await client.get("/settings/notifications", headers={"Authorization": f"Bearer {token_b}"})
    row_b = next(i for i in resp_b.json() if i["event_key"] == key)
    default = next(e for e in NOTIFICATION_EVENTS if e["event_key"] == key)
    assert row_b["sms"] == default["sms"]  # B kullanicisi varsayilanda kaldi
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_notifications_api.py -v`
Expected: FAIL (ImportError — constants yok).

- [ ] **Step 3: Katalog sabitini yaz**

```python
# app/modules/settings/constants.py
"""Bildirim olay katalogu. Migration'da per-user seed YOK — GET varsayilanlarla merge eder.

Yeni olay eklemek yalnizca bu listeyi genisletir; backfill gerekmez.
"""

NOTIFICATION_EVENTS: list[dict] = [
    {"event_key": "progress_payment_created", "label": "Hakedis olusturuldu", "email": True, "in_app": True, "sms": False},
    {"event_key": "vat_due_soon", "label": "KDV odemesi yaklasiyor", "email": True, "in_app": True, "sms": False},
    {"event_key": "approval_pending", "label": "Onay bekleyen islem", "email": False, "in_app": True, "sms": False},
    {"event_key": "stock_low", "label": "Stok kritik seviyede", "email": False, "in_app": True, "sms": False},
    {"event_key": "user_added", "label": "Yeni kullanici eklendi", "email": False, "in_app": True, "sms": False},
]

NOTIFICATION_EVENT_KEYS: set[str] = {event["event_key"] for event in NOTIFICATION_EVENTS}
NOTIFICATION_LABELS: dict[str, str] = {event["event_key"]: event["label"] for event in NOTIFICATION_EVENTS}
```

- [ ] **Step 4: Schemas'a bildirim modellerini ekle**

```python
# app/modules/settings/schemas.py — importlara ekle:
from app.modules.settings.constants import NOTIFICATION_EVENT_KEYS
```
```python
# app/modules/settings/schemas.py — sona ekle:
class NotificationPrefItem(BaseModel):
    event_key: str
    label: str
    email: bool
    in_app: bool
    sms: bool


class NotificationPrefUpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_key: str
    email: bool
    in_app: bool
    sms: bool


class NotificationPrefsUpdate(BaseModel):
    items: list[NotificationPrefUpdateItem]

    @field_validator("items")
    @classmethod
    def _known_event_keys(
        cls, items: list[NotificationPrefUpdateItem]
    ) -> list[NotificationPrefUpdateItem]:
        unknown = {i.event_key for i in items} - NOTIFICATION_EVENT_KEYS
        if unknown:
            raise ValueError(f"Bilinmeyen bildirim olayi: {', '.join(sorted(unknown))}")
        return items
```

- [ ] **Step 5: Service'e bildirim fonksiyonlarını ekle**

```python
# app/modules/settings/service.py — importlara ekle:
from app.modules.settings.constants import NOTIFICATION_EVENTS, NOTIFICATION_LABELS
from app.modules.settings.schemas import NotificationPrefItem, NotificationPrefsUpdate
```
```python
# app/modules/settings/service.py — sona ekle:
async def get_notifications(session: AsyncSession, user: User) -> list[NotificationPrefItem]:
    """Katalogu saklanan satirlarla merge eder; eksik olaylar varsayilanla doner."""
    stored = {p.event_key: p for p in await repository.list_notification_prefs(session, user.id)}
    result: list[NotificationPrefItem] = []
    for event in NOTIFICATION_EVENTS:
        row = stored.get(event["event_key"])
        if row is None:
            result.append(
                NotificationPrefItem(
                    event_key=event["event_key"],
                    label=event["label"],
                    email=event["email"],
                    in_app=event["in_app"],
                    sms=event["sms"],
                )
            )
        else:
            result.append(
                NotificationPrefItem(
                    event_key=row.event_key,
                    label=NOTIFICATION_LABELS[row.event_key],
                    email=row.email,
                    in_app=row.in_app,
                    sms=row.sms,
                )
            )
    return result


async def update_notifications(
    session: AsyncSession, user: User, data: NotificationPrefsUpdate
) -> list[NotificationPrefItem]:
    for item in data.items:
        await repository.upsert_notification_pref(
            session, user.id, item.event_key, item.email, item.in_app, item.sms
        )
    return await get_notifications(session, user)
```

- [ ] **Step 6: Router'a bildirim uçlarını ekle**

```python
# app/modules/settings/router.py — import satirini guncelle:
from app.modules.settings.schemas import (
    NotificationPrefItem,
    NotificationPrefsUpdate,
    PreferencesRead,
    PreferencesUpdate,
)
```
```python
# app/modules/settings/router.py — sona ekle:
@router.get("/notifications", response_model=list[NotificationPrefItem])
async def get_notifications_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[NotificationPrefItem]:
    return await service.get_notifications(session, user)


@router.put("/notifications", response_model=list[NotificationPrefItem])
async def update_notifications_endpoint(
    data: NotificationPrefsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[NotificationPrefItem]:
    return await service.update_notifications(session, user, data)
```

- [ ] **Step 7: Testin geçtiğini doğrula**

Run: `.venv/bin/python -m pytest tests/modules/test_notifications_api.py -v`
Expected: PASS (4 test).

- [ ] **Step 8: ruff + commit**

Run: `.venv/bin/ruff check app/modules/settings`
Expected: temiz.
```bash
git add app/modules/settings/ tests/modules/test_notifications_api.py
git commit -m "feat: bildirim tercihleri self-service (katalog merge + bilinmeyen olay 422)"
```

---

## Task 6: Faz kapanışı — tam suite, kapsam, inceleme, OpenAPI

**Files:**
- Modify (gerekirse): inceleme bulgularına göre.
- Create: `openapi.json` (üretilir, commit'lenmez — frontend oturumunda kullanılır).

- [ ] **Step 1: Tüm B4 odaklı testleri birlikte çalıştır**

Run: `.venv/bin/python -m pytest tests/modules/test_company_settings_models.py tests/modules/test_company_api.py tests/modules/test_company_logo.py tests/modules/test_preferences_api.py tests/modules/test_notifications_api.py -v`
Expected: hepsi PASS.

- [ ] **Step 2: Tam suite + kapsam (bir kez, ~7 dk normal)**

Run: `.venv/bin/python -m pytest --cov=app --cov-report=term-missing -q`
Expected: tüm testler yeşil, kapsam ≥ %85. `company`/`settings` modüllerinde açık kalan satır varsa hedefli test ekle.

- [ ] **Step 3: ruff (tüm değişen alan)**

Run: `.venv/bin/ruff check app tests`
Expected: temiz (gerekirse `.venv/bin/ruff check --fix` sonra elle gözden geçir).

- [ ] **Step 4: Güvenlik + FastAPI incelemesi (paralel)**

`security-reviewer` ve `fastapi-reviewer` ajanlarını `app/modules/company` + `app/modules/settings` + `app/core/config.py` + `app/main.py` diff'i üzerine çalıştır. Odak:
- Logo yükleme: içerik-tipi/boyut doğrulaması, bytea sızıntısı (JSON'da logo_data YOK), SVG içeriğinin yalnızca `Response` ile ikili sunulması (inline render yok).
- Yetki: yazma uçları `settings/full`, okuma yalnızca `get_current_user`; tercih uçlarında kullanıcı yalnızca kendi `user.id`'sine erişiyor (IDOR yok).
- Tekillik: `company` yarış koşulunda IntegrityError → 409 handler'ı ile kapanıyor.
CRITICAL/HIGH bulgu kalırsa düzelt, ilgili testi ekle, commit et.

- [ ] **Step 5: OpenAPI üret (frontend için)**

Run: `.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False))" > openapi.json`
Expected: `openapi.json` içinde `/company`, `/company/logo`, `/settings/preferences`, `/settings/notifications` yolları görünür. Bu dosya commit'lenmez; frontend oturumunda `pnpm gen:api` için kullanılır.

- [ ] **Step 6: Faz kapanış commit'i (varsa artık düzeltmeler)**

```bash
git add -A -- ':!openapi.json'
git commit -m "chore: b4 faz kapanisi - inceleme duzeltmeleri + kapsam" || echo "ek degisiklik yok"
```

- [ ] **Step 7: Merge/deploy için kullanıcıya sor**

Faz bitti; `feat/b4-company-settings` branch'i hazır. Kullanıcıya özet sun (testler, kapsam, migration doğrulaması) ve merge + Railway deploy (canlı migration `1c788f666c43` → yeni head) onayı iste. Onay gelmeden `main`'e push YAPMA. Frontend F5 oturumunda `openapi.json` + `pnpm gen:api` hatırlat.

---

## Self-Review Notu (plan yazarından)

- **Spec kapsamı:** §4.1 `company`/`user_preferences`/`notification_prefs` → Task 1; §6.3 Ayarlar okuma/yazma → Task 2-5; §9 tema/çok-şirketlilik/bildirim-gönderim ödünçleri → Global Constraints + Task 4 tema kapısı. Tümü karşılandı.
- **Tip tutarlılığı:** `get_or_create_singleton`, `CompanyRead.from_model`, `upsert_preferences`, `upsert_notification_pref`, `get_notifications`/`update_notifications` adları tanımlandıkları task ile tüketildikleri task arasında birebir aynı.
- **Placeholder yok:** Her kod adımı tam gövde içerir; `NOTIFICATION_EVENTS` kataloğu nihai değerleriyle verildi.
