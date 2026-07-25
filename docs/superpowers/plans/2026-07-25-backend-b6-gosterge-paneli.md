# B6 — Gösterge Paneli uçları: uygulama planı

> **Ajan işçiler için:** ZORUNLU ALT-SKILL: Bu planı task-by-task uygulamak için
> `superpowers:subagent-driven-development` (önerilen) veya `superpowers:executing-plans`
> kullanın. Adımlar takip için checkbox (`- [ ]`) söz dizimindedir.

**Hedef:** Gösterge paneli ekranının ihtiyaç duyduğu tek okuma ucunu (`GET /dashboard/summary`) yazmak.

**Mimari:** Yeni `app/modules/dashboard/` paketi; router → service → mevcut repository'ler. Yeni tablo ve migration yok. Projeler `user_project_access` üzerinden süzülür; veri kaynağı olmayan beş kart için sabit yer tutucu üretilir.

**Teknoloji:** FastAPI · SQLAlchemy 2 (async) · Pydantic v2 · pytest-asyncio · ruff

**Spec:** `docs/superpowers/specs/2026-07-25-backend-b6-gosterge-paneli-design.md`

## Küresel kısıtlar

- Python **PATH'te yok**. Daima `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/alembic` kullan. PATH'teki global ruff (0.8.6) yanlış pozitif verir; `pyproject.toml` `ruff==0.15.22`'ye sabitli.
- Testler **asla** `backend/.env` içindeki `TEST_DATABASE_URL`'e koşturulmaz — o uzak Railway host'unu gösteriyor ve conftest ona `drop_all` uyguluyor. Lokal `postgresql@18` (port 5432) üzerinde tek kullanımlık DB aç, `TEST_DATABASE_URL` ile yönlendir, iş bitince düşür.
- Saat dilimi tek kaynak: `app/core/timezone.py`. UTC gösterilmez.
- Yeni migration **yazılmaz**. Bu faz salt okuma.
- Yanıt metinleri Türkçe; hata mesajı biçimi mevcut uçlarla aynı (`"Bu işlem için yetkiniz yok"`).
- Denetim günlüğü kaydı **yazılmaz** (B5 yalnızca yazma işlemlerini kaydeder).
- Commit mesajları: `<type>: <açıklama>`, Türkçe, ASCII (mevcut geçmişle tutarlı).

## Dosya yapısı

| Dosya | Sorumluluk |
|---|---|
| `app/modules/dashboard/__init__.py` | paket |
| `app/modules/dashboard/schemas.py` | `MetricPlaceholder`, `ListPlaceholder`, `PendingApprovalsPlaceholder`, `DashboardProjectCard`, `DashboardSummaryResponse` |
| `app/modules/dashboard/service.py` | kapsam süzgeci + yer tutucu üretimi + özet birleştirme |
| `app/modules/dashboard/router.py` | tek uç, izin kapısı |
| `app/modules/projects/repository.py` (değişir) | `list_projects_for_user` eklenir |
| `app/main.py` (değişir) | `dashboard_router` kaydı |
| `tests/modules/test_dashboard_repository.py` | kapsam süzgeci birim testleri |
| `tests/modules/test_dashboard_service.py` | servis birim testleri |
| `tests/modules/test_dashboard_api.py` | şema + uç testleri |

`app/modules/dashboard/repository.py` **yok** — veri erişimi ilgili modülün kendi repository'sinde kalır.

## İzin matrisi gerçekleri (test rolleri için)

`app/modules/roles/seed_data.py:140` → `"dashboard": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N]`
`ROLE_ORDER` = `system_admin, patron, site_chief, field_engineer, hr_manager, accounting, project_manager, procurement`

Yani: `patron` → `full` (izinli), `procurement` → `none` (**403 testi için doğru rol**).

---

## Task 1: Kapsam süzgeci sorgusu

**Dosyalar:**
- Değiştir: `app/modules/projects/repository.py`
- Test: `tests/modules/test_dashboard_repository.py` (yeni)

**Arayüzler:**
- Tüketir: `Project` (`app/modules/projects/models.py`), `UserProjectAccess` (`app/modules/users/models.py`)
- Üretir: `async def list_projects_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Project]` — Task 3 bunu çağırır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_dashboard_repository.py`:

```python
import uuid

from app.modules.projects.repository import list_projects_for_user
from app.modules.users.models import UserProjectAccess


async def test_all_projects_user_sees_every_project(db_session, project_factory):
    await project_factory("GK-A", name="Güneşkent A-Blok")
    await project_factory("OSB-1", name="Çelik OSB Fabrika")
    user_id = uuid.uuid4()
    db_session.add(UserProjectAccess(user_id=user_id, project_id=None, all_projects=True))
    await db_session.flush()

    projects = await list_projects_for_user(db_session, user_id)

    assert [p.code for p in projects] == ["GK-A", "OSB-1"]


async def test_limited_user_sees_only_granted_projects(db_session, project_factory):
    granted = await project_factory("GK-A")
    await project_factory("OSB-1")
    user_id = uuid.uuid4()
    db_session.add(
        UserProjectAccess(user_id=user_id, project_id=granted.id, all_projects=False)
    )
    await db_session.flush()

    projects = await list_projects_for_user(db_session, user_id)

    assert [p.code for p in projects] == ["GK-A"]


async def test_user_without_access_rows_sees_nothing(db_session, project_factory):
    await project_factory("GK-A")

    projects = await list_projects_for_user(db_session, uuid.uuid4())

    assert projects == []
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_repository.py -v`
Beklenen: FAIL — `ImportError: cannot import name 'list_projects_for_user'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/projects/repository.py` başına import ekle:

```python
from app.modules.users.models import UserProjectAccess
```

Dosyanın sonuna ekle:

```python
async def list_projects_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Project]:
    """Kullanicinin user_project_access satirlarina gore gorunur projeler.

    all_projects=True satiri varsa tumu doner; yoksa yalnizca verilen project_id'ler.
    Hic satir yoksa bos liste. Siralama code artan.
    """
    access_rows = (
        (
            await session.execute(
                select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    if not access_rows:
        return []

    if any(row.all_projects for row in access_rows):
        return await list_projects(session)

    project_ids = [row.project_id for row in access_rows if row.project_id is not None]
    if not project_ids:
        return []

    result = await session.execute(
        select(Project).where(Project.id.in_(project_ids)).order_by(Project.code)
    )
    return list(result.scalars().all())
```

Not: import döngüsü riski yoktur — `app/modules/users/models.py` `projects` modülünü
içe aktarmaz. Ruff bir döngü bildirirse importu fonksiyon gövdesine taşı ve nedeni
commit mesajına yaz.

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_repository.py -v`
Beklenen: 3 PASS

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`
Beklenen: temiz. Değilse `.venv/bin/ruff format app tests` çalıştır.

- [ ] **Adım 6: Commit**

```bash
git add app/modules/projects/repository.py tests/modules/test_dashboard_repository.py
git commit -m "feat: kullanici bazli proje kapsam suzgeci"
```

---

## Task 2: Yanıt şemaları

**Dosyalar:**
- Oluştur: `app/modules/dashboard/__init__.py` (boş)
- Oluştur: `app/modules/dashboard/schemas.py`
- Test: `tests/modules/test_dashboard_api.py` (yeni; bu task'ta yalnızca şema testleri)

**Arayüzler:**
- Tüketir: `ProjectStatus` (`app/modules/projects/models.py`)
- Üretir: `DashboardSummaryResponse`, `DashboardProjectCard`, `MetricPlaceholder`, `ListPlaceholder`, `PendingApprovalsPlaceholder` — Task 3 ve 4 bunları kullanır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_dashboard_api.py`:

```python
from decimal import Decimal

from app.modules.dashboard.schemas import (
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)


def test_metric_placeholder_defaults_to_unavailable():
    metric = MetricPlaceholder(pending_module="progress_payments")

    assert metric.available is False
    assert metric.value is None
    assert metric.pending_module == "progress_payments"


def test_pending_approvals_placeholder_has_zero_count():
    placeholder = PendingApprovalsPlaceholder(pending_module="approvals")

    assert placeholder.available is False
    assert placeholder.count == 0
    assert placeholder.items == []


def test_summary_serializes_decimal_project_fields():
    summary = DashboardSummaryResponse(
        role_name="Patron",
        active_project_count=1,
        projects=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "code": "GK-A",
                "name": "Güneşkent A-Blok",
                "status": "active",
                "budget": Decimal("1500000.00"),
                "progress_pct": Decimal("42.50"),
            }
        ],
        portfolio=MetricPlaceholder(pending_module="progress_payments"),
        receivables=MetricPlaceholder(pending_module="invoicing"),
        average_margin=MetricPlaceholder(pending_module="progress_payments"),
        pending_approvals=PendingApprovalsPlaceholder(pending_module="approvals"),
        risks=ListPlaceholder(pending_module="inventory"),
    )

    dumped = summary.model_dump(mode="json")

    assert dumped["projects"][0]["budget"] == "1500000.00"
    assert dumped["risks"]["available"] is False
    assert dumped["risks"]["items"] == []
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_api.py -v`
Beklenen: FAIL — `ModuleNotFoundError: No module named 'app.modules.dashboard'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/dashboard/__init__.py` — boş dosya.

`app/modules/dashboard/schemas.py`:

```python
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.projects.models import ProjectStatus


class MetricPlaceholder(BaseModel):
    """Tek degerli KPI karti. v1'de veri kaynagi olmayan kartlar icin.

    available alani bilincli olarak vardir: frontend sabite degil veriye dallanir,
    ilgili alt-proje geldiginde backend true dondurmeye baslar (spec §2.3).
    """

    available: bool = False
    value: Decimal | None = None
    pending_module: str


class ListPlaceholder(BaseModel):
    """Liste tipli kart (risk uyarilari)."""

    available: bool = False
    items: list[str] = Field(default_factory=list)
    pending_module: str


class PendingApprovalsPlaceholder(ListPlaceholder):
    """Onay bekleyenler karti — rozet sayaci tasir."""

    count: int = 0


class DashboardProjectCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    budget: Decimal
    progress_pct: Decimal


class DashboardSummaryResponse(BaseModel):
    role_name: str
    active_project_count: int
    projects: list[DashboardProjectCard]
    portfolio: MetricPlaceholder
    receivables: MetricPlaceholder
    average_margin: MetricPlaceholder
    pending_approvals: PendingApprovalsPlaceholder
    risks: ListPlaceholder
```

`Field(default_factory=list)` kullanılır — çıplak `[]` varsayılanı Pydantic'te paylaşılan
liste tuzağına yol açmasa da ruff `RUF012` uyarısı verebilir.

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_api.py -v`
Beklenen: 3 PASS

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/modules/dashboard tests/modules/test_dashboard_api.py
git commit -m "feat: gosterge paneli yanit semalari"
```

---

## Task 3: Servis katmanı

**Dosyalar:**
- Oluştur: `app/modules/dashboard/service.py`
- Test: `tests/modules/test_dashboard_service.py` (yeni)

**Arayüzler:**
- Tüketir: `list_projects_for_user` (Task 1), Task 2'nin şemaları, `User` (`app/modules/users/models.py`), `Role` (`app/modules/roles/models.py`)
- Üretir: `async def build_summary(session: AsyncSession, user: User) -> DashboardSummaryResponse` — Task 4 bunu çağırır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_dashboard_service.py`:

```python
from app.modules.dashboard.service import build_summary
from app.modules.users.models import UserProjectAccess


async def test_summary_counts_only_active_projects(seeded_db, user_factory, project_factory):
    await project_factory("GK-A", status="active")
    await project_factory("OSB-1", status="on_hold")
    await project_factory("SAHIL-2", status="completed")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()

    summary = await build_summary(seeded_db, user)

    assert len(summary.projects) == 3
    assert summary.active_project_count == 1


async def test_summary_uses_role_display_name(seeded_db, user_factory):
    user = await user_factory(email="patron2@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.role_name == "Patron"


async def test_summary_placeholders_are_unavailable(seeded_db, user_factory):
    user = await user_factory(email="patron3@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.portfolio.pending_module == "progress_payments"
    assert summary.receivables.pending_module == "invoicing"
    assert summary.average_margin.pending_module == "progress_payments"
    assert summary.pending_approvals.pending_module == "approvals"
    assert summary.risks.pending_module == "inventory"
    assert not any(
        card.available
        for card in (
            summary.portfolio,
            summary.receivables,
            summary.average_margin,
            summary.pending_approvals,
            summary.risks,
        )
    )
    assert summary.pending_approvals.count == 0


async def test_summary_empty_when_no_project_access(seeded_db, user_factory, project_factory):
    await project_factory("GK-A")
    user = await user_factory(email="patron4@t.co", password="parola1234", role_key="patron")

    summary = await build_summary(seeded_db, user)

    assert summary.projects == []
    assert summary.active_project_count == 0
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_service.py -v`
Beklenen: FAIL — `ModuleNotFoundError: No module named 'app.modules.dashboard.service'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/dashboard/service.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.schemas import (
    DashboardProjectCard,
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)
from app.modules.projects.models import ProjectStatus
from app.modules.projects.repository import list_projects_for_user
from app.modules.roles.models import Role
from app.modules.users.models import User

# Spec §7: veri kaynagi olmayan kartlar ve bagli olduklari modul anahtarlari.
# Ilgili alt-proje geldiginde bu kartlar gercek deger dondurmeye baslar.
_PORTFOLIO_MODULE = "progress_payments"
_RECEIVABLES_MODULE = "invoicing"
_MARGIN_MODULE = "progress_payments"
_APPROVALS_MODULE = "approvals"
_RISKS_MODULE = "inventory"


async def build_summary(session: AsyncSession, user: User) -> DashboardSummaryResponse:
    """Gosterge paneli ozeti. Projeler gercek, bes kart bos durum (spec §7)."""
    projects = await list_projects_for_user(session, user.id)
    role = await session.get(Role, user.role_id)

    return DashboardSummaryResponse(
        role_name=role.name if role is not None else "",
        active_project_count=sum(1 for p in projects if p.status is ProjectStatus.active),
        projects=[DashboardProjectCard.model_validate(p) for p in projects],
        portfolio=MetricPlaceholder(pending_module=_PORTFOLIO_MODULE),
        receivables=MetricPlaceholder(pending_module=_RECEIVABLES_MODULE),
        average_margin=MetricPlaceholder(pending_module=_MARGIN_MODULE),
        pending_approvals=PendingApprovalsPlaceholder(pending_module=_APPROVALS_MODULE),
        risks=ListPlaceholder(pending_module=_RISKS_MODULE),
    )
```

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_service.py -v`
Beklenen: 4 PASS

`test_summary_uses_role_display_name` başarısız olursa `app/modules/roles/seed_data.py`
içindeki `patron` rolünün `name` alanını oku ve beklenen değeri ona göre düzelt —
uygulamayı değil testi düzelt, çünkü görünen ad seed'in kararıdır.

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/modules/dashboard/service.py tests/modules/test_dashboard_service.py
git commit -m "feat: gosterge paneli ozet servisi"
```

---

## Task 4: Uç ve izin kapısı

**Dosyalar:**
- Oluştur: `app/modules/dashboard/router.py`
- Değiştir: `app/main.py` (import bloğu + `include_router` bloğu, satır 62-68 civarı)
- Test: `tests/modules/test_dashboard_api.py` (Task 2'de oluşturuldu; uç testleri eklenir)

**Arayüzler:**
- Tüketir: `build_summary` (Task 3), `DashboardSummaryResponse` (Task 2), `require_permission`, `get_current_user`, `get_db`
- Üretir: `router` (`APIRouter`, prefix `/dashboard`) — `app/main.py` bunu kaydeder.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_dashboard_api.py` sonuna ekle (dosyanın başındaki mevcut
import bloğuna `from app.modules.users.models import UserProjectAccess` satırını da ekle):

```python
async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


async def test_summary_requires_authentication(client):
    resp = await client.get("/dashboard/summary")
    assert resp.status_code == 401


async def test_summary_forbidden_without_dashboard_permission(client, user_factory):
    # seed_data.py:140 -> dashboard satirinda procurement = none
    token = await _login(client, user_factory, "procurement")
    resp = await client.get(
        "/dashboard/summary", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_summary_returns_projects_for_permitted_role(
    client, db_session, user_factory, project_factory
):
    await project_factory("GK-A", name="Güneşkent A-Blok", status="active")
    await project_factory("OSB-1", name="Çelik OSB Fabrika", status="on_hold")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "patron@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/dashboard/summary", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [p["code"] for p in body["projects"]] == ["GK-A", "OSB-1"]
    assert body["active_project_count"] == 1
    assert body["role_name"] == "Patron"
    assert body["portfolio"]["available"] is False
    assert body["pending_approvals"]["count"] == 0
    assert "password_hash" not in resp.text


async def test_summary_empty_state_is_not_an_error(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.get(
        "/dashboard/summary", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["projects"] == []
    assert resp.json()["active_project_count"] == 0
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_api.py -v`
Beklenen: yeni 4 test FAIL (404 — rota kayıtlı değil)

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/dashboard/router.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.dashboard.schemas import DashboardSummaryResponse
from app.modules.dashboard.service import build_summary
from app.modules.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=COMMON_ERROR_RESPONSES)


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    dependencies=[require_permission("dashboard", AccessLevel.view)],
)
async def get_dashboard_summary_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardSummaryResponse:
    return await build_summary(session, user)
```

`app/main.py` import bloğuna ekle (alfabetik: `audit_router` ile `auth_router` arasına):

```python
from app.modules.dashboard.router import router as dashboard_router
```

`app/main.py:62-68` bloğuna ekle (alfabetik: `company_router` ile `projects_router` arasına):

```python
app.include_router(dashboard_router)
```

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `.venv/bin/pytest tests/modules/test_dashboard_api.py -v`
Beklenen: 7 PASS (Task 2'nin 3 şema testi + 4 uç testi)

- [ ] **Adım 5: Kapsamı doğrula**

Çalıştır: `.venv/bin/pytest --cov=app/modules/dashboard --cov-report=term-missing`
Beklenen: tüm testler PASS, `app/modules/dashboard` kapsamı ≥%80

- [ ] **Adım 6: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 7: Commit**

```bash
git add app/modules/dashboard/router.py app/main.py tests/modules/test_dashboard_api.py
git commit -m "feat: gosterge paneli ozet ucu"
```

---

## Task 5: OpenAPI üretimi ve faz kapanışı

**Dosyalar:**
- Üret: `openapi.json` (izlenmiyor, `.gitignore`'da)
- Kopyalanır: `../frontend/openapi/openapi.json`

**Arayüzler:**
- Tüketir: Task 4'ün kaydettiği rota
- Üretir: F6'nın `pnpm gen:api` ile tüketeceği güncel şema

- [ ] **Adım 1: Tüm testleri koştur**

Çalıştır: `.venv/bin/pytest`
Beklenen: tümü PASS. Herhangi biri kırıldıysa dur ve nedenini bildir — geçiştirme.

- [ ] **Adım 2: OpenAPI üret**

`backend/README.md`'deki üretim akışını izle, sonra doğrula:

```bash
grep -c "dashboard/summary" openapi.json
```

Beklenen: en az 1.

- [ ] **Adım 3: Frontend'e kopyala**

```bash
cp openapi.json ../frontend/openapi/openapi.json
```

Bu dosya frontend reposunda **izlenir**; commit'i F6 planının Task 1'inde yapılır.
Backend reposunda commit edilecek bir şey yoktur (`openapi.json` `.gitignore`'da).

- [ ] **Adım 4: Faz özetini bildir**

Kullanıcıya rapor et: koşan test sayısı, `app/modules/dashboard` kapsam yüzdesi,
ruff durumu, `openapi.json`'ın frontend'e kopyalandığı. Push/merge/deploy **yapma** —
o karar kullanıcınındır.

---

## Öz-inceleme

**Spec kapsamı:**

| Spec bölümü | Karşılayan task |
|---|---|
| §2 uç + izin kapısı | Task 4 |
| §2.1 kapsam süzgeci | Task 1 |
| §2.2 yanıt gövdesi | Task 2 (şema), Task 3 (değerler) |
| §2.3 yer tutucu sözleşmesi | Task 2, Task 3 |
| §3 yerleşim | Task 2, 3, 4 |
| §4 denetim kaydı yazılmaz | Hiçbir task `record_audit` çağırmıyor; küresel kısıtlarda belirtildi |
| §5 hatalar (401 / 403 / boş liste) | Task 4 testleri |
| §6 test tablosu | Task 1 (3 test), Task 3 (4 test), Task 4 (4 test) |
| §7 OpenAPI | Task 5 |
| §8 kapsam dışı | Hiçbir task `projects.type`, yazma ucu veya `company_assets`'e dokunmuyor |

Boşluk yok.

**Tip tutarlılığı:** `list_projects_for_user` (Task 1) → `build_summary` (Task 3) → router
(Task 4) zinciri aynı adlarla kullanılıyor. Şema adları Task 2'de tanımlanıp Task 3 ve 4'te
aynı yazımla çağrılıyor. `ListPlaceholder` Task 2'de tanımlanıp Task 3'te `risks` için
kullanılıyor; `PendingApprovalsPlaceholder` ondan türüyor ve yalnızca `count` ekliyor.
