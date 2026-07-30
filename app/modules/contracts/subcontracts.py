"""Taşeron sözleşmesi POST/GET/PATCH servis katmanı (spec §6.5, task C10).

`sites/service.py.create_site`/`update_site` deseninin birebiri: doğrulama +
kullanıcı/kartoteks çözümü YAZMADAN ÖNCE biter (§8.2 atomiklik), taslak→yayın
geçişi BİRLEŞİK kayıt üzerinde tam doğrulama koşturur, genel PATCH dalında
zorunluluk kuralları KOŞMAZ (`sites/guards.py` §0.3/3 dersi).

Kurallar `guards.validate_subcontract`den TEK KOPYA çağrılır — burada
yeniden yazılmaz. `site_id`→proje eşleşmesi ve `subcontractor_name` anlık
görüntüsü DB erişimi gerektirdiği için `validate_subcontract` içinde değil,
burada kontrol edilir (guards.py docstring'inin aynı gerekçesi).
"""

import uuid
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, NotFoundError, SiteValidationError
from app.modules.contracts import guards, repository
from app.modules.contracts.models import SubcontractorContract, SubcontractorContractItem
from app.modules.contracts.schemas import (
    SubcontractorContractCreate,
    SubcontractorContractDetail,
    SubcontractorContractItemGroup,
    SubcontractorContractItemResponse,
    SubcontractorContractUpdate,
)
from app.modules.contracts.service import _subcontractor_amount, _visible_project
from app.modules.projects.models import Project
from app.modules.sites import repository as sites_repository
from app.modules.users.models import User

# Spec §3.5: global kısmi benzersizlik (dolu contract_no'lar çakışamaz).
# `subcontractors.py._DUPLICATE_TAX_NUMBER` deseninin aynısı — spec §4
# tablosunun BİREBİR listesinde değildir, bu yüzden `guards.py`de DEĞİL burada
# durur (task C9 kararının aynısı).
_DUPLICATE_CONTRACT_NO = "Bu sözleşme no ile kayıtlı bir sözleşme zaten var."

# PATCH'in BİRLEŞİK kayıt doğrulamasının okuduğu alanlar. `sites/service.py.
# _VALIDATED_FIELDS` deseninin aynısı: `items` burada YOK, kalemler ayrı
# uçlarla yönetilir (C11) — yayına geçişte "girilmiş kalemlerin hepsinde
# birim fiyat" kuralı MEVCUT kalemler üzerinden koşar.
_VALIDATED_FIELDS = (
    "subcontractor_id",
    "work_category",
    "contract_no",
    "signature_date",
    "start_date",
    "end_date",
)


async def _ensure_site_in_project(
    session: AsyncSession, site_id: uuid.UUID | None, project_id: uuid.UUID
) -> None:
    """Spec §4 tutarlılık kuralı — HER ZAMAN koşar (taslakta da)."""
    if site_id is None:
        return
    site = await sites_repository.get_site(session, site_id)
    if site is None or site.project_id != project_id:
        raise SiteValidationError(guards.SITE_PROJECT_MISMATCH)


async def _resolve_subcontractor_name(
    session: AsyncSession, subcontractor_id: uuid.UUID | None
) -> str | None:
    """Anlık görüntü — HER yazmada kartotekten kopyalanır (spec §3.5).

    `subcontractor_id` alan DEĞERİ olarak ele alınır (`sites._resolve_user_name`
    deseninin aynısı): geçersizse 404 DEĞİL, 422 döner.
    """
    if subcontractor_id is None:
        return None
    subcontractor = await repository.get_subcontractor(session, subcontractor_id)
    if subcontractor is None:
        raise SiteValidationError(guards.SUBCONTRACTOR_MISSING)
    return subcontractor.name


async def _ensure_contract_no_unique(
    session: AsyncSession, contract_no: str | None, *, exclude_id: uuid.UUID | None = None
) -> None:
    if contract_no is None:
        return
    existing = await repository.get_subcontractor_contract_by_contract_no(
        session, contract_no, exclude_id=exclude_id
    )
    if existing is not None:
        raise DuplicateError(_DUPLICATE_CONTRACT_NO)


async def create_subcontractor_contract(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: SubcontractorContractCreate
) -> tuple[SubcontractorContract, Project]:
    """`FORM` gövdesi — kalemler İÇ İÇE ve ATOMİK (spec §6.5, `sites` + bölümler

    deseninin aynısı): herhangi bir kalem geçersizse sözleşme de yazılmaz.
    `Project` da döner: router'daki denetim günlüğü satırı proje ADI ister.
    """
    project = await _visible_project(session, actor, project_id)
    # Tutarlılık: HER ZAMAN (taslakta da) — `validate_subcontract` içinde DEĞİL.
    await _ensure_site_in_project(session, data.site_id, project_id)
    subcontractor_name = await _resolve_subcontractor_name(session, data.subcontractor_id)
    guards.validate_subcontract(
        SimpleNamespace(
            project_id=project_id,
            subcontractor_id=data.subcontractor_id,
            work_category=data.work_category,
            contract_no=data.contract_no,
            signature_date=data.signature_date,
            start_date=data.start_date,
            end_date=data.end_date,
            items=data.items,
        ),
        is_draft=data.is_draft,
    )
    await _ensure_contract_no_unique(session, data.contract_no)

    contract = SubcontractorContract(
        project_id=project_id,
        site_id=data.site_id,
        subcontractor_id=data.subcontractor_id,
        subcontractor_name=subcontractor_name,
        work_category=data.work_category,
        contract_no=data.contract_no,
        signature_date=data.signature_date,
        is_notarized=data.is_notarized,
        start_date=data.start_date,
        end_date=data.end_date,
        late_penalty_daily=data.late_penalty_daily,
        advance_pct=data.advance_pct,
        retainage_pct=data.retainage_pct,
        payment_period=data.payment_period,
        payment_term_days=data.payment_term_days,
        materials_by_contractor=data.materials_by_contractor,
        subcontractor_files_own_sgk=data.subcontractor_files_own_sgk,
        vat_withholding=data.vat_withholding,
        status=data.status,
        is_draft=data.is_draft,
        created_by=actor.id,
    )
    session.add(contract)
    await session.flush()
    for index, item in enumerate(data.items):
        session.add(
            SubcontractorContractItem(
                contract_id=contract.id,
                source_contract_item_id=item.source_contract_item_id,
                code=item.code,
                description=item.description,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                sort_order=item.sort_order or index,
            )
        )
    await session.flush()
    await session.refresh(contract)
    return contract, project


async def _visible_contract(
    session: AsyncSession, actor: User, contract_id: uuid.UUID
) -> tuple[SubcontractorContract, Project]:
    """Sözleşme -> proje. Dolaylı kimlikle erişim de görünürlük süzgecinden

    geçmek ZORUNDA (`service._visible_group`/`_visible_item` deseninin aynısı).
    Görünmeyen projedeki gerçek kayıt ile var olmayan kayıt AYNI 404 gövdesini
    döner (spec §6, IDOR).
    """
    contract = await repository.get_subcontractor_contract(session, contract_id)
    if contract is None:
        raise NotFoundError(guards.CONTRACT_MISSING)
    project = await _visible_project(session, actor, contract.project_id, guards.CONTRACT_MISSING)
    return contract, project


async def get_subcontractor_contract(
    session: AsyncSession, actor: User, contract_id: uuid.UUID
) -> SubcontractorContract:
    contract, _ = await _visible_contract(session, actor, contract_id)
    return contract


def _merged_for_validation(contract: SubcontractorContract, changes: dict) -> SimpleNamespace:
    """Mevcut satır + patch = doğrulamanın gördüğü kayıt (`sites/service.py.

    _merged_for_validation` deseninin aynısı). `items` MEVCUT satırdan gelir:
    yayına geçişte "girilmiş kalemlerin hepsinde birim fiyat" kuralı zaten
    kaydedilmiş kalemler üzerinden koşar — PATCH gövdesi kalem TAŞIMAZ.
    """
    merged = {field: changes.get(field, getattr(contract, field)) for field in _VALIDATED_FIELDS}
    return SimpleNamespace(project_id=contract.project_id, items=contract.items, **merged)


async def update_subcontractor_contract(
    session: AsyncSession, actor: User, contract_id: uuid.UUID, data: SubcontractorContractUpdate
) -> tuple[SubcontractorContract, Project]:
    """PATCH GEVŞEK, YAYIN SIKI (`sites.update_site` deseninin aynısı, spec §4).

    Genel dalda zorunluluk kuralları KOŞMAZ — koşsaydı canlıdaki eksik kayıtlı
    taslaklar düzenlenemez hale gelirdi. Tek istisna `is_draft: true -> false`
    geçişidir: orada BİRLEŞİK kayıt üzerinde tüm kurallar koşar ve geçmezse
    satır TASLAK KALIR. Tutarlılık kuralları (şantiye-proje eşleşmesi dahil)
    HER İKİ dalda da koşar.
    """
    contract, project = await _visible_contract(session, actor, contract_id)
    changes = data.model_dump(exclude_unset=True)

    # Tutarlılık: HER ZAMAN — değişen `site_id` (veya mevcut değeri) yeniden
    # kontrol edilir.
    merged_site_id = changes.get("site_id", contract.site_id)
    await _ensure_site_in_project(session, merged_site_id, contract.project_id)

    is_publishing = contract.is_draft and changes.get("is_draft") is False
    guards.validate_subcontract(
        _merged_for_validation(contract, changes), is_draft=not is_publishing
    )

    if "contract_no" in changes and changes["contract_no"] != contract.contract_no:
        await _ensure_contract_no_unique(session, changes["contract_no"], exclude_id=contract.id)

    # Anlık görüntü: `subcontractor_id` değiştiyse ad kartotekten YENİDEN
    # kopyalanır (spec §3.5) — istemciden gelen ad YOKTUR, olamaz da (şema).
    if "subcontractor_id" in changes:
        changes["subcontractor_name"] = await _resolve_subcontractor_name(
            session, changes["subcontractor_id"]
        )

    for field, value in changes.items():
        setattr(contract, field, value)
    await session.flush()
    await session.refresh(contract)
    return contract, project


async def _item_groups(
    session: AsyncSession, items: list[SubcontractorContractItem]
) -> dict[uuid.UUID, SubcontractorContractItemGroup]:
    """Bağlı kalemlerin grup başlıkları — `source_contract_item_id` üzerinden

    TÜRER (spec §3.6, ayrı grup tablosu yok).
    """
    source_ids = [item.source_contract_item_id for item in items if item.source_contract_item_id]
    if not source_ids:
        return {}
    rows = await repository.get_employer_item_groups(session, source_ids)
    return {
        item_id: SubcontractorContractItemGroup(id=group_id, name=group_name)
        for item_id, group_id, group_name in rows
    }


async def to_subcontract_detail(
    session: AsyncSession, contract: SubcontractorContract
) -> SubcontractorContractDetail:
    """`TSD` başlığı + kalemler + türev toplam (spec §6.5)."""
    groups = await _item_groups(session, contract.items)
    items_missing_price = sum(1 for item in contract.items if item.unit_price is None)
    item_responses = [
        SubcontractorContractItemResponse(
            id=item.id,
            contract_id=item.contract_id,
            source_contract_item_id=item.source_contract_item_id,
            code=item.code,
            description=item.description,
            unit=item.unit,
            quantity=item.quantity,
            unit_price=item.unit_price,
            sort_order=item.sort_order,
            group=groups.get(item.source_contract_item_id)
            if item.source_contract_item_id
            else None,
        )
        for item in contract.items
    ]
    return SubcontractorContractDetail(
        id=contract.id,
        project_id=contract.project_id,
        site_id=contract.site_id,
        subcontractor_id=contract.subcontractor_id,
        subcontractor_name=contract.subcontractor_name,
        work_category=contract.work_category,
        contract_no=contract.contract_no,
        signature_date=contract.signature_date,
        is_notarized=contract.is_notarized,
        start_date=contract.start_date,
        end_date=contract.end_date,
        late_penalty_daily=contract.late_penalty_daily,
        advance_pct=contract.advance_pct,
        retainage_pct=contract.retainage_pct,
        payment_period=contract.payment_period,
        payment_term_days=contract.payment_term_days,
        materials_by_contractor=contract.materials_by_contractor,
        subcontractor_files_own_sgk=contract.subcontractor_files_own_sgk,
        vat_withholding=contract.vat_withholding,
        status=contract.status,
        is_draft=contract.is_draft,
        items=item_responses,
        contract_total=_subcontractor_amount(contract),
        items_missing_price=items_missing_price,
    )
