"""Birleşik sözleşme listesi servis katmanı (spec §6.1, task C5).

İki katmanlı koruma (spec §6): `contracts` izni router'da (`_VIEW`) YETKİYİ
verir, bu modül `projects.service.visible_projects` ile KAPSAMI belirler —
görünmeyen projenin sözleşmesi listeye asla girmez. Bu iki katmandan biri
eksikse task başarısızdır (task brief kararı).
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DuplicateError,
    NotFoundError,
    RelatedRecordsExistError,
    SiteValidationError,
)
from app.core.timezone import today
from app.modules.company.service import get_company
from app.modules.contracts import repository
from app.modules.contracts.guards import (
    CONTRACT_MISSING,
    DUPLICATE_ITEM_CODE,
    GROUP_HAS_ITEMS,
    GROUP_MISSING,
    GROUP_PROJECT_MISMATCH,
    ITEM_MISSING,
    ITEM_QUANTITY_BELOW_DISTRIBUTED,
)
from app.modules.contracts.models import (
    ContractStatus,
    EmployerContractGroup,
    EmployerContractItem,
    SubcontractorContract,
)
from app.modules.contracts.schemas import (
    ContractListItem,
    ContractListResponse,
    ContractSummary,
    ContractType,
    EmployerContractDetail,
    EmployerContractGroupCreate,
    EmployerContractGroupItems,
    EmployerContractGroupUpdate,
    EmployerContractItemCreate,
    EmployerContractItemResponse,
    EmployerContractItemsResponse,
    EmployerContractItemUpdate,
    MetricPlaceholder,
)
from app.modules.projects.models import Project, ProjectContract
from app.modules.projects.service import visible_projects
from app.modules.users.models import User

# Spec §2.2: hakediş P7'nin işi, bu dilimde yazılmaz — yer tutucu anahtarı.
_PROGRESS_PAYMENTS = "progress_payments"
_MONEY = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _employer_item(project: Project, contract: ProjectContract) -> ContractListItem:
    """Alan eşlemesi spec §6.1 tablosu — işveren sütunu BİREBİR."""
    return ContractListItem(
        id=project.id,
        title=project.name,
        contract_no=contract.contract_no,
        counterparty_name=project.employer_name,
        amount=contract.amount if contract.amount is not None else Decimal("0"),
        start_date=project.start_date,
        end_date=project.end_date,
        progress_pct=MetricPlaceholder(
            available=True, value=project.progress_pct, pending_module=_PROGRESS_PAYMENTS
        ),
        status=contract.status,
        is_draft=project.is_draft,
    )


def _subcontractor_amount(contract: SubcontractorContract) -> Decimal:
    """`Σ(line_total)` — her satır ÖNCE kuruşa yuvarlanır, SONRA toplanır

    (dal geneli son inceleme kararı: `Numeric(14,3) × Numeric(18,2)` beş
    ondalık üretebildiği için ham çarpımların toplamını TEK SEFERDE
    yuvarlamak `Σ line_total != contract_total` sapmasına yol açabilirdi —
    `schemas.SubcontractorContractItemResponse.line_total` ve
    `distribution.py`nin zaten kullandığı kuralla hizalanır). `unit_price IS
    NULL` olan satır 0 katkı verir (task brief kararı). Kalemler zaten
    `lazy="selectin"` ile yüklü, ek sorgu YOK.
    """
    line_totals = (
        _quantize_money(item.quantity * item.unit_price)
        for item in contract.items
        if item.unit_price is not None
    )
    return sum(line_totals, Decimal("0.00"))


def _subcontractor_title(contract: SubcontractorContract) -> str:
    """`subcontractor_name + " — " + work_category` (`TSD` 40 deseni, spec §6.1)."""
    name = contract.subcontractor_name or ""
    category = contract.work_category or ""
    if name and category:
        return f"{name} — {category}"
    return name or category


def _subcontractor_item(contract: SubcontractorContract) -> ContractListItem:
    return ContractListItem(
        id=contract.id,
        title=_subcontractor_title(contract),
        contract_no=contract.contract_no,
        counterparty_name=contract.subcontractor_name,
        amount=_subcontractor_amount(contract),
        start_date=contract.start_date,
        end_date=contract.end_date,
        progress_pct=MetricPlaceholder(pending_module=_PROGRESS_PAYMENTS),
        status=contract.status,
        is_draft=contract.is_draft,
    )


def _summary(items: list[ContractListItem]) -> ContractSummary:
    """`SZL` 34-38 üst KPI şeridi (spec §6.1). `expiring_this_month_count`:

    durumu `active` VE bitiş tarihi sunucunun görüntüleme saat dilimindeki
    (`app/core/timezone.today`) içinde bulunulan ay içinde olan sözleşmeler.
    """
    total_amount = _quantize_money(sum((item.amount for item in items), Decimal("0")))
    active_count = sum(1 for item in items if item.status is ContractStatus.active)
    current = today()
    expiring_this_month_count = sum(
        1
        for item in items
        if item.status is ContractStatus.active
        and item.end_date is not None
        and item.end_date.year == current.year
        and item.end_date.month == current.month
    )
    return ContractSummary(
        total_amount=total_amount,
        active_count=active_count,
        expiring_this_month_count=expiring_this_month_count,
    )


async def list_contracts(
    session: AsyncSession,
    actor: User,
    contract_type: ContractType,
    project_id: uuid.UUID | None,
    status_filter: ContractStatus | None,
    q: str | None,
) -> ContractListResponse:
    visible_ids = [p.id for p in await visible_projects(session, actor)]

    if contract_type == "employer":
        rows = await repository.list_employer_contracts(
            session,
            visible_ids,
            project_id=project_id,
            status_filter=status_filter,
            q=q,
        )
        items = [_employer_item(project, contract) for project, contract in rows]
    else:
        contracts = await repository.list_subcontractor_contracts(
            session,
            visible_ids,
            project_id=project_id,
            status_filter=status_filter,
            q=q,
        )
        items = [_subcontractor_item(contract) for contract in contracts]

    return ContractListResponse(summary=_summary(items), items=items)


# --- İşveren sözleşmesi: gruplar/kalemler (task C6, spec §6.2) ---
#
# İki katmanlı koruma spec §6'nın aynısı: router'daki `_VIEW`/`_FULL` YETKİYİ,
# aşağıdaki `_visible_project` (`sites/service.py._visible_project` deseninin
# birebiri) `visible_projects` üzerinden KAPSAMI belirler. Görünmeyen projedeki
# gerçek kayıt ile var olmayan kayıt AYNI 404 gövdesini döner.


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = CONTRACT_MISSING
) -> Project:
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


async def _visible_group(
    session: AsyncSession, actor: User, group_id: uuid.UUID
) -> tuple[EmployerContractGroup, Project]:
    """Grup -> proje. Dolaylı kimlikle erişim de görünürlük süzgecinden geçmek

    ZORUNDA (`boq/service.py._visible_group` deseninin aynısı).
    """
    group = await repository.get_employer_group(session, group_id)
    if group is None:
        raise NotFoundError(GROUP_MISSING)
    project = await _visible_project(session, actor, group.project_id, GROUP_MISSING)
    return group, project


async def _visible_item(
    session: AsyncSession, actor: User, item_id: uuid.UUID
) -> tuple[EmployerContractItem, Project]:
    item = await repository.get_employer_item(session, item_id)
    if item is None:
        raise NotFoundError(ITEM_MISSING)
    project = await _visible_project(session, actor, item.project_id, ITEM_MISSING)
    return item, project


async def _ensure_group_in_project(
    session: AsyncSession, group_id: uuid.UUID, project_id: uuid.UUID
) -> EmployerContractGroup:
    """Spec §3.2 grup->sözleşme tutarlılığı: DB'de bileşik FK ile ZORLANMAZ

    (yazma yolu tekil), servis korkuluğuyla sağlanır (`BoqItem` §3.3 invariant
    1'in aynısı). Grup hiç yoksa da aynı 422 ile karşılanır — proje zaten
    görünürlük süzgecinden geçmiş, yalnızca ait olmadığı bir grup engellenir.
    """
    group = await repository.get_employer_group(session, group_id)
    if group is None or group.project_id != project_id:
        raise SiteValidationError(GROUP_PROJECT_MISMATCH)
    return group


async def _ensure_code_unique(
    session: AsyncSession,
    project_id: uuid.UUID,
    code: str,
    exclude_item_id: uuid.UUID | None = None,
) -> None:
    existing = await repository.get_employer_item_by_code(
        session, project_id, code, exclude_item_id
    )
    if existing is not None:
        raise DuplicateError(DUPLICATE_ITEM_CODE)


async def _distributed_quantity(session: AsyncSession, item_id: uuid.UUID) -> Decimal:
    sums = await repository.sum_distributed_quantities(session, [item_id])
    return sums.get(item_id, Decimal("0"))


def to_item_response(
    item: EmployerContractItem, distributed: Decimal
) -> EmployerContractItemResponse:
    return EmployerContractItemResponse(
        id=item.id,
        group_id=item.group_id,
        code=item.code,
        description=item.description,
        unit=item.unit,
        quantity=item.quantity,
        unit_price=item.unit_price,
        sort_order=item.sort_order,
        distributed_quantity=distributed,
        remaining_quantity=item.quantity - distributed,
    )


async def to_item_response_single(
    session: AsyncSession, item: EmployerContractItem
) -> EmployerContractItemResponse:
    return to_item_response(item, await _distributed_quantity(session, item.id))


async def get_employer_contract_detail(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> EmployerContractDetail:
    """`E14` başlığı (spec §6.2): sözleşme + `items_total` + `advance_amount` +

    yüklenici adı (`company` tek satırından). Sözleşmesi olmayan proje de
    (görünür olsa dahi) `CONTRACT_MISSING` ile 404 döner — bu ucun var oluş
    şartı bir sözleşme kaydının bulunmasıdır.
    """
    project = await _visible_project(session, actor, project_id)
    contract = project.contract
    if contract is None:
        raise NotFoundError(CONTRACT_MISSING)

    groups = await repository.list_employer_groups(session, project_id)
    items_total = _quantize_money(
        sum(
            (item.quantity * item.unit_price for group in groups for item in group.items),
            Decimal("0"),
        )
    )
    amount = contract.amount if contract.amount is not None else Decimal("0")
    advance_amount = _quantize_money(amount * contract.advance_pct / Decimal("100"))
    company = await get_company(session)

    return EmployerContractDetail(
        project_id=project.id,
        contract_no=contract.contract_no,
        signature_date=contract.signature_date,
        amount=contract.amount,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        vat_pct=contract.vat_pct,
        late_penalty_daily=contract.late_penalty_daily,
        has_price_escalation=contract.has_price_escalation,
        status=contract.status,
        start_date=project.start_date,
        end_date=project.end_date,
        employer_name=project.employer_name,
        contractor_name=company.name,
        items_total=items_total,
        items_total_diff=amount - items_total,
        advance_amount=advance_amount,
    )


async def get_employer_contract_items(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> EmployerContractItemsResponse:
    """Spec §6.2: gruplar + kalemler, her kalemde `distributed_quantity`/

    `remaining_quantity`. Tek toplu sorgu (`sum_distributed_quantities`) —
    N kalemli listede N+1 üretmez.
    """
    project = await _visible_project(session, actor, project_id)
    if project.contract is None:
        raise NotFoundError(CONTRACT_MISSING)

    groups = await repository.list_employer_groups(session, project_id)
    item_ids = [item.id for group in groups for item in group.items]
    distributed = await repository.sum_distributed_quantities(session, item_ids)

    return EmployerContractItemsResponse(
        groups=[
            EmployerContractGroupItems(
                id=group.id,
                name=group.name,
                sort_order=group.sort_order,
                items=[
                    to_item_response(item, distributed.get(item.id, Decimal("0")))
                    for item in group.items
                ],
            )
            for group in groups
        ]
    )


async def create_employer_group(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: EmployerContractGroupCreate
) -> tuple[EmployerContractGroup, Project]:
    """`Project` da döner: router'daki denetim günlüğü satırı proje ADI ister

    (`section_created` gerekçesinin aynısı) — ikinci bir sorgu atılmasın diye.
    """
    project = await _visible_project(session, actor, project_id)
    if project.contract is None:
        raise NotFoundError(CONTRACT_MISSING)
    group = EmployerContractGroup(project_id=project.id, name=data.name, sort_order=data.sort_order)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return group, project


async def update_employer_group(
    session: AsyncSession, actor: User, group_id: uuid.UUID, data: EmployerContractGroupUpdate
) -> tuple[EmployerContractGroup, Project]:
    group, project = await _visible_group(session, actor, group_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await session.flush()
    await session.refresh(group)
    return group, project


async def create_employer_item(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: EmployerContractItemCreate
) -> tuple[EmployerContractItem, Project]:
    """Spec §3.3 IDOR: gövdedeki `group_id` başka projenin grubu olabilir —

    yol parametresi `project_id` ile karşı karşıya konur, uyuşmazlık 422 döner.
    """
    project = await _visible_project(session, actor, project_id)
    if project.contract is None:
        raise NotFoundError(CONTRACT_MISSING)
    group = await _ensure_group_in_project(session, data.group_id, project.id)
    await _ensure_code_unique(session, project.id, data.code)
    item = EmployerContractItem(
        project_id=project.id,
        group_id=group.id,
        code=data.code,
        description=data.description,
        unit=data.unit,
        quantity=data.quantity,
        unit_price=data.unit_price,
        sort_order=data.sort_order,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item, project


async def update_employer_item(
    session: AsyncSession, actor: User, item_id: uuid.UUID, data: EmployerContractItemUpdate
) -> tuple[EmployerContractItem, Project]:
    """`group_id` verilirse spec §3.2 tutarlılığı tekrar kontrol edilir (başka

    sözleşmenin grubuna taşıma yasak); `code` değişirse tekillik tekrar kontrol
    edilir; `quantity` küçültülürse spec §3.3 kalan hesabı negatif OLAMAZ —
    dağıtılmış toplamın altına indirme 422 döner (task C6 kararı).
    """
    item, project = await _visible_item(session, actor, item_id)
    updates = data.model_dump(exclude_unset=True)
    if "group_id" in updates:
        await _ensure_group_in_project(session, updates["group_id"], project.id)
    if "code" in updates and updates["code"] != item.code:
        await _ensure_code_unique(session, project.id, updates["code"], exclude_item_id=item.id)
    if "quantity" in updates:
        distributed = await _distributed_quantity(session, item.id)
        if updates["quantity"] < distributed:
            raise SiteValidationError(ITEM_QUANTITY_BELOW_DISTRIBUTED)
    for field, value in updates.items():
        setattr(item, field, value)
    await session.flush()
    await session.refresh(item)
    return item, project


# --- Silme uçları (task C12, spec §7) ---
#
# Kimlik SİLMEDEN ÖNCE okunur (`boq/service.py.delete_item` deseninin aynısı):
# denetim metni satır yok olduktan sonra kurulursa `project.name`/`group.name`
# güvenilir okunamaz. Primitif değerler DÖNER, ORM nesnesi DEĞİL — silinmiş
# bir nesnenin alanına flush sonrası erişmek `ObjectDeletedError` riski taşır.


async def delete_employer_group(
    session: AsyncSession, actor: User, group_id: uuid.UUID
) -> tuple[str, str]:
    """409 `GROUP_HAS_ITEMS`: grupta kalem varsa silinmez (spec §7). Kapı `_ADMIN`

    (`boq/router.py.delete_boq_item_endpoint` deseninin aynısı, `can_delete`
    istisnası burada YOK — yalnız `subcontractor_contracts` silme ucunda geçerli).
    """
    group, project = await _visible_group(session, actor, group_id)
    if await repository.employer_group_has_items(session, group.id):
        raise RelatedRecordsExistError(GROUP_HAS_ITEMS)
    project_name, group_name = project.name, group.name
    await session.delete(group)
    await session.flush()
    return project_name, group_name


async def delete_employer_item(
    session: AsyncSession, actor: User, item_id: uuid.UUID
) -> tuple[str, str, str]:
    """Engel YOK (spec §7): bağlı `boq_items.contract_item_id` DB'de `ON DELETE

    SET NULL` ile serbest kalır — şantiyenin kendi başına girdiği bir poz gibi
    (`contract_item_id IS NULL`) BOQ'da kalmaya devam eder, satır SİLİNMEZ.
    """
    item, project = await _visible_item(session, actor, item_id)
    project_name, code, description = project.name, item.code, item.description
    await session.delete(item)
    await session.flush()
    return project_name, code, description
