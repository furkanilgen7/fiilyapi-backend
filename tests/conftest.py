import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base, get_db
from app.core.ratelimit import limiter
from app.core.security import hash_password
from app.main import app
from app.modules.accounting import models as accounting_models  # noqa: F401
from app.modules.approvals import models as approvals_models  # noqa: F401
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
from app.modules.posting import models as posting_models  # noqa: F401
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


# ---------------------------------------------------------------------------
# 🔴 XDIST İŞÇİ YALITIMI (TB-XDIST, 2026-08-25)
#
# `pytest -n N` ile koşulan işçiler AYNI süreçte değil, AYRI süreçlerdedir; ama
# `TEST_DATABASE_URL` hepsinde AYNIdır. Bu kümenin yalıtımı "her test kendi
# transaction'ında koşar + sonunda rollback" desenine dayanır — o desen **tek bir
# veritabanı içindeki tek bir bağlantı** için geçerlidir. İki işçi aynı veritabanına
# yazarsa:
#   · biri `drop_all` + `create_all` koşarken öbürü o tablolara yazıyor olur (sahte kırmızı),
#   · birinin görünür kıldığı satır öbürünün "kaç kayıt var" iddiasına karışır (sahte yeşil).
# Bu yüzden HER İŞÇİ KENDİ VERİTABANINI alır: `<taban>_gw0`, `<taban>_gw1`, …
#
# 🔑 Yama noktası `test_engine` DEĞİL, `settings.test_database_url`dir: bu depodaki
# testlerin bir bölümü (migration dosyaları, `test_fisno_concurrency`, `tests/test_db.py`)
# kendi DSN'lerini/scratch veritabanlarını DOĞRUDAN `settings.test_database_url`den
# türetiyor. Yalnız motoru yamalamak onları paylaşılan veritabanında bırakırdı —
# `tests/test_db.py` sabit adlı bir probe tablosu (`CREATE TABLE … DROP TABLE`) açıyor,
# iki işçide çakışırdı.
#
# ⚠️ `or` YEDEĞİ YOK: `TEST_DATABASE_URL` verilmediğinde `settings` kendi varsayılanına
# düşer (localhost), asla `DATABASE_URL`e DEĞİL.
# ---------------------------------------------------------------------------

XDIST_ISCI = os.environ.get("PYTEST_XDIST_WORKER")


def _isci_veritabani_url(temel: str, isci: str | None) -> str:
    """Taban DSN'e işçi son ekini ekler. Seri koşuda (işçi yok) DSN aynen kalır."""
    if not isci:
        return temel
    url = make_url(temel)
    assert url.database, f"TEST_DATABASE_URL'de veritabanı adı yok: {temel}"
    return url.set(database=f"{url.database}_{isci}").render_as_string(hide_password=False)


settings.test_database_url = _isci_veritabani_url(settings.test_database_url, XDIST_ISCI)


# ---------------------------------------------------------------------------
# 🔴 İŞÇİ BAŞINA GEÇİCİ DİZİN (TB-TMPDIR, 2026-08-26)
#
# 🔑 KÖK KANON: `--dist loadfile` **DOSYA** bütünlüğünü korur, **SÜREÇ** bütünlüğünü
# KORUMAZ. Veritabanı yukarıda işçi başına ayrıldı; `/tmp` ayrılmamıştı — port, soket,
# ortam değişkeni gibi süreç-DIŞI paylaşılan her kaynak hâlâ yarışır.
#
# Fiilen ölçüldü (PR #82 CI turu): `test_import_does_not_persist_file` küresel
# `tempfile.gettempdir()` dizinini istek ÖNCESİ/SONRASI karşılaştırıyor; bu depoda
# **12 test dosyası `openpyxl` kullanıyor** ve `openpyxl.worksheet._writer`
# `NamedTemporaryFile(prefix="openpyxl.", delete=False)` ile AYNI `/tmp`e yazıyor.
# Başka bir işçinin o pencerede açtığı dosya iddiaya karışıyor →
# `assert {'openpyxl.v_pusb94'} == set()`. Aynı `headSha` rerun'ı YEŞİL geldi.
#
# `tempfile.tempdir` **ve** `TMPDIR` birlikte yamalanır: birincisi bu süreçteki
# `tempfile` çağrılarını (kütüphaneler dahil) yönlendirir — `gettempdir()` sonucunu
# önbelleklediği için ortam değişkeni TEK BAŞINA yetmez; ikincisi testlerin açtığı
# ALT SÜREÇLERİ kapsar.
#
# ⚠️ Öksüz bırakılmaz: dizin oturum başında (önceki çöküşten kalmışsa) silinip
# yeniden kurulur, oturum sonunda — başarısızlıkta da — silinir.
# ---------------------------------------------------------------------------

GECICI_KOK = (
    os.path.join(tempfile.gettempdir(), f"fiil-erp-test-{XDIST_ISCI}") if XDIST_ISCI else None
)


def _gecici_kok_yolu() -> str:
    """🔴 Silinecek yolun İŞÇİ son ekini TAŞIDIĞI burada çakılır.

    `_isci_veritabani_adi`nin geçici dizin kardeşi: `rmtree` çalıştıran her yol,
    adın `fiil-erp-test-<isci>` kalıbına uyduğunu doğrulamadan çalışmaz — böylece
    küresel `/tmp` bu koddan ASLA silinemez.
    """
    assert (
        GECICI_KOK
        and XDIST_ISCI
        and os.path.basename(GECICI_KOK) == (f"fiil-erp-test-{XDIST_ISCI}")
    ), f"Geçici dizin adı beklenen kalıba uymuyor: {GECICI_KOK!r}. rmtree çalıştırılmadı."
    return GECICI_KOK


if GECICI_KOK:
    shutil.rmtree(_gecici_kok_yolu(), ignore_errors=True)
    os.makedirs(GECICI_KOK, exist_ok=True)
    os.environ["TMPDIR"] = GECICI_KOK
    tempfile.tempdir = GECICI_KOK


def _duz_dsn(veritabani: str) -> str:
    """`postgresql+asyncpg://…` DSN'i, asyncpg'nin doğrudan yediği düz DSN'e çevirir."""
    return (
        make_url(settings.test_database_url)
        .set(drivername="postgresql", database=veritabani)
        .render_as_string(hide_password=False)
    )


def _isci_veritabani_adi() -> str:
    """🔴 Düşürülecek adın İŞÇİ son ekini TAŞIDIĞI burada çakılır.

    `DROP DATABASE` çalıştıran her yol, adın `_gwN` ile bittiğini doğrulamadan
    çalışmaz — böylece taban veritabanı (ve `.env` uzak Railway'i gösteriyorsa canlı)
    bu koddan ASLA düşürülemez.
    """
    ad = make_url(settings.test_database_url).database
    assert ad and XDIST_ISCI and ad.endswith(f"_{XDIST_ISCI}"), (
        f"İşçi veritabanı adı beklenen `_{XDIST_ISCI}` son ekini taşımıyor: {ad!r}. "
        "DROP DATABASE çalıştırılmadı."
    )
    return ad


async def _admin_calistir(sql: str) -> None:
    baglanti = await asyncpg.connect(_duz_dsn("postgres"))
    try:
        await baglanti.execute(sql)
    finally:
        await baglanti.close()


def pytest_sessionstart(session: pytest.Session) -> None:
    """İşçi kendi veritabanını oturum başında SIFIRDAN kurar (öksüz kalmışsa da)."""
    if not XDIST_ISCI:
        return
    ad = _isci_veritabani_adi()
    asyncio.run(_admin_calistir(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)'))
    asyncio.run(_admin_calistir(f'CREATE DATABASE "{ad}"'))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """🔴 BAŞARISIZLIKTA DA DÜŞER: `pytest_sessionfinish` toplama hatasında, iddia
    kırmızısında ve `-x` ile erken çıkışta da çağrılır (fikstür teardown'ı çağrılmayabilir).
    `WITH (FORCE)` artakalan bağlantıları da keser."""
    if not XDIST_ISCI:
        return
    ad = _isci_veritabani_adi()
    asyncio.run(_admin_calistir(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)'))
    shutil.rmtree(_gecici_kok_yolu(), ignore_errors=True)


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
