"""İK-3 T2 — `compute` akışının fixture'ları.

`tests/timesheet/conftest.py` kardeşi: kök `tests/conftest.py`in
`db_session`/`seeded_db`/`user_factory`/`project_factory` fixture'ları üzerine
kurulur, kardeş test paketlerinden hiçbir şey miras alınmaz.

Oran SEED'i migration'dadır ama test şeması `Base.metadata.create_all` ile
kurulur (migration KOŞMAZ) — bu yüzden oranlar burada AÇIKÇA yaratılır ve
beklentiler seed'in sessizce değişmesine bağlı kalmaz.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll.models import PayrollPeriod, PayrollRate
from app.modules.personnel.models import PaymentMethod, Personnel, WageType
from app.modules.projects.models import Project
from app.modules.site_diary.models import WorkerSource
from app.modules.sites.models import Site
from app.modules.timesheet.models import TimesheetCode, TimesheetEntry
from app.modules.users.models import User

# BY başlığındaki dönem yerine T1 SEED yılı kullanılır: oran seti 2026'ya bağlıdır.
YIL = 2026
AY = 7


# SGK 70-73 / 79-81 (S1) — `test_payroll_compute.py` ile AYNI sayılar.
SGK_4A = {
    "sgk_employee_pct": Decimal("14.000"),
    "unemployment_employee_pct": Decimal("1.000"),
    "income_tax_pct": Decimal("10.000"),
    "stamp_tax_pct": Decimal("0.759"),
    "sgk_employer_pct": Decimal("20.500"),
    "unemployment_employer_pct": Decimal("2.000"),
    "short_work_pct": Decimal("1.000"),
}
ZERO = dict.fromkeys(SGK_4A, Decimal("0.000"))
SERBEST = {**ZERO, "income_tax_pct": Decimal("20.000")}

#: `general` KASTEN YOKTUR (spec §4): bordro tipi değildir, oran satırı da yoktur.
SEED_2026 = {
    WorkerSource.company: SGK_4A,
    WorkerSource.subcontractor: SGK_4A,
    WorkerSource.freelance: SERBEST,
    WorkerSource.intern: ZERO,
}


@pytest.fixture
async def oranlar(db_session: AsyncSession) -> list[PayrollRate]:
    rows = [
        PayrollRate(year=YIL, personnel_source=source, **pct) for source, pct in SEED_2026.items()
    ]
    db_session.add_all(rows)
    await db_session.flush()
    return rows


@pytest.fixture
async def donem(db_session: AsyncSession) -> PayrollPeriod:
    period = PayrollPeriod(year=YIL, month=AY)
    db_session.add(period)
    await db_session.flush()
    return period


@pytest.fixture
async def proje(project_factory) -> Project:
    return await project_factory(code="BR-P01", name="Bordro Projesi")


@pytest.fixture
async def santiye(db_session: AsyncSession, proje: Project) -> Site:
    site = Site(project_id=proje.id, code="BR-A", name="Bordro Şantiyesi")
    db_session.add(site)
    await db_session.flush()
    return site


@pytest.fixture
async def kaydeden(user_factory) -> User:
    return await user_factory(email="bordro@ik3.co", password="parola1234", role_key="system_admin")


@pytest.fixture
def personel_fabrikasi(db_session: AsyncSession):
    async def _create(
        full_name: str,
        *,
        source: WorkerSource = WorkerSource.company,
        wage_type: WageType | None = WageType.daily,
        wage_amount: Decimal | None = Decimal("1800.00"),
        payment_method: PaymentMethod | None = PaymentMethod.bank,
        is_active: bool = True,
        is_draft: bool = False,
    ) -> Personnel:
        person = Personnel(
            full_name=full_name,
            source=source,
            wage_type=wage_type,
            wage_amount=wage_amount,
            payment_method=payment_method,
            is_active=is_active,
            is_draft=is_draft,
        )
        db_session.add(person)
        await db_session.flush()
        return person

    return _create


@pytest.fixture
def puantaj_fabrikasi(db_session: AsyncSession, santiye: Site, kaydeden: User):
    """Belirtilen günlere hücre yazar; kod varsayılanı `worked`."""

    async def _create(
        person: Personnel,
        days: list[int],
        *,
        code: TimesheetCode = TimesheetCode.worked,
        month: int = AY,
        year: int = YIL,
        overtime_hours: Decimal | None = None,
    ) -> None:
        for day in days:
            db_session.add(
                TimesheetEntry(
                    personnel_id=person.id,
                    site_id=santiye.id,
                    project_id=santiye.project_id,
                    work_date=date(year, month, day),
                    code=code,
                    overtime_hours=overtime_hours,
                    created_by=kaydeden.id,
                )
            )
        await db_session.flush()

    return _create


def satir_of(satirlar, personnel_id: uuid.UUID):
    for satir in satirlar:
        if satir.personnel_id == personnel_id:
            return satir
    raise AssertionError(f"bordro satırı yok: {personnel_id}")
