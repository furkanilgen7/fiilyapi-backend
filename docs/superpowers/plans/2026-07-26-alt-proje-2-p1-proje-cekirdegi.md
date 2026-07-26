# Alt-Proje 2 · P1 — Proje çekirdeği: uygulama planı

> **Ajan işçiler için:** ZORUNLU ALT-SKILL: Bu planı task-by-task uygulamak için
> `superpowers:subagent-driven-development` (önerilen) veya `superpowers:executing-plans`
> kullanın. Adımlar takip için checkbox (`- [ ]`) söz dizimindedir.

**Hedef:** `projects` tablosunu Ekran 4'ün üç proje tipine genişletmek, tip uzantı tablolarını (`project_investment`, `project_land_share`, `land_share_shareholder`) kurmak, yeni `projects` izin modülünü seed'lemek ve 4 ucu (`GET` liste + detay, `POST`, `PATCH`) yazmak. Mevcut uçlar `user_management` izninden `projects` iznine taşınır.

**Mimari:** Mevcut `app/modules/projects/` paketine `service.py` eklenir; router → service → repository. Uzantı satırları `Project` üzerindeki `lazy="selectin"` ilişkilerle yüklenir. Veri kaynağı olmayan kart alanları B6 yer tutucu desenini (`available`/`value|count`/`pending_module`) kullanır. Tek migration: sütunlar + enum + 3 tablo + izin modülü.

**Teknoloji:** FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · pytest-asyncio · ruff

**Spec:** `docs/superpowers/specs/2026-07-26-alt-proje-2-p1-proje-cekirdegi-design.md`

## Küresel kısıtlar

- Python **PATH'te yok**. Daima `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/alembic` kullan. PATH'teki global ruff yanlış pozitif verir; `pyproject.toml`'daki sabitlenmiş sürüm geçerlidir.
- Testler **asla** `backend/.env` içindeki `TEST_DATABASE_URL`'e koşturulmaz — o uzak Railway host'unu gösteriyor ve conftest ona `drop_all` uyguluyor. Lokal `postgresql@18` (port 5432) üzerinde tek kullanımlık DB aç, `TEST_DATABASE_URL` env değişkeniyle yönlendir, iş bitince düşür:

  ```bash
  createdb -h localhost -p 5432 fiil_p1_test
  export TEST_DATABASE_URL="postgresql+asyncpg://localhost:5432/fiil_p1_test"
  # ... testler ...
  dropdb -h localhost -p 5432 fiil_p1_test
  ```

- Migration **yalnızca lokal DB'de** upgrade + downgrade test edilir (Task 2, Adım 6) — canlıya/Railway'e karşı **asla** `alembic upgrade` koşturulmaz.
- **Push YOK.** Commit'ler lokalde kalır; push/merge/deploy kararı kullanıcınındır.
- Saat dilimi tek kaynak: `app/core/timezone.py`. UTC gösterilmez.
- `tests/conftest.py`'deki `project_factory` yeni alanlarla güncellenir (Task 1) — tüm mevcut çağrılar (`project_factory("GK-A", name=…)`) kırılmadan çalışmaya devam etmeli.
- İzin geçişi (`user_management` → `projects`) mevcut testleri etkiler: `test_projects_api.py` (patron 403 testi tersine döner), B6 dashboard testleri, `test_seed_matrix.py` (112→120), `test_seed_migration_matches_seed_data.py` (bileşkeye yeni migration katılır). Task 2 ve 6 bunları günceller; Task 7 tam regresyon koşturur.
- Yanıt metinleri Türkçe; hata mesajı biçimi mevcut uçlarla aynı (`"Bu işlem için yetkiniz yok"`, `"Proje bulunamadı"`).
- Commit mesajları: `<type>: <açıklama>`, Türkçe, ASCII.

## Dosya yapısı

| Dosya | Sorumluluk |
|---|---|
| `alembic/versions/<rev>_p1_proje_cekirdegi.py` (yeni) | enum + sütunlar + 3 tablo + `projects` izin modülü |
| `app/modules/projects/models.py` (değişir) | `ProjectType`, yeni sütunlar, `ProjectInvestment`, `ProjectLandShare`, `LandShareShareholder`, ilişkiler |
| `app/modules/roles/seed_data.py` (değişir) | `projects` modül satırı + sort kaydırması + matris satırı |
| `app/modules/projects/schemas.py` (yeniden yazılır) | yer tutucular, kart şemaları, liste/detay/giriş şemaları |
| `app/modules/projects/service.py` (yeni) | görünürlük + sayaçlar + kart üretimi + yazma + tip korkuluğu |
| `app/modules/projects/router.py` (yeniden yazılır) | 4 uç, `projects` izni, denetim kaydı |
| `app/core/errors.py` (değişir) | `ProjectTypeMismatchError` |
| `app/core/exception_handlers.py` (değişir) | 422 handler |
| `app/modules/audit/messages.py` (değişir) | `project_created`, `project_updated` |
| `tests/conftest.py` (değişir) | `project_factory` yeni alanlar |
| `tests/modules/test_project_model.py` (genişler) | uzantı tabloları + cascade + CHECK |
| `tests/modules/test_seed_matrix.py` (değişir) | 120 hücre, 15 modül, `projects` satırı |
| `tests/modules/test_seed_migration_matches_seed_data.py` (değişir) | migration bileşkesine P1 katılır |
| `tests/modules/test_projects_schemas.py` (yeni) | şema testleri |
| `tests/modules/test_projects_service.py` (yeni) | servis testleri |
| `tests/modules/test_projects_api.py` (yeniden yazılır) | 4 ucun API testleri + izin geçişi regresyonu |

## İzin matrisi gerçekleri (test rolleri için)

Yeni satır (Task 2): `"projects": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N]` — `dashboard` satırının aynısı.
`ROLE_ORDER` = `system_admin, patron, site_chief, field_engineer, hr_manager, accounting, project_manager, procurement`.

Yani: `system_admin` → `admin` (kapsam süzgeci istisnası), `patron`/`project_manager` → `full` (yazma testleri), `site_chief` → `view` (yazma 403 testi), `procurement` → `none` (**okuma 403 testi için doğru rol**).

---

## Task 1: Modeller + migration (şema kısmı) + project_factory

**Dosyalar:**
- Değiştir: `app/modules/projects/models.py`
- Oluştur: `alembic/versions/<rev>_p1_proje_cekirdegi.py` (bu task'ta yalnız şema kısmı; seed kısmı Task 2'de aynı dosyaya eklenir — migration henüz hiçbir ortama uygulanmadığı için dosya düzenlenebilir)
- Değiştir: `tests/conftest.py` (`project_factory`)
- Test: `tests/modules/test_project_model.py` (genişler)

**Arayüzler:**
- Üretir: `ProjectType`, `Project` (yeni alanlar + `investment`/`land_share`/`shareholders` ilişkileri), `ProjectInvestment`, `ProjectLandShare`, `LandShareShareholder` — Task 3-6 bunları kullanır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_project_model.py` sonuna ekle (başa `import pytest`, `from decimal import Decimal` zaten var; `from sqlalchemy.exc import IntegrityError` ve yeni model importlarını mevcut import bloğuna ekle):

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.projects.models import (
    LandShareShareholder,
    ProjectInvestment,
    ProjectLandShare,
    ProjectType,
)


def test_project_type_values():
    assert {t.value for t in ProjectType} == {"taahhut", "kendi_yatirim", "kat_karsiligi"}


async def test_project_defaults_to_taahhut(project_factory):
    project = await project_factory("TIP-1")
    assert project.project_type is ProjectType.taahhut
    assert project.category is None
    assert project.employer_name is None


async def test_investment_extension_roundtrip(db_session, project_factory):
    project = await project_factory("KY-1", project_type="kendi_yatirim")
    db_session.add(
        ProjectInvestment(
            project_id=project.id,
            sales_target=Decimal("48200000.00"),
            land_cost=Decimal("9500000.00"),
        )
    )
    await db_session.flush()
    db_session.expire(project)

    loaded = await db_session.get(Project, project.id)

    assert loaded.investment.sales_target == Decimal("48200000.00")
    assert loaded.land_share is None
    assert loaded.shareholders == []


async def test_land_share_extension_with_shareholders(db_session, project_factory):
    project = await project_factory("KK-1", project_type="kat_karsiligi")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    db_session.add(LandShareShareholder(project_id=project.id, name="A. Yılmaz", share_pct=Decimal("60.00")))
    db_session.add(LandShareShareholder(project_id=project.id, name="B. Yılmaz", share_pct=Decimal("40.00")))
    await db_session.flush()
    db_session.expire(project)

    loaded = await db_session.get(Project, project.id)

    assert loaded.land_share.landowner_name == "Yılmaz Ailesi"
    assert [s.name for s in loaded.shareholders] == ["A. Yılmaz", "B. Yılmaz"]


async def test_land_share_pct_total_check(db_session, project_factory):
    project = await project_factory("KK-2", project_type="kat_karsiligi")
    db_session.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Test",
            our_share_pct=Decimal("70.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

`tests/conftest.py` içindeki `project_factory`'yi şu hale getir (imza geriye uyumlu — mevcut çağrılar değişmeden geçer):

```python
@pytest.fixture
def project_factory(db_session: AsyncSession):
    async def _create(
        code: str,
        name: str = "Test Proje",
        status: str = "active",
        budget: str = "1000000.00",
        progress_pct: str = "0.00",
        project_type: str = "taahhut",
        category: str | None = None,
        city: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        contract_no: str | None = None,
        contract_amount: str | None = None,
        employer_name: str | None = None,
    ) -> Project:
        project = Project(
            code=code,
            name=name,
            status=ProjectStatus(status),
            budget=Decimal(budget),
            progress_pct=Decimal(progress_pct),
            project_type=ProjectType(project_type),
            category=category,
            city=city,
            start_date=start_date,
            end_date=end_date,
            contract_no=contract_no,
            contract_amount=Decimal(contract_amount) if contract_amount is not None else None,
            employer_name=employer_name,
        )
        db_session.add(project)
        await db_session.flush()
        return project

    return _create
```

conftest import bloğuna ekle: `from datetime import date` ve `ProjectType`'ı mevcut `from app.modules.projects.models import Project, ProjectStatus` satırına ekle.

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_project_model.py -v`
Beklenen: FAIL — `ImportError: cannot import name 'ProjectType'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/projects/models.py`'yi şu hale getir (mevcut sütunlar korunur, docstring güncellenir — "salt-okunur" ifadesi artık yanlış):

```python
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    on_hold = "on_hold"
    completed = "completed"


class ProjectType(str, enum.Enum):
    """Üç iş modeli — kart düzenini ve gelir mantığını belirler (spec §3.1)."""

    taahhut = "taahhut"
    kendi_yatirim = "kendi_yatirim"
    kat_karsiligi = "kat_karsiligi"


class Project(Base):
    """Proje çekirdeği (Alt-Proje 2 · P1). budget/progress_pct F6 mirasıdır, kalır."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, default=ProjectStatus.active
    )
    project_type: Mapped[ProjectType] = mapped_column(
        Enum(ProjectType, name="project_type"),
        nullable=False,
        default=ProjectType.taahhut,
        server_default="taahhut",
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    employer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    investment: Mapped["ProjectInvestment | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    land_share: Mapped["ProjectLandShare | None"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", uselist=False
    )
    shareholders: Mapped[list["LandShareShareholder"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="LandShareShareholder.name"
    )


class ProjectInvestment(Base):
    """Kendi yatırım uzantısı (1-1). Türev alanlar (satılan, kâr…) P10'un işi."""

    __tablename__ = "project_investment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    sales_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    land_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class ProjectLandShare(Base):
    """Kat karşılığı uzantısı (1-1). Arsa maliyeti sütunu YOK — tanım gereği 0 (spec §3.3)."""

    __tablename__ = "project_land_share"
    __table_args__ = (
        CheckConstraint("our_share_pct + owner_share_pct = 100", name="ck_land_share_pct_total"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    landowner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    our_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    owner_share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    contract_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notary_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    land_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    construction_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_penalty: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    guarantee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class LandShareShareholder(Base):
    """Kat karşılığı hissedarı (1-N). Hissedar başına ünite dağılımı P9'un işi."""

    __tablename__ = "land_share_shareholder"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
```

Migration iskeletini üret:

```bash
.venv/bin/alembic revision -m "p1 proje cekirdegi"
```

Üretilen dosyada `upgrade()`/`downgrade()`'i doldur (dosya başındaki revision kimliklerine dokunma; `down_revision` `2cffc2fcfcf0` olmalı — değilse `alembic heads` ile kontrol et):

```python
import sqlalchemy as sa

from alembic import op

project_type_enum = sa.Enum(
    "taahhut", "kendi_yatirim", "kat_karsiligi", name="project_type"
)


def upgrade() -> None:
    """Upgrade schema."""
    project_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "projects",
        sa.Column("project_type", project_type_enum, server_default="taahhut", nullable=False),
    )
    op.add_column("projects", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column("projects", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column("projects", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("contract_no", sa.String(length=100), nullable=True))
    op.add_column(
        "projects", sa.Column("contract_amount", sa.Numeric(precision=18, scale=2), nullable=True)
    )
    op.add_column("projects", sa.Column("employer_name", sa.String(length=200), nullable=True))

    op.create_table(
        "project_investment",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("sales_target", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("land_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "project_land_share",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("landowner_name", sa.String(length=200), nullable=False),
        sa.Column("our_share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("owner_share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("notary_date", sa.Date(), nullable=True),
        sa.Column("land_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("construction_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("daily_penalty", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("guarantee_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.CheckConstraint(
            "our_share_pct + owner_share_pct = 100", name="ck_land_share_pct_total"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "land_share_shareholder",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_land_share_shareholder_project_id", "land_share_shareholder", ["project_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_land_share_shareholder_project_id", table_name="land_share_shareholder")
    op.drop_table("land_share_shareholder")
    op.drop_table("project_land_share")
    op.drop_table("project_investment")
    op.drop_column("projects", "employer_name")
    op.drop_column("projects", "contract_amount")
    op.drop_column("projects", "contract_no")
    op.drop_column("projects", "end_date")
    op.drop_column("projects", "start_date")
    op.drop_column("projects", "city")
    op.drop_column("projects", "category")
    op.drop_column("projects", "project_type")
    project_type_enum.drop(op.get_bind(), checkfirst=True)
```

(İzin modülü seed'i Task 2'de bu dosyaya eklenecek; upgrade/downgrade doğrulaması da orada yapılır — testler conftest'in `create_all`'u ile koşar, migration'a bağımlı değildir.)

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_project_model.py tests/modules/test_dashboard_repository.py -v`
Beklenen: tümü PASS (dashboard repository testleri ilişki eklemelerinden etkilenmemeli)

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests alembic && .venv/bin/ruff format --check app tests alembic`
Beklenen: temiz. Değilse `.venv/bin/ruff format app tests alembic`.

- [ ] **Adım 6: Commit**

```bash
git add app/modules/projects/models.py alembic/versions tests/conftest.py tests/modules/test_project_model.py
git commit -m "feat: proje tipi enum'u, yeni sutunlar ve tip uzanti tablolari"
```

---

## Task 2: Seed — `projects` izin modülü + geçiş regresyon testleri

**Dosyalar:**
- Değiştir: `app/modules/roles/seed_data.py`
- Değiştir: `alembic/versions/<rev>_p1_proje_cekirdegi.py` (Task 1'in dosyası — seed kısmı eklenir)
- Değiştir: `tests/modules/test_seed_matrix.py`
- Değiştir: `tests/modules/test_seed_migration_matches_seed_data.py`

**Arayüzler:**
- Üretir: seed'de `projects` modülü (`GENEL`, sort 3) + 8 izin satırı — Task 6'nın izin kapısı buna dayanır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_seed_matrix.py`'de:

1. `EXPECTED_MODULE_KEYS` kümesine `"projects"` ekle.
2. `test_seeds_fourteen_modules` adını `test_seeds_fifteen_modules` yap.
3. `test_matrix_is_complete` docstring'ini "8 rol × 15 modül = 120 hücre; hiçbiri eksik olamaz." yap ve `assert len(rows) == 112` → `120`. Dosyadaki diğer tüm `112` sabitlerini `120`, `== 14` modül sayımlarını `== 15` yap (`grep -n "112\|== 14" tests/modules/test_seed_matrix.py` ile tara).
4. Sona ekle:

```python
async def test_projects_module_row_and_sort(seeded_db):
    """projects: GENEL grubunda, approvals ile site_diary arasında (spec §4)."""
    modules = (await seeded_db.execute(select(Module))).scalars().all()
    by_key = {m.key: m for m in modules}
    assert by_key["projects"].group is ModuleGroup.GENEL
    assert by_key["projects"].name == "Projeler"
    assert by_key["approvals"].sort_order < by_key["projects"].sort_order
    assert by_key["projects"].sort_order < by_key["site_diary"].sort_order


async def test_projects_permissions_match_dashboard_row(seeded_db):
    """projects satiri dashboard satirinin aynisidir (spec §4 gerekce)."""
    for role_key in ("system_admin", "patron", "site_chief", "field_engineer",
                     "hr_manager", "accounting", "project_manager", "procurement"):
        assert await _level_of(seeded_db, role_key, "projects") == await _level_of(
            seeded_db, role_key, "dashboard"
        )


async def test_procurement_cannot_see_projects(seeded_db):
    assert await _level_of(seeded_db, "procurement", "projects") == AccessLevel.none
```

`tests/modules/test_seed_migration_matches_seed_data.py`'de uzantı migration'ları genelleştir:

1. Sabitlere ekle (P1 migration'ının gerçek dosya adını kullan):

```python
P1_MIGRATION_PATH = next(VERSIONS_DIR.glob("*_p1_proje_cekirdegi.py"))
EXTENSION_MIGRATION_PATHS = [INVOICING_MIGRATION_PATH, P1_MIGRATION_PATH]
```

2. `_permission_map_from_migrations` sonundaki invoicing bloğunu döngüyle değiştir:

```python
    for path in EXTENSION_MIGRATION_PATHS:
        extension = _load_migration_module(path)
        for module_key, cells in extension.MATRIX.items():
            for role_key, (level, scope) in zip(extension.ROLE_ORDER, cells, strict=True):
                result[(role_key, module_key)] = (_value(level), _value(scope))
    return result
```

3. `_modules_set_from_migrations`'ı bileşke halinde yeniden yaz:

```python
def _modules_set_from_migrations() -> set[tuple[str, str, str, int]]:
    """Ilk migration'in modul satirlari, uzanti migration'lari sirayla uygulanmis halde."""
    captured = _captured_bulk_inserts(_load_seed_migration())
    modules: dict[str, tuple[str, str, int]] = {
        row["key"]: (row["name"], _value(row["group"]), row["sort_order"])
        for row in captured["modules"]
    }
    for path in EXTENSION_MIGRATION_PATHS:
        extension = _load_migration_module(path)
        for key, sort_order in extension.SORT_ORDER_UPDATES.items():
            name, group, _ = modules[key]
            modules[key] = (name, group, sort_order)
        modules[extension.MODULE_KEY] = (
            extension.MODULE_NAME,
            extension.MODULE_GROUP,
            extension.MODULE_SORT_ORDER,
        )
    return {(key, name, group, so) for key, (name, group, so) in modules.items()}
```

4. `test_migration_permission_matrix_has_112_cells` → `_has_120_cells`, iki `112` de `120`.
5. `test_invoicing_migration_role_order_matches_seed_data` ve
   `test_invoicing_migration_downgrade_restores_previous_sort_orders` testlerini
   uzantı listesi üzerinde döngüye çevir:

```python
def test_extension_migration_role_orders_match_seed_data():
    """Sutun sirasi kaymissa izinler yanlis rollere yazilir — sessiz yetki sizintisi."""
    for path in EXTENSION_MIGRATION_PATHS:
        extension = _load_migration_module(path)
        assert list(extension.ROLE_ORDER) == list(app_seed_data.ROLE_ORDER)


def test_extension_migration_downgrades_restore_previous_sort_orders():
    """Her uzanti migration'inin PREVIOUS_SORT_ORDERS'i kendinden onceki bileskeye esit olmali."""
    captured = _captured_bulk_inserts(_load_seed_migration())
    current = {row["key"]: row["sort_order"] for row in captured["modules"]}
    for path in EXTENSION_MIGRATION_PATHS:
        extension = _load_migration_module(path)
        assert extension.PREVIOUS_SORT_ORDERS == {
            key: current[key] for key in extension.SORT_ORDER_UPDATES
        }
        current.update(extension.SORT_ORDER_UPDATES)
        current[extension.MODULE_KEY] = extension.MODULE_SORT_ORDER
```

6. `test_migration_module_keys_match_seed_data` içindeki `{invoicing.MODULE_KEY}` birleşimini uzantı döngüsüne çevir:

```python
def test_migration_module_keys_match_seed_data():
    migration = _load_seed_migration()
    keys = set(migration.MODULE_IDS.keys())
    for path in EXTENSION_MIGRATION_PATHS:
        keys.add(_load_migration_module(path).MODULE_KEY)
    assert keys == {row["key"] for row in app_seed_data.MODULES}
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_seed_matrix.py tests/modules/test_seed_migration_matches_seed_data.py -v`
Beklenen: FAIL — seed'de `projects` yok (KeyError/eksik anahtar/120≠112)

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/roles/seed_data.py`:

1. Modül docstring'indeki "112 izin satırı" → "120 izin satırı", `seed_reference_data` docstring'indeki "8 rol, 14 modül ve 112 izin satırı" → "8 rol, 15 modül ve 120 izin satırı".
2. `MODULES` listesinde `approvals`'tan hemen sonra ekle ve sonraki TÜM satırların `sort_order`'ını +1 kaydır (site_diary 4, timesheet 5, personnel 6, payroll 7, inventory 8, procurement 9, progress_payments 10, accounting 11, invoicing 12, treasury 13, settings 14, user_management 15):

```python
    {"key": "projects", "name": "Projeler", "group": ModuleGroup.GENEL, "sort_order": 3},
```

3. `MATRIX`'e `"approvals"` satırından hemen sonra ekle:

```python
    # dashboard satirinin aynisi: proje kartlari ayni gorunurluk yuzeyi,
    # asil suzgec user_project_access (spec §4).
    "projects": [_A, _F, _LIM, _LIM, _LIM, _FIN, _F, _N],
```

Task 1'in migration dosyasına, `2cffc2fcfcf0` (invoicing) migration'ındaki idempotent SQL desenini birebir izleyen seed kısmını ekle — modül düzeyi sabitler + `upgrade()`/`downgrade()` uçlarına çağrılar:

```python
import uuid

MODULE_KEY = "projects"
MODULE_NAME = "Projeler"
MODULE_GROUP = "GENEL"
MODULE_SORT_ORDER = 3

# projects 3'e girdigi icin sonrasindaki tum moduller birer kayar.
SORT_ORDER_UPDATES: dict[str, int] = {
    "site_diary": 4,
    "timesheet": 5,
    "personnel": 6,
    "payroll": 7,
    "inventory": 8,
    "procurement": 9,
    "progress_payments": 10,
    "accounting": 11,
    "invoicing": 12,
    "treasury": 13,
    "settings": 14,
    "user_management": 15,
}

# downgrade()'in geri yazacagi degerler (2cffc2fcfcf0 sonrasi bileske).
PREVIOUS_SORT_ORDERS: dict[str, int] = {
    "site_diary": 3,
    "timesheet": 4,
    "personnel": 5,
    "payroll": 6,
    "inventory": 7,
    "procurement": 8,
    "progress_payments": 9,
    "accounting": 10,
    "invoicing": 11,
    "treasury": 12,
    "settings": 13,
    "user_management": 14,
}

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

# dashboard satirinin aynisi (seed_data.MATRIX["projects"] ile birebir;
# esitligi tests/modules/test_seed_migration_matches_seed_data.py dogrular).
MATRIX: dict[str, list[tuple[str, str]]] = {
    MODULE_KEY: [
        ("admin", "all"),
        ("full", "all"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "limited"),
        ("view", "finance"),
        ("full", "all"),
        ("none", "all"),
    ],
}

_INSERT_MODULE = sa.text(
    'INSERT INTO modules (id, key, name, "group", sort_order) '
    "VALUES (CAST(:id AS uuid), :key, :name, CAST(:group AS module_group), :sort_order) "
    "ON CONFLICT (key) DO NOTHING"
)

_INSERT_PERMISSION = sa.text(
    "INSERT INTO role_permissions (id, role_id, module_id, access_level, scope) "
    "SELECT CAST(:id AS uuid), r.id, m.id, "
    "CAST(:access_level AS access_level), CAST(:scope AS scope) "
    "FROM roles r, modules m "
    "WHERE r.key = :role_key AND m.key = :module_key "
    "ON CONFLICT ON CONSTRAINT uq_role_module DO NOTHING"
)

_UPDATE_SORT_ORDER = sa.text("UPDATE modules SET sort_order = :sort_order WHERE key = :key")

_DELETE_PERMISSIONS = sa.text(
    "DELETE FROM role_permissions WHERE module_id IN (SELECT id FROM modules WHERE key = :key)"
)

_DELETE_MODULE = sa.text("DELETE FROM modules WHERE key = :key")


def _apply_sort_orders(orders: dict[str, int]) -> None:
    for key, sort_order in orders.items():
        op.execute(_UPDATE_SORT_ORDER.bindparams(key=key, sort_order=sort_order))


def _seed_projects_module() -> None:
    op.execute(
        _INSERT_MODULE.bindparams(
            id=str(uuid.uuid4()),
            key=MODULE_KEY,
            name=MODULE_NAME,
            group=MODULE_GROUP,
            sort_order=MODULE_SORT_ORDER,
        )
    )
    _apply_sort_orders(SORT_ORDER_UPDATES)
    for role_key, (access_level, scope) in zip(ROLE_ORDER, MATRIX[MODULE_KEY], strict=True):
        op.execute(
            _INSERT_PERMISSION.bindparams(
                id=str(uuid.uuid4()),
                role_key=role_key,
                module_key=MODULE_KEY,
                access_level=access_level,
                scope=scope,
            )
        )


def _unseed_projects_module() -> None:
    op.execute(_DELETE_PERMISSIONS.bindparams(key=MODULE_KEY))
    op.execute(_DELETE_MODULE.bindparams(key=MODULE_KEY))
    _apply_sort_orders(PREVIOUS_SORT_ORDERS)
```

`upgrade()` sonuna `_seed_projects_module()`, `downgrade()` başına
`_unseed_projects_module()` çağrısı ekle.

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_seed_matrix.py tests/modules/test_seed_migration_matches_seed_data.py tests/modules/test_permission_model.py -v`
Beklenen: tümü PASS

- [ ] **Adım 5: Migration'ı lokal DB'de doğrula (canlıya ASLA)**

```bash
createdb -h localhost -p 5432 fiil_p1_migration
DATABASE_URL="postgresql+asyncpg://localhost:5432/fiil_p1_migration" .venv/bin/alembic upgrade head
DATABASE_URL="postgresql+asyncpg://localhost:5432/fiil_p1_migration" .venv/bin/alembic downgrade -1
DATABASE_URL="postgresql+asyncpg://localhost:5432/fiil_p1_migration" .venv/bin/alembic upgrade head
psql -h localhost -p 5432 -d fiil_p1_migration -c \
  "SELECT count(*) FROM role_permissions; SELECT key, sort_order FROM modules ORDER BY sort_order; SELECT code, project_type FROM projects;"
dropdb -h localhost -p 5432 fiil_p1_migration
```

Beklenen: 120 izin satırı; `projects` sort_order 3, `user_management` 15; 3 seed projesi `taahhut`.

- [ ] **Adım 6: Lint**

Çalıştır: `.venv/bin/ruff check app tests alembic && .venv/bin/ruff format --check app tests alembic`

- [ ] **Adım 7: Commit**

```bash
git add app/modules/roles/seed_data.py alembic/versions tests/modules/test_seed_matrix.py tests/modules/test_seed_migration_matches_seed_data.py
git commit -m "feat: projects izin modulu ve 8 rol izin satiri"
```

---

## Task 3: Yanıt/giriş şemaları

**Dosyalar:**
- Yeniden yaz: `app/modules/projects/schemas.py`
- Test: `tests/modules/test_projects_schemas.py` (yeni)

**Arayüzler:**
- Tüketir: `ProjectStatus`, `ProjectType` (Task 1)
- Üretir: `MetricPlaceholder`, `CountPlaceholder`, `ContractingCard`, `InvestmentCard`, `ShareholderResponse`, `LandShareCard`, `ProjectCounts`, `ProjectListItem`, `ProjectDetailResponse`, `ProjectListResponse`, `ProjectInvestmentInput`, `ShareholderInput`, `ProjectLandShareInput`, `ProjectCreate`, `ProjectUpdate` — Task 4-6 bunları kullanır. Eski `ProjectResponse` silinir (tek tüketicisi `projects/router.py`, Task 6'da yeniden yazılıyor).

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_projects_schemas.py`:

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.projects.schemas import (
    CountPlaceholder,
    MetricPlaceholder,
    ProjectCreate,
    ProjectLandShareInput,
    ProjectUpdate,
)


def test_metric_placeholder_defaults_to_unavailable():
    metric = MetricPlaceholder(pending_module="progress_payments")
    assert metric.available is False
    assert metric.value is None


def test_count_placeholder_defaults_to_unavailable():
    counter = CountPlaceholder(pending_module="timesheet")
    assert counter.available is False
    assert counter.count is None


def test_land_share_input_rejects_pct_not_summing_to_100():
    with pytest.raises(ValidationError):
        ProjectLandShareInput(
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("70.00"),
            owner_share_pct=Decimal("45.00"),
        )


def test_land_share_input_accepts_valid_pcts():
    data = ProjectLandShareInput(
        landowner_name="Yılmaz Ailesi",
        our_share_pct=Decimal("55.00"),
        owner_share_pct=Decimal("45.00"),
        shareholders=[{"name": "A. Yılmaz", "share_pct": Decimal("60.00")}],
    )
    assert data.shareholders[0].name == "A. Yılmaz"


def test_project_create_minimal_taahhut():
    data = ProjectCreate(code="GK-C", name="Güneşkent C-Blok", project_type="taahhut")
    assert data.status.value == "active"
    assert data.investment is None
    assert data.land_share is None


def test_project_update_has_no_project_type_field():
    """Tip is modelidir, PATCH ile degistirilemez (spec §3.5)."""
    assert "project_type" not in ProjectUpdate.model_fields
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_schemas.py -v`
Beklenen: FAIL — `ImportError: cannot import name 'MetricPlaceholder'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/projects/schemas.py`'yi şu hale getir (eski `ProjectResponse` silinir):

```python
import uuid
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.projects.models import ProjectStatus, ProjectType

# --- B6 yer tutucu deseni (dashboard spec §2.3; bu ekran icin spec §5.3) ---


class MetricPlaceholder(BaseModel):
    """Veri kaynagi henuz yazilmamis tek degerli alan. Sahte rakam yerine durust bos durum."""

    available: bool = False
    value: Decimal | None = None
    pending_module: str


class CountPlaceholder(BaseModel):
    """Veri kaynagi henuz yazilmamis sayac alani ("48 isci", "3 hissedar" gibi)."""

    available: bool = False
    count: int | None = None
    pending_module: str


# --- Tip kartlari (spec §5.3) ---


class ContractingCard(BaseModel):
    """Taahhut karti — sozlesme bedeli/isveren ustte gercek, gerisi bos durum."""

    spent: MetricPlaceholder
    physical_progress: MetricPlaceholder
    final_progress_payment: MetricPlaceholder
    worker_count: CountPlaceholder
    subcontractor_count: CountPlaceholder


class InvestmentCard(BaseModel):
    sales_target: Decimal | None
    land_cost: Decimal | None
    sold_amount: MetricPlaceholder
    sales_ratio: MetricPlaceholder
    unit_summary: CountPlaceholder
    total_cost: MetricPlaceholder
    estimated_profit: MetricPlaceholder
    margin: MetricPlaceholder


class ShareholderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    share_pct: Decimal


class LandShareCard(BaseModel):
    landowner_name: str
    our_share_pct: Decimal
    owner_share_pct: Decimal
    land_cost: Decimal  # daima 0 — tanim geregi, saklanmaz (spec §3.3)
    contract_no: str | None
    notary_date: date | None
    land_area_m2: Decimal | None
    construction_area_m2: Decimal | None
    delivery_date: date | None
    daily_penalty: Decimal | None
    guarantee_amount: Decimal | None
    shareholder_count: int
    shareholders: list[ShareholderResponse]
    our_unit_count: CountPlaceholder
    owner_unit_count: CountPlaceholder
    our_share_value: MetricPlaceholder
    construction_cost: MetricPlaceholder
    estimated_profit: MetricPlaceholder
    margin: MetricPlaceholder
    construction_progress: MetricPlaceholder


# --- Liste/detay yanitlari ---


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    project_type: ProjectType
    category: str | None
    city: str | None
    status: ProjectStatus
    start_date: date | None
    end_date: date | None
    contract_no: str | None
    contract_amount: Decimal | None
    employer_name: str | None
    budget: Decimal
    progress_pct: Decimal
    contracting: ContractingCard | None
    investment: InvestmentCard | None
    land_share: LandShareCard | None


class ProjectDetailResponse(ProjectListItem):
    pass


class ProjectCounts(BaseModel):
    all: int
    taahhut: int
    kendi_yatirim: int
    kat_karsiligi: int
    completed: int


class ProjectListResponse(BaseModel):
    counts: ProjectCounts
    items: list[ProjectListItem]


# --- Giris semalari ---


class ProjectInvestmentInput(BaseModel):
    sales_target: Decimal | None = Field(default=None, ge=0)
    land_cost: Decimal | None = Field(default=None, ge=0)


class ShareholderInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    share_pct: Decimal = Field(gt=0, le=100)


class ProjectLandShareInput(BaseModel):
    landowner_name: str = Field(min_length=1, max_length=200)
    our_share_pct: Decimal = Field(gt=0, lt=100)
    owner_share_pct: Decimal = Field(gt=0, lt=100)
    contract_no: str | None = Field(default=None, max_length=100)
    notary_date: date | None = None
    land_area_m2: Decimal | None = Field(default=None, ge=0)
    construction_area_m2: Decimal | None = Field(default=None, ge=0)
    delivery_date: date | None = None
    daily_penalty: Decimal | None = Field(default=None, ge=0)
    guarantee_amount: Decimal | None = Field(default=None, ge=0)
    shareholders: list[ShareholderInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _pct_total_must_be_100(self) -> Self:
        if self.our_share_pct + self.owner_share_pct != 100:
            msg = "Pay yüzdelerinin toplamı 100 olmalıdır"
            raise ValueError(msg)
        return self


class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    project_type: ProjectType
    status: ProjectStatus = ProjectStatus.active
    category: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    contract_no: str | None = Field(default=None, max_length=100)
    contract_amount: Decimal | None = Field(default=None, ge=0)
    employer_name: str | None = Field(default=None, max_length=200)
    investment: ProjectInvestmentInput | None = None
    land_share: ProjectLandShareInput | None = None


class ProjectUpdate(BaseModel):
    """project_type YOK — tip PATCH ile degistirilemez (spec §3.5)."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    status: ProjectStatus | None = None
    category: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    contract_no: str | None = Field(default=None, max_length=100)
    contract_amount: Decimal | None = Field(default=None, ge=0)
    employer_name: str | None = Field(default=None, max_length=200)
    investment: ProjectInvestmentInput | None = None
    land_share: ProjectLandShareInput | None = None
```

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_schemas.py -v`
Beklenen: 6 PASS

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/modules/projects/schemas.py tests/modules/test_projects_schemas.py
git commit -m "feat: proje liste/detay/giris semalari ve yer tutucular"
```

---

## Task 4: Servis — okuma yolu (görünürlük, sayaçlar, kart üretimi)

**Dosyalar:**
- Oluştur: `app/modules/projects/service.py`
- Test: `tests/modules/test_projects_service.py` (yeni)

**Arayüzler:**
- Tüketir: `list_projects`, `list_projects_for_user`, `get_project` (repository, mevcut); `get_permission` (`app/modules/roles/repository.py`); Task 3 şemaları
- Üretir: `list_projects_overview(session, actor, type_filter, status_filter) -> ProjectListResponse`, `get_project_detail(session, actor, project_id) -> ProjectDetailResponse`, `to_detail(project) -> ProjectDetailResponse` — Task 5-6 bunları kullanır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_projects_service.py`:

```python
from decimal import Decimal

import pytest

from app.core.errors import NotFoundError
from app.modules.projects.models import LandShareShareholder, ProjectLandShare
from app.modules.projects.service import get_project_detail, list_projects_overview
from app.modules.users.models import UserProjectAccess


async def _grant_all(seeded_db, user) -> None:
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()


async def test_counts_ignore_filters(seeded_db, user_factory, project_factory):
    await project_factory("T-1", project_type="taahhut", status="active")
    await project_factory("T-2", project_type="taahhut", status="completed")
    await project_factory("KY-1", project_type="kendi_yatirim", status="active")
    await project_factory("KK-1", project_type="kat_karsiligi", status="active")
    user = await user_factory(email="p@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    result = await list_projects_overview(
        seeded_db, user, type_filter="taahhut", status_filter=None
    )

    assert [p.code for p in result.items] == ["T-1", "T-2"]
    assert result.counts.all == 4
    assert result.counts.taahhut == 2
    assert result.counts.kendi_yatirim == 1
    assert result.counts.kat_karsiligi == 1
    assert result.counts.completed == 1


async def test_status_filter_selects_completed(seeded_db, user_factory, project_factory):
    await project_factory("T-1", status="active")
    await project_factory("T-2", status="completed")
    user = await user_factory(email="p2@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    result = await list_projects_overview(
        seeded_db, user, type_filter=None, status_filter="completed"
    )

    assert [p.code for p in result.items] == ["T-2"]
    assert result.counts.all == 2


async def test_scope_filter_limits_non_admin(seeded_db, user_factory, project_factory):
    granted = await project_factory("T-1")
    await project_factory("T-2")
    user = await user_factory(email="p3@t.co", password="parola1234", role_key="patron")
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await seeded_db.flush()

    result = await list_projects_overview(seeded_db, user, type_filter=None, status_filter=None)

    assert [p.code for p in result.items] == ["T-1"]
    assert result.counts.all == 1


async def test_admin_bypasses_scope_filter(seeded_db, user_factory, project_factory):
    """Ayarlar kilitlenme korumasi: erisim satiri olmayan system_admin her seyi gorur (spec §5.2)."""
    await project_factory("T-1")
    await project_factory("T-2")
    admin = await user_factory(email="a@t.co", password="parola1234", role_key="system_admin")

    result = await list_projects_overview(seeded_db, admin, type_filter=None, status_filter=None)

    assert [p.code for p in result.items] == ["T-1", "T-2"]


async def test_taahhut_item_has_contracting_placeholders(seeded_db, user_factory, project_factory):
    await project_factory(
        "T-1",
        project_type="taahhut",
        category="Konut",
        city="Ankara",
        employer_name="Güneşkent A.Ş.",
        contract_amount="11200000.00",
    )
    user = await user_factory(email="p4@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    item = (await list_projects_overview(seeded_db, user, None, None)).items[0]

    assert item.investment is None
    assert item.land_share is None
    assert item.contract_amount == Decimal("11200000.00")
    assert item.contracting.spent.available is False
    assert item.contracting.spent.pending_module == "progress_payments"
    assert item.contracting.worker_count.pending_module == "timesheet"
    assert item.contracting.subcontractor_count.pending_module == "subcontracts"


async def test_land_share_item_is_real_where_data_exists(seeded_db, user_factory, project_factory):
    project = await project_factory("KK-1", project_type="kat_karsiligi")
    seeded_db.add(
        ProjectLandShare(
            project_id=project.id,
            landowner_name="Yılmaz Ailesi",
            our_share_pct=Decimal("55.00"),
            owner_share_pct=Decimal("45.00"),
        )
    )
    for name in ("A. Yılmaz", "B. Yılmaz", "C. Yılmaz"):
        seeded_db.add(
            LandShareShareholder(project_id=project.id, name=name, share_pct=Decimal("33.33"))
        )
    await seeded_db.flush()
    user = await user_factory(email="p5@t.co", password="parola1234", role_key="patron")
    await _grant_all(seeded_db, user)

    item = (await list_projects_overview(seeded_db, user, None, None)).items[0]

    assert item.contracting is None
    assert item.land_share.landowner_name == "Yılmaz Ailesi"
    assert item.land_share.our_share_pct == Decimal("55.00")
    assert item.land_share.land_cost == Decimal("0")
    assert item.land_share.shareholder_count == 3
    assert item.land_share.construction_cost.pending_module == "project_costs"
    assert item.land_share.our_unit_count.pending_module == "units"


async def test_detail_outside_visible_set_raises_not_found(
    seeded_db, user_factory, project_factory
):
    hidden = await project_factory("T-1")
    user = await user_factory(email="p6@t.co", password="parola1234", role_key="patron")

    with pytest.raises(NotFoundError):
        await get_project_detail(seeded_db, user, hidden.id)
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_service.py -v`
Beklenen: FAIL — `ModuleNotFoundError: No module named 'app.modules.projects.service'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/projects/service.py`:

```python
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.errors import NotFoundError
from app.modules.projects import repository
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    ContractingCard,
    CountPlaceholder,
    InvestmentCard,
    LandShareCard,
    MetricPlaceholder,
    ProjectCounts,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    ShareholderResponse,
)
from app.modules.roles.repository import get_permission
from app.modules.users.models import User

# Spec §2: bos durum alanlari ve bagli olduklari dilim anahtarlari.
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_UNITS = "units"
_PROJECT_COSTS = "project_costs"

_LAND_COST_FIXED = Decimal("0")  # kat karsiliginda tanim geregi 0 (spec §3.3)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def _contracting_card() -> ContractingCard:
    return ContractingCard(
        spent=_metric(_PROGRESS_PAYMENTS),
        physical_progress=_metric(_PROGRESS_PAYMENTS),
        final_progress_payment=_metric(_PROGRESS_PAYMENTS),
        worker_count=_count(_TIMESHEET),
        subcontractor_count=_count(_SUBCONTRACTS),
    )


def _investment_card(project: Project) -> InvestmentCard:
    investment = project.investment
    return InvestmentCard(
        sales_target=investment.sales_target if investment else None,
        land_cost=investment.land_cost if investment else None,
        sold_amount=_metric(_UNITS),
        sales_ratio=_metric(_UNITS),
        unit_summary=_count(_UNITS),
        total_cost=_metric(_PROJECT_COSTS),
        estimated_profit=_metric(_PROJECT_COSTS),
        margin=_metric(_PROJECT_COSTS),
    )


def _land_share_card(project: Project) -> LandShareCard | None:
    land_share = project.land_share
    if land_share is None:
        return None
    return LandShareCard(
        landowner_name=land_share.landowner_name,
        our_share_pct=land_share.our_share_pct,
        owner_share_pct=land_share.owner_share_pct,
        land_cost=_LAND_COST_FIXED,
        contract_no=land_share.contract_no,
        notary_date=land_share.notary_date,
        land_area_m2=land_share.land_area_m2,
        construction_area_m2=land_share.construction_area_m2,
        delivery_date=land_share.delivery_date,
        daily_penalty=land_share.daily_penalty,
        guarantee_amount=land_share.guarantee_amount,
        shareholder_count=len(project.shareholders),
        shareholders=[ShareholderResponse.model_validate(s) for s in project.shareholders],
        our_unit_count=_count(_UNITS),
        owner_unit_count=_count(_UNITS),
        our_share_value=_metric(_UNITS),
        construction_cost=_metric(_PROJECT_COSTS),
        estimated_profit=_metric(_PROJECT_COSTS),
        margin=_metric(_PROJECT_COSTS),
        construction_progress=_metric(_PROGRESS_PAYMENTS),
    )


def _to_item(project: Project) -> ProjectListItem:
    is_contracting = project.project_type is ProjectType.taahhut
    is_investment = project.project_type is ProjectType.kendi_yatirim
    is_land_share = project.project_type is ProjectType.kat_karsiligi
    base = ProjectListItem.model_validate(
        project, update={"contracting": None, "investment": None, "land_share": None}
    )
    return base.model_copy(
        update={
            "contracting": _contracting_card() if is_contracting else None,
            "investment": _investment_card(project) if is_investment else None,
            "land_share": _land_share_card(project) if is_land_share else None,
        }
    )


def to_detail(project: Project) -> ProjectDetailResponse:
    return ProjectDetailResponse(**_to_item(project).model_dump())


async def _visible_projects(session: AsyncSession, actor: User) -> list[Project]:
    """Spec §5.2: user_project_access suzgeci; projects=admin suzgeci atlar.

    Admin istisnasi Ayarlar kilitlenme korumasidir: erisim vermek icin tum
    projeleri listeleyebilmek gerekir.
    """
    permission = await get_permission(session, actor.role_id, "projects")
    if permission is not None and permission.access_level is AccessLevel.admin:
        return await repository.list_projects(session)
    return await repository.list_projects_for_user(session, actor.id)


def _counts(projects: list[Project]) -> ProjectCounts:
    return ProjectCounts(
        all=len(projects),
        taahhut=sum(1 for p in projects if p.project_type is ProjectType.taahhut),
        kendi_yatirim=sum(1 for p in projects if p.project_type is ProjectType.kendi_yatirim),
        kat_karsiligi=sum(1 for p in projects if p.project_type is ProjectType.kat_karsiligi),
        completed=sum(1 for p in projects if p.status is ProjectStatus.completed),
    )


async def list_projects_overview(
    session: AsyncSession,
    actor: User,
    type_filter: ProjectType | str | None,
    status_filter: ProjectStatus | str | None,
) -> ProjectListResponse:
    """Sayaclar filtreden ETKILENMEZ — mockup sekmeleri hep tum kumeyi sayar (spec §5.1)."""
    visible = await _visible_projects(session, actor)
    selected = visible
    if type_filter is not None:
        wanted_type = ProjectType(type_filter)
        selected = [p for p in selected if p.project_type is wanted_type]
    if status_filter is not None:
        wanted_status = ProjectStatus(status_filter)
        selected = [p for p in selected if p.status is wanted_status]
    return ProjectListResponse(
        counts=_counts(visible), items=[_to_item(p) for p in selected]
    )


async def get_project_detail(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ProjectDetailResponse:
    """Gorunur kumede olmayan proje 404 — varligi sizdirilmaz (spec §5.6)."""
    visible = await _visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return to_detail(project)
```

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_service.py -v`
Beklenen: 7 PASS

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/modules/projects/service.py tests/modules/test_projects_service.py
git commit -m "feat: proje liste servisi - gorunurluk, sayaclar, kart uretimi"
```

---

## Task 5: Servis — yazma yolu (tip korkuluğu + 422)

**Dosyalar:**
- Değiştir: `app/core/errors.py`, `app/core/exception_handlers.py`
- Değiştir: `app/modules/projects/service.py` (yazma fonksiyonları eklenir)
- Test: `tests/modules/test_projects_service.py` (genişler)

**Arayüzler:**
- Üretir: `create_project(session, data) -> Project`, `update_project(session, project_id, data) -> Project`, `ProjectTypeMismatchError` — Task 6 bunları kullanır.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_projects_service.py` sonuna ekle (import bloğuna `ProjectTypeMismatchError`'ı `app.core.errors`'tan, `create_project`, `update_project`'i `app.modules.projects.service`'ten, `ProjectCreate`, `ProjectLandShareInput`, `ProjectInvestmentInput`, `ProjectUpdate`'i `app.modules.projects.schemas`'tan ekle):

```python
async def test_create_taahhut_project(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            code="GK-C",
            name="Güneşkent C-Blok",
            project_type="taahhut",
            employer_name="Güneşkent A.Ş.",
            contract_amount=Decimal("11200000.00"),
        ),
    )
    assert project.id is not None
    assert project.investment is None
    assert project.land_share is None


async def test_create_kat_karsiligi_with_shareholders(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            code="KK-9",
            name="Bahçelievler Konut",
            project_type="kat_karsiligi",
            land_share=ProjectLandShareInput(
                landowner_name="Yılmaz Ailesi",
                our_share_pct=Decimal("55.00"),
                owner_share_pct=Decimal("45.00"),
                shareholders=[
                    {"name": "A. Yılmaz", "share_pct": Decimal("60.00")},
                    {"name": "B. Yılmaz", "share_pct": Decimal("40.00")},
                ],
            ),
        ),
    )
    assert project.land_share.our_share_pct == Decimal("55.00")
    assert [s.name for s in project.shareholders] == ["A. Yılmaz", "B. Yılmaz"]


async def test_investment_on_taahhut_raises_422_error(db_session):
    with pytest.raises(ProjectTypeMismatchError):
        await create_project(
            db_session,
            ProjectCreate(
                code="T-9",
                name="Yanlış",
                project_type="taahhut",
                investment=ProjectInvestmentInput(sales_target=Decimal("1.00")),
            ),
        )


async def test_land_share_on_kendi_yatirim_raises_422_error(db_session):
    with pytest.raises(ProjectTypeMismatchError):
        await create_project(
            db_session,
            ProjectCreate(
                code="KY-9",
                name="Yanlış",
                project_type="kendi_yatirim",
                land_share=ProjectLandShareInput(
                    landowner_name="X",
                    our_share_pct=Decimal("50.00"),
                    owner_share_pct=Decimal("50.00"),
                ),
            ),
        )


async def test_update_replaces_shareholder_list(db_session):
    project = await create_project(
        db_session,
        ProjectCreate(
            code="KK-10",
            name="Replace Testi",
            project_type="kat_karsiligi",
            land_share=ProjectLandShareInput(
                landowner_name="Yılmaz Ailesi",
                our_share_pct=Decimal("55.00"),
                owner_share_pct=Decimal("45.00"),
                shareholders=[{"name": "Eski", "share_pct": Decimal("100.00")}],
            ),
        ),
    )

    updated = await update_project(
        db_session,
        project.id,
        ProjectUpdate(
            land_share=ProjectLandShareInput(
                landowner_name="Yılmaz Ailesi",
                our_share_pct=Decimal("60.00"),
                owner_share_pct=Decimal("40.00"),
                shareholders=[
                    {"name": "Yeni 1", "share_pct": Decimal("70.00")},
                    {"name": "Yeni 2", "share_pct": Decimal("30.00")},
                ],
            )
        ),
    )

    assert updated.land_share.our_share_pct == Decimal("60.00")
    assert [s.name for s in updated.shareholders] == ["Yeni 1", "Yeni 2"]


async def test_update_common_fields_only(db_session, project_factory):
    project = await project_factory("T-5", name="Eski Ad")

    updated = await update_project(db_session, project.id, ProjectUpdate(name="Yeni Ad", city="Bursa"))

    assert updated.name == "Yeni Ad"
    assert updated.city == "Bursa"
    assert updated.code == "T-5"


async def test_update_missing_project_raises_not_found(db_session):
    import uuid as uuid_mod

    with pytest.raises(NotFoundError):
        await update_project(db_session, uuid_mod.uuid4(), ProjectUpdate(name="X"))
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_service.py -v`
Beklenen: yeni testler FAIL — `ImportError: cannot import name 'ProjectTypeMismatchError'`

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/core/errors.py` sonuna ekle:

```python
class ProjectTypeMismatchError(DomainError):
    """Tip uzantısı proje tipiyle uyuşmuyor (Alt-Proje 2 P1 spec §3.5) — 422."""
```

`app/core/exception_handlers.py`'a handler ekle (import bloğuna `ProjectTypeMismatchError`; `register_exception_handlers` içinde `NotFoundError` kaydından sonra, genel `DomainError`'dan önce):

```python
async def _project_type_mismatch_handler(
    request: Request, exc: ProjectTypeMismatchError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )
```

```python
    app.add_exception_handler(ProjectTypeMismatchError, _project_type_mismatch_handler)
```

`app/modules/projects/service.py` sonuna ekle (import bloğuna `ProjectTypeMismatchError`, `LandShareShareholder`, `ProjectInvestment`, `ProjectLandShare`, `ProjectCreate`, `ProjectUpdate`, `ProjectInvestmentInput`, `ProjectLandShareInput`):

```python
def _ensure_type_consistency(
    project_type: ProjectType,
    investment: ProjectInvestmentInput | None,
    land_share: ProjectLandShareInput | None,
) -> None:
    """Spec §3.5 korkulugu. Tek yazma yolu burasi oldugu icin kontrol tek noktada."""
    if investment is not None and project_type is not ProjectType.kendi_yatirim:
        raise ProjectTypeMismatchError(
            "Yatırım alanları yalnızca kendi yatırım projelerine girilebilir"
        )
    if land_share is not None and project_type is not ProjectType.kat_karsiligi:
        raise ProjectTypeMismatchError(
            "Arsa payı alanları yalnızca kat karşılığı projelerine girilebilir"
        )


def _apply_investment(project: Project, data: ProjectInvestmentInput) -> None:
    if project.investment is None:
        project.investment = ProjectInvestment(project_id=project.id)
    project.investment.sales_target = data.sales_target
    project.investment.land_cost = data.land_cost


def _apply_land_share(project: Project, data: ProjectLandShareInput) -> None:
    if project.land_share is None:
        project.land_share = ProjectLandShare(project_id=project.id)
    land_share = project.land_share
    land_share.landowner_name = data.landowner_name
    land_share.our_share_pct = data.our_share_pct
    land_share.owner_share_pct = data.owner_share_pct
    land_share.contract_no = data.contract_no
    land_share.notary_date = data.notary_date
    land_share.land_area_m2 = data.land_area_m2
    land_share.construction_area_m2 = data.construction_area_m2
    land_share.delivery_date = data.delivery_date
    land_share.daily_penalty = data.daily_penalty
    land_share.guarantee_amount = data.guarantee_amount
    # Hissedar listesi BUTUNUYLE degistirilir (spec §5.5) — parca parca CRUD yok.
    project.shareholders = [
        LandShareShareholder(name=s.name, share_pct=s.share_pct) for s in data.shareholders
    ]


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    _ensure_type_consistency(data.project_type, data.investment, data.land_share)
    project = Project(
        code=data.code,
        name=data.name,
        project_type=data.project_type,
        status=data.status,
        category=data.category,
        city=data.city,
        start_date=data.start_date,
        end_date=data.end_date,
        contract_no=data.contract_no,
        contract_amount=data.contract_amount,
        employer_name=data.employer_name,
    )
    session.add(project)
    await session.flush()
    if data.investment is not None:
        _apply_investment(project, data.investment)
    if data.land_share is not None:
        _apply_land_share(project, data.land_share)
    await session.flush()
    await session.refresh(project)
    return project


async def update_project(
    session: AsyncSession, project_id: uuid.UUID, data: ProjectUpdate
) -> Project:
    project = await repository.get_project(session, project_id)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    _ensure_type_consistency(project.project_type, data.investment, data.land_share)
    changes = data.model_dump(exclude_unset=True, exclude={"investment", "land_share"})
    for field, value in changes.items():
        setattr(project, field, value)
    if data.investment is not None:
        _apply_investment(project, data.investment)
    if data.land_share is not None:
        _apply_land_share(project, data.land_share)
    await session.flush()
    await session.refresh(project)
    return project
```

Not: `update_project` görünürlük kontrolü yapmaz; yazma uçları `full` izin ister
ve `full` taşıyan roller (patron, PM) örgütün tamamını yönetir. Görünürlük
kontrolü okuma yolundadır (`get_project_detail`). Bu bilinçlidir; değiştirmek
istenirse ayrı karar gerekir.

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_service.py -v`
Beklenen: 14 PASS (Task 4'ün 7'si + yeni 7)

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/core/errors.py app/core/exception_handlers.py app/modules/projects/service.py tests/modules/test_projects_service.py
git commit -m "feat: proje yazma servisi ve tip tutarliligi korkulugu"
```

---

## Task 6: Router — 4 uç, izin geçişi, denetim kaydı

**Dosyalar:**
- Yeniden yaz: `app/modules/projects/router.py`
- Değiştir: `app/modules/audit/messages.py`
- Yeniden yaz: `tests/modules/test_projects_api.py`

**Arayüzler:**
- Tüketir: Task 4-5 servis fonksiyonları, Task 3 şemaları, `require_permission`, `get_current_user`, `get_db`, `record_audit`, `client_ip`
- Üretir: `/projects` uçları `projects` izniyle — `app/main.py` kaydı mevcut, değişmez.

- [ ] **Adım 1: Başarısız testi yaz**

`tests/modules/test_projects_api.py`'yi şu hale getir (eski içerik tamamen değişir — patron 403 testi bilinçli olarak tersine döner, spec §5.4):

```python
import uuid

from sqlalchemy import select

from app.modules.audit.models import AuditAction, AuditLog
from app.modules.users.models import UserProjectAccess


async def _login(client, user_factory, role_key: str) -> str:
    await user_factory(email=f"{role_key}@t.co", password="parola1234", role_key=role_key)
    resp = await client.post(
        "/auth/login", json={"email": f"{role_key}@t.co", "password": "parola1234"}
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_list_projects_unauthenticated(client):
    resp = await client.get("/projects")
    assert resp.status_code == 401


async def test_list_projects_forbidden_for_procurement(client, user_factory):
    """seed: projects satirinda procurement = none."""
    token = await _login(client, user_factory, "procurement")
    resp = await client.get("/projects", headers=_auth(token))
    assert resp.status_code == 403


async def test_system_admin_without_access_rows_sees_all(client, user_factory, project_factory):
    """KRITIK GECIS REGRESYONU (spec §5.4): Ayarlar'daki kullanici-proje erisim
    ekrani bu ucu tuketir; erisim satiri olmayan system_admin tum projeleri gormeli."""
    await project_factory("GK-A", name="Güneşkent A-Blok")
    await project_factory("OSB-1", name="Çelik OSB Fabrika")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get("/projects", headers=_auth(token))

    assert resp.status_code == 200
    assert [p["code"] for p in resp.json()["items"]] == ["GK-A", "OSB-1"]
    assert "password_hash" not in resp.text


async def test_patron_now_allowed_and_scoped(client, db_session, user_factory, project_factory):
    """Eski test patron'a 403 bekliyordu (user_management kapisi); artik projects=full."""
    granted = await project_factory("GK-A")
    await project_factory("OSB-1")
    user = await user_factory(email="patron@t.co", password="parola1234", role_key="patron")
    db_session.add(UserProjectAccess(user_id=user.id, project_id=granted.id, all_projects=False))
    await db_session.flush()
    login = await client.post(
        "/auth/login", json={"email": "patron@t.co", "password": "parola1234"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/projects", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert [p["code"] for p in body["items"]] == ["GK-A"]
    assert body["counts"]["all"] == 1


async def test_list_filters_and_counts(client, user_factory, project_factory):
    await project_factory("T-1", project_type="taahhut", status="active")
    await project_factory("KY-1", project_type="kendi_yatirim", status="completed")
    token = await _login(client, user_factory, "system_admin")

    resp = await client.get("/projects?type=taahhut", headers=_auth(token))

    body = resp.json()
    assert [p["code"] for p in body["items"]] == ["T-1"]
    assert body["counts"] == {
        "all": 2, "taahhut": 1, "kendi_yatirim": 1, "kat_karsiligi": 0, "completed": 1,
    }


async def test_get_project_not_found(client, user_factory):
    token = await _login(client, user_factory, "system_admin")
    resp = await client.get(f"/projects/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


async def test_create_forbidden_for_view_level(client, user_factory):
    """site_chief projects=view tasir; POST full ister."""
    token = await _login(client, user_factory, "site_chief")
    resp = await client.post(
        "/projects",
        json={"code": "X-1", "name": "X", "project_type": "taahhut"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_create_kat_karsiligi_and_audit(client, db_session, user_factory):
    token = await _login(client, user_factory, "patron")

    resp = await client.post(
        "/projects",
        json={
            "code": "KK-1",
            "name": "Bahçelievler Konut",
            "project_type": "kat_karsiligi",
            "category": "Konut",
            "city": "Ankara",
            "land_share": {
                "landowner_name": "Yılmaz Ailesi",
                "our_share_pct": "55.00",
                "owner_share_pct": "45.00",
                "shareholders": [
                    {"name": "A. Yılmaz", "share_pct": "60.00"},
                    {"name": "B. Yılmaz", "share_pct": "40.00"},
                ],
            },
        },
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["project_type"] == "kat_karsiligi"
    assert body["land_share"]["landowner_name"] == "Yılmaz Ailesi"
    assert body["land_share"]["land_cost"] == "0"
    assert body["land_share"]["shareholder_count"] == 2
    assert body["land_share"]["our_unit_count"]["pending_module"] == "units"
    assert body["contracting"] is None
    assert body["investment"] is None

    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.create)))
        .scalars()
        .all()
    )
    assert any("Bahçelievler Konut" in row.detail for row in audit_rows)


async def test_create_type_mismatch_returns_422(client, user_factory):
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/projects",
        json={
            "code": "T-9",
            "name": "Yanlış",
            "project_type": "taahhut",
            "investment": {"sales_target": "1.00"},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_create_duplicate_code_returns_409(client, user_factory, project_factory):
    await project_factory("GK-A")
    token = await _login(client, user_factory, "patron")
    resp = await client.post(
        "/projects",
        json={"code": "GK-A", "name": "Kopya", "project_type": "taahhut"},
        headers=_auth(token),
    )
    assert resp.status_code == 409


async def test_patch_updates_and_audits(client, db_session, user_factory, project_factory):
    project = await project_factory("T-1", name="Eski Ad")
    token = await _login(client, user_factory, "project_manager")

    resp = await client.patch(
        f"/projects/{project.id}", json={"name": "Yeni Ad"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Yeni Ad"
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == AuditAction.update)))
        .scalars()
        .all()
    )
    assert any("Yeni Ad" in row.detail for row in audit_rows)


async def test_patch_ignores_project_type(client, user_factory, project_factory):
    """ProjectUpdate'te alan yok — gonderilirse sessizce yok sayilir (extra alan)."""
    project = await project_factory("T-2", project_type="taahhut")
    token = await _login(client, user_factory, "patron")

    resp = await client.patch(
        f"/projects/{project.id}",
        json={"project_type": "kendi_yatirim", "name": "Ad"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.json()["project_type"] == "taahhut"
```

- [ ] **Adım 2: Testin başarısız olduğunu doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_api.py -v`
Beklenen: FAIL — liste zarfı yok (`items` KeyError) / POST 405 / patron 403

- [ ] **Adım 3: Asgari uygulamayı yaz**

`app/modules/audit/messages.py` sonuna ekle:

```python
def project_created(name: str) -> str:
    return f"Yeni proje oluşturuldu: {name}"


def project_updated(name: str) -> str:
    return f"Proje güncellendi: {name}"
```

`app/modules/projects/router.py`'yi şu hale getir:

```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.projects import service
from app.modules.projects.models import ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectUpdate,
)
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"], responses=COMMON_ERROR_RESPONSES)


@router.get(
    "",
    response_model=ProjectListResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def list_projects_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    type: ProjectType | None = None,
    status_filter: Annotated[ProjectStatus | None, Query(alias="status")] = None,
) -> ProjectListResponse:
    return await service.list_projects_overview(session, user, type, status_filter)


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    dependencies=[require_permission("projects", AccessLevel.view)],
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    return await service.get_project_detail(session, user, project_id)


@router.post(
    "",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("projects", AccessLevel.full)],
)
async def create_project_endpoint(
    request: Request,
    data: ProjectCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    project = await service.create_project(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.project_created(project.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return service.to_detail(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    dependencies=[require_permission("projects", AccessLevel.full)],
)
async def update_project_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: ProjectUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDetailResponse:
    project = await service.update_project(session, project_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.project_updated(project.name),
        actor_user_id=current_user.id,
        ip_address=client_ip(request),
    )
    return service.to_detail(project)
```

İki uygulama notu:

- `Query` importu: `from fastapi import APIRouter, Depends, Query, Request, status`.
- `client_ip` yardımcı fonksiyonunun import yolu için `app/modules/users/router.py`'deki mevcut importa bak ve **aynısını** kullan (`grep -n "client_ip" app/modules/users/router.py`).

- [ ] **Adım 4: Testin geçtiğini doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest tests/modules/test_projects_api.py -v`
Beklenen: 13 PASS

Not: `test_create_kat_karsiligi_and_audit` içindeki `land_cost == "0"` beklentisi
Pydantic'in `Decimal("0")` serileştirmesine bağlıdır; `"0.00"` dönerse testteki
beklentiyi gerçek çıktıya göre düzelt (ikisi de doğru — sabit sıfırdır).

- [ ] **Adım 5: Lint**

Çalıştır: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Adım 6: Commit**

```bash
git add app/modules/projects/router.py app/modules/audit/messages.py tests/modules/test_projects_api.py
git commit -m "feat: proje uclari projects iznine tasindi, yazma uclari eklendi"
```

---

## Task 7: Tam regresyon + OpenAPI üretimi + faz kapanışı

**Dosyalar:**
- Üret: `openapi.json` (izlenmiyor, `.gitignore`'da)
- Kopyalanır: `../frontend/openapi/openapi.json`

**Arayüzler:**
- Tüketir: Task 6'nın uçları
- Üretir: Ekran 4 frontend spec'inin tüketeceği güncel şema

- [ ] **Adım 1: Tüm testleri koştur (izin geçişi regresyonu)**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest`
Beklenen: tümü PASS. Özellikle izle: `test_dashboard_*` (ilişki eklemeleri +
izin değişimi), `test_user_project_access*` (Ayarlar akışı),
`test_seed_migration_matches_seed_data`, `test_auth*`. Herhangi biri kırıldıysa
dur ve nedenini bildir — geçiştirme, testi silme.

- [ ] **Adım 2: Kapsamı doğrula**

Çalıştır: `TEST_DATABASE_URL=… .venv/bin/pytest --cov=app/modules/projects --cov-report=term-missing`
Beklenen: tüm testler PASS, `app/modules/projects` kapsamı ≥%80

- [ ] **Adım 3: Lint (son)**

Çalıştır: `.venv/bin/ruff check app tests alembic && .venv/bin/ruff format --check app tests alembic`

- [ ] **Adım 4: OpenAPI üret ve doğrula**

```bash
.venv/bin/python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > openapi.json
grep -c "ProjectListResponse" openapi.json
grep -c "ProjectTypeMismatch\|kat_karsiligi" openapi.json
```

Beklenen: her grep en az 1.

- [ ] **Adım 5: Frontend'e kopyala**

```bash
cp openapi.json ../frontend/openapi/openapi.json
```

Bu dosya frontend reposunda **izlenir**; commit'i Ekran 4 frontend planının ilk
task'ında yapılır. Backend reposunda commit edilecek bir şey yoktur
(`openapi.json` `.gitignore`'da). Liste yanıtının `{counts, items}` zarfına
dönüşmesi frontend'deki kullanıcı-proje erişim ekranını `pnpm gen:api` sonrası
derleme hatasıyla görünür kılar — bu beklenen ve istenen sinyaldir (spec §5.4).

- [ ] **Adım 6: Faz özetini bildir**

Kullanıcıya rapor et: koşan test sayısı, `app/modules/projects` kapsam yüzdesi,
ruff durumu, migration'ın lokalde upgrade+downgrade doğrulandığı,
`openapi.json`'ın frontend'e kopyalandığı, izin geçişinin (patron artık
`GET /projects`'e girer) davranış değişikliği olduğu. Push/merge/deploy
**yapma** — o karar kullanıcınındır.

---

## Öz-inceleme

**Spec kapsamı:**

| Spec bölümü | Karşılayan task |
|---|---|
| §2 dürüstlük tablosu (gerçek/boş alanlar) | Task 3 (şemalar), Task 4 (üretim) |
| §3.1 sütunlar + enum | Task 1 |
| §3.2–3.4 uzantı tabloları + CHECK | Task 1 |
| §3.5 tip korkuluğu + PATCH'te tip yok | Task 5, Task 3 (`ProjectUpdate`), Task 6 (`test_patch_ignores_project_type`) |
| §4 izin modülü + matris satırı + sort 3 | Task 2 |
| §5.1 filtreler + değişmez sayaçlar | Task 4, Task 6 |
| §5.2 kapsam süzgeci + admin istisnası | Task 4 |
| §5.3 yanıt gövdesi | Task 3, Task 4 |
| §5.4 kritik geçiş + regresyon | Task 2 (seed), Task 6 (`test_system_admin_without_access_rows_sees_all`, patron testi tersine) |
| §5.5 yazma uçları + hissedar replace + denetim | Task 5, Task 6 |
| §5.6 hatalar (401/403/404/422/409) | Task 5 (422 handler), Task 6 (testler) |
| §6 tek migration + parite testi | Task 1 + Task 2 (aynı dosya), Task 2 Adım 5 (lokal upgrade/downgrade) |
| §7 test tablosu | Task 1-6 testleri, Task 7 tam koşu |
| §8 OpenAPI | Task 7 |
| §9 kapsam dışı | Hiçbir task şantiye/ünite/maliyet/silme/employers/company_assets'e dokunmuyor |
| §10 çelişki çözümleri | 1→Task 4, 2→Task 6, 4→Task 1 (docstring), 5→Task 2 |

Boşluk yok.

**Tip tutarlılığı:** `ProjectType`/`ProjectInvestment`/`ProjectLandShare`/`LandShareShareholder`
(Task 1) → şemalar (Task 3) → `list_projects_overview`/`get_project_detail`/`to_detail`
(Task 4) → `create_project`/`update_project`/`_ensure_type_consistency` (Task 5) →
router (Task 6) zinciri aynı adlarla akıyor. `MetricPlaceholder`/`CountPlaceholder`
adları B6'nın desenini izliyor; `pending_module` anahtarları
(`progress_payments`, `timesheet`, `subcontracts`, `units`, `project_costs`)
spec §2 tablosuyla birebir. Migration sabitleri (`MODULE_KEY`, `SORT_ORDER_UPDATES`,
`PREVIOUS_SORT_ORDERS`, `MATRIX`) invoicing migration'ının parite testinin beklediği
arayüzü birebir taşıyor (Task 2'nin genelleştirilmiş testi ikisini de okuyor).
