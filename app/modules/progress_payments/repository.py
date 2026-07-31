"""İşveren hakedişi (P7) okuma/yazma sorguları — task H4.

`contracts/repository.py` deseninin aynısı: filtreler SQL düzeyinde uygulanır,
kapsam (`visible_project_ids`) her zaman çağıran servisten gelir — bu modül
KENDİSİ görünürlük kararı VERMEZ (spec §9.0, `contracts/service.py._visible_project`
deseni).
"""

import uuid
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqItem
from app.modules.contracts.models import EmployerContractGroup, EmployerContractItem
from app.modules.progress_payments.models import (
    ProgressPayment,
    ProgressPaymentLine,
    ProgressPaymentStatus,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.sites.models import Site

# D8: "açık" hakediş — henüz onaylanmamış/reddedilmemiş taslak veya onay bekleyen.
OPEN_STATUSES = (ProgressPaymentStatus.draft, ProgressPaymentStatus.pending_approval)
# §6.6/§6.3: "tamamlanmış" hakedişler — kümülatif türevlerin ve avans mahsubu
# tavanının dayandığı küme (D8 sayesinde nettir).
COMPLETED_STATUSES = (ProgressPaymentStatus.approved, ProgressPaymentStatus.paid)


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> ProgressPayment | None:
    """`lines` `lazy="selectin"` olduğu için ek sorgu YOK."""
    return await session.get(ProgressPayment, payment_id)


async def get_contract_locked(
    session: AsyncSession, project_id: uuid.UUID
) -> ProjectContract | None:
    """D8 + `sequence_no` üretiminin dayandığı kilit satırı (spec §7 eşzamanlılık
    notunun oluşturmaya izdüşümü). `SELECT … FOR UPDATE`: aynı projede iki eşzamanlı
    `POST` bu satırda sıraya girer, ikisi de aynı `sequence_no`'yu ÜRETEMEZ ve D8
    kontrolünü aynı anda GEÇEMEZ. Sözleşme yoksa `None` — çağıran `NO_EMPLOYER_CONTRACT`'a
    çevirir.
    """
    stmt = select(ProjectContract).where(ProjectContract.project_id == project_id).with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_open_payment(session: AsyncSession, project_id: uuid.UUID) -> ProgressPayment | None:
    """D8: bu sözleşmede zaten açık (draft/pending_approval) bir hakediş var mı?

    `get_contract_locked` ile AYNI transaction'da, kilit ALINDIKTAN SONRA
    çağrılmalıdır (spec §7 eşzamanlılık notu) — aksi halde iki eşzamanlı `POST`
    ikisi de bu kontrolü boşken geçebilir.
    """
    stmt = select(ProgressPayment).where(
        ProgressPayment.project_id == project_id,
        ProgressPayment.status.in_(OPEN_STATUSES),
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_next_sequence_no(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Proje içi maks+1 (proje kodu deseni, kalıcı karar 9). Kilitli sözleşme
    satırı sayesinde bu sorgu da eşzamanlılık güvenlidir (spec §7)."""
    stmt = select(func.max(ProgressPayment.sequence_no)).where(
        ProgressPayment.project_id == project_id
    )
    current_max = (await session.execute(stmt)).scalar_one_or_none()
    return (current_max or 0) + 1


async def list_payments(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
    status_filter: ProgressPaymentStatus | None,
) -> list[tuple[ProgressPayment, Project]]:
    """SHK 93-113 listesi (spec §9.1). `site_id` filtresi satırlarda `EXISTS` ile
    uygulanır — kayıt tek, iki görünüm (D1): hakediş projeye bağlıdır, şantiye
    kırılımı yalnız satır düzeyindedir.
    """
    if not visible_project_ids:
        return []
    stmt = (
        select(ProgressPayment, Project)
        .join(Project, Project.id == ProgressPayment.project_id)
        .where(ProgressPayment.project_id.in_(visible_project_ids))
        .order_by(Project.code, ProgressPayment.sequence_no)
    )
    if project_id is not None:
        stmt = stmt.where(ProgressPayment.project_id == project_id)
    if status_filter is not None:
        stmt = stmt.where(ProgressPayment.status == status_filter)
    if site_id is not None:
        stmt = stmt.where(
            exists().where(
                ProgressPaymentLine.payment_id == ProgressPayment.id,
                ProgressPaymentLine.site_id == site_id,
            )
        )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def list_prior_completed_payments(
    session: AsyncSession, project_id: uuid.UUID, before_sequence_no: int
) -> list[ProgressPayment]:
    """Önceki tamamlanmış hakedişler, sıra ARTAN (spec §6.3 avans tavanı zinciri +
    §6.6/§8 kümülatif türevler). D8 sayesinde küme nettir — "önceki" belirsizliği
    yoktur. `lines` `lazy="selectin"` ile birlikte gelir, ek sorgu YOK.
    """
    stmt = (
        select(ProgressPayment)
        .where(
            ProgressPayment.project_id == project_id,
            ProgressPayment.status.in_(COMPLETED_STATUSES),
            ProgressPayment.sequence_no < before_sequence_no,
        )
        .order_by(ProgressPayment.sequence_no)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_site(session: AsyncSession, site_id: uuid.UUID) -> Site | None:
    return await session.get(Site, site_id)


async def get_sites_by_ids(
    session: AsyncSession, site_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Site]:
    """Satır doğrulamasının şantiye sahipliği kontrolü (spec §6.5/3) — gövdedeki
    TÜM şantiyeler TEK sorguda okunur (satır başına `session.get` N+1 olurdu)."""
    if not site_ids:
        return {}
    stmt = select(Site).where(Site.id.in_(site_ids))
    result = await session.execute(stmt)
    return {site.id: site for site in result.scalars().all()}


async def get_distributed_quotas(
    session: AsyncSession, item_ids: list[uuid.UUID], site_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    """(kalem, şantiye) → dağıtılmış BOQ kotası (spec §6.5/1-2).

    Sözlükte ANAHTARIN BULUNMAMASI "bu çift dağıtılmamış" demektir
    (`ITEM_NOT_DISTRIBUTED`); değeri ise kota tavanıdır (`QUANTITY_EXCEEDS_QUOTA`).
    `uq_boq_items_contract_item_site` kısmi benzersiz indeksi çift başına en fazla
    bir satır garanti eder (`boq/models.py:75-81`) — toplama gerekmez.
    """
    if not item_ids or not site_ids:
        return {}
    stmt = select(BoqItem.contract_item_id, BoqItem.site_id, BoqItem.quantity).where(
        BoqItem.contract_item_id.in_(item_ids), BoqItem.site_id.in_(site_ids)
    )
    result = await session.execute(stmt)
    return {(row[0], row[1]): row[2] for row in result.all()}


async def get_employer_items_with_group_by_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[EmployerContractItem, str | None]]:
    """Satır snapshot'ı (spec §4.2/§5) için: kalem + grup adı TEK sorguda.

    `EmployerContractItem`'da `group` ilişkisi tanımlı DEĞİL (yalnız `group_id`
    FK) — `group_name` snapshot'ı için açık `JOIN` gerekir.
    """
    if not item_ids:
        return {}
    stmt = (
        select(EmployerContractItem, EmployerContractGroup.name)
        .join(EmployerContractGroup, EmployerContractGroup.id == EmployerContractItem.group_id)
        .where(EmployerContractItem.id.in_(item_ids))
    )
    result = await session.execute(stmt)
    return {item.id: (item, group_name) for item, group_name in result.all()}


async def get_employer_items_by_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, EmployerContractItem]:
    """§6.6/§8 türevleri (canlı `unit_price`/`quantity` okuması) için — snapshot
    DEĞİL, güncel kalem."""
    if not item_ids:
        return {}
    stmt = select(EmployerContractItem).where(EmployerContractItem.id.in_(item_ids))
    result = await session.execute(stmt)
    return {item.id: item for item in result.scalars().all()}


async def get_contract_items_total_value(session: AsyncSession, project_id: uuid.UUID) -> Decimal:
    """§8 fiziksel ilerleme paydası: `Σ(kalem.quantity × kalem.unit_price)` — sözleşmenin
    TÜM kalemleri (yalnız hakedişe giren pozlar değil)."""
    stmt = select(
        func.coalesce(func.sum(EmployerContractItem.quantity * EmployerContractItem.unit_price), 0)
    ).where(EmployerContractItem.project_id == project_id)
    result = await session.execute(stmt)
    return Decimal(result.scalar_one())
