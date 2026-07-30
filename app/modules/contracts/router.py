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
from app.modules.contracts import distribution, service, subcontractors
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
