"""Task H4 — eşzamanlılık: `SELECT … FOR UPDATE` kilidi altında D8 + `sequence_no`

üretimi (spec §7 eşzamanlılık notunun oluşturmaya izdüşümü). İki eşzamanlı
`POST` aynı `sequence_no`'yu ÜRETEMEZ; ikisi de D8 kontrolünü boşken GEÇEMEZ —
yalnız biri başarılı olur, diğeri 409 `OPEN_PAYMENT_EXISTS` alır.

Neden `client`/`seeded_db` KULLANILMAZ: `tests/conftest.py`'deki `db_session`
her testi TEK bir bağlantı üzerinde SAVEPOINT'e sarar ve dış transaction'ı asla
gerçekten COMMIT ETMEZ (kendi docstring'i) — o session üzerinde iki `asyncio.gather`
görevi de AYNI bağlantıyı paylaşır, gerçek satır kilidi/eşzamanlılık test EDİLEMEZ.
Bu test bilinçli olarak `test_engine`'den İKİ BAĞIMSIZ bağlantı açar, kurulum
verisini GERÇEKTEN commit eder ve sonunda GERÇEKTEN temizler.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.security import hash_password
from app.modules.progress_payments import schemas, service
from app.modules.progress_payments.models import ProgressPayment
from app.modules.projects.models import Project, ProjectContract
from app.modules.roles.models import Role
from app.modules.roles.seed_data import seed_reference_data
from app.modules.users.models import User
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio

_SessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def test_iki_esZamanli_olusturma_yalniz_biri_gecer() -> None:
    project_id, user_id = await _kurulum()
    try:
        results = await asyncio.gather(
            _attempt_create(project_id, user_id), _attempt_create(project_id, user_id)
        )

        assert sorted(results) == ["conflict", "created"]

        async with _SessionFactory() as verify_session:
            actor = await verify_session.get(User, user_id)
            listed = await service.list_payments(
                verify_session, actor, project_id=project_id, site_id=None, status_filter=None
            )
        assert len(listed.items) == 1
        assert listed.items[0].sequence_no == 1
    finally:
        await _temizle(project_id, user_id)


async def _kurulum() -> tuple[uuid.UUID, uuid.UUID]:
    """Reel commit'li kurulum: `seed_reference_data` idempotenttir (modülün

    kendi garantisi) — bu test hangi sırada koşarsa koşsun güvenlidir.
    """
    async with _SessionFactory() as session:
        await seed_reference_data(session)
        await session.commit()

        role = (await session.execute(select(Role).where(Role.key == "system_admin"))).scalar_one()

        project = Project(code="PP-CONC-001", name="Eşzamanlılık Projesi")
        session.add(project)
        await session.flush()
        contract = ProjectContract(
            project_id=project.id,
            contract_no="SZL-2026-CONC",
            amount=Decimal("1000000"),
            advance_pct=Decimal("10"),
            retainage_pct=Decimal("5"),
            vat_pct=Decimal("20"),
        )
        session.add(contract)
        user = User(
            email="concurrency@pp-crud.co",
            password_hash=hash_password("parola1234"),
            full_name="Eşzamanlılık Test",
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        return project.id, user.id


async def _attempt_create(project_id: uuid.UUID, actor_id: uuid.UUID) -> str:
    async with _SessionFactory() as session:
        actor = await session.get(User, actor_id)
        try:
            await service.create(session, actor, project_id, schemas.ProgressPaymentCreate())
            await session.commit()
            return "created"
        except ConflictError:
            await session.rollback()
            return "conflict"


async def _temizle(project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with _SessionFactory() as session:
        await session.execute(
            delete(ProgressPayment).where(ProgressPayment.project_id == project_id)
        )
        await session.execute(
            delete(ProjectContract).where(ProjectContract.project_id == project_id)
        )
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()
