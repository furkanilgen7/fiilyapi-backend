"""Sözleşmeler (P5) uçları — task C5 yalnız birleşik liste ucunu açar.

`boq/router.py` deseninin aynısı: kapı sabitleri modül düzeyinde tanımlanır,
sonraki task'lar (C6-C12) `_VIEW`/`_FULL`/`_ADMIN`'i buradan import eder.
"""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.contracts import distribution, service, subcontractors, subcontracts
from app.modules.contracts.models import ContractStatus
from app.modules.contracts.schemas import (
    ContractDistributionResponse,
    ContractDistributionSave,
    ContractListResponse,
    ContractType,
    EmployerContractDetail,
    EmployerContractGroupCreate,
    EmployerContractGroupResponse,
    EmployerContractGroupUpdate,
    EmployerContractItemCreate,
    EmployerContractItemResponse,
    EmployerContractItemsResponse,
    EmployerContractItemUpdate,
    SubcontractorContractCreate,
    SubcontractorContractDetail,
    SubcontractorContractItemCreate,
    SubcontractorContractItemResponse,
    SubcontractorContractItemsLoadResponse,
    SubcontractorContractItemUpdate,
    SubcontractorContractUpdate,
    SubcontractorCreate,
    SubcontractorListResponse,
    SubcontractorResponse,
    SubcontractorUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["contracts"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("contracts", AccessLevel.view)
_FULL = require_permission("contracts", AccessLevel.full)
# KULLANICI KARARI 2026-07-30 (kalıcı karar 2, `boq/router.py` deseninin aynısı):
# silme YALNIZ sistem yöneticisindedir — `full` yazmayı kapsar, SİLMEYİ KAPSAMAZ.
_ADMIN = require_permission("contracts", AccessLevel.admin)


@router.get("/contracts", response_model=ContractListResponse, dependencies=[_VIEW])
async def list_contracts_endpoint(
    contract_type: Annotated[ContractType, Query(alias="type")],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID | None = None,
    status_filter: Annotated[ContractStatus | None, Query(alias="status")] = None,
    q: str | None = None,
) -> ContractListResponse:
    return await service.list_contracts(session, user, contract_type, project_id, status_filter, q)


# --- İşveren sözleşmesi: okuma + poz grup/kalem yazma (task C6, spec §6.2) ---
#
# Uç kökleri `boq/router.py` deseninin aynısı: GET/POST alt kaynakta
# `/projects/{project_id}/contract/...` altında, PATCH düz kökte
# `/contracts/employer/...` (dolaylı kimlik çözümlemesi kullanır).
#
# Denetim günlüğü mesajları C13'te `app/modules/audit/messages.py`'ye
# merkezileştirilecek (spec §8: `employer_contract_group_created/updated`,
# `employer_contract_item_created/updated`). O fonksiyonlar henüz YOK — task
# brief kararı gereği burada `boq_group_created`/`boq_item_created` metin
# DESENİNİN AYNISI kullanılarak GEÇİCİ, modül-içi yardımcılarla yazılır.


def _employer_contract_group_created(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu oluşturuldu: {project_name} · {name}"


def _employer_contract_group_updated(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu güncellendi: {project_name} · {name}"


def _employer_contract_item_created(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi oluşturuldu: {project_name} · {code} — {description}"


def _employer_contract_item_updated(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi güncellendi: {project_name} · {code} — {description}"


def _contract_distribution_saved(project_name: str) -> str:
    """Task C8 — spec §8'de `contract_distribution_saved` olarak merkezileşecek.
    `audit/messages.py`'de HENÜZ YOK; C6'nın geçici yardımcı deseni izlenir."""
    return f"Poz dağılımı kaydedildi: {project_name}"


# --- Taşeron kartoteksi (task C9, spec §3.4/§6.4) ---
#
# `employer_created`'in aynı geçici-yardımcı gerekçesi: C13, spec §8'de
# `subcontractor_created`/`subcontractor_updated` olarak merkezileştirecek —
# bugün `audit/messages.py`'de YOK.


def _subcontractor_created(name: str) -> str:
    return f"Taşeron oluşturuldu: {name}"


def _subcontractor_updated(name: str) -> str:
    return f"Taşeron güncellendi: {name}"


@router.get(
    "/projects/{project_id}/contract",
    response_model=EmployerContractDetail,
    dependencies=[_VIEW],
)
async def get_employer_contract_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractDetail:
    return await service.get_employer_contract_detail(session, user, project_id)


@router.get(
    "/projects/{project_id}/contract/items",
    response_model=EmployerContractItemsResponse,
    dependencies=[_VIEW],
)
async def get_employer_contract_items_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractItemsResponse:
    return await service.get_employer_contract_items(session, user, project_id)


@router.get(
    "/projects/{project_id}/contract/distribution",
    response_model=ContractDistributionResponse,
    dependencies=[_VIEW],
)
async def get_contract_distribution_endpoint(
    project_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractDistributionResponse:
    return await distribution.build_distribution(session, user, project_id)


@router.put(
    "/projects/{project_id}/contract/distribution",
    response_model=ContractDistributionResponse,
    dependencies=[_FULL],
)
async def save_contract_distribution_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: ContractDistributionSave,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContractDistributionResponse:
    """`POZ` 24 "Dağılımı Kaydet" — ekranın tamamı tek atomik istekte."""
    result = await distribution.save_distribution(session, user, project_id, data)
    project = await service._visible_project(session, user, project_id)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_contract_distribution_saved(project.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return result


@router.post(
    "/projects/{project_id}/contract/groups",
    response_model=EmployerContractGroupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_employer_contract_group_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: EmployerContractGroupCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractGroupResponse:
    group, project = await service.create_employer_group(session, user, project_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_employer_contract_group_created(project.name, group.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return EmployerContractGroupResponse(id=group.id, name=group.name, sort_order=group.sort_order)


@router.patch(
    "/contracts/employer/groups/{group_id}",
    response_model=EmployerContractGroupResponse,
    dependencies=[_FULL],
)
async def update_employer_contract_group_endpoint(
    request: Request,
    group_id: uuid.UUID,
    data: EmployerContractGroupUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractGroupResponse:
    group, project = await service.update_employer_group(session, user, group_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_employer_contract_group_updated(project.name, group.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return EmployerContractGroupResponse(id=group.id, name=group.name, sort_order=group.sort_order)


def _employer_contract_group_deleted(project_name: str, name: str) -> str:
    return f"Sözleşme poz grubu silindi: {project_name} · {name}"


@router.delete(
    "/contracts/employer/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ADMIN],
)
async def delete_employer_contract_group_endpoint(
    request: Request,
    group_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7. 409 `GROUP_HAS_ITEMS`: grupta poz varsa silinmez. Kapı `_ADMIN`

    (`boq/router.py.delete_boq_item_endpoint` deseninin birebiri).
    """
    project_name, group_name = await service.delete_employer_group(session, user, group_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=_employer_contract_group_deleted(project_name, group_name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.post(
    "/projects/{project_id}/contract/items",
    response_model=EmployerContractItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_employer_contract_item_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: EmployerContractItemCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractItemResponse:
    item, project = await service.create_employer_item(session, user, project_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_employer_contract_item_created(project.name, item.code, item.description),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    # Yeni oluşturulan kaleme henüz hiçbir BOQ satırı bağlı OLAMAZ — dağıtım
    # sıfırdır, ek sorgu atmaya gerek yok.
    return service.to_item_response(item, Decimal("0"))


@router.patch(
    "/contracts/employer/items/{item_id}",
    response_model=EmployerContractItemResponse,
    dependencies=[_FULL],
)
async def update_employer_contract_item_endpoint(
    request: Request,
    item_id: uuid.UUID,
    data: EmployerContractItemUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EmployerContractItemResponse:
    item, project = await service.update_employer_item(session, user, item_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_employer_contract_item_updated(project.name, item.code, item.description),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await service.to_item_response_single(session, item)


def _employer_contract_item_deleted(project_name: str, code: str, description: str) -> str:
    return f"Sözleşme poz kalemi silindi: {project_name} · {code} — {description}"


@router.delete(
    "/contracts/employer/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ADMIN],
)
async def delete_employer_contract_item_endpoint(
    request: Request,
    item_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7. Engel YOK: bağlı `boq_items.contract_item_id` DB'de `ON DELETE

    SET NULL` ile serbest kalır, satır SİLİNMEZ. Kapı `_ADMIN`
    (`boq/router.py.delete_boq_item_endpoint` deseninin birebiri).
    """
    project_name, code, description = await service.delete_employer_item(session, user, item_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=_employer_contract_item_deleted(project_name, code, description),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


# --- Taşeron kartoteksi (task C9, spec §6.4) ---
#
# `employers_router` (`app/modules/projects/router.py`) deseninin birebiri.
# DELETE bu task'ta AÇILMAZ — C12'nin işi (409 `SUBCONTRACTOR_HAS_CONTRACTS`).
# `visible_projects` süzgeci BİLİNÇLİ OLARAK yok: kartoteks proje-bağımsızdır
# (`Employer` de aynı şekilde geçmiyor).


@router.get(
    "/subcontractors",
    response_model=SubcontractorListResponse,
    dependencies=[_VIEW],
)
async def list_subcontractors_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    active_only: bool = True,
) -> SubcontractorListResponse:
    items = await subcontractors.list_subcontractors(session, q, active_only)
    return SubcontractorListResponse(items=[SubcontractorResponse.model_validate(s) for s in items])


@router.post(
    "/subcontractors",
    response_model=SubcontractorResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_subcontractor_endpoint(
    request: Request,
    data: SubcontractorCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorResponse:
    subcontractor = await subcontractors.create_subcontractor(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_subcontractor_created(subcontractor.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return SubcontractorResponse.model_validate(subcontractor)


@router.patch(
    "/subcontractors/{subcontractor_id}",
    response_model=SubcontractorResponse,
    dependencies=[_FULL],
)
async def update_subcontractor_endpoint(
    request: Request,
    subcontractor_id: uuid.UUID,
    data: SubcontractorUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorResponse:
    subcontractor = await subcontractors.update_subcontractor(session, subcontractor_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_subcontractor_updated(subcontractor.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return SubcontractorResponse.model_validate(subcontractor)


def _subcontractor_deleted(name: str) -> str:
    return f"Taşeron silindi: {name}"


@router.delete(
    "/subcontractors/{subcontractor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ADMIN],
)
async def delete_subcontractor_endpoint(
    request: Request,
    subcontractor_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7. 409 `SUBCONTRACTOR_HAS_CONTRACTS`: taşeronun sözleşmesi varsa

    silinmez. Kapı `_ADMIN` — `boq/router.py.delete_boq_item_endpoint`/
    `sites/router.py.delete_site_endpoint` deseninin BİREBİRİ, `can_delete`
    istisnası YOK (yalnız `subcontractor-contracts` silme ucunda geçerli).
    """
    name = await subcontractors.delete_subcontractor(session, subcontractor_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=_subcontractor_deleted(name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


# --- Taşeron sözleşmesi POST/GET/PATCH (task C10, spec §6.5) ---
#
# DELETE, kalem uçları ve `load-from-employer` bu task'ta AÇILMAZ — C11/C12'nin
# işi. `_subcontractor_contract_created`/`_updated`: C6/C9'un aynı geçici-
# yardımcı gerekçesi — C13, spec §8'de merkezileştirecek.


def _subcontract_label(contract_no: str | None, subcontractor_name: str | None) -> str:
    return contract_no or subcontractor_name or "taslak"


def _subcontractor_contract_created(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi oluşturuldu: {project_name} · {label}"


def _subcontractor_contract_updated(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi güncellendi: {project_name} · {label}"


@router.post(
    "/projects/{project_id}/subcontractor-contracts",
    response_model=SubcontractorContractDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_subcontractor_contract_endpoint(
    request: Request,
    project_id: uuid.UUID,
    data: SubcontractorContractCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractDetail:
    contract, project = await subcontracts.create_subcontractor_contract(
        session, user, project_id, data
    )
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_subcontractor_contract_created(
            project.name, _subcontract_label(contract.contract_no, contract.subcontractor_name)
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await subcontracts.to_subcontract_detail(session, contract)


@router.get(
    "/subcontractor-contracts/{contract_id}",
    response_model=SubcontractorContractDetail,
    dependencies=[_VIEW],
)
async def get_subcontractor_contract_endpoint(
    contract_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractDetail:
    contract = await subcontracts.get_subcontractor_contract(session, user, contract_id)
    return await subcontracts.to_subcontract_detail(session, contract)


@router.patch(
    "/subcontractor-contracts/{contract_id}",
    response_model=SubcontractorContractDetail,
    dependencies=[_FULL],
)
async def update_subcontractor_contract_endpoint(
    request: Request,
    contract_id: uuid.UUID,
    data: SubcontractorContractUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractDetail:
    contract, project = await subcontracts.update_subcontractor_contract(
        session, user, contract_id, data
    )
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_subcontractor_contract_updated(
            project.name, _subcontract_label(contract.contract_no, contract.subcontractor_name)
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await subcontracts.to_subcontract_detail(session, contract)


def _subcontractor_contract_deleted(project_name: str, label: str) -> str:
    return f"Taşeron sözleşmesi silindi: {project_name} · {label}"


@router.delete(
    "/subcontractor-contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_FULL],
)
async def delete_subcontractor_contract_endpoint(
    request: Request,
    contract_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7, §5.0. KAPI KARARI (task C12, belirsizlik notu): bu ucun dısındaki

    DÖRT DELETE ucu (`subcontractors`, kalemler, işveren grup/kalem) `boq`/
    `sites` deseninin BİREBİRİ — saf `_ADMIN` kapısı, servis katmanında ek
    kontrol YOK. Bu uç TEK istisna: kapı `_FULL`'dir, kesin yetki kararını
    `subcontracts.delete_subcontractor_contract` içindeki `can_delete`
    (`app/core/access.py`, spec §5.0 taslak istisnası) verir. Gerekçe: `boq`/
    `sites` DELETE uçlarının HİÇBİRİ `can_delete`'i KULLANMIYOR (kod taraması
    doğrulandı) — saf `_ADMIN` kapısı proje müdürünün KENDİ taslağını silmesini
    de engellerdi, bu da spec §5.0'ın taslak istisnasını uçta ANLAMSIZ
    bırakırdı. En yakın emsal `projects/service.py.visible_projects`'in
    `get_permission` ile aktörün gerçek erişim seviyesini SERVİSTE okuma
    deseni — o da router kapısının (`_VIEW`) ötesinde ek bir servis içi karar
    örneğidir.
    """
    (
        project_name,
        contract_no,
        subcontractor_name,
    ) = await subcontracts.delete_subcontractor_contract(session, user, contract_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=_subcontractor_contract_deleted(
            project_name, _subcontract_label(contract_no, subcontractor_name)
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


# --- Taşeron sözleşmesi kalemleri + `load-from-employer` (task C11, spec §6.5) ---
#
# DELETE bu task'ta AÇILMAZ — C12'nin işi. `_subcontract_item_created/_updated/
# _items_loaded`: C6/C9/C10'un aynı geçici-yardımcı gerekçesi — spec §8'de
# `subcontract_item_created/updated`, `subcontract_items_loaded` olarak
# merkezileşecek, `audit/messages.py`'de HENÜZ YOK (C13 taşır).


def _subcontract_item_created(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi oluşturuldu: {contract_no or 'taslak'} · {code}"


def _subcontract_item_updated(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi güncellendi: {contract_no or 'taslak'} · {code}"


def _subcontract_items_loaded(contract_no: str | None, count: int) -> str:
    label = contract_no or "taslak"
    return f"Taşeron sözleşmesi kalemleri işverenden yüklendi: {label} · {count} kalem"


@router.post(
    "/subcontractor-contracts/{contract_id}/items",
    response_model=SubcontractorContractItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_subcontract_item_endpoint(
    request: Request,
    contract_id: uuid.UUID,
    data: SubcontractorContractItemCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractItemResponse:
    item, contract, _ = await subcontracts.create_subcontract_item(session, user, contract_id, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_subcontract_item_created(contract.contract_no, item.code),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await subcontracts.to_subcontract_item_response(session, item)


@router.patch(
    "/subcontractor-contracts/items/{item_id}",
    response_model=SubcontractorContractItemResponse,
    dependencies=[_FULL],
)
async def update_subcontract_item_endpoint(
    request: Request,
    item_id: uuid.UUID,
    data: SubcontractorContractItemUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractItemResponse:
    item, contract, _ = await subcontracts.update_subcontract_item(session, user, item_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=_subcontract_item_updated(contract.contract_no, item.code),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await subcontracts.to_subcontract_item_response(session, item)


def _subcontract_item_deleted(contract_no: str | None, code: str) -> str:
    return f"Taşeron sözleşmesi kalemi silindi: {contract_no or 'taslak'} · {code}"


@router.delete(
    "/subcontractor-contracts/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_ADMIN],
)
async def delete_subcontract_item_endpoint(
    request: Request,
    item_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Spec §7. Engel YOK. Kapı `_ADMIN` — `can_delete` istisnası burada YOK,

    yalnız `DELETE /subcontractor-contracts/{contract_id}` ucunda geçerlidir
    (task brief kararı).
    """
    contract_no, code = await subcontracts.delete_subcontract_item(session, user, item_id)
    await record_audit(
        session,
        action=AuditAction.delete,
        detail=_subcontract_item_deleted(contract_no, code),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.post(
    "/subcontractor-contracts/{contract_id}/items/load-from-employer",
    response_model=SubcontractorContractItemsLoadResponse,
    dependencies=[_FULL],
)
async def load_subcontract_items_from_employer_endpoint(
    request: Request,
    contract_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubcontractorContractItemsLoadResponse:
    created_count, skipped_count, contract, _ = await subcontracts.load_items_from_employer(
        session, user, contract_id
    )
    await record_audit(
        session,
        action=AuditAction.create,
        detail=_subcontract_items_loaded(contract.contract_no, created_count),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return SubcontractorContractItemsLoadResponse(
        created_count=created_count, skipped_count=skipped_count
    )
