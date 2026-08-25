"""H5 fixture'ları: `PUT …/lines` korkulukları — dağıtım, kota ve FF ortamları
(spec §6.5). `tests/progress_payments/conftest.py` bölmesi.

🔴 Bu modül `conftest.py`ye AÇIKÇA import edilir; fixture görünürlüğü ve kapsamı
bölme öncesiyle AYNIDIR.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site
from app.modules.users.models import User

from ._fixtures_base import _dagit

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
