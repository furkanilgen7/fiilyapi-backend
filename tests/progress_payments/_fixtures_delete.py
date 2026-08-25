"""H8 fixture'ları: silme + `sites` RESTRICT korkuluğu (spec §7.1).
`tests/progress_payments/conftest.py` bölmesi.

🔴 Bu modül `conftest.py`ye AÇIKÇA import edilir; fixture görünürlüğü ve kapsamı
bölme öncesiyle AYNIDIR.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
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
