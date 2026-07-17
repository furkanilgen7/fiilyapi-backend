# Backend B3 — Kullanıcı Yönetimi + Projeler + Rol/İzin Router Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B0–B2 çekirdeğinin üstüne kullanıcı yönetimini (CRUD + parola sıfırlama + silme), salt-okunur `projects` referansını, `user_project_access` proje kapsamını ve F4'ü tam açan rol/izin-matrisi HTTP router'ını eklemek.

**Architecture:** Modüler FastAPI; her modül `models · schemas · repository · service · router` iskeletini izler. Yetki tek bir `require_permission` bağımlılığından geçer. Bu faz, B0–B2'de biriken iki teknik borcu (saf domain'i `access.py`'ye ayırıp döngüsel import'u YAPISAL kırmak; `NotFoundError`→404) ilk iki task olarak kapatır, sonra kullanıcı/proje/rol uçlarını inşa eder. `projects` v1'de salt-okunur, migration ile seed'lenir; yazma ucu yoktur (spec §4.1).

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async, asyncpg) · Alembic · Pydantic v2 + pydantic-settings · argon2-cffi · PyJWT · pytest + pytest-asyncio + httpx

**Spec:** `docs/superpowers/specs/2026-07-17-temel-modul-design.md` — çelişki hâlinde spec kazanır. Referanslar: §4.1 (tablolar), §5.0/§5.3 (izin ve kapsam), §8 (fazlar, B3=satır 407), §9 (tek rol, çok-şirketlilik yok).

## Global Constraints

- **Repo:** Tüm yollar `/Users/furkanilgen/Documents/Projeler/insaat/backend` köküne görelidir. Frontend ayrı bir repodur; bu planda ona dokunulmaz.
- **Dil:** Kod, değişken ve fonksiyon adları İngilizce. Kullanıcıya dönen hata mesajları Türkçe.
- **Çok şirketlilik yok.** Hiçbir tabloya `company_id` eklenmez (spec §9.1).
- **Tek rol:** Kullanıcı başına tek `role_id` (spec §9, ödünç #7). Çoklu rol yok.
- **Silme:** `full` seviyesi silmeyi **kapsamaz**. Silme yalnızca `admin` seviyesindedir (spec §5.0). Kullanıcı ve rol silme yalnızca Sistem Yöneticisi'ndedir.
- **Rol anahtarı sabit:** Yetki kontrolü `role.key` üzerinden yapılır, `role.name` üzerinden **asla**. `key` kullanıcı tarafından değiştirilemez; `name` değiştirilebilir.
- **Kilitlenme koruması:** `system_admin` rolünün izin satırları hiçbir aktör tarafından değiştirilemez; rol silinemez.
- **Modül sayısı sabit:** Tam olarak 13 modül vardır. `projects` bir izin **modülü değildir**; proje uçları `user_management` modülü üzerinden yetkilendirilir (B3'te projeler yalnızca kullanıcı-erişim seçicisi ve gelecekteki dashboard için okunur). Matrise yeni modül **eklenmez**; 104 izin satırı korunur.
- **Seviye sırası:** `none < view < draft < request < approve < full < admin`
- **Yetki eşiği:** Kullanıcı/rol **okuma** → `require_permission("user_management", AccessLevel.view)`. **Yazma** (oluştur/güncelle) → `AccessLevel.full`. **Silme + parola sıfırlama** → `AccessLevel.admin`. Seed matrisinde `user_management` yalnızca `system_admin`'de (admin) olduğundan bunların tümü fiilen yalnızca Sistem Yöneticisi'ndedir.
- **Yanıt gövdesi:** Parola, `password_hash`, token veya iç auth durumu HİÇBİR yanıt modelinde yer almaz.
- **Dosya boyutu:** Tek dosya 400 satırı geçmemeli; geçiyorsa böl.
- **Migration:** Yeni PG enum tipleri `downgrade()` içinde AÇIKÇA düşürülmeli (`sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`) — boş-kolonlu `drop_table` otomatik düşürmez. Migration'lar dev DB'de değil `TEST_DATABASE_URL`'de denenir; `downgrade -1 && upgrade head` doğrulanır.
- **Test:** Her task TDD ile — önce başarısız test, sonra minimal implementasyon. Faz sonunda kapsam ≥ %80.
- **Commit:** Her task sonunda commit. Format: `<type>: <açıklama>` (feat, fix, refactor, test, chore, docs). Commit mesajlarında Türkçe diakritik kullanma (ör. "saglik", "izin").

---

## File Structure

| Dosya | Sorumluluk |
|---|---|
| `app/core/access.py` | **YENİ** — saf domain: `AccessLevel`, `Scope`, `satisfies`, `Deletable`, `can_delete`. FastAPI/DB bağımlılığı yok. |
| `app/core/permissions.py` | Yalnızca `require_permission` kapısı; enum/domain'i `access.py`'den içe aktarır. Fonksiyon-içi import'lar modül seviyesine çıkar (döngü yapısal kırıldı). |
| `app/core/errors.py` | `NotFoundError` eklenir. |
| `app/core/exception_handlers.py` | `NotFoundError` → 404 handler'ı eklenir (DomainError yedeğinden önce). |
| `app/modules/projects/__init__.py` | Boş paket işareti. |
| `app/modules/projects/models.py` | `Project`, `ProjectStatus` (active·on_hold·completed). |
| `app/modules/projects/schemas.py` | `ProjectResponse`. |
| `app/modules/projects/repository.py` | `list_projects`, `get_project`. |
| `app/modules/projects/router.py` | `GET /projects`, `GET /projects/{id}` (salt-okunur). |
| `app/modules/users/models.py` | `UserProjectAccess` eklenir (user_id · project_id null · all_projects). |
| `app/modules/users/schemas.py` | `UserCreate`, `UserUpdate`, `UserResponse`, `PasswordReset`, `ProjectAccessInput`, `ProjectAccessResponse`. |
| `app/modules/users/repository.py` | Kullanıcı ve proje-erişimi veri erişimi. |
| `app/modules/users/service.py` | `create_user`, `update_user`, `set_user_password`, `delete_user`, `set_project_access`. |
| `app/modules/users/router.py` | `/users` CRUD + `/users/{id}/password` + `/users/{id}/project-access`. |
| `app/modules/roles/schemas.py` | **YENİ** — `RoleResponse`, `RoleCreate`, `RoleRename`, `ModuleResponse`, `PermissionCell`, `PermissionUpdate`. |
| `app/modules/roles/repository.py` | `list_roles`, `get_role`, `list_modules`, `get_role_matrix`, `create_custom_role`, `delete_role` eklenir. |
| `app/modules/roles/service.py` | `create_custom_role`, `delete_role` eklenir; `update_role_permission` 404 semantiğine geçer. |
| `app/modules/roles/router.py` | **YENİ** — `/roles` yönetimi + `/modules` + izin-hücresi düzenleme. |
| `app/main.py` | Yeni router'lar (projects, users, roles) kaydedilir. |
| `alembic/versions/*` | 3 yeni migration: projects tablosu · projects seed · user_project_access tablosu. |
| `tests/conftest.py` | `project_factory` fixture eklenir. |
| `tests/core/test_access.py` | Saf domain testleri (access.py). |
| `tests/modules/test_projects_api.py` | Projects okuma uçları. |
| `tests/modules/test_users_service.py`, `test_users_api.py` | Kullanıcı servis + uç testleri (negatif izin dahil). |
| `tests/modules/test_user_project_access.py` | Proje-erişimi atama testleri. |
| `tests/modules/test_roles_api.py` | Rol/izin-matrisi uç testleri (kilit + 404 dahil). |

---

## Task 1: Saf domain'i `access.py`'ye ayır ve döngüsel import'u yapısal kır

**Files:**
- Create: `app/core/access.py`, `tests/core/test_access.py`
- Modify: `app/core/permissions.py` (yalnızca `require_permission` kalır, import'lar modül seviyesine çıkar), `app/modules/roles/models.py:9`, `app/modules/roles/seed_data.py:10`, `app/modules/roles/service.py:7`, ve `app.core.permissions`'tan `AccessLevel/Scope/satisfies/can_delete/Deletable` içe aktaran tüm test dosyaları (`tests/core/test_permissions.py`, `tests/core/test_can_delete.py`, `tests/core/test_require_permission.py`)
- Test: `tests/core/test_access.py`

**Interfaces:**
- Consumes: mevcut `app/core/permissions.py` içeriği
- Produces:
  - `app.core.access:AccessLevel`, `app.core.access:Scope` (enum'lar)
  - `app.core.access:satisfies(actual: AccessLevel, required: AccessLevel) -> bool`
  - `app.core.access:Deletable` (Protocol), `app.core.access:can_delete(actor_id, level, record) -> bool`
  - `app.core.permissions:require_permission(module_key: str, min_level: AccessLevel)` — davranışı DEĞİŞMEZ; artık modül-seviyesi import kullanır
  - Yeni import döngüsü: `permissions → deps → users.models → roles.models → access` (geri dönüş YOK)

> **Neden yapısal:** Bugün `roles/models.py` `permissions`'tan enum import ediyor; `permissions` da fonksiyon-içi `deps`/`users.models` import ediyor. Enum'lar FastAPI'siz `access.py`'ye taşınınca `roles.models → access` olur ve `permissions`'a geri dönen kenar kopar. Böylece `require_permission` içindeki üç fonksiyon-içi import modül seviyesine çıkabilir. Bu, "kapıyı ayrı tut, domain'i ayır" hedefidir.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/core/test_access.py
import uuid

from app.core.access import AccessLevel, Scope, can_delete, satisfies


def test_access_exports_pure_domain_without_fastapi():
    # access.py FastAPI/DB'ye bağımlı OLMAMALI — saf domain.
    import app.core.access as access_module

    with open(access_module.__file__, encoding="utf-8") as handle:
        text = handle.read()
    assert "fastapi" not in text.lower()
    assert "get_db" not in text


def test_level_ordering():
    assert satisfies(AccessLevel.admin, AccessLevel.full)
    assert satisfies(AccessLevel.approve, AccessLevel.approve)
    assert not satisfies(AccessLevel.view, AccessLevel.draft)


def test_scope_values():
    assert {s.value for s in Scope} == {"all", "own", "project", "finance", "stock", "limited"}


class _Rec:
    def __init__(self, created_by: uuid.UUID, is_draft: bool):
        self.created_by = created_by
        self.is_draft = is_draft


def test_can_delete_admin_always():
    rec = _Rec(uuid.uuid4(), is_draft=False)
    assert can_delete(uuid.uuid4(), AccessLevel.admin, rec) is True


def test_can_delete_draft_exception_only_for_owner():
    owner = uuid.uuid4()
    rec = _Rec(owner, is_draft=True)
    assert can_delete(owner, AccessLevel.draft, rec) is True
    assert can_delete(uuid.uuid4(), AccessLevel.draft, rec) is False


def test_permissions_module_has_no_function_level_domain_imports():
    # Döngü yapısal kırıldıysa require_permission gövdesinde artık girintili
    # (fonksiyon içi) "from app.modules.roles.repository import" OLMAMALI.
    import app.core.permissions as perm_module

    with open(perm_module.__file__, encoding="utf-8") as handle:
        body = handle.read()
    assert body.count("from app.core.deps import get_current_user") == 1  # modül seviyesinde, 1 kez
    assert "\n        from app.modules.roles.repository import get_permission" not in body
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/core/test_access.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.access'`

- [ ] **Step 3: `access.py`'yi oluştur (saf domain)**

```python
# app/core/access.py
import enum
import uuid
from typing import Protocol


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

- [ ] **Step 4: `permissions.py`'yi yalnızca kapıya indir**

```python
# app/core/permissions.py
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.db import get_db
from app.core.deps import get_current_user
from app.modules.roles.repository import get_permission
from app.modules.users.models import User


def require_permission(module_key: str, min_level: AccessLevel):
    """Uç için asgari yetki kapısı.

    Kullanımı:
        @router.post(
            "/x", dependencies=[require_permission("progress_payments", AccessLevel.draft)]
        )

    İzin satırı yoksa erişim reddedilir (varsayılan kapalı).
    """

    async def _check(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        permission = await get_permission(session, user.role_id, module_key)
        if permission is None or not satisfies(permission.access_level, min_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok"
            )

    return Depends(_check)
```

> Not: `AccessLevel`/`Scope`/`satisfies`/`can_delete`/`Deletable` artık `app.core.access`'te. `require_permission` hâlâ `app.core.permissions`'ta (kapı ayrı). Fonksiyon-içi import'lar kalktı çünkü `permissions → access` (döngüsüz).

- [ ] **Step 5: Tüketici import'larını `access.py`'ye taşı**

Şu satırları değiştir (yalnızca import kaynağı; kullanım aynı):
- `app/modules/roles/models.py:9` → `from app.core.access import AccessLevel, Scope`
- `app/modules/roles/seed_data.py:10` → `from app.core.access import AccessLevel, Scope`
- `app/modules/roles/service.py:7` → `from app.core.access import AccessLevel, Scope`
- Testlerde `from app.core.permissions import AccessLevel` / `Scope` / `satisfies` / `can_delete` / `Deletable` geçen her yeri `from app.core.access import ...` yap (`tests/core/test_permissions.py`, `tests/core/test_can_delete.py`, `tests/core/test_require_permission.py`). `require_permission` import'ları `app.core.permissions`'ta KALIR.

Doğrula: `grep -rn "from app.core.permissions import" app tests` çıktısında yalnızca `require_permission` kalmalı.

- [ ] **Step 6: Tüm testlerin geçtiğini doğrula (regresyon yok)**

Run: `python -m pytest -q`
Expected: PASS — mevcut 85 test + yeni `tests/core/test_access.py` (6 passed) yeşil. Ayrıca:
Run: `python -c "import app.core.permissions; import app.main"`
Expected: hatasız (döngüsel import yok).

- [ ] **Step 7: Commit**

```bash
git add app/core/access.py app/core/permissions.py app/modules/roles/models.py app/modules/roles/seed_data.py app/modules/roles/service.py tests/
git commit -m "refactor: saf domaini access.py'ye ayir, dongusel importu yapisal kir"
```

---

## Task 2: `NotFoundError` → 404 ve `update_role_permission` semantiği

**Files:**
- Modify: `app/core/errors.py`, `app/core/exception_handlers.py`, `app/modules/roles/service.py`, mevcut `tests/modules/test_role_service.py` (beklenen istisna değişir)
- Test: `tests/modules/test_role_service.py`

**Interfaces:**
- Consumes: `app.core.errors:DomainError`
- Produces:
  - `app.core.errors:NotFoundError` (DomainError alt sınıfı) → HTTP **404**
  - `update_role_permission(...)`: izin satırı yoksa (özel rol) veya `role_id` bulunamazsa → `NotFoundError`; `system_admin` → hâlâ `PermissionLockedError` (403)

> **Neden:** Bugün `update_role_permission` izin satırı bulunamayınca `PermissionLockedError`(403) atıyor. Özel roller izin satırı olmadan var olabilir (Task 12'de oluşturulur); "yok" durumu 404 olmalı, "kilitli" (system_admin) 403 kalmalı. Ayrıca geçersiz `role_id` şu an `NoResultFound`→500 verir; 404'e çevrilir.

- [ ] **Step 1: Başarısız testi yaz / mevcut testi güncelle**

```python
# tests/modules/test_role_service.py — ekle; eski "izin bulunamadi -> PermissionLockedError"
# assertion'ini NotFoundError'a cevir.
import uuid

import pytest
from sqlalchemy import select

from app.core.access import AccessLevel, Scope
from app.core.errors import NotFoundError, PermissionLockedError
from app.modules.roles.models import Role
from app.modules.roles.service import update_role_permission


async def test_update_permission_missing_row_raises_not_found(seeded_db):
    patron = (await seeded_db.execute(select(Role).where(Role.key == "patron"))).scalar_one()
    with pytest.raises(NotFoundError):
        await update_role_permission(
            seeded_db, patron.id, "olmayan_modul", AccessLevel.view, Scope.all
        )


async def test_update_permission_unknown_role_raises_not_found(seeded_db):
    with pytest.raises(NotFoundError):
        await update_role_permission(
            seeded_db, uuid.uuid4(), "dashboard", AccessLevel.view, Scope.all
        )


async def test_update_permission_system_admin_still_locked(seeded_db):
    sysadmin = (
        await seeded_db.execute(select(Role).where(Role.key == "system_admin"))
    ).scalar_one()
    with pytest.raises(PermissionLockedError):
        await update_role_permission(
            seeded_db, sysadmin.id, "dashboard", AccessLevel.view, Scope.all
        )
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_role_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'NotFoundError'`.

- [ ] **Step 3: `NotFoundError` ekle**

```python
# app/core/errors.py — sona ekle
class NotFoundError(DomainError):
    """İstenen kayıt bulunamadı — router katmanı 404'e çevirir."""
```

- [ ] **Step 4: 404 handler'ını kaydet**

```python
# app/core/exception_handlers.py
from app.core.errors import (
    DeleteNotAllowedError,
    DomainError,
    NotFoundError,
    PermissionLockedError,
)


async def _not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})
```

`register_exception_handlers` içine (DomainError yedeğinden ÖNCE) ekle:
```python
    app.add_exception_handler(NotFoundError, _not_found_handler)
```

- [ ] **Step 5: Servis semantiğini güncelle**

```python
# app/modules/roles/service.py — import satirina NotFoundError ekle:
from app.core.errors import NotFoundError, PermissionLockedError

# update_role_permission govdesinin bası:
    role = (
        await session.execute(select(Role).where(Role.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")

    if role.key == SYSTEM_ADMIN_KEY:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    permission = await get_permission(session, role_id, module_key)
    if permission is None:
        raise NotFoundError("İzin satırı bulunamadı")
```

- [ ] **Step 6: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_role_service.py tests/core/test_exception_handlers.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/errors.py app/core/exception_handlers.py app/modules/roles/service.py tests/modules/test_role_service.py
git commit -m "feat: NotFoundError->404 ve rol izin guncelleme 404 semantigi"
```

---

## Task 3: `Project` modeli + tablo migration'ı

**Files:**
- Create: `app/modules/projects/__init__.py`, `app/modules/projects/models.py`, `tests/modules/test_project_model.py`, `alembic/versions/<rev>_projects_tablosu.py`
- Modify: `alembic/env.py` (projects modelini import et ki `Base.metadata` tam olsun), `tests/conftest.py` (projects modelini import et)
- Test: `tests/modules/test_project_model.py`

**Interfaces:**
- Consumes: `app.core.db:Base`
- Produces:
  - `app.modules.projects.models:Project` (tablo `projects`): `id` UUID PK · `code` str unique · `name` str · `status` ProjectStatus · `budget` Numeric(18,2) · `progress_pct` Numeric(5,2) · `created_at`/`updated_at`
  - `app.modules.projects.models:ProjectStatus` (`active`·`on_hold`·`completed`, PG enum `project_status`)

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_project_model.py
from decimal import Decimal

from sqlalchemy import select

from app.modules.projects.models import Project, ProjectStatus


async def test_create_and_read_project(db_session):
    project = Project(
        code="GK-A",
        name="Güneşkent A-Blok",
        status=ProjectStatus.active,
        budget=Decimal("1500000.00"),
        progress_pct=Decimal("42.50"),
    )
    db_session.add(project)
    await db_session.flush()

    loaded = (
        await db_session.execute(select(Project).where(Project.code == "GK-A"))
    ).scalar_one()
    assert loaded.name == "Güneşkent A-Blok"
    assert loaded.status is ProjectStatus.active
    assert loaded.budget == Decimal("1500000.00")


def test_project_status_values():
    assert {s.value for s in ProjectStatus} == {"active", "on_hold", "completed"}
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_project_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.projects'`

- [ ] **Step 3: Modeli oluştur**

```python
# app/modules/projects/__init__.py
```
(boş dosya)

```python
# app/modules/projects/models.py
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class Project(Base):
    """v1'de minimal ve salt-okunur referans (spec §4.1). Yazma ucu yok."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, default=ProjectStatus.active
    )
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 4: `env.py` ve `conftest.py`'ye import ekle**

`alembic/env.py` içinde diğer model import'larının yanına: `from app.modules.projects import models as projects_models  # noqa: F401`
`tests/conftest.py` içinde: `from app.modules.projects import models as projects_models  # noqa: F401`
(Böylece `Base.metadata.create_all` projects tablosunu da kurar ve autogenerate onu görür.)

- [ ] **Step 5: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_project_model.py -v`
Expected: PASS (`_create_schema` fixture tabloyu modelden kurar).

- [ ] **Step 6: Migration yaz**

```bash
alembic revision -m "projects tablosu"
```
Üretilen dosyayı düzenle — `down_revision = "a477fdf00fdf"` (mevcut head), ve:

```python
def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "on_hold", "completed", name="project_status"),
            nullable=False,
        ),
        sa.Column("budget", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("progress_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_code"), "projects", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_projects_code"), table_name="projects")
    op.drop_table("projects")
    # Bos-kolonlu drop_table enum'u otomatik dusurmez — acikca dusur (DuplicateObject korumasi).
    sa.Enum(name="project_status").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 7: Migration zincirini `TEST_DATABASE_URL`'de doğrula**

Run: `DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head && DATABASE_URL="$TEST_DATABASE_URL" alembic downgrade -1 && DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head`
Expected: hatasız (ASLA dev DB'de değil). Sonra test şemasının migration'la uyumu için `python -m pytest -q` yeşil.

- [ ] **Step 8: Commit**

```bash
git add app/modules/projects/ alembic/ tests/modules/test_project_model.py tests/conftest.py
git commit -m "feat: projects tablosu ve modeli (salt okunur referans)"
```

---

## Task 4: Örnek projeleri seed'le + `project_factory` fixture'ı

**Files:**
- Create: `alembic/versions/<rev>_projects_seed.py`
- Modify: `tests/conftest.py` (`project_factory` fixture)
- Test: `tests/conftest.py` üzerinden dolaylı; ayrıca migration doğrulaması

**Interfaces:**
- Consumes: Task 3 `projects` tablosu
- Produces:
  - Migration ile 3 örnek proje (frozen veri): `GK-A` Güneşkent A-Blok (active), `MERKEZ-1` Merkez Ofis (on_hold), `SAHIL-2` Sahil Sitesi (completed)
  - `tests/conftest.py:project_factory(code, name, status="active", ...) -> Project` — testlerde proje üretir

> **Neden migration + fixture ayrı:** Canlı/gerçek veri migration'la yüklenir (dashboard ve erişim seçicisi gerçek satır ister — spec §7). Testler izolasyon için `_create_schema`'yı modelden kurar ve seed migration çalıştırmaz; bu yüzden testler proje satırını `project_factory` ile yaratır.

- [ ] **Step 1: `project_factory` fixture'ını ekle (başarısız testle değil, fixture olarak)**

```python
# tests/conftest.py — sona ekle
from decimal import Decimal

from app.modules.projects.models import Project, ProjectStatus


@pytest.fixture
def project_factory(db_session: AsyncSession):
    async def _create(
        code: str,
        name: str = "Test Proje",
        status: str = "active",
        budget: str = "1000000.00",
        progress_pct: str = "0.00",
    ) -> Project:
        project = Project(
            code=code,
            name=name,
            status=ProjectStatus(status),
            budget=Decimal(budget),
            progress_pct=Decimal(progress_pct),
        )
        db_session.add(project)
        await db_session.flush()
        return project

    return _create
```

- [ ] **Step 2: Fixture'ı kullanan geçici doğrulama testiyle çalıştığını gör**

```python
# tests/modules/test_project_model.py — ek test
async def test_project_factory_creates_row(project_factory):
    project = await project_factory("TMP-1", name="Geçici")
    assert project.id is not None
    assert project.code == "TMP-1"
```

Run: `python -m pytest tests/modules/test_project_model.py -v`
Expected: PASS.

- [ ] **Step 3: Seed migration'ı yaz**

```bash
alembic revision -m "projects seed"
```
`down_revision` = Task 3 migration revision'ı. Gövde (frozen, hardcoded — migration app kodundan bağımsız olmalı):

```python
import uuid

def upgrade() -> None:
    projects = sa.table(
        "projects",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("status", sa.Enum(name="project_status")),
        sa.column("budget", sa.Numeric()),
        sa.column("progress_pct", sa.Numeric()),
    )
    op.bulk_insert(
        projects,
        [
            {"id": uuid.uuid4(), "code": "GK-A", "name": "Güneşkent A-Blok",
             "status": "active", "budget": 1500000.00, "progress_pct": 42.50},
            {"id": uuid.uuid4(), "code": "MERKEZ-1", "name": "Merkez Ofis",
             "status": "on_hold", "budget": 800000.00, "progress_pct": 15.00},
            {"id": uuid.uuid4(), "code": "SAHIL-2", "name": "Sahil Sitesi",
             "status": "completed", "budget": 3200000.00, "progress_pct": 100.00},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM projects WHERE code IN ('GK-A', 'MERKEZ-1', 'SAHIL-2')")
```

- [ ] **Step 4: Migration zincirini doğrula**

Run: `DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head && DATABASE_URL="$TEST_DATABASE_URL" alembic downgrade -1 && DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head`
Expected: hatasız; `SELECT count(*) FROM projects` → 3.

- [ ] **Step 5: Commit**

```bash
git add alembic/ tests/conftest.py tests/modules/test_project_model.py
git commit -m "feat: ornek proje seed migrationi ve project_factory fixture"
```

---

## Task 5: Projects repository + schema + salt-okunur router

**Files:**
- Create: `app/modules/projects/repository.py`, `app/modules/projects/schemas.py`, `app/modules/projects/router.py`, `tests/modules/test_projects_api.py`
- Modify: `app/main.py` (projects router'ı kaydet)
- Test: `tests/modules/test_projects_api.py`

**Interfaces:**
- Consumes: `app.modules.projects.models:Project`, `app.core.permissions:require_permission`, `app.core.errors:NotFoundError`
- Produces:
  - `app.modules.projects.repository:list_projects(session) -> list[Project]`
  - `app.modules.projects.repository:get_project(session, project_id) -> Project | None`
  - `app.modules.projects.schemas:ProjectResponse`
  - `GET /projects` → `list[ProjectResponse]` (gate: `user_management` view)
  - `GET /projects/{project_id}` → `ProjectResponse` | 404 (gate: `user_management` view)

> **Yetki notu:** `projects` bir izin modülü değil (13 modül sabit). B3'te projeler yalnızca kullanıcı-erişim seçicisi için okunur; bu yüzden `user_management` view kapısı kullanılır (fiilen yalnızca Sistem Yöneticisi). B6 dashboard geldiğinde proje kartları kendi dashboard ucundan servis edilir; bu uç değişmez.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_projects_api.py
async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_list_projects_as_system_admin(client, user_factory, project_factory):
    await project_factory("GK-A", name="Güneşkent A-Blok")
    token = await _login(client, user_factory, "system_admin")
    resp = await client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    codes = [p["code"] for p in resp.json()]
    assert "GK-A" in codes
    assert "password_hash" not in resp.text


async def test_list_projects_forbidden_for_non_admin(client, user_factory, project_factory):
    await project_factory("GK-A")
    token = await _login(client, user_factory, "patron")  # patron'da user_management=none
    resp = await client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_get_project_not_found(client, user_factory):
    import uuid

    token = await _login(client, user_factory, "system_admin")
    resp = await client.get(
        f"/projects/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


async def test_list_projects_unauthenticated(client):
    resp = await client.get("/projects")
    assert resp.status_code == 401
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_projects_api.py -v`
Expected: FAIL — `404` (route yok) / `ModuleNotFoundError` router import'ta.

- [ ] **Step 3: Repository + schema + router yaz**

```python
# app/modules/projects/repository.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project


async def list_projects(session: AsyncSession) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.code))
    return list(result.scalars().all())


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await session.get(Project, project_id)
```

```python
# app/modules/projects/schemas.py
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.projects.models import ProjectStatus


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    budget: Decimal
    progress_pct: Decimal
```

```python
# app/modules/projects/router.py
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.projects import repository
from app.modules.projects.schemas import ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_projects_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectResponse]:
    projects = await repository.list_projects(session)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await repository.get_project(session, project_id)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return ProjectResponse.model_validate(project)
```

- [ ] **Step 4: Router'ı kaydet**

```python
# app/main.py
from app.modules.projects.router import router as projects_router
app.include_router(projects_router)
```

- [ ] **Step 5: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_projects_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app/modules/projects/ app/main.py tests/modules/test_projects_api.py
git commit -m "feat: salt okunur projects okuma uclari"
```

---

## Task 6: `UserProjectAccess` modeli + tablo migration'ı

**Files:**
- Create: `alembic/versions/<rev>_user_project_access_tablosu.py`, `tests/modules/test_user_project_access.py`
- Modify: `app/modules/users/models.py` (`UserProjectAccess` ekle)
- Test: `tests/modules/test_user_project_access.py`

**Interfaces:**
- Consumes: `users`, `projects` tabloları
- Produces:
  - `app.modules.users.models:UserProjectAccess` (tablo `user_project_access`): `id` UUID PK · `user_id` FK→users CASCADE · `project_id` FK→projects nullable · `all_projects` bool default False
  - Semantik: `all_projects=True` (project_id null) → tüm projeler; aksi hâlde her satır bir projeye erişim (spec §4.1)

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_user_project_access.py
from sqlalchemy import select

from app.modules.users.models import UserProjectAccess


async def test_grant_specific_project_access(db_session, user_factory, project_factory):
    user = await user_factory(email="u@t.co", password="parola1234", role_key="site_chief")
    project = await project_factory("GK-A")
    db_session.add(
        UserProjectAccess(user_id=user.id, project_id=project.id, all_projects=False)
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(UserProjectAccess).where(UserProjectAccess.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].project_id == project.id


async def test_grant_all_projects_access(db_session, user_factory):
    user = await user_factory(email="a@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await db_session.flush()

    row = (
        await db_session.execute(
            select(UserProjectAccess).where(UserProjectAccess.user_id == user.id)
        )
    ).scalar_one()
    assert row.all_projects is True
    assert row.project_id is None
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_user_project_access.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserProjectAccess'`

- [ ] **Step 3: Modeli ekle**

```python
# app/modules/users/models.py — sona ekle (importlara Boolean ekle)
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func

class UserProjectAccess(Base):
    """Kullanıcının erişebildiği projeler (spec §4.1).

    all_projects=True (project_id NULL) → tüm projeler. Aksi hâlde her satır bir proje.
    """

    __tablename__ = "user_project_access"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    all_projects: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_user_project_access.py -v`
Expected: PASS.

- [ ] **Step 5: Migration yaz**

```bash
alembic revision -m "user_project_access tablosu"
```
`down_revision` = Task 4 seed migration revision'ı. Gövde (yeni enum YOK, sadece bool/FK):

```python
def upgrade() -> None:
    op.create_table(
        "user_project_access",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("all_projects", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_project_access_user_id"), "user_project_access", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_project_access_user_id"), table_name="user_project_access")
    op.drop_table("user_project_access")
```

- [ ] **Step 6: Migration zincirini doğrula**

Run: `DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head && DATABASE_URL="$TEST_DATABASE_URL" alembic downgrade -1 && DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head`
Expected: hatasız.

- [ ] **Step 7: Commit**

```bash
git add app/modules/users/models.py alembic/ tests/modules/test_user_project_access.py
git commit -m "feat: user_project_access tablosu ve modeli"
```

---

## Task 7: Users schemas + repository

**Files:**
- Create: `app/modules/users/schemas.py`, `app/modules/users/repository.py`, `tests/modules/test_users_repository.py`
- Test: `tests/modules/test_users_repository.py`

**Interfaces:**
- Consumes: `app.modules.users.models:User`, `app.modules.roles.models:Role`, `app.core.security:hash_password`
- Produces:
  - `schemas:UserCreate` (email · password[min 8] · full_name · title · role_id · status), `UserUpdate` (full_name/title/role_id/status opsiyonel), `UserResponse` (parola YOK; role_key + role_name dahil), `PasswordReset` (new_password[min 8])
  - `repository:list_users(session) -> list[User]` (role joinedload)
  - `repository:get_user(session, user_id) -> User | None` (role joinedload)
  - `repository:get_user_by_email(session, email) -> User | None`
  - `repository:add_user(session, user) -> User`

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_users_repository.py
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users import repository


async def _role_id(session, key: str):
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one().id


async def test_add_and_get_user_loads_role(seeded_db):
    user = User(
        email="a@t.co",
        password_hash=hash_password("parola1234"),
        full_name="Ahmet Yılmaz",
        role_id=await _role_id(seeded_db, "patron"),
    )
    await repository.add_user(seeded_db, user)

    loaded = await repository.get_user(seeded_db, user.id)
    assert loaded is not None
    assert loaded.role.key == "patron"  # joinedload — lazy="raise" patlamaz


async def test_get_user_by_email(seeded_db):
    user = User(
        email="b@t.co",
        password_hash=hash_password("parola1234"),
        full_name="B",
        role_id=await _role_id(seeded_db, "accounting"),
    )
    await repository.add_user(seeded_db, user)
    found = await repository.get_user_by_email(seeded_db, "b@t.co")
    assert found is not None and found.email == "b@t.co"
    assert await repository.get_user_by_email(seeded_db, "yok@t.co") is None
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_users_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.users.repository'`

- [ ] **Step 3: Repository yaz**

```python
# app/modules/users/repository.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.users.models import User


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).options(joinedload(User.role)).order_by(User.full_name)
    )
    return list(result.scalars().all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(
        select(User).options(joinedload(User.role)).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def add_user(session: AsyncSession, user: User) -> User:
    session.add(user)
    await session.flush()
    return user
```

- [ ] **Step 4: Schemas yaz**

```python
# app/modules/users/schemas.py
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import UserStatus


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    title: str = Field(default="", max_length=150)
    role_id: uuid.UUID
    status: UserStatus = UserStatus.active


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    role_id: uuid.UUID | None = None
    status: UserStatus | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    title: str
    role_id: uuid.UUID
    status: UserStatus
```

> Not: `UserResponse`'ta `password_hash` YOK (Global Constraints). `role_key`/`role_name` gerekiyorsa router ayrı bir zenginleştirilmiş şema kullanır; şimdilik `role_id` yeterli (frontend rolleri `/roles`'tan alır). `EmailStr` için `pydantic[email]` kurulu olmalı — yoksa `pyproject.toml`'a ekle.

- [ ] **Step 5: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_users_repository.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/users/schemas.py app/modules/users/repository.py tests/modules/test_users_repository.py
git commit -m "feat: kullanici schema ve repository katmani"
```

---

## Task 8: Users service (create · update · password · delete)

**Files:**
- Create: `app/modules/users/service.py`, `tests/modules/test_users_service.py`
- Test: `tests/modules/test_users_service.py`

**Interfaces:**
- Consumes: `repository`, `app.core.security:hash_password`, `app.core.errors:NotFoundError`/`DomainError`, `app.modules.roles.models:Role`
- Produces:
  - `service:create_user(session, data: UserCreate) -> User` — email benzersizse; rol yoksa `NotFoundError`; email çakışırsa `DomainError`
  - `service:update_user(session, user_id, data: UserUpdate) -> User` — kullanıcı/rol yoksa `NotFoundError`
  - `service:set_user_password(session, user_id, new_password) -> None` — kullanıcı yoksa `NotFoundError`
  - `service:delete_user(session, user_id) -> None` — kullanıcı yoksa `NotFoundError`

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_users_service.py
import uuid

import pytest
from sqlalchemy import select

from app.core.errors import DomainError, NotFoundError
from app.core.security import verify_password
from app.modules.roles.models import Role
from app.modules.users.models import User, UserStatus
from app.modules.users.schemas import UserCreate, UserUpdate
from app.modules.users import service


async def _role_id(session, key):
    return (await session.execute(select(Role).where(Role.key == key))).scalar_one().id


async def test_create_user_hashes_password(seeded_db):
    data = UserCreate(
        email="a@t.co", password="parola1234", full_name="Ahmet",
        role_id=await _role_id(seeded_db, "patron"),
    )
    user = await service.create_user(seeded_db, data)
    assert user.password_hash != "parola1234"
    assert verify_password("parola1234", user.password_hash)


async def test_create_user_duplicate_email_raises(seeded_db):
    rid = await _role_id(seeded_db, "patron")
    await service.create_user(
        seeded_db, UserCreate(email="d@t.co", password="parola1234", full_name="A", role_id=rid)
    )
    with pytest.raises(DomainError):
        await service.create_user(
            seeded_db,
            UserCreate(email="d@t.co", password="parola1234", full_name="B", role_id=rid),
        )


async def test_create_user_unknown_role_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.create_user(
            seeded_db,
            UserCreate(email="x@t.co", password="parola1234", full_name="X", role_id=uuid.uuid4()),
        )


async def test_update_user_changes_status(seeded_db, user_factory):
    user = await user_factory(email="u@t.co", password="parola1234", role_key="site_chief")
    updated = await service.update_user(
        seeded_db, user.id, UserUpdate(status=UserStatus.passive)
    )
    assert updated.status is UserStatus.passive


async def test_set_password(seeded_db, user_factory):
    user = await user_factory(email="p@t.co", password="parola1234", role_key="patron")
    await service.set_user_password(seeded_db, user.id, "yeniParola9")
    refreshed = (await seeded_db.execute(select(User).where(User.id == user.id))).scalar_one()
    assert verify_password("yeniParola9", refreshed.password_hash)


async def test_delete_user(seeded_db, user_factory):
    user = await user_factory(email="del@t.co", password="parola1234", role_key="accounting")
    await service.delete_user(seeded_db, user.id)
    assert (await seeded_db.execute(select(User).where(User.id == user.id))).scalar_one_or_none() is None


async def test_delete_unknown_user_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.delete_user(seeded_db, uuid.uuid4())
```

> Not: `verify_password`'ın `app.core.security`'de var olduğunu doğrula; yoksa ismi mevcut doğrulama fonksiyonuyla değiştir (Task 5 auth zaten parola doğruluyor).

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_users_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.users.service'`

- [ ] **Step 3: Service yaz**

```python
# app/modules/users/service.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.core.security import hash_password
from app.modules.roles.models import Role
from app.modules.users import repository
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate


async def _require_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    return role


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    if await repository.get_user_by_email(session, data.email) is not None:
        raise DomainError("Bu e-posta zaten kayıtlı")
    await _require_role(session, data.role_id)

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        title=data.title,
        role_id=data.role_id,
        status=data.status,
    )
    return await repository.add_user(session, user)


async def update_user(session: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    if data.role_id is not None:
        await _require_role(session, data.role_id)
        user.role_id = data.role_id
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.title is not None:
        user.title = data.title
    if data.status is not None:
        user.status = data.status
    await session.flush()
    return user


async def set_user_password(
    session: AsyncSession, user_id: uuid.UUID, new_password: str
) -> None:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    user.password_hash = hash_password(new_password)
    await session.flush()


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    await session.delete(user)
    await session.flush()
```

- [ ] **Step 4: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_users_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/modules/users/service.py tests/modules/test_users_service.py
git commit -m "feat: kullanici servis katmani (olustur/guncelle/parola/sil)"
```

---

## Task 9: Users router (CRUD + parola sıfırlama)

**Files:**
- Create: `app/modules/users/router.py`, `tests/modules/test_users_api.py`
- Modify: `app/main.py` (users router'ı kaydet)
- Test: `tests/modules/test_users_api.py`

**Interfaces:**
- Consumes: `service`, `repository`, `schemas`, `require_permission`, `NotFoundError`
- Produces (hepsi `user_management` kapılı):
  - `GET /users` → `list[UserResponse]` (view)
  - `GET /users/{id}` → `UserResponse` | 404 (view)
  - `POST /users` → `UserResponse` 201 (full)
  - `PATCH /users/{id}` → `UserResponse` (full)
  - `PATCH /users/{id}/password` → 204 (admin)
  - `DELETE /users/{id}` → 204 (admin)

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_users_api.py
from sqlalchemy import select

from app.modules.roles.models import Role


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def _role_id(session, key: str):
    return str((await session.execute(select(Role).where(Role.key == key))).scalar_one().id)


async def test_create_and_list_user_as_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _role_id(seeded_db, "accounting")
    resp = await client.post(
        "/users",
        json={"email": "yeni@t.co", "password": "parola1234", "full_name": "Yeni Kullanıcı",
              "role_id": rid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "yeni@t.co"
    assert "password" not in body and "password_hash" not in body

    listing = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert listing.status_code == 200
    assert any(u["email"] == "yeni@t.co" for u in listing.json())


async def test_create_user_forbidden_for_non_admin(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "patron")  # user_management=none
    rid = await _role_id(seeded_db, "accounting")
    resp = await client.post(
        "/users",
        json={"email": "z@t.co", "password": "parola1234", "full_name": "Z", "role_id": rid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_reset_password_admin_only(client, user_factory, seeded_db):
    admin_token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="t@t.co", password="parola1234", role_key="site_chief")
    resp = await client.patch(
        f"/users/{target.id}/password",
        json={"new_password": "yeniParola9"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


async def test_delete_user_admin_only(client, user_factory):
    admin_token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="d@t.co", password="parola1234", role_key="accounting")
    resp = await client.delete(
        f"/users/{target.id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 204
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_users_api.py -v`
Expected: FAIL — route yok (404) / import hatası.

- [ ] **Step 3: Router yaz**

```python
# app/modules/users/router.py
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.users import repository, service
from app.modules.users.schemas import PasswordReset, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=list[UserResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_users_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserResponse]:
    users = await repository.list_users(session)
    return [UserResponse.model_validate(u) for u in users]


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_user_endpoint(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    return UserResponse.model_validate(user)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def create_user_endpoint(
    data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await service.create_user(session, data)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def update_user_endpoint(
    user_id: uuid.UUID,
    data: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await service.update_user(session, user_id, data)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def reset_password_endpoint(
    user_id: uuid.UUID,
    data: PasswordReset,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.set_user_password(session, user_id, data.new_password)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def delete_user_endpoint(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.delete_user(session, user_id)
```

- [ ] **Step 4: Router'ı kaydet**

```python
# app/main.py
from app.modules.users.router import router as users_router
app.include_router(users_router)
```

- [ ] **Step 5: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_users_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app/modules/users/router.py app/main.py tests/modules/test_users_api.py
git commit -m "feat: kullanici yonetimi uclari (CRUD + parola sifirlama)"
```

---

## Task 10: Kullanıcı proje-erişimi atama ucu (Tüm Projeler + liste)

**Files:**
- Create: `tests/modules/test_user_project_access_api.py`
- Modify: `app/modules/users/schemas.py` (`ProjectAccessInput`, `ProjectAccessResponse`), `app/modules/users/repository.py` (`replace_project_access`, `get_project_access`), `app/modules/users/service.py` (`set_project_access`), `app/modules/users/router.py` (`PUT`/`GET /users/{id}/project-access`)
- Test: `tests/modules/test_user_project_access_api.py`

**Interfaces:**
- Consumes: `UserProjectAccess`, `repository.get_user`, `require_permission`
- Produces:
  - `schemas:ProjectAccessInput` (`all_projects: bool`, `project_ids: list[uuid.UUID] = []`)
  - `schemas:ProjectAccessResponse` (`all_projects: bool`, `project_ids: list[uuid.UUID]`)
  - `service:set_project_access(session, user_id, data)` — kullanıcı yoksa 404; `all_projects=True` ise tek satır (project_id=None), aksi hâlde her proje için bir satır (eskiler silinir/replace)
  - `PUT /users/{id}/project-access` → `ProjectAccessResponse` (full) · `GET /users/{id}/project-access` → `ProjectAccessResponse` (view)

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_user_project_access_api.py
async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_set_all_projects_access(client, user_factory, project_factory):
    token = await _login(client, user_factory, "system_admin")
    target = await user_factory(email="u@t.co", password="parola1234", role_key="patron")
    resp = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": True, "project_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["all_projects"] is True


async def test_set_specific_projects_then_replace(client, user_factory, project_factory):
    token = await _login(client, user_factory, "system_admin")
    p1 = await project_factory("GK-A")
    p2 = await project_factory("MERKEZ-1")
    target = await user_factory(email="s@t.co", password="parola1234", role_key="site_chief")

    r1 = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": False, "project_ids": [str(p1.id), str(p2.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    assert set(r1.json()["project_ids"]) == {str(p1.id), str(p2.id)}

    # replace: yalnizca p1 kalmali
    r2 = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": False, "project_ids": [str(p1.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.json()["project_ids"] == [str(p1.id)]


async def test_project_access_forbidden_for_non_admin(client, user_factory):
    token = await _login(client, user_factory, "accounting")
    target = await user_factory(email="t@t.co", password="parola1234", role_key="site_chief")
    resp = await client.put(
        f"/users/{target.id}/project-access",
        json={"all_projects": True, "project_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_user_project_access_api.py -v`
Expected: FAIL — route yok.

- [ ] **Step 3: Schema ekle**

```python
# app/modules/users/schemas.py — ekle
class ProjectAccessInput(BaseModel):
    all_projects: bool = False
    project_ids: list[uuid.UUID] = Field(default_factory=list)


class ProjectAccessResponse(BaseModel):
    all_projects: bool
    project_ids: list[uuid.UUID]
```

- [ ] **Step 4: Repository ekle**

```python
# app/modules/users/repository.py — ekle
from sqlalchemy import delete
from app.modules.users.models import UserProjectAccess


async def get_project_access(session: AsyncSession, user_id: uuid.UUID) -> list[UserProjectAccess]:
    result = await session.execute(
        select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
    )
    return list(result.scalars().all())


async def replace_project_access(
    session: AsyncSession,
    user_id: uuid.UUID,
    all_projects: bool,
    project_ids: list[uuid.UUID],
) -> list[UserProjectAccess]:
    await session.execute(
        delete(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
    )
    rows: list[UserProjectAccess] = []
    if all_projects:
        rows.append(UserProjectAccess(user_id=user_id, project_id=None, all_projects=True))
    else:
        rows = [
            UserProjectAccess(user_id=user_id, project_id=pid, all_projects=False)
            for pid in project_ids
        ]
    for row in rows:
        session.add(row)
    await session.flush()
    return rows
```

- [ ] **Step 5: Service ekle**

```python
# app/modules/users/service.py — ekle
from app.modules.users.schemas import ProjectAccessInput
from app.modules.users.models import UserProjectAccess


async def set_project_access(
    session: AsyncSession, user_id: uuid.UUID, data: ProjectAccessInput
) -> list[UserProjectAccess]:
    user = await repository.get_user(session, user_id)
    if user is None:
        raise NotFoundError("Kullanıcı bulunamadı")
    return await repository.replace_project_access(
        session, user_id, data.all_projects, data.project_ids
    )
```

- [ ] **Step 6: Router ekle**

```python
# app/modules/users/router.py — ekle (importlara ProjectAccessInput, ProjectAccessResponse ekle)
@router.put(
    "/{user_id}/project-access",
    response_model=ProjectAccessResponse,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def set_project_access_endpoint(
    user_id: uuid.UUID,
    data: ProjectAccessInput,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectAccessResponse:
    rows = await service.set_project_access(session, user_id, data)
    all_projects = any(r.all_projects for r in rows)
    project_ids = [r.project_id for r in rows if r.project_id is not None]
    return ProjectAccessResponse(all_projects=all_projects, project_ids=project_ids)


@router.get(
    "/{user_id}/project-access",
    response_model=ProjectAccessResponse,
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_project_access_endpoint(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectAccessResponse:
    rows = await repository.get_project_access(session, user_id)
    all_projects = any(r.all_projects for r in rows)
    project_ids = [r.project_id for r in rows if r.project_id is not None]
    return ProjectAccessResponse(all_projects=all_projects, project_ids=project_ids)
```

- [ ] **Step 7: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_user_project_access_api.py -v`
Expected: PASS (3 passed).

- [ ] **Step 8: Commit**

```bash
git add app/modules/users/ tests/modules/test_user_project_access_api.py
git commit -m "feat: kullanici proje-erisimi atama ucu (tum projeler + liste)"
```

---

## Task 11: Roles schemas + repository genişletmeleri (matris okuma + özel rol)

**Files:**
- Create: `app/modules/roles/schemas.py`, `tests/modules/test_roles_repository.py`
- Modify: `app/modules/roles/repository.py` (`list_roles`, `get_role`, `list_modules`, `get_role_matrix`, `create_custom_role`, `delete_role`), `app/modules/roles/service.py` (`create_custom_role`, `delete_role`)
- Test: `tests/modules/test_roles_repository.py`

**Interfaces:**
- Consumes: `Role`, `Module`, `RolePermission`, `MATRIX` yok — yeni rol tüm modüllerde `none/all` başlar; `SYSTEM_ADMIN_KEY`, `NotFoundError`, `PermissionLockedError`
- Produces:
  - `schemas:RoleResponse` (id·key·name·emoji·description·is_system), `RoleCreate` (key·name·emoji·description), `RoleRename` (name·emoji·description), `ModuleResponse` (id·key·name·group·sort_order), `PermissionCell` (module_key·access_level·scope), `PermissionUpdate` (access_level·scope)
  - `repository:list_roles`, `get_role`, `list_modules`, `get_role_matrix(session, role_id) -> list[(Module, RolePermission)]`
  - `service:create_custom_role(session, data: RoleCreate) -> Role` — key çakışırsa `DomainError`; `is_system=False`; 13 modül için `none/all` izin satırı üretir
  - `service:delete_role(session, role_id) -> None` — yoksa `NotFoundError`; `is_system=True` ise `PermissionLockedError`

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_roles_repository.py
import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import DomainError, NotFoundError, PermissionLockedError
from app.modules.roles.models import Role, RolePermission
from app.modules.roles.schemas import RoleCreate
from app.modules.roles import repository, service


async def test_create_custom_role_seeds_full_matrix(seeded_db):
    role = await service.create_custom_role(
        seeded_db, RoleCreate(key="saha_amiri", name="Saha Amiri", emoji="🚧", description="")
    )
    assert role.is_system is False
    count = (
        await seeded_db.execute(
            select(func.count()).select_from(RolePermission).where(RolePermission.role_id == role.id)
        )
    ).scalar_one()
    assert count == 13  # her modul icin bir hucre (none/all)


async def test_create_custom_role_duplicate_key_raises(seeded_db):
    with pytest.raises(DomainError):
        await service.create_custom_role(
            seeded_db, RoleCreate(key="patron", name="X", emoji="", description="")
        )


async def test_delete_system_role_locked(seeded_db):
    sysadmin = (
        await seeded_db.execute(select(Role).where(Role.key == "system_admin"))
    ).scalar_one()
    with pytest.raises(PermissionLockedError):
        await service.delete_role(seeded_db, sysadmin.id)


async def test_delete_unknown_role_raises(seeded_db):
    with pytest.raises(NotFoundError):
        await service.delete_role(seeded_db, uuid.uuid4())


async def test_get_role_matrix_returns_all_modules(seeded_db):
    patron = (await seeded_db.execute(select(Role).where(Role.key == "patron"))).scalar_one()
    matrix = await repository.get_role_matrix(seeded_db, patron.id)
    assert len(matrix) == 13
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_roles_repository.py -v`
Expected: FAIL — `cannot import name 'RoleCreate'` / `create_custom_role` yok.

- [ ] **Step 3: Schemas yaz**

```python
# app/modules/roles/schemas.py
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.core.access import AccessLevel, Scope
from app.modules.roles.models import ModuleGroup


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    name: str
    emoji: str
    description: str
    is_system: bool


class RoleCreate(BaseModel):
    key: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default="", max_length=8)
    description: str = Field(default="", max_length=2000)


class RoleRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default="", max_length=8)
    description: str = Field(default="", max_length=2000)


class ModuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    name: str
    group: ModuleGroup
    sort_order: int


class PermissionCell(BaseModel):
    module_key: str
    access_level: AccessLevel
    scope: Scope


class PermissionUpdate(BaseModel):
    access_level: AccessLevel
    scope: Scope
```

- [ ] **Step 4: Repository genişlet**

```python
# app/modules/roles/repository.py — ekle
from app.modules.roles.models import Role


async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    return list(result.scalars().all())


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    return await session.get(Role, role_id)


async def list_modules(session: AsyncSession) -> list[Module]:
    result = await session.execute(select(Module).order_by(Module.sort_order))
    return list(result.scalars().all())


async def get_role_matrix(
    session: AsyncSession, role_id: uuid.UUID
) -> list[tuple[Module, RolePermission]]:
    stmt = (
        select(Module, RolePermission)
        .join(RolePermission, RolePermission.module_id == Module.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Module.sort_order)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]
```

- [ ] **Step 5: Service genişlet**

```python
# app/modules/roles/service.py — ekle (importlara DomainError, NotFoundError, AccessLevel, Scope, Module)
from app.core.access import AccessLevel, Scope
from app.core.errors import DomainError, NotFoundError, PermissionLockedError
from app.modules.roles.models import Module, Role, RolePermission
from app.modules.roles.schemas import RoleCreate


async def create_custom_role(session: AsyncSession, data: RoleCreate) -> Role:
    existing = (
        await session.execute(select(Role).where(Role.key == data.key))
    ).scalar_one_or_none()
    if existing is not None:
        raise DomainError("Bu rol anahtarı zaten kullanılıyor")

    role = Role(
        key=data.key, name=data.name, emoji=data.emoji,
        description=data.description, is_system=False,
    )
    session.add(role)
    await session.flush()

    modules = (await session.execute(select(Module))).scalars().all()
    for module in modules:
        session.add(
            RolePermission(
                role_id=role.id, module_id=module.id,
                access_level=AccessLevel.none, scope=Scope.all,
            )
        )
    await session.flush()
    return role


async def delete_role(session: AsyncSession, role_id: uuid.UUID) -> None:
    role = (
        await session.execute(select(Role).where(Role.id == role_id))
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    if role.is_system:
        raise PermissionLockedError("Sistem rolleri silinemez")
    await session.delete(role)  # role_permissions CASCADE ile silinir
    await session.flush()
```

- [ ] **Step 6: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_roles_repository.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/modules/roles/schemas.py app/modules/roles/repository.py app/modules/roles/service.py tests/modules/test_roles_repository.py
git commit -m "feat: rol schema/repository ve ozel rol olustur/sil servisi"
```

---

## Task 12: Roles router — Rol Yönetimi + İzin Matrisi (F4)

**Files:**
- Create: `app/modules/roles/router.py`, `tests/modules/test_roles_api.py`
- Modify: `app/main.py` (roles router'ı kaydet)
- Test: `tests/modules/test_roles_api.py`

**Interfaces:**
- Consumes: `repository`, `service`, `schemas`, `update_role_permission` (Task 2'de 404 semantiğine geçti), `require_permission`, `NotFoundError`
- Produces (hepsi `user_management` kapılı):
  - `GET /roles` → `list[RoleResponse]` (view)
  - `GET /modules` → `list[ModuleResponse]` (view)
  - `GET /roles/{id}/permissions` → `list[PermissionCell]` (view) | 404
  - `POST /roles` → `RoleResponse` 201 (full)
  - `PATCH /roles/{id}` → `RoleResponse` (full) — rename
  - `PUT /roles/{id}/permissions/{module_key}` → `PermissionCell` (full) — system_admin 403, satır yoksa 404
  - `DELETE /roles/{id}` → 204 (admin) — sistem rolü 403

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/modules/test_roles_api.py
from sqlalchemy import select

from app.modules.roles.models import Role


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def _rid(session, key):
    return str((await session.execute(select(Role).where(Role.key == key))).scalar_one().id)


async def test_list_roles_and_modules(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    roles = await client.get("/roles", headers=h)
    assert roles.status_code == 200 and len(roles.json()) == 8
    modules = await client.get("/modules", headers=h)
    assert modules.status_code == 200 and len(modules.json()) == 13


async def test_update_permission_cell(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "site_chief")
    resp = await client.put(
        f"/roles/{rid}/permissions/dashboard",
        json={"access_level": "full", "scope": "all"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_level"] == "full"


async def test_update_system_admin_cell_locked(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "system_admin")
    resp = await client.put(
        f"/roles/{rid}/permissions/dashboard",
        json={"access_level": "view", "scope": "all"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_update_permission_unknown_module_404(client, user_factory, seeded_db):
    token = await _login(client, user_factory, "site_chief")  # once bir rol lazim degil; admin gerek
    admin = await _login(client, user_factory, "system_admin")
    rid = await _rid(seeded_db, "patron")
    resp = await client.put(
        f"/roles/{rid}/permissions/olmayan_modul",
        json={"access_level": "view", "scope": "all"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 404


async def test_create_and_delete_custom_role(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    h = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/roles",
        json={"key": "saha_amiri", "name": "Saha Amiri", "emoji": "🚧", "description": ""},
        headers=h,
    )
    assert created.status_code == 201
    new_id = created.json()["id"]
    deleted = await client.delete(f"/roles/{new_id}", headers=h)
    assert deleted.status_code == 204


async def test_roles_forbidden_for_non_admin(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.get("/roles", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Run: `python -m pytest tests/modules/test_roles_api.py -v`
Expected: FAIL — route yok.

- [ ] **Step 3: Router yaz**

```python
# app/modules/roles/router.py
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.roles import repository, service
from app.modules.roles.schemas import (
    ModuleResponse,
    PermissionCell,
    PermissionUpdate,
    RoleCreate,
    RoleRename,
    RoleResponse,
)
from app.modules.roles.service import update_role_permission

router = APIRouter(tags=["roles"])


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_roles_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[RoleResponse]:
    return [RoleResponse.model_validate(r) for r in await repository.list_roles(session)]


@router.get(
    "/modules",
    response_model=list[ModuleResponse],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def list_modules_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ModuleResponse]:
    return [ModuleResponse.model_validate(m) for m in await repository.list_modules(session)]


@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[PermissionCell],
    dependencies=[require_permission("user_management", AccessLevel.view)],
)
async def get_role_permissions_endpoint(
    role_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PermissionCell]:
    if await repository.get_role(session, role_id) is None:
        raise NotFoundError("Rol bulunamadı")
    matrix = await repository.get_role_matrix(session, role_id)
    return [
        PermissionCell(module_key=module.key, access_level=perm.access_level, scope=perm.scope)
        for module, perm in matrix
    ]


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def create_role_endpoint(
    data: RoleCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    return RoleResponse.model_validate(await service.create_custom_role(session, data))


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def rename_role_endpoint(
    role_id: uuid.UUID,
    data: RoleRename,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    if await repository.get_role(session, role_id) is None:
        raise NotFoundError("Rol bulunamadı")
    role = await service.rename_role(session, role_id, data.name, data.emoji, data.description)
    return RoleResponse.model_validate(role)


@router.put(
    "/roles/{role_id}/permissions/{module_key}",
    response_model=PermissionCell,
    dependencies=[require_permission("user_management", AccessLevel.full)],
)
async def update_permission_endpoint(
    role_id: uuid.UUID,
    module_key: str,
    data: PermissionUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionCell:
    # system_admin -> PermissionLockedError(403); satir/rol yok -> NotFoundError(404)
    perm = await update_role_permission(
        session, role_id, module_key, data.access_level, data.scope
    )
    return PermissionCell(module_key=module_key, access_level=perm.access_level, scope=perm.scope)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("user_management", AccessLevel.admin)],
)
async def delete_role_endpoint(
    role_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await service.delete_role(session, role_id)
```

> Not: `rename_role` mevcut servis fonksiyonu (`app/modules/roles/service.py`), `key`'e asla dokunmaz.

- [ ] **Step 4: Router'ı kaydet**

```python
# app/main.py
from app.modules.roles.router import router as roles_router
app.include_router(roles_router)
```

- [ ] **Step 5: Testlerin geçtiğini doğrula**

Run: `python -m pytest tests/modules/test_roles_api.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add app/modules/roles/router.py app/main.py tests/modules/test_roles_api.py
git commit -m "feat: rol yonetimi ve izin matrisi uclari (F4)"
```

---

## Task 13: Faz kapanışı — kapsam, lint, migration zinciri ve inceleme

**Files:**
- Modify: gerekiyorsa küçük düzeltmeler; yeni kod yok
- Test: tüm suite

**Interfaces:**
- Produces: Yeşil suite · ≥%80 kapsam · temiz ruff · doğrulanmış migration zinciri · temiz güvenlik/fastapi incelemesi · güncel OpenAPI

- [ ] **Step 1: Tüm testler + kapsam**

Run: `python -m pytest --cov=app --cov-report=term-missing`
Expected: PASS — tüm testler geçer, kapsam ≥ %80. Düşükse eksik dalları (negatif izin, 404, replace) test ekleyerek kapat — testi silerek değil.

- [ ] **Step 2: Lint + format**

Run: `python -m ruff check . && python -m ruff format --check .`
Expected: temiz.

- [ ] **Step 3: Migration zincirini sıfırdan doğrula (`TEST_DATABASE_URL`)**

Run: `DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head` (boş şemada); sonra `alembic downgrade base && alembic upgrade head`.
Expected: hatasız. `projects` seed → 3 satır; enum'lar (`project_status`) downgrade'de düşer; `upgrade head` tekrarında `DuplicateObject` YOK.

- [ ] **Step 4: Güvenlik incelemesi**

`security-reviewer` ajanını yeni uçlar için çalıştır (auth kapıları, parola sıfırlama, yetki eşikleri, yanıt gövdesinde sızıntı yok). CRITICAL/HIGH bulgu kalmayana dek düzelt.

- [ ] **Step 5: FastAPI incelemesi**

`fastapi-reviewer` ajanını çalıştır (async doğruluğu, DI, response_model, şema ayrımı). CRITICAL/HIGH kalmaz.

- [ ] **Step 6: OpenAPI üret + doğrula**

Run: `python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi()))"`
Expected: `/users`, `/roles`, `/modules`, `/projects` uçları görünür. (Frontend F4 bu şemadan tip üretecek — o oturumda `pnpm gen:api` hatırlatılır.)

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "chore: B3 faz kapanisi - kapsam, lint, migration ve inceleme"
```

---

## Faz sonu kabul kriterleri

Aşağıdakilerin **hepsi** doğru olmadan B3 bitmiş sayılmaz:

- [ ] `python -m pytest --cov=app` → tüm testler geçer, kapsam ≥ %80
- [ ] `python -m ruff check .` ve `ruff format --check .` → temiz
- [ ] `alembic upgrade head` boş veritabanında hatasız çalışır; `downgrade base && upgrade head` hatasız (enum'lar açıkça düşer)
- [ ] Veritabanında hâlâ tam olarak 8 rol, 13 modül, 104 izin satırı var (matrise modül eklenmedi); `projects` seed 3 satır
- [ ] Döngüsel import yapısal kırıldı: `app.core.permissions` fonksiyon-içi domain import'u içermiyor; `python -c "import app.main"` temiz
- [ ] `update_role_permission`: system_admin → 403 (PermissionLockedError); özel rol/olmayan modül/olmayan rol → 404 (NotFoundError)
- [ ] Kullanıcı uçları: oluştur/güncelle `full`, parola sıfırlama + silme `admin`, listeleme/görüntüleme `view` — hepsi `user_management` kapılı; `patron` gibi roller 403 alır (negatif testler mevcut ve geçiyor)
- [ ] Hiçbir yanıt gövdesinde `password`, `password_hash` veya token yok
- [ ] Proje-erişimi: `all_projects=True` tek satır (project_id null); aksi hâlde liste; PUT replace çalışıyor
- [ ] Rol/izin-matrisi uçları F4'ü karşılıyor: `GET /roles` (8), `GET /modules` (13), izin hücresi düzenleme, özel rol oluştur/sil (sistem rolü 403)
- [ ] `security-reviewer` ve `fastapi-reviewer` → CRITICAL/HIGH bulgu yok
- [ ] `/docs` (OpenAPI) açılıyor ve yeni uçları gösteriyor — frontend F4'ün tip üreteceği kaynak burası
