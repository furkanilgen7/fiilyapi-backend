"""Alıcı (müşteri) kartoteksi uçları — P8 T2 (spec §4).

`contracts/router.py`nin `/subcontractors` bloğunun birebiri: kapı sabitleri
modül düzeyinde tanımlanır, denetim metinleri `audit/messages.py`den gelir.

**`visible_projects` süzgeci BİLİNÇLİ OLARAK yok** (spec §6): `customers`
proje-bağımsızdır, tabloda `project_id` kolonu bile yoktur. Erişim yalnız `sales`
izin seviyesindedir. IDOR unutulmuş DEĞİLDİR — sonraki okuyucu bunu "eksik"
sanıp proje süzgeci EKLEMESİN.

**DELETE ucu AÇILMAZ** (spec §4): alıcıya bağlı satış kaydı bulunabilir
(`unit_sales.customer_id` RESTRICT). Kartoteksten çıkarma ihtiyacı doğarsa
çözüm bir aktiflik bayrağıdır, silme değil.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.core.ratelimit import client_ip
from app.modules.audit import messages
from app.modules.audit.models import AuditAction
from app.modules.audit.service import record_audit
from app.modules.customers import service
from app.modules.customers.schemas import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
)
from app.modules.users.models import User

router = APIRouter(tags=["customers"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("sales", AccessLevel.view)
_FULL = require_permission("sales", AccessLevel.full)


@router.get("/customers", response_model=CustomerListResponse, dependencies=[_VIEW])
async def list_customers_endpoint(
    session: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
) -> CustomerListResponse:
    """`q` ad / TCKN / VKN üzerinde kısmi arar (spec §4)."""
    items = await service.list_customers(session, q)
    return CustomerListResponse(items=[CustomerResponse.model_validate(c) for c in items])


@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_FULL],
)
async def create_customer_endpoint(
    request: Request,
    data: CustomerCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerResponse:
    customer = await service.create_customer(session, data)
    await record_audit(
        session,
        action=AuditAction.create,
        detail=messages.customer_created(customer.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return CustomerResponse.model_validate(customer)


@router.get("/customers/{customer_id}", response_model=CustomerResponse, dependencies=[_VIEW])
async def get_customer_endpoint(
    customer_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerResponse:
    customer = await service.get_customer(session, customer_id)
    return CustomerResponse.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse, dependencies=[_FULL])
async def update_customer_endpoint(
    request: Request,
    customer_id: uuid.UUID,
    data: CustomerUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerResponse:
    customer = await service.update_customer(session, customer_id, data)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.customer_updated(customer.name),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return CustomerResponse.model_validate(customer)
