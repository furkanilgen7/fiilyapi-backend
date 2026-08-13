"""İK-3 T2/T3 — `compute` akışının ve bordro uçlarının fixture'ları.

`tests/timesheet/conftest.py` kardeşi: kök `tests/conftest.py`in
`db_session`/`seeded_db`/`user_factory`/`project_factory` fixture'ları üzerine
kurulur, kardeş test paketlerinden hiçbir şey miras alınmaz.

Oran SEED'i migration'dadır ama test şeması `Base.metadata.create_all` ile
kurulur (migration KOŞMAZ) — bu yüzden oranlar burada AÇIKÇA yaratılır ve
beklentiler seed'in sessizce değişmesine bağlı kalmaz.

## T3 yetki fixture'ları

İzin matrisi (`roles/seed_data.py:182`, **`payroll`** — seed'de ZATEN VAR, matris
DEĞİŞMEDİ): system_admin=**_A** · patron=_F · site_chief=**_N** ·
field_engineer=**_N** · hr_manager=**_F** · accounting=**_F** ·
project_manager=**_N** · procurement=**_N**.

`payroll` satırında `view` seviyeli HİÇBİR hazır rol yoktur; okuma/yazma ayrımı
(spec S9) yine de uçlarda durur — özel roller (`roles` modülü) o seviyeyi
kurabilir. Bu yüzden fixture'lar üç seviyeyi temsil eder:

* `admin_headers`    — `system_admin` (`_A`);
* `ik_headers`       — `hr_manager` (`_F`), bordronun gerçek kullanıcısı;
* `yetkisiz_headers` — `site_chief` (`_N`): OKUMADA BİLE 403.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
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


# --- T3: yetki başlıkları --------------------------------------------------


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(client: AsyncClient, user_factory) -> dict[str, str]:
    return _auth(await _login(client, user_factory, "system_admin", "bordro.admin@ik3.co"))


@pytest.fixture
async def ik_headers(client: AsyncClient, user_factory) -> dict[str, str]:
    """`hr_manager` (`payroll=_F`) — bordronun gerçek kullanıcısı."""
    return _auth(await _login(client, user_factory, "hr_manager", "bordro.ik@ik3.co"))


@pytest.fixture
async def yetkisiz_headers(client: AsyncClient, user_factory) -> dict[str, str]:
    """`site_chief` (`payroll=_N`) — OKUMADA BİLE 403."""
    return _auth(await _login(client, user_factory, "site_chief", "bordro.sef@ik3.co"))


# --- T3: dört tipli senaryo ------------------------------------------------
#
# BY'nin dört bölümünü (124/172/240/268) + S4'ün "hesaplanamadı" durumunu tek
# fixture'da toplar. Sayılar ORANLARDAN türer, BY/BG tutarlarından DEĞİL (S1):
#
#   şirket   · 5 gün × 1.800 = brüt  9.000,00 · kesinti %25,759 → 2.318,31 · net 6.681,69
#   taşeron  · 5 gün × 1.800 = brüt  9.000,00 · aynı hesap        · net 6.681,69 (EXCLUDED)
#   serbest  · aylık          brüt 12.500,00 · %20 stopaj        · net 10.000,00
#   stajyer  · aylık          brüt  7.500,00 · kesinti YOK       · net  7.500,00
#   ücretsiz · ücret tanımsız → brüt/net `null`, satır UNCOMPUTED (S4)


@pytest.fixture
async def dort_tip(donem, oranlar, personel_fabrikasi, puantaj_fabrikasi):
    """Beş personel + puantajları. Dönem HENÜZ hesaplanmamıştır."""
    kisiler = {
        "sirket": await personel_fabrikasi("Ayşe Demir"),
        "taseron": await personel_fabrikasi("Mehmet Yılmaz", source=WorkerSource.subcontractor),
        "serbest": await personel_fabrikasi(
            "Kemal Tunç",
            source=WorkerSource.freelance,
            wage_type=WageType.monthly,
            wage_amount=Decimal("12500.00"),
        ),
        "stajyer": await personel_fabrikasi(
            "Burak Aydın",
            source=WorkerSource.intern,
            wage_type=WageType.monthly,
            wage_amount=Decimal("7500.00"),
        ),
        "ucretsiz": await personel_fabrikasi(
            "Zeynep Ak", wage_type=None, wage_amount=None, payment_method=None
        ),
    }
    for kisi in kisiler.values():
        await puantaj_fabrikasi(kisi, [1, 2, 3, 4, 5])
    return kisiler
