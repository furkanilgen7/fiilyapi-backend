"""SA T1 — sunucu tarafi numara ureticileri (§7 S6).

`SAT-YYYY-NNNN` (talep) ve `SP-YYYY-NNNN` (siparis): DORT haneli sifir dolgulu,
YIL BAZLI sira. SIP mockup'undaki uc hane cizim artefaktidir (kullanici karari).

En kritik test `test_esZAMANLI_uretim_ayni_numarayi_vermez`: numarayi
"MAX + 1" ile ureten naif bir uygulama iki es zamanli istekte AYNI numarayi
verir ve UQ ihlaliyle 500 uretir (ya da UQ olmasaydi iki talep ayni numarayla
yasardi). Kilit gercek OLDUGUNDA ikinci islem birincinin commit'ini BEKLER.
"""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import Base
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchasePriority,
    PurchaseRequest,
    PurchaseRequestStatus,
    Supplier,
)
from app.modules.procurement.numbering import (
    ORDER_NUMBER_PREFIX,
    REQUEST_NUMBER_PREFIX,
    SEQUENCE_WIDTH,
    generate_order_number,
    generate_request_number,
)


async def _add_request(
    session: AsyncSession,
    *,
    request_no: str,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    request_date: date = date(2026, 8, 12),
) -> PurchaseRequest:
    request = PurchaseRequest(
        request_no=request_no,
        request_date=request_date,
        priority=PurchasePriority.normal,
        project_id=project_id,
        status=PurchaseRequestStatus.draft,
        created_by_user_id=user_id,
    )
    session.add(request)
    await session.flush()
    return request


async def _add_order(
    session: AsyncSession,
    *,
    order_no: str,
    project_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
) -> PurchaseOrder:
    order = PurchaseOrder(
        order_no=order_no,
        supplier_id=supplier_id,
        project_id=project_id,
        total_amount=Decimal("1000.00"),
        status=PurchaseOrderStatus.approved,
        created_by_user_id=user_id,
    )
    session.add(order)
    await session.flush()
    return order


@pytest.fixture
async def numara_ortami(db_session: AsyncSession, project_factory, user_factory):
    """Numara ureticilerinin ihtiyac duydugu en kucuk FK zemini."""
    project = await project_factory(code=f"P-{uuid.uuid4().hex[:6]}")
    user = await user_factory(
        email=f"{uuid.uuid4().hex[:8]}@ornek.test", password="x", role_key="system_admin"
    )
    supplier = Supplier(name="Beton A.S.", payment_terms="days_30")
    db_session.add(supplier)
    await db_session.flush()
    return db_session, project, user, supplier


async def test_yilin_ilk_numarasi_bir_ile_baslar(numara_ortami):
    session, *_ = numara_ortami
    assert await generate_request_number(session, year=2026) == "SAT-2026-0001"
    assert await generate_order_number(session, year=2026) == "SP-2026-0001"


async def test_numara_dort_haneli_sifir_dolgulu(numara_ortami):
    """§7 S6 kullanici karari: IKISI DE dort hane. SIP'in uc hanesi cizim
    artefaktidir — `SP-2026-035` DEGIL `SP-2026-0035` uretilir."""
    session, project, user, supplier = numara_ortami
    await _add_order(
        session,
        order_no="SP-2026-0034",
        project_id=project.id,
        supplier_id=supplier.id,
        user_id=user.id,
    )
    assert await generate_order_number(session, year=2026) == "SP-2026-0035"
    assert SEQUENCE_WIDTH == 4
    assert (REQUEST_NUMBER_PREFIX, ORDER_NUMBER_PREFIX) == ("SAT", "SP")


async def test_sira_mevcut_en_buyuk_numaradan_devam_eder(numara_ortami):
    session, project, user, _ = numara_ortami
    for numara in ("SAT-2026-0001", "SAT-2026-0007", "SAT-2026-0003"):
        await _add_request(session, request_no=numara, project_id=project.id, user_id=user.id)
    # EN BUYUK + 1 — "satir sayisi + 1" olsaydi 0004 dondurup UQ'yu ihlal ederdi.
    assert await generate_request_number(session, year=2026) == "SAT-2026-0008"


async def test_yil_sinirinda_sira_sifirlanir(numara_ortami):
    """Sira YIL BAZLIDIR: 2025'in 42 talebi 2026'nin ilkini 0043 yapmaz."""
    session, project, user, _ = numara_ortami
    await _add_request(
        session,
        request_no="SAT-2025-0042",
        project_id=project.id,
        user_id=user.id,
        request_date=date(2025, 12, 31),
    )
    assert await generate_request_number(session, year=2026) == "SAT-2026-0001"
    assert await generate_request_number(session, year=2025) == "SAT-2025-0043"


async def test_iki_dizi_birbirinden_bagimsiz(numara_ortami):
    """Talep ve siparis sayaclari AYRIDIR — ortak sayac SP'yi bosluklu yapardi."""
    session, project, user, supplier = numara_ortami
    for numara in ("SAT-2026-0001", "SAT-2026-0002", "SAT-2026-0003"):
        await _add_request(session, request_no=numara, project_id=project.id, user_id=user.id)
    assert await generate_order_number(session, year=2026) == "SP-2026-0001"
    await _add_order(
        session,
        order_no="SP-2026-0001",
        project_id=project.id,
        supplier_id=supplier.id,
        user_id=user.id,
    )
    assert await generate_request_number(session, year=2026) == "SAT-2026-0004"


async def test_dolgu_genisligi_asilinca_numara_uzar(numara_ortami):
    """Dort hane bir TAVAN degil, en az genisliktir: 9999'dan sonra 10000 gelir
    ve numara yine TEKILDIR (basa donup UQ'yu ihlal etmez)."""
    session, project, user, _ = numara_ortami
    await _add_request(session, request_no="SAT-2026-9999", project_id=project.id, user_id=user.id)
    assert await generate_request_number(session, year=2026) == "SAT-2026-10000"


async def test_baska_yilin_bes_haneli_numarasi_ayristirilir(numara_ortami):
    session, project, user, _ = numara_ortami
    await _add_request(session, request_no="SAT-2026-10000", project_id=project.id, user_id=user.id)
    assert await generate_request_number(session, year=2026) == "SAT-2026-10001"


async def test_yil_verilmezse_bugunun_yili_kullanilir(numara_ortami):
    session, *_ = numara_ortami
    bugun = date.today().year
    assert await generate_request_number(session) == f"SAT-{bugun}-0001"


# --------------------------------------------------------------------------- #
# Yaris kosulu — GERCEK es zamanlilik (paylasilan test oturumu YETMEZ)
# --------------------------------------------------------------------------- #


def _asyncpg_dsn(database: str) -> str:
    base = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    return base.rsplit("/", 1)[0] + f"/{database}"


def _sqlalchemy_dsn(database: str) -> str:
    return settings.test_database_url.rsplit("/", 1)[0] + f"/{database}"


async def _create_scratch_database() -> str:
    database = f"procurement_no_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    return database


async def _drop_scratch_database(database: str) -> None:
    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.close()


async def test_eszamanli_uretim_ayni_numarayi_vermez():
    """IKI AYRI BAGLANTI ayni anda numara ister.

    Kilit YOKSA ikisi de commit edilmemis durumu okur, ikisi de `SAT-2026-0001`
    doner ve ikincisi UQ ihlaliyle 500 uretir. Kilit VARSA ikinci uretim
    birincinin commit'ini BEKLER (asagida `not done` ile olculur) ve 0002 alir.

    Paylasilan `db_session` fixture'i bunu OLCEMEZ: tek baglanti + savepoint
    oldugu icin gercek eszamanlilik yoktur. Bu yuzden tek kullanimlik bir
    veritabani acilir (`.env`/`TEST_DATABASE_URL` veritabani ELLENMEZ).
    """
    database = await _create_scratch_database()
    engine = create_async_engine(_sqlalchemy_dsn(database))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        raw = await asyncpg.connect(_asyncpg_dsn(database))
        try:
            role_id, user_id, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await raw.execute(
                "INSERT INTO roles (id, key, name, emoji, description, is_system) "
                "VALUES ($1, 'sa_yaris', 'SA Rol', '', '', false)",
                role_id,
            )
            await raw.execute(
                "INSERT INTO users (id, email, password_hash, full_name, title, role_id, "
                "status, token_version) "
                "VALUES ($1, 'yaris@ornek.test', 'x', 'SA', '', $2, 'active', 0)",
                user_id,
                role_id,
            )
            await raw.execute(
                "INSERT INTO projects (id, code, name, status, budget, progress_pct) "
                "VALUES ($1, 'P-YARIS', 'Yaris', 'active', 0, 0)",
                project_id,
            )
        finally:
            await raw.close()

        Session = async_sessionmaker(engine, expire_on_commit=False)

        async def _uret_ve_yaz(session: AsyncSession) -> str:
            numara = await generate_request_number(session, year=2026)
            await _add_request(session, request_no=numara, project_id=project_id, user_id=user_id)
            await session.commit()
            return numara

        async with Session() as birinci, Session() as ikinci:
            ilk_numara = await generate_request_number(birinci, year=2026)
            await _add_request(
                birinci, request_no=ilk_numara, project_id=project_id, user_id=user_id
            )

            # Ikinci oturum HENUZ commit edilmemis birincinin ustune biner.
            gorev = asyncio.create_task(_uret_ve_yaz(ikinci))
            await asyncio.sleep(0.3)
            assert not gorev.done(), (
                "ikinci uretim beklemedi — kilit yok, iki istek ayni numarayi alir"
            )

            await birinci.commit()
            ikinci_numara = await asyncio.wait_for(gorev, timeout=10)

        assert ilk_numara == "SAT-2026-0001"
        assert ikinci_numara == "SAT-2026-0002"
    finally:
        await engine.dispose()
        await _drop_scratch_database(database)
