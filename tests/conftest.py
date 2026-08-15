from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base, get_db
from app.core.ratelimit import limiter
from app.core.security import hash_password
from app.main import app
from app.modules.accounting import models as accounting_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.boq import models as boq_models  # noqa: F401
from app.modules.company import models as company_models  # noqa: F401
from app.modules.contracts import models as contracts_models  # noqa: F401
from app.modules.customers import models as customers_models  # noqa: F401
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.equipment import models as equipment_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.invoicing import models as invoicing_models  # noqa: F401
from app.modules.payroll import models as payroll_models  # noqa: F401
from app.modules.personnel import models as personnel_models  # noqa: F401
from app.modules.procurement import models as procurement_models  # noqa: F401
from app.modules.progress_payments import models as progress_payments_models  # noqa: F401
from app.modules.projects import models as projects_models  # noqa: F401
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.roles import models as roles_models  # noqa: F401
from app.modules.roles.models import Role
from app.modules.roles.seed_data import seed_reference_data
from app.modules.sales import models as sales_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
from app.modules.site_diary import models as site_diary_models  # noqa: F401
from app.modules.site_planning import models as site_planning_models  # noqa: F401
from app.modules.sites import models as sites_models  # noqa: F401
from app.modules.subcontractor_progress_payments import (  # noqa: F401
    models as subcontractor_progress_payments_models,
)
from app.modules.timesheet import models as timesheet_models  # noqa: F401
from app.modules.treasury import models as treasury_models  # noqa: F401
from app.modules.units import models as units_models  # noqa: F401
from app.modules.users import models as users_models  # noqa: F401
from app.modules.users.models import User, UserStatus

# Testlerde login/refresh hız sınırını kapat: login-yoğun testler paylaşılan in-memory
# limiter'da birbirini boğmasın. test_auth_ratelimit kendi ayrı limiter'ını kurar.
limiter.enabled = False

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
    """Her test kendi transaction'ında koşar ve sonunda geri alınır — testler birbirini kirletmez.

    Session, dış transaction'ın üstünde bir SAVEPOINT (nested transaction) üzerinde çalışır.
    Test altındaki kod `await session.commit()` çağırsa bile bu yalnızca SAVEPOINT'i kapatır;
    dış transaction etkilenmez.

    `join_transaction_mode="create_savepoint"` tek başına yeterli: session'ın kendi "autobegin"
    davranışı, her yeni işlemden (execute/flush) önce bağlantının hâlâ açık bir dış transaction
    içinde olduğunu görüp otomatik olarak YENİ bir SAVEPOINT açar — commit sonrası da dahil.
    Bu ampirik olarak doğrulandı: `connection.begin_nested()` çağrısını session oluşturulmadan
    önce elle yapmak ve/veya bir `after_transaction_end` dinleyicisiyle SAVEPOINT'i elle yeniden
    başlatmak denendi; elle `begin_nested()` çağrısı SAVEPOINT'i session'dan bağımsız olarak
    kalıcı şekilde açık tuttuğu için dinleyicinin "yeniden başlat" dalı hiçbir zaman çalışmıyordu
    (her seferinde no-op). Elle `begin_nested()` çağrısı kaldırılınca dinleyici gerçekten
    tetiklenip SAVEPOINT'i yeniden açtı, fakat art arda üç `commit()` içeren bir stres testi
    dinleyici tamamen kaldırıldığında da (yalnızca `join_transaction_mode` ile) sızıntısız
    geçti. Yani koruma tamamen `join_transaction_mode`'dan geliyor; elle `begin_nested()` ve
    `after_transaction_end` dinleyicisi gereksizdi ve kaldırıldı.

    Teardown'da dış transaction her zaman geri alınır, dolayısıyla hiçbir yazı `fiil_erp_test`
    veritabanına kalıcı olarak sızmaz.
    (SQLAlchemy'nin resmi "joining a session into an external transaction" tarifi.)
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = TestSessionLocal(bind=connection, join_transaction_mode="create_savepoint")

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


@pytest.fixture
async def seeded_db(db_session: AsyncSession) -> AsyncSession:
    """Rolleri, modülleri ve izin matrisini yükler. Test sonunda geri alınır."""
    await seed_reference_data(db_session)
    return db_session


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
