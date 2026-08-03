"""Şantiye günlüğü (T2) fixture'ları — bağımsız kurulum.

Kök `tests/conftest.py`'deki `db_session`/`seeded_db`/`user_factory`/`project_factory`
üzerine kurulur. Kardeş test paketleri (`tests/progress_payments`, `tests/subcontractor_
progress_payments`) pytest tarafından otomatik YÜKLENMEZ; erişim deseni burada
yeniden kurulur.

`tests/progress_payments/test_concurrency.py`'nin bilinen seed sızıntısı borcuna
BULAŞILMAZ: bu paketin hiçbir fixture'ı oradan miras almaz, her fixture kendi
verisini kurar ve kök `db_session` savepoint'i içinde geri alınır.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.projects.models import Project, ProjectContract
from app.modules.site_diary.models import DiaryStatus, SiteDiaryEntry, SiteDiaryLine
from app.modules.sites.models import Section, Site
from app.modules.users.models import User, UserProjectAccess

VARSAYILAN_TARIH = date(2026, 7, 15)


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _scoped_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    role_key: str,
    email: str,
    project: Project,
) -> dict[str, str]:
    """Rolü verilen ama kapsamı TEK projeye kısıtlanmış kullanıcı."""
    await user_factory(email=email, password="parola1234", role_key=role_key)
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=project.id, all_projects=False))
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return _auth(resp.json()["access_token"])


# --- Erişim/kapsam fixture'ları (izin matrisi: şef/saha=_F, PM=_V, İK=_N) ---


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    token = await _login(client, user_factory, "system_admin", "admin@sd-t2.co")
    return _auth(token)


@pytest.fixture
async def admin_kullanicisi(seeded_db: AsyncSession, admin_headers: dict[str, str]) -> User:
    return (
        await seeded_db.execute(select(User).where(User.email == "admin@sd-t2.co"))
    ).scalar_one()


@pytest.fixture
async def hr_headers(client: AsyncClient, seeded_db: AsyncSession, user_factory) -> dict[str, str]:
    """`hr_manager` — matriste `site_diary=_N`: okuma dahil 403 (kapı en dışta)."""
    token = await _login(client, user_factory, "hr_manager", "ik@sd-t2.co")
    return _auth(token)


@pytest.fixture
async def proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="SD-P01", name="Günlük Kayıt Projesi")


@pytest.fixture
async def sef_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`site_chief` (`site_diary=_F`) — yalnız `proje`ye atanmış."""
    return await _scoped_headers(
        client, seeded_db, user_factory, "site_chief", "sef@sd-t2.co", proje
    )


@pytest.fixture
async def sef_kullanicisi(seeded_db: AsyncSession, sef_headers: dict[str, str]) -> User:
    return (await seeded_db.execute(select(User).where(User.email == "sef@sd-t2.co"))).scalar_one()


@pytest.fixture
async def saha_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`field_engineer` (`site_diary=_F`) — şefle AYNI projede, farklı kullanıcı.

    `can_delete` reddinin kanıtı: seviyesi yeter ama kaydı O AÇMAMIŞTIR.
    """
    return await _scoped_headers(
        client, seeded_db, user_factory, "field_engineer", "saha@sd-t2.co", proje
    )


@pytest.fixture
async def pm_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`project_manager` (`site_diary=_V`) — SALT OKUR; yazma uçlarında 403."""
    return await _scoped_headers(
        client, seeded_db, user_factory, "project_manager", "pm@sd-t2.co", proje
    )


@pytest.fixture
async def patron_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`patron` — matriste `site_diary=_F` (şef/saha ile AYNI seviye).

    T4 `reopen` kapısı `admin` seviyesidir; bu fixture "tam yetkili ama admin
    DEĞİL" hâlinin ikinci kanıtıdır (matris DEĞİŞMEZ — spec §1).
    """
    return await _scoped_headers(
        client, seeded_db, user_factory, "patron", "patron@sd-t2.co", proje
    )


@pytest.fixture
async def kapsamli_admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory, proje: Project
) -> dict[str, str]:
    """`system_admin` (`site_diary=_A`) ama kapsamı TEK projeye kısıtlı.

    `admin_headers` TÜM projeleri görür; `admin` kapılı `reopen` ucunun IDOR
    yüzeyi ancak kapsamı kısıtlı bir admin ile kanıtlanabilir.
    """
    return await _scoped_headers(
        client, seeded_db, user_factory, "system_admin", "kapsamli@sd-t4.co", proje
    )


# --- Veri kurulumu ---


@pytest.fixture
def santiye_fabrikasi(seeded_db: AsyncSession, project_factory):
    """Proje + şantiye + BOQ grubu + poz kalemleri kurar.

    BOQ iskeleti testinin kaynağı budur: `POST /sites/{id}/diary` bu pozlardan
    satır üretmek ZORUNDADIR (GK'de satır ekle/sil yoktur).
    """

    async def _create(
        code: str,
        *,
        project: Project | None = None,
        item_specs: list[tuple[str, Decimal, Decimal]] | None = None,
    ) -> tuple[Site, Project, list[BoqItem]]:
        if project is None:
            project = await project_factory(code=code, name=f"{code} Projesi")
        site = Site(project_id=project.id, code=f"{code}-SNT", name=f"{code} Şantiyesi")
        seeded_db.add(site)
        await seeded_db.flush()

        group = BoqGroup(site_id=site.id, name="A — Betonarme İşleri", sort_order=0)
        seeded_db.add(group)
        await seeded_db.flush()

        specs = (
            item_specs
            if item_specs is not None
            else [
                ("01.001", Decimal("200.000"), Decimal("21500.00")),
                ("02.001", Decimal("450.000"), Decimal("1850.00")),
            ]
        )
        items: list[BoqItem] = []
        for index, (item_code, quantity, unit_price) in enumerate(specs):
            item = BoqItem(
                site_id=site.id,
                group_id=group.id,
                code=item_code,
                description=f"{item_code} kalemi",
                unit="Ton",
                quantity=quantity,
                unit_price=unit_price,
                sort_order=index,
            )
            seeded_db.add(item)
            items.append(item)
        await seeded_db.flush()
        return site, project, items

    return _create


@pytest.fixture
async def santiye(santiye_fabrikasi, proje: Project) -> tuple[Site, Project, list[BoqItem]]:
    return await santiye_fabrikasi("SD-A", project=proje)


@pytest.fixture
async def bolum(seeded_db: AsyncSession, santiye) -> Section:
    site, _, _ = santiye
    section = Section(site_id=site.id, code="B-1", name="A Blok")
    seeded_db.add(section)
    await seeded_db.flush()
    return section


@pytest.fixture
async def gorunmeyen_santiye(santiye_fabrikasi) -> Site:
    """`sef_headers`/`pm_headers` kapsamı DIŞINDAKİ projenin şantiyesi (IDOR yüzeyi)."""
    site, _, _ = await santiye_fabrikasi("SD-G")
    return site


@pytest.fixture
def gunluk_fabrikasi(seeded_db: AsyncSession):
    """Doğrudan DB'ye günlük kaydı yazar — durum geçişi uçları T4'tedir."""

    async def _create(
        site: Site,
        creator: User,
        *,
        entry_date: date = VARSAYILAN_TARIH,
        status: DiaryStatus = DiaryStatus.draft,
        lines: list[tuple[str, Decimal, Decimal]] | None = None,
    ) -> SiteDiaryEntry:
        entry = SiteDiaryEntry(
            site_id=site.id,
            project_id=site.project_id,
            entry_date=entry_date,
            status=status,
            created_by=creator.id,
        )
        for code, quantity, unit_price in lines or []:
            entry.lines.append(
                SiteDiaryLine(
                    code=code,
                    description=f"{code} kalemi",
                    unit="Ton",
                    unit_price=unit_price,
                    quantity=quantity,
                )
            )
        seeded_db.add(entry)
        await seeded_db.flush()
        return entry

    return _create


@pytest.fixture
def sozlesme_kalemi_fabrikasi(seeded_db: AsyncSession):
    """İşveren sözleşmesi kalemi kurar ve BOQ pozuna KÖPRÜLER.

    T4 `summary` ucunun `contract_item_*` alanlarının kaynağı budur
    (`boq_items.contract_item_id`); T5 "günlükten doldur" önerisi de aynı köprüyü
    tüketecektir.
    """

    async def _create(
        boq_item: BoqItem,
        project: Project,
        *,
        quantity: Decimal = Decimal("1200.000"),
        unit_price: Decimal = Decimal("1850.00"),
    ) -> EmployerContractItem:
        if await seeded_db.get(ProjectContract, project.id) is None:
            seeded_db.add(
                ProjectContract(
                    project_id=project.id,
                    contract_no=f"{project.code}-SZL",
                    amount=Decimal("11200000"),
                )
            )
            await seeded_db.flush()
        group = (
            (
                await seeded_db.execute(
                    select(EmployerContractGroup).where(
                        EmployerContractGroup.project_id == project.id
                    )
                )
            )
            .scalars()
            .first()
        )
        if group is None:
            group = EmployerContractGroup(project_id=project.id, name="A — Betonarme", sort_order=0)
            seeded_db.add(group)
            await seeded_db.flush()
        item = EmployerContractItem(
            project_id=project.id,
            group_id=group.id,
            code=f"SZL-{boq_item.code}",
            description=f"{boq_item.code} sözleşme kalemi",
            unit=boq_item.unit,
            quantity=quantity,
            unit_price=unit_price,
        )
        seeded_db.add(item)
        await seeded_db.flush()
        boq_item.contract_item_id = item.id
        await seeded_db.flush()
        return item

    return _create


@pytest.fixture
async def gorunmeyen_gunluk(
    gorunmeyen_santiye: Site, gunluk_fabrikasi, admin_kullanicisi: User
) -> uuid.UUID:
    entry = await gunluk_fabrikasi(gorunmeyen_santiye, admin_kullanicisi)
    return entry.id
