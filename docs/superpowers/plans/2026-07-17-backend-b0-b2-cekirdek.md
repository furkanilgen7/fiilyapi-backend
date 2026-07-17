# Backend Çekirdek (B0–B2) Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kimlik doğrulaması yapan ve 8 rol × 13 modüllük izin matrisini uygulayan çalışır bir FastAPI + Postgres API çekirdeği kurmak.

**Architecture:** Modüler FastAPI. Her modül `models · schemas · repository · service · router` iskeletini izler. Yetki tek bir `require_permission` bağımlılığından geçer; modüllere dağılmaz. Silme ayrı bir seviyedir (`admin`) ve yalnızca Sistem Yöneticisi'ndedir; sahibi kendi onaylanmamış taslağını silebilir.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · Pydantic v2 + pydantic-settings · argon2-cffi · PyJWT · pytest + pytest-asyncio + httpx

**Spec:** `docs/superpowers/specs/2026-07-17-temel-modul-design.md` — çelişki hâlinde spec kazanır.

## Global Constraints

- **Repo:** Tüm yollar `/Users/furkanilgen/Documents/Projeler/insaat/backend` köküne görelidir. Frontend ayrı bir repodur; bu planda ona dokunulmaz.
- **Dil:** Kod, değişken ve fonksiyon adları İngilizce. Kullanıcıya dönen hata mesajları Türkçe.
- **Çok şirketlilik yok.** Hiçbir tabloya `company_id` eklenmez (spec §9.1).
- **Silme:** `full` seviyesi silmeyi **kapsamaz**. Silme yalnızca `admin` seviyesindedir (spec §5.0).
- **Rol anahtarı sabit:** Yetki kontrolü `role.key` üzerinden yapılır, `role.name` üzerinden **asla**. Ad kullanıcı tarafından değiştirilebilir.
- **Kilitlenme koruması:** `system_admin` rolünün izin satırları hiçbir aktör tarafından değiştirilemez.
- **Seviye sırası:** `none < view < draft < request < approve < full < admin`
- **Dosya boyutu:** Tek dosya 400 satırı geçmemeli; geçiyorsa böl.
- **Test:** Her task TDD ile — önce başarısız test, sonra minimal implementasyon. Faz sonunda kapsam ≥ %80.
- **Commit:** Her task sonunda commit. Format: `<type>: <açıklama>` (feat, fix, test, chore, docs).

---

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `pyproject.toml` | Bağımlılıklar, pytest/ruff yapılandırması |
| `.env.example` | Ortam değişkeni şablonu (gerçek `.env` hazır, git'te değil) |
| `app/main.py` | FastAPI uygulaması, router kaydı, sağlık ucu |
| `app/core/config.py` | Ortam değişkenleri (pydantic-settings) |
| `app/core/db.py` | `Base`, engine, `SessionLocal`, `get_db` |
| `app/core/security.py` | Parola özeti (argon2), JWT üret/çöz |
| `app/core/deps.py` | `get_current_user` |
| `app/core/permissions.py` | `AccessLevel`, `Scope`, `satisfies`, `require_permission`, `can_delete` |
| `app/core/errors.py` | Alan hataları (`PermissionLockedError` vb.) |
| `app/modules/roles/models.py` | `Role`, `Module`, `RolePermission` |
| `app/modules/roles/seed_data.py` | 8 rol × 13 modül matrisinin başlangıç değerleri |
| `app/modules/roles/repository.py` | İzin okuma sorguları |
| `app/modules/roles/service.py` | Kilitlenme koruması, izin güncelleme, rol yeniden adlandırma |
| `app/modules/users/models.py` | `User`, `UserStatus` |
| `app/modules/auth/schemas.py` | `LoginRequest`, `TokenPair`, `MeResponse` |
| `app/modules/auth/service.py` | Kimlik doğrulama iş kuralı |
| `app/modules/auth/router.py` | `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me` |
| `alembic/versions/*` | Şema + seed migration'ları |
| `tests/conftest.py` | Test veritabanı, istemci, kullanıcı fabrikaları |

---

## Task 1: Proje iskeleti ve sağlık ucu

**Files:**
- Create: `pyproject.toml`, `.env.example`, `app/__init__.py`, `app/main.py`, `app/core/__init__.py`, `app/core/config.py`
- Test: `tests/__init__.py`, `tests/conftest.py`, `tests/test_health.py`

**Interfaces:**
- Consumes: —
- Produces: `app.main:app` (FastAPI örneği) · `app.core.config:settings` (`Settings` örneği; alanlar: `database_url: str`, `test_database_url: str`, `jwt_secret: str`, `jwt_algorithm: str = "HS256"`, `access_token_expire_minutes: int = 15`, `refresh_token_expire_days: int = 30`, `environment: str = "development"`)

- [ ] **Step 1: Bağımlılıkları tanımla**

`pyproject.toml` oluştur:

```toml
[project]
name = "fiil-erp-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "pydantic[email]>=2.10",
    "pydantic-settings>=2.7",
    "argon2-cffi>=23.1",
    "pyjwt>=2.10",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "pytest-cov>=6.0",
    "httpx>=0.28",
    "ruff>=0.8",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["app"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

Run: `pip install -e ".[dev]"`
Expected: `Successfully installed fiil-erp-backend-0.1.0`

- [ ] **Step 2: Başarısız testi yaz**

`tests/test_health.py`:

```python
async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

`tests/conftest.py`:

```python
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
```

`tests/__init__.py`, `app/__init__.py`, `app/core/__init__.py` boş dosya olarak oluştur.

- [ ] **Step 3: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Minimal implementasyonu yaz**

`app/core/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp"
    test_database_url: str = "postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    environment: str = "development"


settings = Settings()
```

`app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

`.env.example`:

```bash
DATABASE_URL=postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp
TEST_DATABASE_URL=postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test
JWT_SECRET=change-me-in-production
ENVIRONMENT=development
```

- [ ] **Step 5: Testin geçtiğini doğrula**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS — `1 passed`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example app tests
git commit -m "feat: FastAPI iskeleti ve saglik ucu"
```

---

## Task 2: Postgres, SQLAlchemy tabanı ve Alembic

**Files:**
- Create: `app/core/db.py`, `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`
- Modify: `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `app.core.config:settings`
- Produces: `app.core.db:Base` (DeclarativeBase) · `app.core.db:get_db` (`AsyncGenerator[AsyncSession, None]` FastAPI bağımlılığı) · `app.core.db:engine` · pytest fixture `db_session: AsyncSession`

- [ ] **Step 1: Postgres bağlantısını doğrula**

**Docker YOK.** Veritabanı Railway'de bulut olarak çalışıyor (proje: `fiilyapi`, servis: `Postgres`). Geliştirme makinesine hiçbir şey kurulmuyor.

`.env` dosyası **zaten hazır** ve `.gitignore`'da — içinde `DATABASE_URL` (railway veritabanı), `TEST_DATABASE_URL` (`fiil_erp_test` veritabanı) ve `JWT_SECRET` var. Her ikisi de `postgresql+asyncpg://` sürücüsüyle ve Railway'in **public proxy** adresini kullanıyor (`*.proxy.rlwy.net`), yani makineden doğrudan erişilebilir.

`fiil_erp_test` veritabanı da oluşturulmuş durumda. Testler şemayı silip yeniden kurduğu için ayrı veritabanı **zorunludur** — `DATABASE_URL` ile `TEST_DATABASE_URL` asla aynı olmamalı.

Run: `python -c "import os; from pathlib import Path; print([l.split('=')[0] for l in Path('.env').read_text().splitlines() if l])"`
Expected: `['DATABASE_URL', 'TEST_DATABASE_URL', 'JWT_SECRET', 'ENVIRONMENT']`

> Not: Testler internet üzerinden Railway'e bağlandığı için lokal veritabanına göre yavaş koşar. Bu beklenen davranıştır, hata değildir.

- [ ] **Step 2: Başarısız testi yaz**

`tests/test_db.py`:

```python
from sqlalchemy import text


async def test_db_session_executes_query(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
```

- [ ] **Step 3: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `fixture 'db_session' not found`

- [ ] **Step 4: Minimal implementasyonu yaz**

`app/core/db.py`:

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

`tests/conftest.py` — tüm dosyayı bununla değiştir:

```python
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app

test_engine = create_async_engine(settings.test_database_url, pool_pre_ping=True)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncGenerator[None, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Her test kendi transaction'ında koşar ve sonunda geri alınır — testler birbirini kirletmez."""
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = TestSessionLocal(bind=connection)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()
```

- [ ] **Step 5: Testin geçtiğini doğrula**

Run: `python -m pytest tests/test_db.py tests/test_health.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 6: Alembic'i kur**

Run: `python -m alembic init -t async alembic`

`alembic.ini` içinde `sqlalchemy.url` satırını **boş bırak** (`sqlalchemy.url =`); URL'yi `env.py` ortamdan okuyacak.

`alembic/env.py` — şu üç değişikliği yap:

```python
# 1) import bloğunun altına ekle:
from app.core.config import settings
from app.core.db import Base
# Task 4'te bu iki satırın yorumunu aç (modelleri metadata'ya kaydeder):
# from app.modules.roles import models as roles_models  # noqa: F401
# from app.modules.users import models as users_models  # noqa: F401

# 2) target_metadata satırını değiştir:
target_metadata = Base.metadata

# 3) config nesnesi tanımlandıktan hemen sonra ekle:
config.set_main_option("sqlalchemy.url", settings.database_url)
```

- [ ] **Step 7: Commit**

```bash
git add app/core/db.py alembic.ini alembic tests
git commit -m "feat: SQLAlchemy tabani ve Alembic kurulumu"
```

> `.env` commit **edilmez** — Railway şifresi içeriyor ve `.gitignore`'da.

---

## Task 3: CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml` dev bağımlılıkları
- Produces: —

- [ ] **Step 1: CI yapılandırmasını yaz**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: fiil
          POSTGRES_PASSWORD: fiil
          POSTGRES_DB: fiil_erp_test
        ports:
          - 5433:5432
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 3s --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test
      DATABASE_URL: postgresql+asyncpg://fiil:fiil@localhost:5433/fiil_erp_test
      JWT_SECRET: ci-secret
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: python -m ruff check .
      - run: python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80
```

- [ ] **Step 2: Lint'in lokalde geçtiğini doğrula**

Run: `python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add .github
git commit -m "ci: test ve lint is akisi"
```

---

## Task 4: Rol ve kullanıcı modelleri

**Files:**
- Create: `app/modules/__init__.py`, `app/modules/roles/__init__.py`, `app/modules/roles/models.py`, `app/modules/users/__init__.py`, `app/modules/users/models.py`
- Modify: `alembic/env.py` (Task 2 Step 6'daki yorumlu import'ları aç)
- Test: `tests/modules/__init__.py`, `tests/modules/test_role_model.py`

**Interfaces:**
- Consumes: `app.core.db:Base`
- Produces:
  - `app.modules.roles.models:Role` — `id: UUID`, `key: str`, `name: str`, `emoji: str`, `description: str`, `is_system: bool`
  - `app.modules.roles.models:SYSTEM_ADMIN_KEY = "system_admin"`
  - `app.modules.users.models:User` — `id: UUID`, `email: str`, `password_hash: str`, `full_name: str`, `title: str`, `role_id: UUID`, `role: Role`, `status: UserStatus`, `last_login_at: datetime | None`, `created_at: datetime`, `updated_at: datetime`
  - `app.modules.users.models:UserStatus` — `active` · `on_leave` · `passive`

- [ ] **Step 1: Başarısız testi yaz**

`tests/modules/test_role_model.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.roles.models import Role


async def test_role_key_is_unique(db_session):
    db_session.add(Role(key="patron", name="Patron"))
    await db_session.flush()

    db_session.add(Role(key="patron", name="Baska Ad"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_defaults_to_non_system(db_session):
    role = Role(key="ozel_rol", name="Özel Rol")
    db_session.add(role)
    await db_session.flush()
    assert role.is_system is False
```

`tests/modules/__init__.py` boş dosya olarak oluştur.

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_role_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/modules/roles/models.py`:

```python
import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SYSTEM_ADMIN_KEY = "system_admin"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

`app/modules/users/models.py`:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.modules.roles.models import Role


class UserStatus(str, enum.Enum):
    active = "active"
    on_leave = "on_leave"
    passive = "passive"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), nullable=False, default=UserStatus.active
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # lazy="raise" kasıtlıdır: async ortamda tembel yükleme sessizce patlar.
    # Bu ayar, ilişkiyi açıkça yüklemeyi unuttuğumuzda hatayı geliştirme anında görünür kılar.
    role: Mapped[Role] = relationship(lazy="raise")
```

`app/modules/__init__.py`, `app/modules/roles/__init__.py`, `app/modules/users/__init__.py` boş dosyalar.

`alembic/env.py` içindeki iki yorumlu import satırının yorumunu aç.

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_role_model.py -v`
Expected: PASS — `2 passed`

- [ ] **Step 5: Migration üret ve uygula**

Run: `python -m alembic revision --autogenerate -m "roles ve users tablolari"`

Üretilen dosyayı `alembic/versions/` altında **aç ve oku**: `roles` ve `users` tablolarını, `user_status` enum'unu ve `users.role_id` yabancı anahtarını içermeli. Beklenmeyen bir `DROP` ifadesi varsa dur ve nedenini araştır.

Run: `python -m alembic upgrade head`
Expected: `Running upgrade  -> <hash>, roles ve users tablolari`

- [ ] **Step 6: Commit**

```bash
git add app/modules alembic tests
git commit -m "feat: Role ve User modelleri + ilk migration"
```

---

## Task 5: Parola özeti ve JWT

**Files:**
- Create: `app/core/security.py`
- Test: `tests/core/__init__.py`, `tests/core/test_security.py`

**Interfaces:**
- Consumes: `app.core.config:settings`
- Produces:
  - `hash_password(plain: str) -> str`
  - `verify_password(plain: str, hashed: str) -> bool`
  - `create_access_token(user_id: uuid.UUID) -> str`
  - `create_refresh_token(user_id: uuid.UUID) -> str`
  - `decode_token(token: str, expected_type: str) -> uuid.UUID` — geçersiz/süresi geçmiş/yanlış tipte token'da `TokenError` fırlatır
  - `TokenError(Exception)`

- [ ] **Step 1: Başarısız testi yaz**

`tests/core/test_security.py`:

```python
import uuid

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_does_not_return_plaintext():
    hashed = hash_password("gizli-parola")
    assert hashed != "gizli-parola"
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_correct_and_rejects_wrong():
    hashed = hash_password("gizli-parola")
    assert verify_password("gizli-parola", hashed) is True
    assert verify_password("yanlis-parola", hashed) is False


def test_same_password_hashes_differently_each_time():
    """Tuz (salt) kullanıldığını doğrular — aynı parola iki farklı özet üretmeli."""
    assert hash_password("ayni") != hash_password("ayni")


def test_verify_password_on_corrupt_hash_returns_false():
    """Bozuk özet çökmeye değil, False'a dönüşmeli."""
    assert verify_password("herhangi", "bu-bir-argon2-ozeti-degil") is False


def test_access_token_roundtrips_user_id():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_token(token, expected_type="access") == user_id


def test_refresh_token_is_not_accepted_as_access_token():
    """Token tipi karıştırılamaz — refresh ile korumalı uca girilemez."""
    token = create_refresh_token(uuid.uuid4())
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access")


def test_garbage_token_raises():
    with pytest.raises(TokenError):
        decode_token("bu-bir-token-degil", expected_type="access")
```

`tests/core/__init__.py` boş dosya olarak oluştur.

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/core/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/core/security.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()


class TokenError(Exception):
    """Token geçersiz, süresi geçmiş veya beklenen tipte değil."""


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False


def _create_token(user_id: uuid.UUID, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("Token geçersiz veya süresi dolmuş") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Token tipi beklenenden farklı")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Token içeriği bozuk") from exc
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/core/test_security.py -v`
Expected: PASS — `7 passed`

- [ ] **Step 5: Commit**

```bash
git add app/core/security.py tests/core
git commit -m "feat: argon2 parola ozeti ve JWT uret/coz"
```

---

## Task 6: İzin seviyeleri ve karşılaştırma

**Files:**
- Create: `app/core/permissions.py`
- Test: `tests/core/test_permissions.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `AccessLevel(str, Enum)` — `none · view · draft · request · approve · full · admin`
  - `Scope(str, Enum)` — `all · own · project · finance · stock · limited`
  - `satisfies(actual: AccessLevel, required: AccessLevel) -> bool`

- [ ] **Step 1: Başarısız testi yaz**

`tests/core/test_permissions.py`:

```python
import pytest

from app.core.permissions import AccessLevel, satisfies


def test_levels_are_ordered():
    assert satisfies(AccessLevel.full, AccessLevel.view) is True
    assert satisfies(AccessLevel.view, AccessLevel.full) is False


def test_same_level_satisfies_itself():
    assert satisfies(AccessLevel.approve, AccessLevel.approve) is True


def test_none_satisfies_nothing_above_it():
    for required in (AccessLevel.view, AccessLevel.draft, AccessLevel.full, AccessLevel.admin):
        assert satisfies(AccessLevel.none, required) is False


def test_admin_satisfies_every_level():
    for required in AccessLevel:
        assert satisfies(AccessLevel.admin, required) is True


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        (AccessLevel.draft, AccessLevel.view, True),
        (AccessLevel.request, AccessLevel.draft, True),
        (AccessLevel.approve, AccessLevel.request, True),
        (AccessLevel.full, AccessLevel.approve, True),
        (AccessLevel.admin, AccessLevel.full, True),
        (AccessLevel.full, AccessLevel.admin, False),
        (AccessLevel.approve, AccessLevel.full, False),
    ],
)
def test_level_ordering_matrix(actual, required, expected):
    assert satisfies(actual, required) is expected


def test_full_does_not_satisfy_admin():
    """Spec §5.0: full silmeyi kapsamaz — silme yalnızca admin seviyesindedir."""
    assert satisfies(AccessLevel.full, AccessLevel.admin) is False
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/core/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.permissions'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/core/permissions.py`:

```python
import enum


class AccessLevel(str, enum.Enum):
    """Erişim seviyesi. Sıralıdır: none < view < draft < request < approve < full < admin.

    full silmeyi KAPSAMAZ — silme yalnızca admin seviyesindedir (spec §5.0).
    """

    none = "none"
    view = "view"
    draft = "draft"
    request = "request"
    approve = "approve"
    full = "full"
    admin = "admin"


class Scope(str, enum.Enum):
    """Veri kapsamı — aktörün modül içinde hangi kayıtları görebildiği."""

    all = "all"
    own = "own"
    project = "project"
    finance = "finance"
    stock = "stock"
    limited = "limited"


_LEVEL_ORDER: dict[AccessLevel, int] = {
    AccessLevel.none: 0,
    AccessLevel.view: 1,
    AccessLevel.draft: 2,
    AccessLevel.request: 3,
    AccessLevel.approve: 4,
    AccessLevel.full: 5,
    AccessLevel.admin: 6,
}


def satisfies(actual: AccessLevel, required: AccessLevel) -> bool:
    """actual seviyesi, required seviyesini karşılıyor mu?"""
    return _LEVEL_ORDER[actual] >= _LEVEL_ORDER[required]
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/core/test_permissions.py -v`
Expected: PASS — `11 passed`

- [ ] **Step 5: Commit**

```bash
git add app/core/permissions.py tests/core/test_permissions.py
git commit -m "feat: AccessLevel/Scope enumlari ve seviye karsilastirma"
```

---

## Task 7: Modül ve izin tabloları

**Files:**
- Modify: `app/modules/roles/models.py` (`ModuleGroup`, `Module`, `RolePermission` ekle)
- Test: `tests/modules/test_permission_model.py`

**Interfaces:**
- Consumes: `app.core.permissions:AccessLevel`, `app.core.permissions:Scope`, `app.core.db:Base`
- Produces:
  - `app.modules.roles.models:ModuleGroup` — `GENEL · SAHA · STOK_SATINALMA · MALI · SISTEM`
  - `app.modules.roles.models:Module` — `id: UUID`, `key: str`, `name: str`, `group: ModuleGroup`, `sort_order: int`
  - `app.modules.roles.models:RolePermission` — `id: UUID`, `role_id: UUID`, `module_id: UUID`, `access_level: AccessLevel`, `scope: Scope`; UNIQUE(`role_id`, `module_id`)

- [ ] **Step 1: Başarısız testi yaz**

`tests/modules/test_permission_model.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.permissions import AccessLevel, Scope
from app.modules.roles.models import Module, ModuleGroup, Role, RolePermission


async def test_one_permission_row_per_role_and_module(db_session):
    role = Role(key="test_rol", name="Test Rol")
    module = Module(key="test_modul", name="Test Modül", group=ModuleGroup.GENEL, sort_order=1)
    db_session.add_all([role, module])
    await db_session.flush()

    db_session.add(
        RolePermission(
            role_id=role.id, module_id=module.id, access_level=AccessLevel.view, scope=Scope.all
        )
    )
    await db_session.flush()

    db_session.add(
        RolePermission(
            role_id=role.id, module_id=module.id, access_level=AccessLevel.full, scope=Scope.all
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_module_key_is_unique(db_session):
    db_session.add(Module(key="ayni", name="Bir", group=ModuleGroup.GENEL, sort_order=1))
    await db_session.flush()

    db_session.add(Module(key="ayni", name="Iki", group=ModuleGroup.MALI, sort_order=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_permission_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Module' from 'app.modules.roles.models'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/modules/roles/models.py` — tüm dosyayı bununla değiştir:

```python
import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.permissions import AccessLevel, Scope

SYSTEM_ADMIN_KEY = "system_admin"


class ModuleGroup(str, enum.Enum):
    GENEL = "GENEL"
    SAHA = "SAHA"
    STOK_SATINALMA = "STOK_SATINALMA"
    MALI = "MALI"
    SISTEM = "SISTEM"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Module(Base):
    """İzin matrisinin satırları. Sabit referans verisi — migration ile seed edilir."""

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    group: Mapped[ModuleGroup] = mapped_column(
        Enum(ModuleGroup, name="module_group"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RolePermission(Base):
    """Matrisin bir hücresi: (rol, modül) -> seviye + kapsam."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "module_id", name="uq_role_module"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel, name="access_level"), nullable=False, default=AccessLevel.none
    )
    scope: Mapped[Scope] = mapped_column(
        Enum(Scope, name="scope"), nullable=False, default=Scope.all
    )
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/ -v`
Expected: PASS — `4 passed`

- [ ] **Step 5: Migration üret ve uygula**

Run: `python -m alembic revision --autogenerate -m "modules ve role_permissions tablolari"`

Üretilen dosyayı oku: `modules`, `role_permissions` tabloları, `module_group`/`access_level`/`scope` enum'ları ve `uq_role_module` kısıtı olmalı.

Run: `python -m alembic upgrade head`
Expected: `Running upgrade <önceki> -> <hash>, modules ve role_permissions tablolari`

- [ ] **Step 6: Commit**

```bash
git add app/modules/roles/models.py alembic/versions tests/modules/test_permission_model.py
git commit -m "feat: Module ve RolePermission modelleri + migration"
```

---

## Task 8: Seed — 8 rol × 13 modül matrisi

**Files:**
- Create: `app/modules/roles/seed_data.py`, `alembic/versions/<hash>_seed_roller_modul_izinler.py`
- Modify: `tests/conftest.py` (`seeded_db` fixture)
- Test: `tests/modules/test_seed_matrix.py`

**Interfaces:**
- Consumes: Task 7'nin tabloları
- Produces:
  - `app.modules.roles.seed_data:ROLES`, `MODULES`, `MATRIX`, `ROLE_ORDER`
  - `app.modules.roles.seed_data:seed_reference_data(session: AsyncSession) -> None`
  - pytest fixture `seeded_db: AsyncSession`
  - Veritabanında 8 `roles`, 13 `modules`, 104 `role_permissions` satırı

**Kaynak:** Spec §5.1 ve §5.2. Aşağıdaki matris spec'ten birebir alınmıştır; **değiştirme**.

- [ ] **Step 1: Başarısız testi yaz**

`tests/modules/test_seed_matrix.py`:

```python
from sqlalchemy import select

from app.core.permissions import AccessLevel
from app.modules.roles.models import Module, Role, RolePermission

EXPECTED_ROLE_KEYS = {
    "system_admin",
    "patron",
    "site_chief",
    "field_engineer",
    "hr_manager",
    "accounting",
    "project_manager",
    "procurement",
}

EXPECTED_MODULE_KEYS = {
    "dashboard",
    "approvals",
    "site_diary",
    "timesheet",
    "personnel",
    "payroll",
    "inventory",
    "procurement",
    "progress_payments",
    "accounting",
    "treasury",
    "settings",
    "user_management",
}


async def _level_of(session, role_key: str, module_key: str) -> AccessLevel:
    stmt = (
        select(RolePermission.access_level)
        .join(Role, Role.id == RolePermission.role_id)
        .join(Module, Module.id == RolePermission.module_id)
        .where(Role.key == role_key, Module.key == module_key)
    )
    return (await session.execute(stmt)).scalar_one()


async def test_seeds_eight_roles(seeded_db):
    keys = set((await seeded_db.execute(select(Role.key))).scalars())
    assert keys == EXPECTED_ROLE_KEYS


async def test_seeds_thirteen_modules(seeded_db):
    keys = set((await seeded_db.execute(select(Module.key))).scalars())
    assert keys == EXPECTED_MODULE_KEYS


async def test_matrix_is_complete(seeded_db):
    """8 rol × 13 modül = 104 hücre; hiçbiri eksik olamaz."""
    rows = (await seeded_db.execute(select(RolePermission))).scalars().all()
    assert len(rows) == 104


async def test_system_admin_has_admin_level_everywhere(seeded_db):
    for module_key in EXPECTED_MODULE_KEYS:
        assert await _level_of(seeded_db, "system_admin", module_key) == AccessLevel.admin


async def test_patron_cannot_access_settings(seeded_db):
    """Spec §5.2: Patron'un Ayarlar erişimi yok — mockup çelişkisi İzin Matrisi lehine çözüldü."""
    assert await _level_of(seeded_db, "patron", "settings") == AccessLevel.none
    assert await _level_of(seeded_db, "patron", "user_management") == AccessLevel.none


async def test_patron_has_full_but_not_admin_on_payroll(seeded_db):
    """Patron silemez — full, admin değil."""
    assert await _level_of(seeded_db, "patron", "payroll") == AccessLevel.full


async def test_site_chief_can_only_draft_progress_payments(seeded_db):
    assert await _level_of(seeded_db, "site_chief", "progress_payments") == AccessLevel.draft


async def test_field_engineer_can_only_view_timesheet(seeded_db):
    """Saha Mühendisi puantajı görür ama giremez — Şantiye Şefi'nden tek farkı budur."""
    assert await _level_of(seeded_db, "field_engineer", "timesheet") == AccessLevel.view
    assert await _level_of(seeded_db, "site_chief", "timesheet") == AccessLevel.full


async def test_hr_manager_is_confined_to_people_modules(seeded_db):
    for module_key in ("personnel", "payroll", "timesheet"):
        assert await _level_of(seeded_db, "hr_manager", module_key) == AccessLevel.full
    for module_key in ("accounting", "treasury", "inventory", "site_diary"):
        assert await _level_of(seeded_db, "hr_manager", module_key) == AccessLevel.none
```

`tests/conftest.py` — sonuna ekle:

```python
from app.modules.roles.seed_data import seed_reference_data


@pytest.fixture
async def seeded_db(db_session: AsyncSession) -> AsyncSession:
    """Rolleri, modülleri ve izin matrisini yükler. Test sonunda geri alınır."""
    await seed_reference_data(db_session)
    return db_session
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_seed_matrix.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.roles.seed_data'`

- [ ] **Step 3: Seed verisini ve yükleyiciyi yaz**

`app/modules/roles/seed_data.py`:

```python
"""Rol/modül/izin matrisinin başlangıç değerleri — spec §5.1 ve §5.2.

Bu yalnızca ilk kurulum değeridir. Kullanıcı İzin Matrisi ekranından her hücreyi
değiştirebilir; tek istisna system_admin rolüdür (kilitlenme koruması, spec §5.0).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AccessLevel, Scope
from app.modules.roles.models import Module, ModuleGroup, Role, RolePermission

ROLES: list[dict] = [
    {
        "key": "system_admin",
        "name": "Sistem Yöneticisi",
        "emoji": "🛡️",
        "is_system": True,
        "description": "Tüm modüller · Tüm projeler · Ayarlar · Kullanıcı yönetimi · Silme yetkisi",
    },
    {
        "key": "patron",
        "name": "Patron",
        "emoji": "👔",
        "is_system": True,
        "description": "Tüm modüller · Tüm projeler (ayarlar hariç)",
    },
    {
        "key": "site_chief",
        "name": "Şantiye Şefi",
        "emoji": "👷",
        "is_system": False,
        "description": "Günlük kayıt, puantaj, stok görüntüle",
    },
    {
        "key": "field_engineer",
        "name": "Saha Mühendisi",
        "emoji": "📐",
        "is_system": False,
        "description": "Günlük kayıt, hakediş taslağı, puantaj görüntüle",
    },
    {
        "key": "hr_manager",
        "name": "İK Müdürü",
        "emoji": "👥",
        "is_system": False,
        "description": "Personel, puantaj, bordro",
    },
    {
        "key": "accounting",
        "name": "Muhasebe",
        "emoji": "📒",
        "is_system": False,
        "description": "Yevmiye, bordro, hakediş onay, e-fatura",
    },
    {
        "key": "project_manager",
        "name": "Proje Müdürü",
        "emoji": "🏗",
        "is_system": False,
        "description": "Proje görünümü, raporlar, hakediş onay",
    },
    {
        "key": "procurement",
        "name": "Satınalma",
        "emoji": "🛒",
        "is_system": False,
        "description": "Stok, satınalma, teklif, tedarikçi",
    },
]

MODULES: list[dict] = [
    {"key": "dashboard", "name": "Gösterge Paneli", "group": ModuleGroup.GENEL, "sort_order": 1},
    {"key": "approvals", "name": "Onay Kutusu", "group": ModuleGroup.GENEL, "sort_order": 2},
    {"key": "site_diary", "name": "Günlük Kayıt", "group": ModuleGroup.SAHA, "sort_order": 3},
    {"key": "timesheet", "name": "Puantaj", "group": ModuleGroup.SAHA, "sort_order": 4},
    {"key": "personnel", "name": "Personel", "group": ModuleGroup.SAHA, "sort_order": 5},
    {"key": "payroll", "name": "Bordro", "group": ModuleGroup.SAHA, "sort_order": 6},
    {
        "key": "inventory",
        "name": "Stok & Depo",
        "group": ModuleGroup.STOK_SATINALMA,
        "sort_order": 7,
    },
    {
        "key": "procurement",
        "name": "Satınalma & Teklif",
        "group": ModuleGroup.STOK_SATINALMA,
        "sort_order": 8,
    },
    {
        "key": "progress_payments",
        "name": "Hakedişler",
        "group": ModuleGroup.MALI,
        "sort_order": 9,
    },
    {"key": "accounting", "name": "Muhasebe", "group": ModuleGroup.MALI, "sort_order": 10},
    {"key": "treasury", "name": "Hazine", "group": ModuleGroup.MALI, "sort_order": 11},
    {"key": "settings", "name": "Ayarlar", "group": ModuleGroup.SISTEM, "sort_order": 12},
    {
        "key": "user_management",
        "name": "Kullanıcı & Rol Yönetimi",
        "group": ModuleGroup.SISTEM,
        "sort_order": 13,
    },
]

# Kısayollar — matrisi okunur tutmak için.
_A = (AccessLevel.admin, Scope.all)        # ✓ Süper (silme dahil)
_F = (AccessLevel.full, Scope.all)         # ✓ Tam (silme hariç)
_N = (AccessLevel.none, Scope.all)         # —
_V = (AccessLevel.view, Scope.all)         # Görüntüle
_LIM = (AccessLevel.view, Scope.limited)   # Sınırlı
_FIN = (AccessLevel.view, Scope.finance)   # Mali
_OWN = (AccessLevel.view, Scope.own)       # Kendi
_PRJ = (AccessLevel.view, Scope.project)   # Proje
_STK = (AccessLevel.view, Scope.stock)     # Stok
_DRF = (AccessLevel.draft, Scope.project)  # Taslak
_REQ = (AccessLevel.request, Scope.all)    # Talep
_APR = (AccessLevel.approve, Scope.all)    # Onay

# Sütun sırası — MATRIX'teki her satır bu sırayla okunur.
ROLE_ORDER = [
    "system_admin",
    "patron",
    "site_chief",
    "field_engineer",
    "hr_manager",
    "accounting",
    "project_manager",
    "procurement",
]

# Spec §5.2 matrisi.
MATRIX: dict[str, list[tuple[AccessLevel, Scope]]] = {
    #                    sysadmin patron  şef    saha   İK     muhasebe  PM     satınalma
    "dashboard":         [_A,     _F,     _LIM,  _LIM,  _LIM,  _FIN,     _F,    _N],
    "approvals":         [_A,     _F,     _OWN,  _OWN,  _OWN,  _FIN,     _PRJ,  _STK],
    "site_diary":        [_A,     _F,     _F,    _F,    _N,    _N,       _V,    _N],
    "timesheet":         [_A,     _F,     _F,    _V,    _F,    _V,       _N,    _N],
    "personnel":         [_A,     _F,     _V,    _V,    _F,    _F,       _V,    _N],
    "payroll":           [_A,     _F,     _N,    _N,    _F,    _F,       _N,    _N],
    "inventory":         [_A,     _F,     _V,    _V,    _N,    _N,       _V,    _F],
    "procurement":       [_A,     _F,     _REQ,  _REQ,  _N,    _N,       _APR,  _F],
    "progress_payments": [_A,     _F,     _DRF,  _DRF,  _N,    _APR,     _APR,  _N],
    "accounting":        [_A,     _F,     _N,    _N,    _N,    _F,       _V,    _N],
    "treasury":          [_A,     _F,     _N,    _N,    _N,    _F,       _V,    _N],
    "settings":          [_A,     _N,     _N,    _N,    _N,    _N,       _N,    _N],
    "user_management":   [_A,     _N,     _N,    _N,    _N,    _N,       _N,    _N],
}


async def seed_reference_data(session: AsyncSession) -> None:
    """Rolleri, modülleri ve izin matrisini yükler. Idempotent: mevcut satırlara dokunmaz."""
    existing_roles = set((await session.execute(select(Role.key))).scalars())
    roles_by_key: dict[str, Role] = {}
    for row in ROLES:
        if row["key"] in existing_roles:
            continue
        role = Role(**row)
        session.add(role)
        roles_by_key[row["key"]] = role

    existing_modules = set((await session.execute(select(Module.key))).scalars())
    modules_by_key: dict[str, Module] = {}
    for row in MODULES:
        if row["key"] in existing_modules:
            continue
        module = Module(**row)
        session.add(module)
        modules_by_key[row["key"]] = module

    await session.flush()

    for module_key, cells in MATRIX.items():
        module = modules_by_key.get(module_key)
        if module is None:
            continue
        # strict=True kasıtlı: matris satırı 8 hücreden azsa sessizce eksik izin
        # üretmek yerine burada patlar. Sessiz eksik izin ERP'de en tehlikeli hatadır.
        for role_key, (level, scope) in zip(ROLE_ORDER, cells, strict=True):
            role = roles_by_key.get(role_key)
            if role is None:
                continue
            session.add(
                RolePermission(
                    role_id=role.id, module_id=module.id, access_level=level, scope=scope
                )
            )
    await session.flush()
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_seed_matrix.py -v`
Expected: PASS — `9 passed`

- [ ] **Step 5: Data migration yaz ve uygula**

Run: `python -m alembic revision -m "seed roller modul ve izinler"` (autogenerate **değil**)

Üretilen dosyanın `upgrade()` fonksiyonuna `ROLES`, `MODULES` ve `MATRIX` verisini **satır satır kopyalayarak** `op.bulk_insert` çağrıları yaz. Migration uygulama kodunu import **etmemeli** — kod zamanla değişir, uygulanmış bir migration değişmez.

İskelet:

```python
import uuid

import sqlalchemy as sa
from alembic import op

revision = "<hash>"
down_revision = "<önceki hash>"
branch_labels = None
depends_on = None

roles_table = sa.table(
    "roles",
    sa.column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("emoji", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_system", sa.Boolean),
)

# modules_table ve role_permissions_table için aynı deseni tekrarla.

ROLE_IDS = {key: uuid.uuid4() for key in (
    "system_admin", "patron", "site_chief", "field_engineer",
    "hr_manager", "accounting", "project_manager", "procurement",
)}
MODULE_IDS = {key: uuid.uuid4() for key in (
    "dashboard", "approvals", "site_diary", "timesheet", "personnel", "payroll",
    "inventory", "procurement", "progress_payments", "accounting", "treasury",
    "settings", "user_management",
)}


def upgrade() -> None:
    op.bulk_insert(roles_table, [
        {"id": ROLE_IDS["system_admin"], "key": "system_admin", "name": "Sistem Yöneticisi",
         "emoji": "🛡️", "description": "Tüm modüller · Tüm projeler · Ayarlar · Kullanıcı yönetimi · Silme yetkisi",
         "is_system": True},
        # ... kalan 7 rolü seed_data.ROLES'tan birebir kopyala ...
    ])
    # op.bulk_insert(modules_table, [...])  — 13 modül
    # op.bulk_insert(role_permissions_table, [...])  — 104 hücre


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions")
    op.execute("DELETE FROM modules")
    op.execute("DELETE FROM roles")
```

Run: `python -m alembic upgrade head && python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: Üç komut da hatasız — migration'ın geri alınabilir olduğunu kanıtlar.

- [ ] **Step 6: Seed'in migration ile aynı olduğunu doğrula**

Run:
```bash
python - <<'PY'
import asyncio, re
from pathlib import Path
import asyncpg
url = next(l.split("=",1)[1] for l in Path(".env").read_text().splitlines() if l.startswith("DATABASE_URL"))
async def main():
    conn = await asyncpg.connect(re.sub(r"\+asyncpg", "", url))
    print("role_permissions:", await conn.fetchval("SELECT count(*) FROM role_permissions"))
    await conn.close()
asyncio.run(main())
PY
```
Expected: `role_permissions: 104`

- [ ] **Step 7: Commit**

```bash
git add app/modules/roles/seed_data.py alembic/versions tests/modules/test_seed_matrix.py tests/conftest.py
git commit -m "feat: 8 rol x 13 modul izin matrisi seed"
```

---

## Task 9: Oturum açma ve `get_current_user`

**Files:**
- Create: `app/modules/auth/__init__.py`, `app/modules/auth/schemas.py`, `app/modules/auth/service.py`, `app/modules/auth/router.py`, `app/core/deps.py`
- Modify: `app/main.py` (router'ı kaydet), `tests/conftest.py` (`user_factory`)
- Test: `tests/modules/test_auth.py`

**Interfaces:**
- Consumes: `app.core.security` (Task 5), `app.modules.users.models:User`, `app.core.db:get_db`
- Produces:
  - `app.core.deps:get_current_user` — FastAPI bağımlılığı, `User` döner; token yok/geçersizse 401
  - `app.modules.auth.service:authenticate(session, email, password) -> User`, `app.modules.auth.service:AuthError`
  - `POST /auth/login` → `{"access_token": str, "refresh_token": str, "token_type": "bearer"}`
  - `POST /auth/refresh` → aynı gövde
  - `POST /auth/logout` → 204
  - `GET /auth/me` → `{"id", "email", "full_name", "title", "role_key", "status"}`
  - pytest fixture `user_factory(email, password, role_key, status="active", full_name="Test Kullanıcı") -> User`

- [ ] **Step 1: Başarısız testi yaz**

`tests/modules/test_auth.py`:

```python
async def test_login_returns_token_pair(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="dogru-parola", role_key="patron")

    response = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "dogru-parola"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_with_wrong_password_is_rejected(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="dogru-parola", role_key="patron")

    response = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "yanlis-parola"}
    )

    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client, seeded_db):
    response = await client.post(
        "/auth/login", json={"email": "yok@fiil.com", "password": "herhangi"}
    )
    assert response.status_code == 401


async def test_login_error_does_not_reveal_whether_email_exists(client, seeded_db, user_factory):
    """Kullanıcı sayımını engeller: iki hata da birebir aynı mesajı döndürmeli."""
    await user_factory(email="var@fiil.com", password="dogru-parola", role_key="patron")

    wrong_password = await client.post(
        "/auth/login", json={"email": "var@fiil.com", "password": "yanlis"}
    )
    unknown_email = await client.post(
        "/auth/login", json={"email": "yok@fiil.com", "password": "yanlis"}
    )

    assert wrong_password.json() == unknown_email.json()


async def test_passive_user_cannot_log_in(client, seeded_db, user_factory):
    await user_factory(
        email="pasif@fiil.com", password="parola", role_key="patron", status="passive"
    )
    response = await client.post(
        "/auth/login", json={"email": "pasif@fiil.com", "password": "parola"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )
    token = login.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "patron@fiil.com"
    assert response.json()["role_key"] == "patron"


async def test_me_without_token_is_rejected(client, seeded_db):
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_with_garbage_token_is_rejected(client, seeded_db):
    response = await client.get("/auth/me", headers={"Authorization": "Bearer cop-token"})
    assert response.status_code == 401


async def test_refresh_token_cannot_be_used_as_access_token(client, seeded_db, user_factory):
    """Token tipi karıştırılamaz."""
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )
    refresh = login.json()["refresh_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401


async def test_refresh_issues_new_access_token(client, seeded_db, user_factory):
    await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    login = await client.post(
        "/auth/login", json={"email": "patron@fiil.com", "password": "parola"}
    )

    response = await client.post(
        "/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_stamps_last_login_at(client, seeded_db, user_factory):
    user = await user_factory(email="patron@fiil.com", password="parola", role_key="patron")
    assert user.last_login_at is None

    await client.post("/auth/login", json={"email": "patron@fiil.com", "password": "parola"})

    await seeded_db.refresh(user)
    assert user.last_login_at is not None
```

`tests/conftest.py` — sonuna ekle:

```python
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.roles.models import Role
from app.modules.users.models import User, UserStatus


@pytest.fixture
def user_factory(seeded_db: AsyncSession):
    async def _create(
        email: str,
        password: str,
        role_key: str,
        status: str = "active",
        full_name: str = "Test Kullanıcı",
    ) -> User:
        role = (await seeded_db.execute(select(Role).where(Role.key == role_key))).scalar_one()
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role_id=role.id,
            status=UserStatus(status),
        )
        seeded_db.add(user)
        await seeded_db.flush()
        return user

    return _create
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_auth.py -v`
Expected: FAIL — testler 404 döner (`/auth/login` ucu yok)

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/modules/auth/schemas.py`:

```python
import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    title: str
    role_key: str
    status: str
```

`app/modules/auth/service.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.modules.users.models import User, UserStatus


class AuthError(Exception):
    """Kimlik doğrulama başarısız."""


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """E-posta ve parolayı doğrular, aktif kullanıcıyı döner.

    Başarısızlığın nedeni (kullanıcı yok / parola yanlış / pasif) çağırana
    ayrıştırılmadan bildirilir — kullanıcı sayımını (user enumeration) engellemek için.
    """
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Kimlik bilgileri hatalı")

    if user.status is not UserStatus.active:
        raise AuthError("Kimlik bilgileri hatalı")

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user
```

`app/core/deps.py`:

```python
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db import get_db
from app.core.security import TokenError, decode_token
from app.modules.users.models import User, UserStatus

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Oturum geçersiz veya süresi dolmuş",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED

    try:
        user_id = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise _UNAUTHORIZED from exc

    user = await session.get(User, user_id, options=[joinedload(User.role)])
    if user is None or user.status is not UserStatus.active:
        raise _UNAUTHORIZED

    return user
```

`app/modules/auth/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import TokenError, create_access_token, create_refresh_token, decode_token
from app.modules.auth.schemas import LoginRequest, MeResponse, RefreshRequest, TokenPair
from app.modules.auth.service import AuthError, authenticate
from app.modules.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    try:
        user = await authenticate(session, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Kimlik bilgileri hatalı"
        ) from exc

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest) -> TokenPair:
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum süresi dolmuş"
        ) from exc

    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    """Token'lar durumsuzdur; oturumu sonlandırmak cookie'yi silen BFF katmanının işidir."""
    return None


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        title=user.title,
        role_key=user.role.key,
        status=user.status.value,
    )
```

`app/main.py`:

```python
from fastapi import FastAPI

from app.modules.auth.router import router as auth_router

app = FastAPI(title="FİİL Yapı ERP API", version="0.1.0")
app.include_router(auth_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

`app/modules/auth/__init__.py` boş dosya.

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_auth.py -v`
Expected: PASS — `11 passed`

- [ ] **Step 5: Commit**

```bash
git add app/modules/auth app/core/deps.py app/main.py tests
git commit -m "feat: oturum acma, token yenileme ve get_current_user"
```

---

## Task 10: `require_permission` ve negatif izin testleri

**Files:**
- Create: `app/modules/roles/repository.py`
- Modify: `app/core/permissions.py` (`require_permission` ekle)
- Test: `tests/core/test_require_permission.py`

**Interfaces:**
- Consumes: `app.core.deps:get_current_user`, `app.modules.roles.models:RolePermission`
- Produces:
  - `app.modules.roles.repository:get_permission(session, role_id, module_key) -> RolePermission | None`
  - `app.core.permissions:require_permission(module_key: str, min_level: AccessLevel)` — FastAPI `Depends` döner; yetersizse 403

- [ ] **Step 1: Başarısız testi yaz**

`tests/core/test_require_permission.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.db import get_db
from app.core.permissions import AccessLevel, require_permission


@pytest.fixture
def guarded_app(db_session):
    """require_permission ile korunan tek uçlu bir test uygulaması."""
    test_app = FastAPI()

    @test_app.get(
        "/korumali", dependencies=[require_permission("progress_payments", AccessLevel.approve)]
    )
    async def korumali() -> dict[str, bool]:
        return {"ok": True}

    async def _override_get_db():
        yield db_session

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


@pytest.fixture
async def guarded_client(guarded_app):
    transport = ASGITransport(app=guarded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _token_for(client, email: str) -> str:
    login = await client.post("/auth/login", json={"email": email, "password": "parola"})
    return login.json()["access_token"]


async def test_role_with_sufficient_level_is_allowed(
    guarded_client, client, seeded_db, user_factory
):
    """Muhasebe hakedişte approve seviyesinde — geçmeli."""
    await user_factory(email="muhasebe@fiil.com", password="parola", role_key="accounting")
    token = await _token_for(client, "muhasebe@fiil.com")

    response = await guarded_client.get("/korumali", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


async def test_site_chief_cannot_approve_progress_payments(
    guarded_client, client, seeded_db, user_factory
):
    """NEGATİF: Şantiye Şefi hakedişte yalnızca draft seviyesinde — onaylayamaz."""
    await user_factory(email="sef@fiil.com", password="parola", role_key="site_chief")
    token = await _token_for(client, "sef@fiil.com")

    response = await guarded_client.get("/korumali", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


async def test_hr_manager_has_no_access_to_progress_payments(
    guarded_client, client, seeded_db, user_factory
):
    """NEGATİF: İK Müdürü hakedişe hiç giremez."""
    await user_factory(email="ik@fiil.com", password="parola", role_key="hr_manager")
    token = await _token_for(client, "ik@fiil.com")

    response = await guarded_client.get("/korumali", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


async def test_unauthenticated_request_is_rejected(guarded_client):
    response = await guarded_client.get("/korumali")
    assert response.status_code == 401


async def test_system_admin_passes_every_gate(guarded_client, client, seeded_db, user_factory):
    await user_factory(email="admin@fiil.com", password="parola", role_key="system_admin")
    token = await _token_for(client, "admin@fiil.com")

    response = await guarded_client.get("/korumali", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
```

> `guarded_client` ile `client` iki ayrı uygulamaya bağlanır ama **aynı** `db_session`'ı paylaşır: token'ı gerçek `/auth/login` ucundan alıp korumalı test ucunda kullanırız.

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/core/test_require_permission.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_permission'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/modules/roles/repository.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.models import Module, RolePermission


async def get_permission(
    session: AsyncSession, role_id: uuid.UUID, module_key: str
) -> RolePermission | None:
    stmt = (
        select(RolePermission)
        .join(Module, Module.id == RolePermission.module_id)
        .where(RolePermission.role_id == role_id, Module.key == module_key)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

`app/core/permissions.py` — dosyanın sonuna ekle (import'ları en üste taşı):

```python
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.modules.users.models import User


def require_permission(module_key: str, min_level: AccessLevel):
    """Uç için asgari yetki kapısı.

    Kullanımı:
        @router.post("/x", dependencies=[require_permission("progress_payments", AccessLevel.draft)])

    İzin satırı yoksa erişim reddedilir (varsayılan kapalı).
    """

    async def _check(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        # Fonksiyon içi import kasıtlı: app.core.permissions <-> app.modules.roles
        # arasındaki döngüsel import'u kırar. Modül seviyesine taşıma.
        from app.modules.roles.repository import get_permission

        permission = await get_permission(session, user.role_id, module_key)
        if permission is None or not satisfies(permission.access_level, min_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok"
            )

    return Depends(_check)
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/core/test_require_permission.py -v`
Expected: PASS — `5 passed`

- [ ] **Step 5: Commit**

```bash
git add app/core/permissions.py app/modules/roles/repository.py tests/core/test_require_permission.py
git commit -m "feat: require_permission yetki kapisi + negatif izin testleri"
```

---

## Task 11: Silme kuralı ve kilitlenme koruması

**Files:**
- Create: `app/core/errors.py`, `app/modules/roles/service.py`
- Modify: `app/core/permissions.py` (`Deletable`, `can_delete` ekle)
- Test: `tests/core/test_can_delete.py`, `tests/modules/test_role_service.py`

**Interfaces:**
- Consumes: `app.core.permissions:AccessLevel`, `app.modules.roles.models:SYSTEM_ADMIN_KEY`, `app.modules.roles.repository:get_permission`
- Produces:
  - `app.core.errors:DomainError` · `PermissionLockedError` · `DeleteNotAllowedError`
  - `app.core.permissions:Deletable` (Protocol) — `created_by: uuid.UUID`, `is_draft: bool`
  - `app.core.permissions:can_delete(actor_id: uuid.UUID, level: AccessLevel, record: Deletable) -> bool`
  - `app.modules.roles.service:update_role_permission(session, role_id, module_key, level, scope) -> RolePermission`
  - `app.modules.roles.service:rename_role(session, role_id, name, emoji, description) -> Role`

- [ ] **Step 1: Başarısız testi yaz**

`tests/core/test_can_delete.py`:

```python
import uuid
from dataclasses import dataclass

from app.core.permissions import AccessLevel, can_delete


@dataclass
class FakeRecord:
    created_by: uuid.UUID
    is_draft: bool


def test_admin_can_delete_anything():
    record = FakeRecord(created_by=uuid.uuid4(), is_draft=False)
    assert can_delete(uuid.uuid4(), AccessLevel.admin, record) is True


def test_full_cannot_delete_finalised_record():
    """Spec §5.0: full silmeyi kapsamaz."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=False)
    assert can_delete(actor, AccessLevel.full, record) is False


def test_owner_can_delete_own_draft():
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=True)
    assert can_delete(actor, AccessLevel.draft, record) is True


def test_owner_cannot_delete_own_finalised_record():
    """Onaylanmış kayıt, oluşturanı tarafından bile silinemez."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=False)
    assert can_delete(actor, AccessLevel.draft, record) is False


def test_user_cannot_delete_someone_elses_draft():
    record = FakeRecord(created_by=uuid.uuid4(), is_draft=True)
    assert can_delete(uuid.uuid4(), AccessLevel.draft, record) is False


def test_view_level_cannot_delete_even_own_draft():
    """Taslak istisnası en az draft seviyesi ister."""
    actor = uuid.uuid4()
    record = FakeRecord(created_by=actor, is_draft=True)
    assert can_delete(actor, AccessLevel.view, record) is False
```

`tests/modules/test_role_service.py`:

```python
import pytest
from sqlalchemy import select

from app.core.errors import PermissionLockedError
from app.core.permissions import AccessLevel, Scope
from app.modules.roles.models import Role
from app.modules.roles.service import rename_role, update_role_permission


async def _role(session, key: str) -> Role:
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one()


async def test_permission_can_be_raised_for_normal_role(seeded_db):
    role = await _role(seeded_db, "site_chief")
    updated = await update_role_permission(
        seeded_db, role.id, "progress_payments", AccessLevel.approve, Scope.all
    )
    assert updated.access_level is AccessLevel.approve


async def test_permission_can_be_lowered_for_normal_role(seeded_db):
    role = await _role(seeded_db, "patron")
    updated = await update_role_permission(seeded_db, role.id, "payroll", AccessLevel.view, Scope.all)
    assert updated.access_level is AccessLevel.view


async def test_system_admin_permissions_are_locked(seeded_db):
    """Kilitlenme koruması: system_admin izin satırları hiç kimse tarafından değiştirilemez."""
    role = await _role(seeded_db, "system_admin")
    with pytest.raises(PermissionLockedError):
        await update_role_permission(seeded_db, role.id, "settings", AccessLevel.none, Scope.all)


async def test_system_admin_can_still_be_renamed(seeded_db):
    """Ad/emoji/açıklama düzenlenebilir; kilitli olan yalnızca izinlerdir."""
    role = await _role(seeded_db, "system_admin")
    renamed = await rename_role(
        seeded_db, role.id, name="Süper Yönetici", emoji="⚡", description=""
    )
    assert renamed.name == "Süper Yönetici"
    assert renamed.key == "system_admin"


async def test_renaming_never_changes_key(seeded_db):
    """Yetki kontrolü key'e dayanır; ad değişince yetkiler kaymamalı."""
    role = await _role(seeded_db, "field_engineer")
    renamed = await rename_role(seeded_db, role.id, name="Teknik Ofis", emoji="📐", description="")
    assert renamed.key == "field_engineer"
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/core/test_can_delete.py tests/modules/test_role_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.errors'`

- [ ] **Step 3: Minimal implementasyonu yaz**

`app/core/errors.py`:

```python
class DomainError(Exception):
    """Alan kuralı ihlali. Router katmanı bunu uygun HTTP koduna çevirir."""


class PermissionLockedError(DomainError):
    """system_admin rolünün izinleri değiştirilemez (kilitlenme koruması, spec §5.0)."""


class DeleteNotAllowedError(DomainError):
    """Silme koşulları sağlanmadı (spec §5.0)."""
```

`app/core/permissions.py` — ekle (`uuid` ve `Protocol` import'larını en üste taşı):

```python
import uuid
from typing import Protocol


class Deletable(Protocol):
    """Silinebilirliği değerlendirilecek kaydın taşıması gereken asgari alanlar."""

    created_by: uuid.UUID
    is_draft: bool


def can_delete(actor_id: uuid.UUID, level: AccessLevel, record: Deletable) -> bool:
    """Spec §5.0 silme kuralı.

    admin seviyesi her şeyi siler. Bunun dışında yalnızca taslak istisnası geçerlidir:
    kaydı aktör oluşturmuş + kayıt hâlâ taslak + aktörün en az draft seviyesi var.
    """
    if satisfies(level, AccessLevel.admin):
        return True

    return record.created_by == actor_id and record.is_draft and satisfies(level, AccessLevel.draft)
```

`app/modules/roles/service.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionLockedError
from app.core.permissions import AccessLevel, Scope
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Role, RolePermission
from app.modules.roles.repository import get_permission


async def update_role_permission(
    session: AsyncSession,
    role_id: uuid.UUID,
    module_key: str,
    level: AccessLevel,
    scope: Scope,
) -> RolePermission:
    """Matrisin bir hücresini günceller.

    system_admin rolünün hiçbir hücresi değiştirilemez — aktör kim olursa olsun.
    """
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one()

    if role.key == SYSTEM_ADMIN_KEY:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    permission = await get_permission(session, role_id, module_key)
    if permission is None:
        raise PermissionLockedError("İzin satırı bulunamadı")

    permission.access_level = level
    permission.scope = scope
    await session.flush()
    return permission


async def rename_role(
    session: AsyncSession,
    role_id: uuid.UUID,
    name: str,
    emoji: str,
    description: str,
) -> Role:
    """Rolün görünen bilgilerini günceller. key asla değişmez — kod ona dayanır."""
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one()
    role.name = name
    role.emoji = emoji
    role.description = description
    await session.flush()
    return role
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/core/test_can_delete.py tests/modules/test_role_service.py -v`
Expected: PASS — `11 passed`

- [ ] **Step 5: Commit**

```bash
git add app/core/errors.py app/core/permissions.py app/modules/roles/service.py tests
git commit -m "feat: silme kurali (can_delete) ve kilitlenme korumasi"
```

---

## Task 12: Faz kapanışı — kapsam, lint ve inceleme

**Files:**
- Modify: gerektiği kadar (eksik test veya lint düzeltmesi)

**Interfaces:**
- Consumes: Task 1–11
- Produces: Yeşil CI, ≥%80 kapsam, temiz inceleme

- [ ] **Step 1: Tüm testleri kapsamla çalıştır**

Run: `python -m pytest --cov=app --cov-report=term-missing`
Expected: Tüm testler PASS, `TOTAL` satırı ≥ %80.

Kapsam düşükse eksik satırlar için test ekle. **Kapsamı yükseltmek için testi silme veya `# pragma: no cover` ekleme** — kapsam bir sonuç, hedef değil.

- [ ] **Step 2: Lint**

Run: `python -m ruff check . && python -m ruff format --check .`
Expected: `All checks passed!`

- [ ] **Step 3: Migration zincirini sıfırdan doğrula**

Migration zincirinin sıfırdan çalıştığını, geliştirme veritabanını bozmadan `fiil_erp_test` üzerinde doğrula:

```bash
python - <<'PY'
import asyncio, os, re
from pathlib import Path
url = next(l.split("=",1)[1] for l in Path(".env").read_text().splitlines() if l.startswith("TEST_DATABASE_URL"))
import asyncpg
async def main():
    raw = re.sub(r"\+asyncpg", "", url)
    conn = await asyncpg.connect(raw)
    await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await conn.close()
    print("test semasi sifirlandi")
asyncio.run(main())
PY

DATABASE_URL="$(grep '^TEST_DATABASE_URL' .env | cut -d= -f2-)" python -m alembic upgrade head
```

Expected: Tüm migration'lar boş şemada hatasız uygulanır. Bu, `alembic upgrade head`'in canlıda çalışacağının kanıtıdır.

Ardından seed'in gerçekten 104 satır yazdığını doğrula:

```bash
python - <<'PY'
import asyncio, re
from pathlib import Path
import asyncpg
url = next(l.split("=",1)[1] for l in Path(".env").read_text().splitlines() if l.startswith("TEST_DATABASE_URL"))
async def main():
    conn = await asyncpg.connect(re.sub(r"\+asyncpg", "", url))
    print("role_permissions:", await conn.fetchval("SELECT count(*) FROM role_permissions"))
    await conn.close()
asyncio.run(main())
PY
```

Expected: `role_permissions: 104`

- [ ] **Step 4: Güvenlik incelemesi**

`security-reviewer` agent'ını şu kapsamla çalıştır: `app/core/security.py`, `app/core/deps.py`, `app/core/permissions.py`, `app/modules/auth/`.

Özellikle doğrulat: parola özeti tuzlu mu · token tipi karışıyor mu · giriş hatası kullanıcı varlığını sızdırıyor mu · yetki kapısı varsayılan kapalı mı · 401 ile 403 doğru ayrılmış mı · JWT gizli anahtarı koda gömülü mü.

CRITICAL ve HIGH bulguların **hepsi** düzeltilmeden faz kapanmaz.

- [ ] **Step 5: Kod incelemesi**

`fastapi-reviewer` agent'ını `app/` kapsamıyla çalıştır. Özellikle: async doğruluğu (tembel yükleme yok), bağımlılık enjeksiyonu, Pydantic şemaları, N+1 sorgu.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: B0-B2 faz kapanisi — kapsam, lint ve inceleme duzeltmeleri"
```

---

## Faz sonu kabul kriterleri

Aşağıdakilerin **hepsi** doğru olmadan B0–B2 bitmiş sayılmaz:

- [ ] `python -m pytest --cov=app` → tüm testler geçer, kapsam ≥ %80
- [ ] `python -m ruff check .` → temiz
- [ ] `alembic upgrade head` boş veritabanında hatasız çalışır
- [ ] `alembic downgrade -1 && alembic upgrade head` seed migration'ında hatasız çalışır
- [ ] Veritabanında tam olarak 8 rol, 13 modül, 104 izin satırı var
- [ ] Negatif izin testleri mevcut ve geçiyor (en az: şef onaylayamaz, İK hakedişe giremez, patron ayarlara giremez)
- [ ] `system_admin` izinlerini değiştirme denemesi `PermissionLockedError` fırlatıyor
- [ ] `full` seviyesindeki bir rol kesinleşmiş kaydı silemiyor
- [ ] `security-reviewer` CRITICAL/HIGH bulgusu yok
- [ ] `/docs` (OpenAPI) açılıyor — frontend'in tip üreteceği kaynak burası
