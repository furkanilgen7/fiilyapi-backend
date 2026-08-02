"""Birleşik sözleşme listesi için okuma sorguları (spec §6.1, task C5).

`boq/repository.py` deseninin aynısı: filtreler SQL düzeyinde uygulanır, N+1
üretilmez. Taşeron tarafında `SubcontractorContract.items` ilişkisi
`lazy="selectin"` tanımlıdır (models.py) — erişildiğinde tüm sözleşmelerin
kalemleri TEK ek sorguda (IN listesi) toplu gelir.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem
from app.modules.contracts.models import (
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
    Subcontractor,
    SubcontractorContract,
    SubcontractorContractItem,
)
from app.modules.projects.models import Project, ProjectContract


async def list_employer_contracts(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> list[tuple[Project, ProjectContract]]:
    """İşveren "sözleşme kaydı" = `project_contracts` satırı olan proje (spec §6.1).

    INNER JOIN: sözleşmesi olmayan proje listede ÇIKMAZ.
    """
    if not visible_project_ids:
        return []
    stmt = (
        select(Project, ProjectContract)
        .join(ProjectContract, ProjectContract.project_id == Project.id)
        .where(Project.id.in_(visible_project_ids))
        .order_by(Project.code)
    )
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)
    if status_filter is not None:
        stmt = stmt.where(ProjectContract.status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                ProjectContract.contract_no.ilike(pattern),
                Project.employer_name.ilike(pattern),
            )
        )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def list_subcontractor_contracts(
    session: AsyncSession,
    visible_project_ids: list[uuid.UUID],
    *,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> list[SubcontractorContract]:
    if not visible_project_ids:
        return []
    stmt = (
        select(SubcontractorContract)
        .where(SubcontractorContract.project_id.in_(visible_project_ids))
        .order_by(SubcontractorContract.created_at)
    )
    if project_id is not None:
        stmt = stmt.where(SubcontractorContract.project_id == project_id)
    if status_filter is not None:
        stmt = stmt.where(SubcontractorContract.status == status_filter)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                SubcontractorContract.contract_no.ilike(pattern),
                SubcontractorContract.subcontractor_name.ilike(pattern),
            )
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- İşveren sözleşmesi poz grup/kalem (task C6, `boq/repository.py` deseninin
# aynısı — spec §3.2, §6.2) ---


async def list_employer_groups(
    session: AsyncSession, project_id: uuid.UUID
) -> list[EmployerContractGroup]:
    """Bir sözleşmenin poz grupları, sıralı. Kalemler ayrı sorgu ATILMAZ:

    `EmployerContractGroup.items` ilişkisi `lazy="selectin"` tanımlıdır (C1),
    erişildiğinde tüm grupların kalemleri TEK ek sorguda toplu gelir.
    """
    result = await session.execute(
        select(EmployerContractGroup)
        .where(EmployerContractGroup.project_id == project_id)
        .order_by(EmployerContractGroup.sort_order, EmployerContractGroup.created_at)
    )
    return list(result.scalars().all())


async def lock_employer_items(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Bir sözleşmenin TÜM poz kalemlerini `SELECT … FOR UPDATE` ile kilitler.

    `progress_payments/repository.py::get_contract_locked` deseninin aynısı,
    yalnız kilit kümesi çok satırlı: dağıtımın doğruladığı kota (`Σ şantiye
    kotası ≤ contract_item.quantity`) kalem satırının kendisine yazılıdır, bu
    yüzden kilitlenmesi gereken şey o kalemlerdir. Dağıtım yazımından ÖNCE,
    doğrulamayı besleyen okumalardan da ÖNCE çağrılmak ZORUNDA — aksi hâlde iki
    eşzamanlı istek aynı "kalan"ı okur, ikisi de geçerli sanılır, ikisi de yazar
    ve toplam sözleşme miktarını aşar (TOCTOU, spec §2).

    `ORDER BY id` OPSİYONEL DEĞİLDİR: kilit kümesi çok satırlı olduğu için sıra
    tutarsız olursa iki eşzamanlı istek karşılıklı kilitlenir (A kalem-1'i,
    B kalem-2'yi tutarken ikisi de diğerini bekler → deadlock). Küresel ve
    deterministik bir sıra (birincil anahtar) her iki isteğin de AYNI satırda
    buluşmasını, dolayısıyla birinin BEKLEMESİNİ garanti eder.
    """
    stmt = (
        select(EmployerContractItem.id)
        .where(EmployerContractItem.project_id == project_id)
        .order_by(EmployerContractItem.id)
        .with_for_update()
    )
    await session.execute(stmt)


async def get_employer_group(
    session: AsyncSession, group_id: uuid.UUID
) -> EmployerContractGroup | None:
    return await session.get(EmployerContractGroup, group_id)


async def get_employer_item(
    session: AsyncSession, item_id: uuid.UUID
) -> EmployerContractItem | None:
    return await session.get(EmployerContractItem, item_id)


async def get_employer_item_by_code(
    session: AsyncSession,
    project_id: uuid.UUID,
    code: str,
    exclude_item_id: uuid.UUID | None = None,
) -> EmployerContractItem | None:
    """`(project_id, code)` çakışmasını `IntegrityError`'a düşmeden ÖNCE yakalar

    (`DuplicateError` deseni, `boq/repository.py.get_item_by_code` emsali).
    """
    stmt = select(EmployerContractItem).where(
        EmployerContractItem.project_id == project_id, EmployerContractItem.code == code
    )
    if exclude_item_id is not None:
        stmt = stmt.where(EmployerContractItem.id != exclude_item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_distributed_boq_items(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> list[BoqItem]:
    """Spec §6.3 (`POZ` ekranı): verilen sözleşme kalemlerine bağlı TÜM BOQ

    satırları TEK sorguda (`IN` listesi) — `distribution.build_distribution`
    kalem başına ayrı sorgu ATMAZ. `contract_item_id IS NULL` satırlar zaten
    `item_ids` filtresiyle elenir (spec §3.3: bu satırlar dağıtım ekranında
    görünmez).
    """
    if not item_ids:
        return []
    stmt = select(BoqItem).where(BoqItem.contract_item_id.in_(item_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_boq_items_for_sites(
    session: AsyncSession, site_ids: list[uuid.UUID]
) -> list[BoqItem]:
    """Verilen şantiyelerin TÜM BOQ satırları TEK sorguda (task C8).

    `contract_item_id IS NULL` satırlar da gelir — dağıtım yazarken
    `uq_boq_items_site_code` çakışması bu satırlardan da doğabilir
    (şantiyenin kendi başına girdiği poz aynı numarayı tutuyor olabilir).
    """
    if not site_ids:
        return []
    stmt = select(BoqItem).where(BoqItem.site_id.in_(site_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_boq_groups_for_sites(
    session: AsyncSession, site_ids: list[uuid.UUID]
) -> list[BoqGroup]:
    """Verilen şantiyelerin BOQ grupları TEK sorguda (task C8 grup önbelleği).

    Sıralama DETERMİNİSTİK olmak ZORUNDA: `BoqGroup`'ta `(site_id, name)`
    benzersizliği yok, aynı adlı iki grup varsa önbelleğin hangisini seçtiği
    sıralamaya bağlıdır. `created_at, id` → her zaman EN ESKİ grup.
    """
    if not site_ids:
        return []
    stmt = (
        select(BoqGroup)
        .where(BoqGroup.site_id.in_(site_ids))
        .order_by(BoqGroup.created_at, BoqGroup.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def sum_distributed_quantities(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Spec §3.3: `distributed_quantity` bağlı `boq_items.quantity` toplamı.

    Kalem başına ayrı sorgu ATILMAZ — `GROUP BY` ile TEK sorguda toplanır
    (`GET .../contract/items` N kalemli listede N+1 üretmez).
    """
    if not item_ids:
        return {}
    stmt = (
        select(BoqItem.contract_item_id, func.sum(BoqItem.quantity))
        .where(BoqItem.contract_item_id.in_(item_ids))
        .group_by(BoqItem.contract_item_id)
    )
    result = await session.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


# --- Taşeron kartoteksi (task C9, spec §3.4/§6.4) ---
#
# `projects/repository.py`'deki `list_employers`/`get_employer_by_tax_number`/
# `add_employer` desenlerinin birebiri.


async def list_subcontractors(
    session: AsyncSession, q: str | None, active_only: bool
) -> list[Subcontractor]:
    """Ada göre ILIKE süzgeci + aktiflik; sıralama DB'de (ORDER BY name)."""
    stmt = select(Subcontractor)
    if active_only:
        stmt = stmt.where(Subcontractor.is_active.is_(True))
    if q:
        stmt = stmt.where(Subcontractor.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Subcontractor.name)
    return list((await session.execute(stmt)).scalars().all())


async def get_subcontractor(
    session: AsyncSession, subcontractor_id: uuid.UUID
) -> Subcontractor | None:
    return await session.get(Subcontractor, subcontractor_id)


async def get_subcontractor_by_tax_number(
    session: AsyncSession, tax_number: str, exclude_id: uuid.UUID | None = None
) -> Subcontractor | None:
    stmt = select(Subcontractor).where(Subcontractor.tax_number == tax_number)
    if exclude_id is not None:
        stmt = stmt.where(Subcontractor.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_subcontractor(session: AsyncSession, subcontractor: Subcontractor) -> Subcontractor:
    session.add(subcontractor)
    await session.flush()
    await session.refresh(subcontractor)
    return subcontractor


# --- Silme korkulukları (task C12, spec §7) ---
#
# `sites/repository.py.site_has_sections` deseninin aynısı:
# `select(<altsorgu>.exists())` — SATIR ÇEKMEZ, `count(*)` KULLANILMAZ (hata
# metinlerinde adet verilmez, spec §7 tablosu).


async def subcontractor_has_contracts(session: AsyncSession, subcontractor_id: uuid.UUID) -> bool:
    """Taşerona bağlı sözleşme var mı (`subcontractor_contracts.subcontractor_id`

    -> RESTRICT). DB kendiliğinden korur ama korkuluksuz bırakılırsa kullanıcı
    "Veri bütünlüğü hatası" görür (`sites/repository.py.site_has_contracts`
    dersinin aynısı).
    """
    result = await session.execute(
        select(
            select(SubcontractorContract.id)
            .where(SubcontractorContract.subcontractor_id == subcontractor_id)
            .exists()
        )
    )
    return bool(result.scalar_one())


async def employer_group_has_items(session: AsyncSession, group_id: uuid.UUID) -> bool:
    """Grupta poz kalemi var mı (`employer_contract_items.group_id` -> CASCADE).

    `sites/repository.py.site_has_boq` gerekçesinin aynısı: DB CASCADE ile
    korur ama korkuluksuz bırakılırsa kalemler sessizce yok olur.
    """
    result = await session.execute(
        select(
            select(EmployerContractItem.id)
            .where(EmployerContractItem.group_id == group_id)
            .exists()
        )
    )
    return bool(result.scalar_one())


# --- Taşeron sözleşmesi (task C10, spec §3.5/§6.5) ---


async def get_subcontractor_contract(
    session: AsyncSession, contract_id: uuid.UUID
) -> SubcontractorContract | None:
    return await session.get(SubcontractorContract, contract_id)


async def get_subcontractor_contract_by_contract_no(
    session: AsyncSession,
    contract_no: str,
    exclude_id: uuid.UUID | None = None,
) -> SubcontractorContract | None:
    """`contract_no` çakışmasını `IntegrityError`'a düşmeden ÖNCE yakalar

    (`get_employer_item_by_code` deseninin aynısı) — global kısmi benzersiz
    indeks (spec §3.5), NULL değerler serbestçe çoğalabilir.
    """
    stmt = select(SubcontractorContract).where(SubcontractorContract.contract_no == contract_no)
    if exclude_id is not None:
        stmt = stmt.where(SubcontractorContract.id != exclude_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# --- Taşeron sözleşmesi kalemleri (task C11, spec §3.6/§6.5) ---


async def get_subcontract_item(
    session: AsyncSession, item_id: uuid.UUID
) -> SubcontractorContractItem | None:
    return await session.get(SubcontractorContractItem, item_id)


async def get_subcontract_item_by_code(
    session: AsyncSession,
    contract_id: uuid.UUID,
    code: str,
    exclude_item_id: uuid.UUID | None = None,
) -> SubcontractorContractItem | None:
    """`(contract_id, code)` çakışmasını `IntegrityError`'a düşmeden ÖNCE yakalar

    (`get_employer_item_by_code` deseninin aynısı).
    """
    stmt = select(SubcontractorContractItem).where(
        SubcontractorContractItem.contract_id == contract_id,
        SubcontractorContractItem.code == code,
    )
    if exclude_item_id is not None:
        stmt = stmt.where(SubcontractorContractItem.id != exclude_item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_employer_item_groups(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """`(employer_item_id, group_id, group_name)` üçlüleri — taşeron kalemi

    grubu `source_contract_item_id` üzerinden TÜRER (spec §3.6), ayrı grup
    tablosu yoktur.
    """
    if not item_ids:
        return []
    stmt = (
        select(EmployerContractItem.id, EmployerContractGroup.id, EmployerContractGroup.name)
        .join(EmployerContractGroup, EmployerContractItem.group_id == EmployerContractGroup.id)
        .where(EmployerContractItem.id.in_(item_ids))
    )
    result = await session.execute(stmt)
    return [(row[0], row[1], row[2]) for row in result.all()]
