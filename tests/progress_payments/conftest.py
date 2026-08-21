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

from app.modules.approvals.models import ApprovalRole, UserApprovalRole
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
async def ters_sirali_onayli_gecmis(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, EmployerContractItem, Site]:
    """H6 denetimi K1 — kota kümesinin SIRASIZ olduğunu ölçen kurulum.

    Kota 1.000; `sequence_no=2` hakediş ONAYLI (600 birim), `sequence_no=1`
    hakediş TASLAK. Sıra tabanlı bir kota okuması taslağın (seq 1) onaylı
    kaydı (seq 2) "önceki" saymamasına yol açar ve 1.000'e kadar yazmaya izin
    verirdi; sırasız tam küme 600 + yazılan > 1.000 olduğunda 422 verir.

    Durum geçiş uçlarıyla kurulamaz (D8 tek açık hakediş kuralı ile seq 1'in
    taslak, seq 2'nin onaylı olduğu bu diziliş meşru uçlardan ancak
    `unapprove`+`reject` zinciriyle üretilebilir — o zinciri
    `test_transitions.py` uçtan uca ayrıca koşar); burada doğrudan DB kurulumu
    testin ÖLÇTÜĞÜ şey değil, ÖN KOŞULUDUR.
    """
    project = await project_factory(code="PP-Q04", name="Ters Sıralı Onay Projesi")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-PP-Q04",
        amount=Decimal("5000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    site = Site(project_id=project.id, code="SNT-PP-Q04", name="Ters Sıra Şantiyesi")
    group = EmployerContractGroup(project_id=project.id, name="Ters Sıra Grubu", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="10.001",
        description="Ters sıralı poz",
        unit="m³",
        quantity=Decimal("1000"),
        unit_price=Decimal("100"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("1000"))

    taslak = ProgressPayment(
        project_id=project.id,
        sequence_no=1,
        status=ProgressPaymentStatus.draft,
        period_year=2026,
        period_month=1,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    onayli = ProgressPayment(
        project_id=project.id,
        sequence_no=2,
        status=ProgressPaymentStatus.approved,
        period_year=2026,
        period_month=2,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        created_by=hakedis_olusturan.id,
    )
    onayli.lines = [
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
    seeded_db.add_all([taslak, onayli])
    await seeded_db.flush()
    return taslak.id, item, site


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


# --- H8 fixture'ları: silme + `sites` RESTRICT korkuluğu (spec §7.1) ---


@pytest.fixture
async def sef_kullanicisi(seeded_db: AsyncSession, site_chief_headers: dict[str, str]) -> User:
    """`site_chief_headers`in giriş yaptığı kullanıcının kaydı — `can_delete`in

    `created_by` karşılaştırması için gerçek `User.id` gerekir (fixture yalnız
    header döner). `site_chief_headers` bağımlılığı kullanıcıyı ÖNCE oluşturur.
    """
    return (
        await seeded_db.execute(select(User).where(User.email == "sefi@pp-crud.co"))
    ).scalar_one()


@pytest.fixture
async def kisitli_kullanicisi(seeded_db: AsyncSession, kisitli_headers: dict[str, str]) -> User:
    """`kisitli_headers`in kullanıcısı — şeften FARKLI bir "başkası" olarak

    "şef başkasının taslağını silemez" testinde `created_by` doldurmak için.
    """
    return (
        await seeded_db.execute(select(User).where(User.email == "kisitli@pp-crud.co"))
    ).scalar_one()


@pytest.fixture
async def _kisitli_proje_sozlesmesi(
    seeded_db: AsyncSession, kisitli_proje: Project
) -> ProjectContract:
    """`kisitli_proje`nin `progress_payments.project_id` FK'sinin hedef aldığı

    `project_contracts` satırı (`project_contracts.project_id` PK/FK'tir) —
    `kisitli_proje` çıplak proje olarak kurulur, sözleşmesiz projeye hakediş
    YAZILAMAZ (`progress_payments_project_id_fkey`). `kisitli_projede_onay_
    bekleyen` deseninin aynısı, TEK KOPYA (iki H8 fixture'ı da bunu paylaşır).
    """
    contract = ProjectContract(
        project_id=kisitli_proje.id,
        contract_no="SZL-2026-060",
        amount=Decimal("2000000"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    return contract


@pytest.fixture
async def kendi_taslagi(
    seeded_db: AsyncSession,
    kisitli_proje: Project,
    sef_kullanicisi: User,
    _kisitli_proje_sozlesmesi: ProjectContract,
) -> uuid.UUID:
    """`kisitli_proje`de şefin KENDİ taslağı — `can_delete` taslak istisnasının

    pozitif hücresi (`created_by == actor AND is_draft`, spec §7.1/2).
    """
    payment = ProgressPayment(
        project_id=kisitli_proje.id,
        sequence_no=101,
        status=ProgressPaymentStatus.draft,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        created_by=sef_kullanicisi.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def baskasinin_taslagi(
    seeded_db: AsyncSession,
    kisitli_proje: Project,
    kisitli_kullanicisi: User,
    _kisitli_proje_sozlesmesi: ProjectContract,
) -> uuid.UUID:
    """`kisitli_proje`de BAŞKASININ (şef değil) taslağı — aynı projeyi gören

    ama taslağı AÇMAMIŞ bir şef için `can_delete` reddetmelidir (spec §7.1/2:
    "yalnız kaydı AÇAN aktör").
    """
    payment = ProgressPayment(
        project_id=kisitli_proje.id,
        sequence_no=102,
        status=ProgressPaymentStatus.draft,
        vat_pct=Decimal("20"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        created_by=kisitli_kullanicisi.id,
    )
    seeded_db.add(payment)
    await seeded_db.flush()
    return payment.id


@pytest.fixture
async def hakedisli_santiye(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """Yalnız hakediş satırı taşıyan (BOQ dağıtımı OLMAYAN) şantiye — `sites`

    RESTRICT korkuluğu testinin ön koşulu (spec §4.2, `progress_payment_lines.
    site_id` RESTRICT). `hakedis_santiyesi`/`hakedis_kalemi` BİLİNÇLİ OLARAK
    kullanılmaz: o fixture zinciri `_dagit` ile bir `BoqItem` de açar, bu da
    `sites.service.delete_site`'ın SIRADAKİ ilk korkuluğu olan `site_has_boq`yu
    da tetikler ve bu testin ÖLÇMEK istediği `SITE_HAS_PROGRESS_PAYMENTS`
    dalına hiç ulaşılmaz (fixture içindeki `_dagit` yorumunu doğrulayan ayrı
    bir kurulum gerekir). Durum ÖNEMSİZ (taslak bile RESTRICT'i tetikler, FK
    hangi durumda olursa olsun aynı satırı hedefler).
    """
    project = await project_factory(code="PP-H8-RESTRICT", name="Yalnız Hakedişli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-2026-070",
        amount=Decimal("1000000"),
        advance_pct=Decimal("10"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    site = Site(project_id=project.id, code="SNT-H8-RESTRICT", name="Yalnız Hakedişli Şantiye")
    seeded_db.add_all([contract, site])
    await seeded_db.flush()
    group = EmployerContractGroup(project_id=project.id, name="H8 Grubu", sort_order=1)
    seeded_db.add(group)
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="11.001",
        description="H8 RESTRICT pozu",
        unit="m³",
        quantity=Decimal("100"),
        unit_price=Decimal("1000"),
        sort_order=1,
    )
    seeded_db.add(item)
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
    payment.lines = [
        ProgressPaymentLine(
            contract_item_id=item.id,
            site_id=site.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=Decimal("1.000"),
            quantity=Decimal("10"),
            group_name=group.name,
        )
    ]
    seeded_db.add(payment)
    await seeded_db.flush()
    return site.id


# --- H9 fixture'ları: özet ucu + `contracts` placeholder'ları (spec §9.6) ---


async def _ozet_ortami(
    seeded_db: AsyncSession,
    project_factory,
    olusturan: User,
    *,
    code: str,
    amount: Decimal | None,
    plan: list[tuple[ProgressPaymentStatus, Decimal | None]],
    advance_pct: Decimal = Decimal("20"),
    unit_price: Decimal = Decimal("100"),
) -> tuple[Project, Site, EmployerContractItem]:
    """Özet testlerinin ortak kurulumu: `plan` sırasıyla `sequence_no` 1..n
    hakediş üretir; her öğe `(durum, miktar)` — miktar `None` ise satırsız.

    Durum geçiş uçlarıyla kurulamaz (D8 tek açık hakediş kuralı birden çok
    `pending_approval` kaydı meşru uçlardan üretilmesini engeller; SHK 84 ise
    "Onay Bekleyen 3" der): kurulum testin ÖLÇTÜĞÜ şey değil, ÖN KOŞULUDUR.
    """
    project = await project_factory(code=code, name=f"Özet Projesi {code}")
    contract = ProjectContract(
        project_id=project.id,
        contract_no=f"SZL-{code}",
        amount=amount,
        advance_pct=advance_pct,
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    site = Site(project_id=project.id, code=f"SNT-{code}", name=f"Özet Şantiyesi {code}")
    group = EmployerContractGroup(project_id=project.id, name="Özet Grubu", sort_order=1)
    seeded_db.add_all([site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="03.001",
        description="Özet pozu",
        unit="m³",
        quantity=Decimal("100000"),
        unit_price=unit_price,
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, site, item, Decimal("100000"))

    for sequence_no, (durum, miktar) in enumerate(plan, start=1):
        payment = ProgressPayment(
            project_id=project.id,
            sequence_no=sequence_no,
            status=durum,
            period_year=2026,
            period_month=((sequence_no - 1) % 12) + 1,
            vat_pct=contract.vat_pct,
            advance_pct=contract.advance_pct,
            retainage_pct=contract.retainage_pct,
            created_by=olusturan.id,
        )
        if miktar is not None:
            payment.lines = [
                ProgressPaymentLine(
                    contract_item_id=item.id,
                    site_id=site.id,
                    code=item.code,
                    description=item.description,
                    unit=item.unit,
                    contract_unit_price=item.unit_price,
                    coefficient=Decimal("1.000"),
                    quantity=miktar,
                    group_name=group.name,
                )
            ]
        seeded_db.add(payment)
        await seeded_db.flush()
    return project, site, item


@pytest.fixture
async def dort_onayli_hakedisli_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """E14 127-147 altın senaryosu: bedel 11.200.000 · 4 tamamlanmış hakediş
    (3 `approved` + 1 `paid`), her biri 21.000 × ₺100 = 2.100.000 brüt →
    kümülatif 8.400.000 (%75)."""
    project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S01",
        amount=Decimal("11200000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.paid, Decimal("21000")),
        ],
    )
    return project.id


@pytest.fixture
async def karisik_durumlu_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """SHK 82/84 sayaçları: 4 tamamlanmış (3 `approved` + 1 `paid`) + 3
    `pending_approval` + 1 `draft`."""
    project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S02",
        amount=Decimal("11200000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.paid, Decimal("21000")),
            (ProgressPaymentStatus.pending_approval, Decimal("5000")),
            (ProgressPaymentStatus.pending_approval, Decimal("5000")),
            (ProgressPaymentStatus.pending_approval, Decimal("5000")),
            (ProgressPaymentStatus.draft, Decimal("5000")),
        ],
    )
    return project.id


@pytest.fixture
async def taslakli_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """1 `approved` (2.100.000) + 1 `draft` (2.100.000): kümülatif YALNIZ
    onaylıyı sayar (spec §6.6 `prev` kümesi)."""
    project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S03",
        amount=Decimal("11200000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.draft, Decimal("21000")),
        ],
    )
    return project.id


@pytest.fixture
async def avans_tavanina_dayanan_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> uuid.UUID:
    """§6.3 kümülatif TAVAN özette de koşar: bedel 1.000.000 · avans %20 →
    tavan 200.000. İki onaylı hakediş, her biri 800.000 brüt: ilki 160.000
    kesinti alır, ikincisi tavanda kalan 40.000'i alır → toplam 200.000.
    Basit toplam (`Σ gross × %20`) 320.000 verirdi."""
    project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S04",
        amount=Decimal("1000000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("8000")),
            (ProgressPaymentStatus.approved, Decimal("8000")),
        ],
    )
    return project.id


@pytest.fixture
async def iki_projeli_ozet_ortami(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, uuid.UUID]:
    """Toplu (batch) çekimin GRUPLAMA doğruluğu için: iki ayrı proje, farklı
    tutarlarda tamamlanmış hakedişler. Gruplama anahtarı yanlışsa sayılar
    projeler arasında karışır."""
    a_project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S05A",
        amount=Decimal("11200000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("21000")),
            (ProgressPaymentStatus.approved, Decimal("21000")),
        ],
    )
    b_project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S05B",
        amount=Decimal("5000000"),
        plan=[(ProgressPaymentStatus.approved, Decimal("3000"))],
    )
    return a_project.id, b_project.id


@pytest.fixture
async def iki_santiyeli_cok_hakedisli_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """`(proje, şantiye)` kırılımı: TEK projede iki şantiye, üç tamamlanmış
    hakediş; her hakediş iki şantiyeye de satır yazar. Toplu çekimin
    gruplaması şantiye düzeyinde de doğru olmalı (E15 "Önceki" kolonu).

    Dönüş: `(project_id, a_site_id, b_site_id)`.
    """
    project = await project_factory(code="PP-S06", name="İki Şantiyeli Proje")
    contract = ProjectContract(
        project_id=project.id,
        contract_no="SZL-PP-S06",
        amount=Decimal("10000000"),
        advance_pct=Decimal("20"),
        retainage_pct=Decimal("5"),
        vat_pct=Decimal("20"),
    )
    seeded_db.add(contract)
    await seeded_db.flush()
    a_site = Site(project_id=project.id, code="SNT-PP-S06-A", name="A-Blok")
    b_site = Site(project_id=project.id, code="SNT-PP-S06-B", name="B-Blok")
    group = EmployerContractGroup(project_id=project.id, name="Betonarme İşleri", sort_order=1)
    seeded_db.add_all([a_site, b_site, group])
    await seeded_db.flush()
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code="03.001",
        description="Beton dökümü",
        unit="m³",
        quantity=Decimal("100000"),
        unit_price=Decimal("100"),
        sort_order=1,
    )
    seeded_db.add(item)
    await seeded_db.flush()
    await _dagit(seeded_db, a_site, item, Decimal("50000"))
    await _dagit(seeded_db, b_site, item, Decimal("50000"))

    # A şantiyesi her hakedişte 100, B şantiyesi 10 birim: karışırsa sayılar tutmaz.
    for sequence_no in (1, 2, 3):
        payment = ProgressPayment(
            project_id=project.id,
            sequence_no=sequence_no,
            status=ProgressPaymentStatus.approved,
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
                site_id=a_site.id,
                code=item.code,
                description=item.description,
                unit=item.unit,
                contract_unit_price=item.unit_price,
                coefficient=Decimal("1.000"),
                quantity=Decimal("100"),
                group_name=group.name,
            ),
            ProgressPaymentLine(
                contract_item_id=item.id,
                site_id=b_site.id,
                code=item.code,
                description=item.description,
                unit=item.unit,
                contract_unit_price=item.unit_price,
                coefficient=Decimal("1.000"),
                quantity=Decimal("10"),
                group_name=group.name,
            ),
        ]
        seeded_db.add(payment)
        await seeded_db.flush()
    return project.id, a_site.id, b_site.id


@pytest.fixture
async def tavana_dayanan_iki_proje(
    seeded_db: AsyncSession, project_factory, hakedis_olusturan: User
) -> tuple[uuid.UUID, uuid.UUID]:
    """Toplu çekimin gruplamasını AVANS TAVANI üzerinden ölçen kurulum.

    A projesi: bedel 1.000.000, avans %20 → tavan 200.000; iki onaylı hakediş,
    her biri 800.000 brüt. A#2'nin kesintisi tavanda kalan 40.000'dir.
    B projesi: bedel 5.000.000 (tavan 1.000.000), `sequence_no=1` onaylı hakediş
    800.000 brüt → 160.000 kesinti.

    Gruplama anahtarı yanlışsa (ya da sıra eşiği kendi kaydını içeriyorsa) A#2'nin
    "önceki" kümesi şişer, tavan aşılmış sayılır ve kesinti 40.000 yerine 0 olur —
    brüt/teminat değişmediği için fark YALNIZ avans üzerinden görünür. Kümülatif
    tavan olmasaydı bu iki hata da sessiz kalırdı.
    """
    a_project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S07A",
        amount=Decimal("1000000"),
        plan=[
            (ProgressPaymentStatus.approved, Decimal("8000")),
            (ProgressPaymentStatus.approved, Decimal("8000")),
        ],
    )
    b_project, _, _ = await _ozet_ortami(
        seeded_db,
        project_factory,
        hakedis_olusturan,
        code="PP-S07B",
        amount=Decimal("5000000"),
        plan=[(ProgressPaymentStatus.approved, Decimal("8000"))],
    )
    return a_project.id, b_project.id


@pytest.fixture
async def zincir_onaycilari(
    seeded_db: AsyncSession, admin_headers: dict[str, str], muhasebe_headers: dict[str, str]
) -> None:
    """🔴 OK-1A T3 — `submit`ten GEÇEN akışların ONAY ROLÜ ihtiyacı.

    Bu modülün fabrikaları hakedişi doğrudan DB'ye yazar (durumu elle verir), o
    yüzden zincirleri YOKTUR ve bugünkü tek adımlı davranışları sürer. Ama
    `submit` → `approve` sırasını UÇTAN koşan testlerde artık gerçek bir zincir
    açılır ve `/approve` aktörden ADIM ROLÜNÜ ister (uç kapısı `progress_
    payments ≥ approve` yetmez — onay rolü ≠ sistem rolü, K1).

    Fixture bunu OPT-IN bırakır (autouse DEĞİL): rolü olmayan aktörün 403
    aldığını ölçen testler (`test_onay_ROLU_olmayan_aktor_403`) aynı
    `muhasebe_headers`ı KULLANIR ve sessizce yeşile boyanmamalıdır.

    Verilen tek rol `accounting`tir: işveren hakedişi zincirinin eşik ALTI tek
    adımı odur (mockup `Onay Kutusu.dc.html:210-240`). `patron` bilinçli olarak
    VERİLMEZ — eşik üstü akışlar kendi aktörünü kurar.
    """
    for email in ("admin@pp-crud.co", "muhasebe@pp-transitions.co"):
        user = (await seeded_db.execute(select(User).where(User.email == email))).scalar_one()
        seeded_db.add(UserApprovalRole(user_id=user.id, approval_role=ApprovalRole.accounting))
    await seeded_db.flush()
