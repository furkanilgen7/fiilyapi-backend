"""`progress_payments` modülüne özgü fixture'lar — H1 (model) + H4 (CRUD/IDOR).

Kök `tests/conftest.py`'deki `db_session`/`seeded_db`/`user_factory`/`project_factory`
üzerine kurulur. Login/erişim fixture'ları `tests/contracts/conftest.py` deseninin
BİREBİRİDİR — pytest sibling `tests/contracts/conftest.py`'yi OTOMATİK yüklemez
(yalnız üst dizin ağacındaki conftest'ler yüklenir), bu yüzden aynı desen burada
YENİDEN kurulur (fixture adları doğrulanır, uydurulmaz).
"""

import itertools
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site
from app.modules.users.models import User, UserProjectAccess


async def _login(client: AsyncClient, user_factory, role_key: str, email: str) -> str:
    await user_factory(email=email, password="parola1234", role_key=role_key)
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- H1 fixture'ları (mevcut, model/migration testleri) ---


@pytest.fixture
async def hakedis_sozlesmesi(
    seeded_db: AsyncSession, project_factory
) -> tuple[Project, ProjectContract]:
    """OLU 92 deseni: sözleşmeli proje — `test_employer_items.py::_contract` varsayılanlarıyla."""
    project = await project_factory(code="PP-001", name="Hakedişli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-010",
        amount=Decimal("11200000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return project, contract


@pytest.fixture
async def hakedis_santiyesi(seeded_db: AsyncSession, hakedis_sozlesmesi) -> Site:
    project, _ = hakedis_sozlesmesi
    site = Site(project_id=project.id, code="SNT-2026-001", name="Test Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
async def hakedis_olusturan(seeded_db: AsyncSession, user_factory) -> User:
    return await user_factory(
        email="olusturan@progress-payments.co", password="parola1234", role_key="system_admin"
    )


# --- H4 fixture'ları: login/erişim (`tests/contracts/conftest.py` deseni) ---


@pytest.fixture
async def admin_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`system_admin` — `projects=_A` admin istisnası sayesinde tüm projeleri görür."""
    token = await _login(client, user_factory, "system_admin", "admin@pp-crud.co")
    return _auth(token)


@pytest.fixture
async def hr_headers(client: AsyncClient, seeded_db: AsyncSession, user_factory) -> dict[str, str]:
    """`hr_manager` — matriste `progress_payments=_N`: 403 beklenir (kapı, görünürlükten ÖNCE)."""
    token = await _login(client, user_factory, "hr_manager", "ik@pp-crud.co")
    return _auth(token)


@pytest.fixture
async def kisitli_proje(seeded_db: AsyncSession, project_factory) -> Project:
    return await project_factory(code="PP-K01", name="Kısıtlı Erişim Projesi")


@pytest.fixture
async def gorunmeyen_proje(seeded_db: AsyncSession, project_factory) -> uuid.UUID:
    """`kisitli_headers`/`site_chief_headers` kullanıcılarına ASLA görünürlük verilmeyen proje."""
    project = await project_factory(code="PP-K02", name="Görünmeyen Proje")
    return project.id


@pytest.fixture
async def kisitli_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    kisitli_proje: Project,
    gorunmeyen_proje: uuid.UUID,
) -> AsyncGenerator[dict[str, str], None]:
    """`project_manager` (`progress_payments=_APR`) ama `user_project_access`

    yalnız `kisitli_proje`'yi kapsar; `gorunmeyen_proje` kapsam DIŞI (spec §9.0
    iki katman: izin=yetki, `user_project_access`=kapsam).
    """
    email = "kisitli@pp-crud.co"
    await user_factory(email=email, password="parola1234", role_key="project_manager")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(
        UserProjectAccess(user_id=user.id, project_id=kisitli_proje.id, all_projects=False)
    )
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    yield _auth(resp.json()["access_token"])


@pytest.fixture
async def site_chief_headers(
    client: AsyncClient,
    seeded_db: AsyncSession,
    user_factory,
    kisitli_proje: Project,
    gorunmeyen_proje: uuid.UUID,
) -> AsyncGenerator[dict[str, str], None]:
    """`site_chief` (`progress_payments=_DRF`, draft/scope=project) — yalnız

    `kisitli_proje`'ye atanmış; `gorunmeyen_proje`de oluşturma denemesi 404
    dönmelidir (403 DEĞİL — spec §9.0, varlık sızdırmaz).
    """
    email = "sefi@pp-crud.co"
    await user_factory(email=email, password="parola1234", role_key="site_chief")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(
        UserProjectAccess(user_id=user.id, project_id=kisitli_proje.id, all_projects=False)
    )
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    yield _auth(resp.json()["access_token"])


# --- H4 fixture'ları: P7'ye özgü veri kurulumu ---


@pytest.fixture
async def sozlesmeli_proje(hakedis_sozlesmesi: tuple[Project, ProjectContract]) -> uuid.UUID:
    project, _ = hakedis_sozlesmesi
    return project.id


@pytest.fixture
async def sozlesmesiz_proje(seeded_db: AsyncSession, project_factory) -> uuid.UUID:
    """Sözleşme kaydı YOK — `NO_EMPLOYER_CONTRACT` 422 testinde kullanılır."""
    project = await project_factory(code="PP-005", name="Sözleşmesiz Proje")
    return project.id


@pytest.fixture
async def taslak_hakedisli_proje(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_olusturan: User,
) -> uuid.UUID:
    """Zaten AÇIK (draft) bir hakedişi olan proje — D8/409 testinde kullanılır."""
    project, contract = hakedis_sozlesmesi
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return project.id


@pytest.fixture
async def onay_bekleyen_hakedis(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_olusturan: User,
) -> uuid.UUID:
    """`pending_approval` durumunda — `PATCH` 409 testinde kullanılır."""
    project, contract = hakedis_sozlesmesi
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.pending_approval,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def gorunmeyen_hakedis(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """Kendi başına bir proje+sözleşme+taslak hakediş — `kisitli_headers`/

    `site_chief_headers` kullanıcılarına HİÇBİR ZAMAN görünmeyen bir projededir.
    """
    project = await project_factory(code="PP-006", name="Görünmeyen Hakedişli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-011",
        amount=Decimal("1000000"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def ikinci_sozlesmeli_proje(
    seeded_db: AsyncSession, project_factory
) -> tuple[Project, ProjectContract]:
    """Y1 (H4 denetimi): `sozlesmeli_proje`'den TAMAMEN ayrı bir ikinci proje —
    çapraz-proje `contract_item_id`/`site_id` IDOR testlerinde "B projesi" olarak
    kullanılır. `admin_headers` (system_admin) HER İKİ projeyi de görür; testin
    amacı yetki DEĞİL, `service._build_lines`'taki sahiplik korkuluğudur."""
    project = await project_factory(code="PP-002", name="İkinci Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-020",
        amount=Decimal("5000000"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return project, contract


@pytest.fixture
async def ikinci_proje_santiyesi(
    seeded_db: AsyncSession, ikinci_sozlesmeli_proje: tuple[Project, ProjectContract]
) -> Site:
    project, _ = ikinci_sozlesmeli_proje
    site = Site(project_id=project.id, code="SNT-2026-002", name="İkinci Proje Şantiyesi")
    seeded_db.add(site)
    await seeded_db.flush()
    return site


@pytest.fixture
async def ikinci_proje_kalemi(
    seeded_db: AsyncSession, ikinci_sozlesmeli_proje: tuple[Project, ProjectContract]
) -> EmployerContractItem:
    project, _ = ikinci_sozlesmeli_proje
    group = EmployerContractGroup(project_id=project.id, name="İkinci Proje Grubu", sort_order=1)
    seeded_db.add(group)
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="03.002",
        description="İkinci proje kalemi",
        unit="m³",
        quantity=Decimal("500"),
        unit_price=Decimal("2000"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    return item


async def _dagit(
    seeded_db: AsyncSession, site: Site, item: EmployerContractItem, quota: Decimal
) -> BoqItem:
    """POZ dağıtımının test karşılığı: (kalem, şantiye) çiftine kota satırı açar.

    H5'in `ITEM_NOT_DISTRIBUTED`/`QUANTITY_EXCEEDS_QUOTA` korkulukları (spec §6.5/1-2)
    tam olarak bu satırın VARLIĞINA ve `quantity`sine bakar.
    """
    group = (
        (await seeded_db.execute(select(BoqGroup).where(BoqGroup.site_id == site.id)))
        .scalars()
        .first()
    )
    if group is None:
        group = BoqGroup(site_id=site.id, name="Dağıtım Grubu", sort_order=1)
        seeded_db.add(group)
        await seeded_db.flush()
    boq = BoqItem(
        site_id=site.id,
        group_id=group.id,
        code=item.code,
        description=item.description,
        unit=item.unit,
        quantity=quota,
        unit_price=item.unit_price,
        contract_item_id=item.id,
    )
    seeded_db.add(boq)
    await seeded_db.flush()
    return boq


@pytest.fixture
async def hakedis_kalemi(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_santiyesi: Site,
) -> tuple[EmployerContractItem, str]:
    """OLU 114/116/119/100 satırı: `03.001` betonarme kalemi — snapshot testinde

    kullanılır. H5'ten itibaren dağıtım ön şartı (§6.5/1) HER yazımda koşar
    (POST'un iç içe `lines[]`'ı dahil, tek yol `lines.py`), bu yüzden kalem
    `hakedis_santiyesi`'ne 1.000 birim kotayla DAĞITILMIŞ olarak kurulur —
    dağıtılmamış hâli için ayrı `dagitilmamis_kalem` fixture'ı vardır.
    """
    project, _ = hakedis_sozlesmesi
    group = EmployerContractGroup(project_id=project.id, name="Betonarme İşleri", sort_order=1)
    seeded_db.add(group)
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="03.001",
        description="Beton C30/37 dökümü",
        unit="m³",
        quantity=Decimal("1000"),
        unit_price=Decimal("1850"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, hakedis_santiyesi, item, Decimal("1000"))
    return item, group.name


# --- H5 fixture'ları: `PUT …/lines` (dağıtım/kota/FF korkulukları, spec §6.5) ---


@pytest.fixture
async def dagitilmamis_kalem(
    seeded_db: AsyncSession, hakedis_sozlesmesi: tuple[Project, ProjectContract]
) -> EmployerContractItem:
    """Sözleşmede VAR ama hiçbir şantiyeye dağıtılmamış kalem — `ITEM_NOT_DISTRIBUTED`."""
    project, _ = hakedis_sozlesmesi
    group = EmployerContractGroup(project_id=project.id, name="Dağıtımsız Grup", sort_order=2)
    seeded_db.add(group)
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="09.999",
        description="Dağıtılmamış poz",
        unit="m²",
        quantity=Decimal("500"),
        unit_price=Decimal("300"),
        sort_order=2,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    return item


@pytest.fixture
async def ikinci_dagitilmis_kalem(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_santiyesi: Site,
) -> EmployerContractItem:
    """Aynı şantiyeye dağıtılmış İKİNCİ kalem — değiştirme semantiği testinde
    gövdeden çıkarılan satırın kaynağıdır."""
    project, _ = hakedis_sozlesmesi
    group = EmployerContractGroup(project_id=project.id, name="Kalıp İşleri", sort_order=3)
    seeded_db.add(group)
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="04.001",
        description="Kalıp yapılması",
        unit="m²",
        quantity=Decimal("800"),
        unit_price=Decimal("450"),
        sort_order=3,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, hakedis_santiyesi, item, Decimal("800"))
    return item


@pytest.fixture
async def taslak_hakedis(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_olusturan: User,
) -> uuid.UUID:
    """`sozlesmeli_proje` üzerinde satırsız `draft` hakediş — `PUT …/lines` hedefi."""
    project, contract = hakedis_sozlesmesi
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def ff_kapali_ortam(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, EmployerContractItem, Site]:
    """`has_price_escalation=False` sözleşme + dağıtılmış kalem + taslak hakediş.

    Spec §10/5: bu sözleşmede `coefficient != 1` gönderimi 422 `ESCALATION_DISABLED`.
    """
    project = await project_factory(code="PP-FF0", name="Fiyat Farksız Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-030",
        amount=Decimal("2000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
        has_price_escalation=False,
    )
    seeded_db.add(contract)
    # `employer_contract_groups.project_id` FK'si `project_contracts`'e bakar —
    # sözleşme grubun ÖNCESİNDE flush edilmelidir.
    await seeded_db.flush()
    site = Site(project_id=project.id, code="SNT-2026-030", name="FF Şantiyesi")
    group = EmployerContractGroup(project_id=project.id, name="FF Grubu", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="05.001",
        description="FF'siz poz",
        unit="m³",
        quantity=Decimal("400"),
        unit_price=Decimal("1000"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("400"))
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id, item, site


@pytest.fixture
async def ff_kapali_hakedissiz_proje(seeded_db: AsyncSession, project_factory) -> uuid.UUID:
    """FF'siz sözleşmeli, HENÜZ HAKEDİŞİ OLMAYAN proje.

    Başlık FF kilidinin (H5 denetimi Y1) `POST …/progress-payments` yolunu test
    eder. `ff_kapali_ortam` bunun için KULLANILAMAZ: orada zaten açık bir taslak
    vardır ve D8 409'u (`OPEN_PAYMENT_EXISTS`) FF 422'sinden ÖNCE koşar.
    """
    project = await project_factory(code="PP-FF1", name="Hakedişsiz FF'siz Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-031",
        amount=Decimal("1500000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
        has_price_escalation=False,
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return project.id


async def _gecmisli_ortam(
    seeded_db: AsyncSession,
    project_factory,
    olusturan: User,
    *,
    code: str,
    onceki_durum: ProgressPaymentStatus,
    onceki_miktar: Decimal,
) -> tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem]:
    """Kota testlerinin ortak kurulumu: kotası 1.000 olan bir (kalem, şantiye)
    çiftinde `onceki_durum` durumunda 1 no'lu hakediş (`onceki_miktar` miktarlı)
    + üzerine yazılacak 2 no'lu `draft` hakediş.

    Dördüncü öğe: AYNI şantiyeye dağıtılmış, geçmişi olmayan ikinci kalem —
    atomiklik testinde "gövdedeki geçerli ilk satır" olarak kullanılır.
    """
    project = await project_factory(code=code, name=f"Geçmişli Proje {code}")
    contract = ProjectContract(
        project_id=project.id,
        contract_no=f"SZL-{code}",
        amount=Decimal("5000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()  # FK: sözleşme grubu `project_contracts`'e bağlıdır
    site = Site(project_id=project.id, code=f"SNT-{code}", name="Geçmişli Şantiye")
    group = EmployerContractGroup(project_id=project.id, name="Geçmiş Grubu", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="06.001",
        description="Kotalı poz",
        unit="m³",
        quantity=Decimal("1000"),
        unit_price=Decimal("100"),
        sort_order=1,
    )
    ikinci_item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="06.002",
        description="Geçmişsiz poz",
        unit="m²",
        quantity=Decimal("500"),
        unit_price=Decimal("50"),
        sort_order=2,
    )
    seeded_db.add_all([item, ikinci_item])
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("1000"))
    await _dagit(seeded_db, site, ikinci_item, Decimal("500"))

    onceki = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=onceki_durum,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=olusturan.id,
    )
    onceki.lines = [
        ProgressPaymentLine(
            contract_item_id=item.id,
            site_id=site.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=onceki_miktar,
            group_name=group.name,
        )
    ]
    guncel = ProgressPayment(
        project_id=project.id,
        sequence_no=2,
        status=ProgressPaymentStatus.draft,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=olusturan.id,
    )
    seeded_db.add_all([onceki, guncel])
    await seeded_db.flush()
    return guncel.id, item, site, ikinci_item


# --- H6 fixture'ları: durum geçişleri (spec §7) ---


@pytest.fixture
async def muhasebe_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`accounting` — matriste `progress_payments=_APR` (onay seviyesi).

    `all_projects=True` erişimiyle kurulur: bu fixture'ın testleri YETKİ
    seviyesini (approve var, admin YOK) ölçer, kapsamı değil — kapsam testleri
    `kisitli_headers` ile ayrıca koşar.
    """
    email = "muhasebe@pp-transitions.co"
    await user_factory(email=email, password="parola1234", role_key="accounting")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return _auth(resp.json()["access_token"])


@pytest.fixture
async def saha_headers(
    client: AsyncClient, seeded_db: AsyncSession, user_factory
) -> dict[str, str]:
    """`field_engineer` — matriste `progress_payments=_DRF` (taslak seviyesi,
    scope=project): kendi projesinde `submit` yapabilir, `approve` yapamaz."""
    email = "saha@pp-transitions.co"
    await user_factory(email=email, password="parola1234", role_key="field_engineer")
    user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
    seeded_db.add(UserProjectAccess(user_id=user.id, project_id=None, all_projects=True))
    await seeded_db.flush()
    resp = await client.post("/auth/login", json={"email": email, "password": "parola1234"})
    assert resp.status_code == 200, resp.text
    return _auth(resp.json()["access_token"])


@pytest.fixture
async def hakedis_fabrikasi(
    seeded_db: AsyncSession,
    hakedis_sozlesmesi: tuple[Project, ProjectContract],
    hakedis_santiyesi: Site,
    hakedis_kalemi: tuple[EmployerContractItem, str],
    hakedis_olusturan: User,
):
    """İstenen DURUMDA hakediş üreten fabrika — geçiş matrisi testinin dayanağı.

    D8 "tek açık hakediş" uygulama kontrolünün DB karşılığı YOKTUR (spec §7
    devir notu); bu fabrika bilinçli olarak doğrudan DB'ye yazar, böylece
    "aynı projede iki açık hakediş" tehlikesi de kurulabilir. `sequence_no`
    her çağrıda artar (`uq_progress_payments_project_sequence`).
    """
    project, contract = hakedis_sozlesmesi
    item, group_name = hakedis_kalemi
    sequence = itertools.count(1)

    async def _olustur(
        durum: ProgressPaymentStatus,
        *,
        donem: bool = True,
        miktar: Decimal | None = Decimal("100"),
    ) -> uuid.UUID:
        payment = ProgressPayment(
            project_id=project.id,
            sequence_no=next(sequence),
            status=durum,
            period_year=2026 if donem else None,
            period_month=3 if donem else None,
            vat_pct=contract.vat_pct,
            advance_pct=contract.advance_pct,
            retainage_pct=contract.retainage_pct,
            created_by=hakedis_olusturan.id,
        )
        if miktar is not None:
            payment.lines = [
                ProgressPaymentLine(
                    contract_item_id=item.id,
                    site_id=hakedis_santiyesi.id,
                    code=item.code,
                    description=item.description,
                    unit=item.unit,
                    contract_unit_price=item.unit_price,
                    coefficient=Decimal("1.000"),
                    quantity=miktar,
                    group_name=group_name,
                )
            ]
        seeded_db.add(payment)
        await seeded_db.flush()
        return payment.id

    return _olustur


@pytest.fixture
async def gecerli_taslak(hakedis_fabrikasi) -> uuid.UUID:
    """Onaya gönderilmeye HAZIR taslak: dönem dolu + Σ miktar > 0 + sözleşme
    bedeli dolu (`hakedis_sozlesmesi.amount = 11.200.000`)."""
    return await hakedis_fabrikasi(ProgressPaymentStatus.draft)


@pytest.fixture
async def bedelsiz_sozlesmede_taslak(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """`contract.amount IS NULL` (taslak sözleşme) + dönem + satır dolu taslak.

    §6.3 avans tavanı uygulanamadığı için `submit` 422 `CONTRACT_AMOUNT_REQUIRED`
    vermelidir — dönem/satır kuralları GEÇİLDİKTEN sonra (sıra kanıtı).
    """
    project = await project_factory(code="PP-T00", name="Bedelsiz Sözleşmeli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-040",
        amount=None,
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    site = Site(project_id=project.id, code="SNT-2026-040", name="Bedelsiz Şantiye")
    group = EmployerContractGroup(project_id=project.id, name="Bedelsiz Grup", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="07.001",
        description="Bedelsiz sözleşme pozu",
        unit="m³",
        quantity=Decimal("300"),
        unit_price=Decimal("500"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("300"))
    payment = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        period_year=2026,
        period_month=3,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    payment.lines = [
        ProgressPaymentLine(
            contract_item_id=item.id,
            site_id=site.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=Decimal("50"),
            group_name=group.name,
        )
    ]
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def kisitli_projede_onay_bekleyen(
    seeded_db: AsyncSession, kisitli_proje: Project, hakedis_olusturan: User
) -> uuid.UUID:
    """`site_chief_headers`/`kisitli_headers` kullanıcılarının GÖRDÜĞÜ projede
    `pending_approval` hakediş.

    Kapının görünürlükten ÖNCE çalıştığını kanıtlayan testler için şart: kayıt
    görünmeseydi 403 ile 404 ayırt edilemezdi.
    """
    contract = ProjectContract(
        project_id=kisitli_proje.id,
        contract_no="SZL-2026-050",
        amount=Decimal("3000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    payment = ProgressPayment(
        project_id=kisitli_proje.id,
        sequence_no=1,
        status=ProgressPaymentStatus.pending_approval,
        period_year=2026,
        period_month=3,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def kota_bolusen_iki_hakedis(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, uuid.UUID]:
    """H5'ten DEVREDİLEN zorunluluğun senaryosu (H5 denetimi O2).

    Aynı (kalem, şantiye) çiftinde kota 1.000; AYNI ANDA açık iki
    `pending_approval` hakediş, her biri 600 birim. Her biri TEK BAŞINA kotaya
    sığar (yazma anındaki kontrol ikisini de geçirir, çünkü o kontrol yalnız
    `approved|paid` kümesine bakar); ikisi de onaylanırsa toplam 1.200 > 1.000
    olur. Kotanın nihai bekçisi bu yüzden ONAY anıdır.
    """
    project = await project_factory(code="PP-Q03", name="Kota Bölüşen Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-PP-Q03",
        amount=Decimal("5000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    site = Site(project_id=project.id, code="SNT-PP-Q03", name="Kota Şantiyesi")
    group = EmployerContractGroup(project_id=project.id, name="Kota Grubu", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="08.001",
        description="Kota bölüşen poz",
        unit="m³",
        quantity=Decimal("1000"),
        unit_price=Decimal("100"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("1000"))

    payment_ids: list[uuid.UUID] = []
    for sequence_no in (1, 2):
        payment = ProgressPayment(
            project_id=project.id,
            sequence_no=sequence_no,
            status=ProgressPaymentStatus.pending_approval,
            period_year=2026,
            period_month=sequence_no,
            vat_pct=contract.vat_pct,
            advance_pct=contract.advance_pct,
            retainage_pct=contract.retainage_pct,
            created_by=hakedis_olusturan.id,
        )
        payment.lines = [
            ProgressPaymentLine(
                contract_item_id=item.id,
                site_id=site.id,
                code=item.code,
                description=item.description,
                unit=item.unit,
                contract_unit_price=item.unit_price,
                coefficient=Decimal("1.000"),
                quantity=Decimal("600"),
                group_name=group.name,
            )
        ]
        seeded_db.add(payment)
        await seeded_db.flush()
        payment_ids.append(payment.id)
    return payment_ids[0], payment_ids[1]


@pytest.fixture
async def onayli_gecmisli_ortam(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem]:
    """Önceki hakediş `approved` ve 600 birim: kalan kota 400 (spec §6.5/2)."""
    return await _gecmisli_ortam(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-Q01",
        onceki_durum=ProgressPaymentStatus.approved,
        onceki_miktar=Decimal("600"),
    )


@pytest.fixture
async def taslak_gecmisli_ortam(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, EmployerContractItem, Site, EmployerContractItem]:
    """Önceki hakediş `draft` ve 600 birim: kümülatif kümeye GİRMEZ (§6.6
    `prev = approved|paid`), kalan kota yine 1.000."""
    return await _gecmisli_ortam(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-Q02",
        onceki_durum=ProgressPaymentStatus.draft,
        onceki_miktar=Decimal("600"),
    )
