"""Taşeron hakedişi CRUD servis katmanı (T2).

İki katmanlı koruma (`progress_payments/service.py` deseninin birebiri, spec §9.0):
`progress_payments` izni router'da YETKİYİ verir — **yeni izin modülü AÇILMAZ**,
iki hakediş ailesi aynı ekran ailesidir — bu modül `projects.service.visible_projects`
ile KAPSAMI belirler. Görünmeyen projedeki GERÇEK kayıt ile var OLMAYAN kimlik
AYIRT EDİLEMEZ 404 döner.

İşveren modülünden KOPYALANMAYAN, ÇAĞRILAN parçalar: `visible_projects` (kapsam),
`can_delete` (silme kuralı), `contracts.repository.get_employer_item_groups`
(grup adı zinciri), `progress_payments.calculations.line_total` (silme denetim
satırındaki tutar) ve `guards`ın paylaşılan metinleri.
"""

import uuid
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, can_delete
from app.core.errors import ConflictError, DeleteNotAllowedError, NotFoundError, SiteValidationError
from app.modules.contracts import guards as contract_guards
from app.modules.contracts import repository as contracts_repository
from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.progress_payments import calculations
from app.modules.projects.models import Project
from app.modules.projects.service import visible_projects
from app.modules.roles.repository import get_permission
from app.modules.subcontractor_progress_payments import guards, repository
from app.modules.subcontractor_progress_payments.models import (
    SubcontractorPaymentStatus,
    SubcontractorProgressPayment,
    SubcontractorProgressPaymentLine,
)
from app.modules.subcontractor_progress_payments.schemas import (
    SubcontractorProgressPaymentCreate,
    SubcontractorProgressPaymentUpdate,
)
from app.modules.users.models import User

_DEFAULT_COEFFICIENT = Decimal("1.000")
_ZERO_QUANTITY = Decimal("0")

# Denetim günlüğü etiketi. İşveren modülündeki `_STATUS_LABELS`ten AYRI durur:
# anahtar tipi farklı bir enum'dur (`SubcontractorPaymentStatus`), ortak bir
# sözlük iki enum'u birbirine kilitlerdi (modeldeki "enum tipi ayrı" kararının
# aynı gerekçesi).
_STATUS_LABELS: dict[SubcontractorPaymentStatus, str] = {
    SubcontractorPaymentStatus.draft: "Taslak",
    SubcontractorPaymentStatus.pending_approval: "Onay Bekliyor",
    SubcontractorPaymentStatus.approved: "Onaylandı",
    SubcontractorPaymentStatus.paid: "Ödendi",
}


class PaymentContext(NamedTuple):
    """Kapsam süzgecinden geçmiş üçlü — router'ın denetim satırı da bunu okur."""

    payment: SubcontractorProgressPayment
    contract: SubcontractorContract
    project: Project


class DeletedPaymentSummary(NamedTuple):
    """`session.delete` ÖNCESİNDE çıkarılmış özet — kayıt gittiğinde bu dörtlü
    bir daha okunamaz (işveren `DeletedPaymentSummary` deseninin aynısı)."""

    project_name: str
    subcontractor_name: str | None
    sequence_no: int
    status_label: str
    amount: Decimal


# --- Kapsam (spec §9.0) ---


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, message: str
) -> Project:
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(message)
    return project


async def _visible_contract(
    session: AsyncSession, actor: User, contract_id: uuid.UUID
) -> tuple[SubcontractorContract, Project]:
    """Sözleşme → proje. Görünmeyen projenin sözleşmesi ile var olmayan sözleşme
    AYNI 404 gövdesini döner; metin `contracts` modülünün TEK "sözleşme
    bulunamadı" cümlesidir (kopya metin üretilmez)."""
    contract = await contracts_repository.get_subcontractor_contract(session, contract_id)
    if contract is None:
        raise NotFoundError(contract_guards.CONTRACT_MISSING)
    project = await _visible_project(
        session, actor, contract.project_id, contract_guards.CONTRACT_MISSING
    )
    return contract, project


async def visible_payment(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> PaymentContext:
    """Kapsam süzgeci — `read.py` de bu TEK kapıdan geçer (public olmasının nedeni)."""
    payment = await repository.get_payment(session, payment_id)
    if payment is None:
        raise NotFoundError(guards.PAYMENT_MISSING)
    project = await _visible_project(session, actor, payment.project_id, guards.PAYMENT_MISSING)
    contract = await contracts_repository.get_subcontractor_contract(session, payment.contract_id)
    if contract is None:
        # FK CASCADE'i sayesinde ulaşılamaz; yine de sessizce None taşımak yerine
        # kaydın yokluğuyla aynı 404'e düşülür.
        raise NotFoundError(guards.PAYMENT_MISSING)
    return PaymentContext(payment=payment, contract=contract, project=project)


async def _visible_payment_locked(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> PaymentContext:
    """Kapsam kararı (404) kilitten ÖNCE verilir — görünmeyen kaydın satırı
    boşuna kilitlenmez. Kilit sırası `create` ile AYNIDIR: önce SÖZLEŞME, sonra
    hakediş; ters sırada kilitleyen bir yol karşılıklı kilitlenme doğurur."""
    context = await visible_payment(session, actor, payment_id)
    await repository.get_contract_locked(session, context.contract.id)
    locked = await repository.get_payment_locked(session, payment_id)
    if locked is None:
        raise NotFoundError(guards.PAYMENT_MISSING)
    return context._replace(payment=locked)


# --- Bölüm sahipliği (spec §8 S2) ---


async def _validate_section(
    session: AsyncSession, section_id: uuid.UUID | None, contract: SubcontractorContract
) -> None:
    """Bilgi alanı olması SAHİPSİZ olması demek DEĞİLDİR: bölüm, sözleşmenin
    şantiyesine (sözleşme proje geneliyse projenin bir şantiyesine) ait olmalı."""
    if section_id is None:
        return
    row = await repository.get_section_with_site(session, section_id)
    if row is None:
        raise SiteValidationError(guards.SECTION_MISMATCH)
    _, site = row
    if contract.site_id is not None:
        if site.id != contract.site_id:
            raise SiteValidationError(guards.SECTION_MISMATCH)
    elif site.project_id != contract.project_id:
        raise SiteValidationError(guards.SECTION_MISMATCH)


# --- Satır üretimi (O66: kalemler sözleşmeden OTOMATİK) ---


async def _build_lines(
    session: AsyncSession,
    items: list[SubcontractorContractItem],
    default_coefficient: Decimal,
) -> list[SubcontractorProgressPaymentLine]:
    """Sözleşme kalemlerinin snapshot BEŞLİSİNİ satıra kopyalar (spec §2).

    `group_name` `source_contract_item_id → employer_contract_groups` zincirinden
    çözülür; zincir `contracts.repository.get_employer_item_groups` ile TEK
    sorguda okunur (kalem başına sorgu N+1 olurdu, `contracts.subcontracts.
    _item_groups` ile aynı kaynak).

    Fiyatsız kalem varsa HİÇBİR satır üretilmez (422): "girilmedi ≠ 0 TL".
    Kontrol satır kurmadan ÖNCE, TÜM kalemler üzerinde koşar — kısmi hakediş
    (fiyatlıları alıp fiyatsızları sessizce atlamak) evrağı eksik doğurur.
    """
    ordered = sorted(items, key=lambda item: (item.sort_order, item.code))
    if any(item.unit_price is None for item in ordered):
        raise SiteValidationError(guards.ITEM_PRICE_REQUIRED)

    source_ids = [item.source_contract_item_id for item in ordered if item.source_contract_item_id]
    group_names = {
        item_id: group_name
        for item_id, _, group_name in await contracts_repository.get_employer_item_groups(
            session, source_ids
        )
    }
    return [
        SubcontractorProgressPaymentLine(
            contract_item_id=item.id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            contract_unit_price=item.unit_price,
            coefficient=default_coefficient,
            quantity=_ZERO_QUANTITY,
            group_name=group_names.get(item.source_contract_item_id),
            sort_order=index,
        )
        for index, item in enumerate(ordered)
    ]


# --- Oluşturma ---


async def create(
    session: AsyncSession,
    actor: User,
    contract_id: uuid.UUID,
    data: SubcontractorProgressPaymentCreate,
) -> PaymentContext:
    """Açık-hakediş kontrolü + `sequence_no` üretimi AYNI kilit altında koşar
    (işveren `create` deseninin aynısı): sözleşme satırı `SELECT … FOR UPDATE`
    ile kilitlenir, aynı sözleşmedeki ikinci eşzamanlı `POST` burada bekler.

    `project_id` sözleşmeden KOPYALANIR (görünürlük süzgeci her liste sorgusunda
    JOIN gerektirmesin diye, model docstring'i).
    """
    contract, project = await _visible_contract(session, actor, contract_id)

    locked = await repository.get_contract_locked(session, contract.id)
    if locked is None:
        raise NotFoundError(contract_guards.CONTRACT_MISSING)

    if await repository.get_open_payment(session, contract.id) is not None:
        raise ConflictError(guards.OPEN_PAYMENT_EXISTS)

    await _validate_section(session, data.section_id, contract)

    default_coefficient = data.default_coefficient or _DEFAULT_COEFFICIENT
    # Satırlar `session.add`DAN ÖNCE kurulur: fiyatsız kalem 422'si başlığı da
    # yazmadan döner (kısmi yazma yok).
    lines = await _build_lines(session, list(contract.items), default_coefficient)

    payment = SubcontractorProgressPayment(
        contract_id=contract.id,
        project_id=contract.project_id,
        sequence_no=await repository.get_next_sequence_no(session, contract.id),
        period_year=data.period_year,
        period_month=data.period_month,
        description=data.description,
        vat_pct=contract.vat_pct,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        default_coefficient=default_coefficient,
        section_id=data.section_id,
        created_by=actor.id,
    )
    payment.lines = lines
    session.add(payment)
    await session.flush()
    await session.refresh(payment)
    return PaymentContext(payment=payment, contract=contract, project=project)


# --- Düzenleme (yalnız draft) ---


async def update(
    session: AsyncSession,
    actor: User,
    payment_id: uuid.UUID,
    data: SubcontractorProgressPaymentUpdate,
) -> PaymentContext:
    context = await visible_payment(session, actor, payment_id)
    if context.payment.status != SubcontractorPaymentStatus.draft:
        raise ConflictError(guards.INVALID_STATUS_TRANSITION)

    changes = data.model_dump(exclude_unset=True)
    if "section_id" in changes:
        await _validate_section(session, changes["section_id"], context.contract)

    for field, value in changes.items():
        setattr(context.payment, field, value)
    await session.flush()
    await session.refresh(context.payment)
    return context


# --- Silme (işveren K8'in İKİ KATMANLI kuralı birebir) ---


async def delete_payment(
    session: AsyncSession, actor: User, payment_id: uuid.UUID
) -> DeletedPaymentSummary:
    """Katman 1: `approved`/`paid` ADMİN DAHİL kimseye silinmez (409).
    Katman 2: kalan kümede `can_delete` — admin koşulsuz, aksi hâlde yalnız
    kaydı AÇAN aktörün KENDİ taslağı (403).

    Silme de bir YAZMA işlemidir (işveren H8 denetimi K1): satır kilitsiz
    okunursa eşzamanlı bir onay katman-1 kontrolünü TOCTOU ile atlatabilir —
    bu yüzden kararlar KİLİTLİ satır üzerinden verilir.
    """
    payment, contract, project = await _visible_payment_locked(session, actor, payment_id)

    if payment.status in (SubcontractorPaymentStatus.approved, SubcontractorPaymentStatus.paid):
        raise ConflictError(guards.PAYMENT_NOT_DELETABLE)

    permission = await get_permission(session, actor.role_id, "progress_payments")
    level = permission.access_level if permission is not None else AccessLevel.none
    if not can_delete(actor.id, level, payment):
        raise DeleteNotAllowedError(guards.DELETE_NOT_ALLOWED)

    # Özet `session.delete` ÖNCESİNDE kurulur — sonra okunursa denetim satırı
    # sessizce varsayılanlara düşer (işveren H10 mutasyon denetiminin bulgusu).
    summary = DeletedPaymentSummary(
        project_name=project.name,
        subcontractor_name=contract.subcontractor_name,
        sequence_no=payment.sequence_no,
        status_label=_STATUS_LABELS[payment.status],
        amount=sum(
            (
                calculations.line_total(line.contract_unit_price, line.coefficient, line.quantity)
                for line in payment.lines
            ),
            Decimal("0.00"),
        ),
    )

    # `lines` cascade="all, delete-orphan" — satırlar birlikte gider.
    await session.delete(payment)
    await session.flush()
    return summary
