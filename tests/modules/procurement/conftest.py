"""SA T2 — tedarikçi + talep uçlarının login/yetki/kapsam fixture'ları.

`tests/modules/inventory/conftest.py` deseninin kardeşi: kök `tests/conftest.py`de
hazır başlık fixture'ı YOKTUR, her test paketi kendi `_login`/`_auth` yardımcısını
kurar.

İzin matrisi (`roles/seed_data.py`, **`procurement`** — 10. modül, grup
STOK_SATINALMA; seed'de ZATEN VARDI, matris DEĞİŞMEDİ):
system_admin=**_A** · patron=_F · site_chief=**_REQ** · field_engineer=**_REQ** ·
hr_manager=**_N** · accounting=**_N** · project_manager=**_APR** · procurement=_F.

Seviye sırası `none < view < draft < request < approve < full < admin`
(`app/core/access.py`). T2'nin kapıları buradan çıkar:

* okuma (`view`)            → şef/saha/PM/satınalma/patron/sysadmin geçer,
                              İK ve muhasebe GEÇEMEZ;
* TALEP yazımı (`request`)  → şef ve saha da geçer (talebi sahadan açan onlardır);
* TEDARİKÇİ yazımı (`full`) → yalnız satınalma/patron/sysadmin — katalog şefin
                              işi DEĞİLDİR, şef tedarikçi ekleyemez (403).

Fixture seçimi bu dört seviyeyi temsil eder:
* `admin_headers`     — `system_admin` (`_A`); `projects=_A` olduğu için
  `visible_projects` süzgecini ATLAR (tüm projeleri görür).
* `satinalma_headers` — `procurement` (`_F`); `projects=_N` olduğu için kapsamı
  `user_project_access`ten gelir — **IDOR testlerinin taşıyıcısı budur.**
* `sef_headers`       — `site_chief` (`_REQ`): talep açar, TEDARİKÇİ AÇAMAZ.
* `yetkisiz_headers`  — `accounting` (`_N`): okumada bile 403.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import StockCategory, StockItem, Warehouse
from app.modules.procurement.models import PaymentTerms, Supplier
from app.modules.projects.models import Project
from app.modules.sites.models import Section, Site
from app.modules.users.models import User, UserProjectAccess


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def gorunen_proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="SA-P01", name="Güneşkent A-Blok")


@pytest.fixture
async def gorunmeyen_proje(seeded_db: AsyncSession, project_factory) -> Project:
    """`satinalma_headers` kullanıcısına ASLA erişim verilmeyen proje."""
    return await project_factory(code="SA-P02", name="Liman Altyapı")


@pytest.fixture
async def gorunen_santiye(seeded_db: AsyncSession, gorunen_proje: Project) -> Site:
    site = Site(project_id=gorunen_proje.id, code="SA-A", name="A-Blok Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
async def gorunen_bolum(seeded_db: AsyncSession, gorunen_santiye: Site) -> Section:
    section = Section(site_id=gorunen_santiye.id, code="SA-A-1", name="Kat 6–10 Kaba İnşaat")
    seeded_db.add(section)
    await seeded_db.flush()
    return section


@pytest.fixture
async def gorunmeyen_santiye(seeded_db: AsyncSession, gorunmeyen_proje: Project) -> Site:
    site = Site(project_id=gorunmeyen_proje.id, code="SA-B", name="Liman Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` — `procurement=_A`, `projects=_A` (kapsam süzgecini atlar)."""
    token = await _login(client, user_factory, "system_admin", "admin@satinalma.co")
    return _auth(token)


@pytest.fixture
async def satinalma_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    gorunen_proje: Project,
    gorunmeyen_proje: Project,
) -> dict[str, str]:
    """`procurement` — `procurement=_F`; kapsamı YALNIZ `gorunen_proje`dir.

    `projects=_N` olduğu için `visible_projects` `user_project_access`ten okur;
    `gorunmeyen_proje` bilinçli olarak verilmez.
    """
    email = "satinalma@satinalma.co"
    user = await user_factory(email=email, password="parola1234", role_key="procurement")
    seeded_db.add(
        UserProjectAccess(user_id=user.id, project_id=gorunen_proje.id, all_projects=False)
    )
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return _auth(resp.json()["access_token"])


@pytest.fixture
async def sef_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    gorunen_proje: Project,
) -> dict[str, str]:
    """`site_chief` — `procurement=_REQ`: TALEP açar, TEDARİKÇİ açamaz (403)."""
    email = "sef@satinalma.co"
    user = await user_factory(email=email, password="parola1234", role_key="site_chief")
    seeded_db.add(
        UserProjectAccess(user_id=user.id, project_id=gorunen_proje.id, all_projects=False)
    )
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return _auth(resp.json()["access_token"])


@pytest.fixture
async def yetkisiz_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`accounting` — `procurement=_N`: her uçta 403 (okuma dahil)."""
    token = await _login(client, user_factory, "accounting", "muhasebe@satinalma.co")
    return _auth(token)


@pytest.fixture
def tedarikci_fabrikasi(seeded_db: AsyncSession):
    async def _create(
        name: str,
        *,
        category: str | None = "Demir-Çelik",
        tax_no: str | None = "1234567890",
        phone: str | None = "0212 555 00 01",
        payment_terms: PaymentTerms = PaymentTerms.days_30,
        is_active: bool = True,
    ) -> Supplier:
        supplier = Supplier(
            name=name,
            category=category,
            tax_no=tax_no,
            phone=phone,
            payment_terms=payment_terms,
            is_active=is_active,
        )
        seeded_db.add(supplier)
        await seeded_db.flush()
        return supplier

    return _create


@pytest.fixture
def kart_fabrikasi(seeded_db: AsyncSession):
    """ST malzeme kartı — talep kaleminin "stok kartından seç" bacağı (FST 104)."""

    async def _create(
        code: str,
        name: str = "Nervürlü Demir Ø12",
        *,
        category: StockCategory = StockCategory.steel,
        unit: str = "Ton",
    ) -> StockItem:
        item = StockItem(code=code, name=name, category=category, unit=unit, min_stock=None)
        seeded_db.add(item)
        await seeded_db.flush()
        return item

    return _create


@pytest.fixture
def depo_fabrikasi(seeded_db: AsyncSession):
    """ "Mevcut Stok" türevinin kaynağı — bakiye ST depolarından okunur."""

    async def _create(name: str, *, site: Site | None = None) -> Warehouse:
        warehouse = Warehouse(name=name, site_id=None if site is None else site.id)
        seeded_db.add(warehouse)
        await seeded_db.flush()
        return warehouse

    return _create


@pytest.fixture
def stok_girisi_fabrikasi(seeded_db: AsyncSession):
    """Bakiye üretir: `purchase` hareketi + tek satır (ST `balance.legs` kaynağı)."""

    from datetime import date

    from app.modules.inventory.models import StockEntry, StockEntryLine, StockEntryType

    async def _create(warehouse: Warehouse, item: StockItem, quantity: str) -> StockEntry:
        entry = StockEntry(
            entry_type=StockEntryType.purchase,
            entry_date=date(2026, 7, 20),
            warehouse_id=warehouse.id,
        )
        seeded_db.add(entry)
        await seeded_db.flush()
        seeded_db.add(
            StockEntryLine(entry_id=entry.id, item_id=item.id, quantity=Decimal(quantity))
        )
        await seeded_db.flush()
        return entry

    return _create


@pytest.fixture
async def kullanici_kimligi(seeded_db: AsyncSession):
    """Denetim testleri için: e-postadan kullanıcı kimliği çözer."""

    async def _resolve(email: str) -> uuid.UUID:
        return (await seeded_db.execute(select(User).where(User.email == email))).scalar_one().id

    return _resolve
