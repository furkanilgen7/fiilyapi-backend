"""Makine & ekipman uçları (MK-1 spec §4) — T1'de BOŞ.

Kapı `equipment` iznidir (21. modül, spec §6): okuma `view`, yazmanın tamamı
`full`. Görünmeyen kayıt 404'tür.

`inventory`/`documents` router'larının aksine bu router PREFIX TAŞIR (`/equipment`):
spec §4'ün SAYDIĞI uçların hepsi tek kökün altındadır (`/equipment`,
`/equipment/summary`, `/equipment/work-logs`, `/equipment/work-summary`,
`/equipment/fuel-logs`, `/equipment/fuel-summary`) — ikinci bir kök yoktur.

## AÇILMAYAN uç (spec §4, icat yasağı)

**`DELETE /equipment/{id}` YOKTUR.** Kullanımdan kaldırma
`PATCH {"is_active": false}` iledir; kaydı olan ekipman zaten `RESTRICT`
yüzünden DB seviyesinde de silinemez. Yol tanımlı olmadığı için FastAPI 405
döner ve bu bir BEKÇİ TESTİYLE kilitlenmiştir (`test_silme_ucu_yoktur_405`).
Kira hakedişi (M5) ve ekipman belgeleri MK-2'nindir (spec §9) — bu router'da
HİÇBİRİ açılmaz.

Çalışma kaydı, yakıt ve özet uçları (spec §4'ün kalan blokları) T4-T5'indir.

`GET` uçları `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez);
yazma uçlarının ikisi de tek denetim satırı yazar ve metin servis katmanında
kurulur.

## Yol SIRASI önemlidir

`/equipment/summary` `/equipment/{equipment_id}`den ÖNCE tanımlanır: sonra
gelseydi FastAPI "summary"yi bir UUID sanıp yolu 422'ye düşürürdü.
"""

import uuid
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
from app.modules.equipment import service
from app.modules.equipment.models import (
    EquipmentCategory,
    EquipmentOwnership,
    EquipmentStatus,
)
from app.modules.equipment.schemas import (
    EquipmentCreate,
    EquipmentListResponse,
    EquipmentResponse,
    EquipmentSummaryResponse,
    EquipmentUpdate,
)
from app.modules.users.models import User

router = APIRouter(prefix="/equipment", tags=["equipment"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)


async def _audit(
    request: Request,
    session: AsyncSession,
    user: User,
    action: AuditAction,
    detail: str,
) -> None:
    """Denetim satırı (B5 deseni). Metin PARAMETREDİR, burada kurulmaz."""
    await record_audit(
        session,
        action=action,
        detail=detail,
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )


@router.get("", response_model=EquipmentListResponse, dependencies=[_VIEW])
async def list_equipment_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[EquipmentStatus | None, Query(alias="status")] = None,
    category: EquipmentCategory | None = None,
    site_id: uuid.UUID | None = None,
    ownership: EquipmentOwnership | None = None,
    q: str | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EquipmentListResponse:
    """M1 kart listesi — süzgeçler AND'lidir, kapsam (K20) HER ZAMAN üsttedir.

    `q` ad + marka + model + plaka + seri üzerinde kısmi arar: M1 kartı bu
    alanları üst üste basar ve tek alanda aramak kullanıcıyı "yok" sanısına
    düşürürdü.

    `is_active` spec §4'ün SAYDIĞI süzgeçlerden değildir ama listenin varsayılanı
    "hepsi"dir; pasifleri ayıklamak isteyen ekran onu açıkça verir. Varsayılan
    `false` yapılsaydı hurdaya ayrılan makine hiçbir listede bulunamazdı.
    """
    items, total = await service.list_equipment(
        session,
        user,
        status=status_filter,
        category=category,
        site_id=site_id,
        ownership=ownership,
        q=q,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return EquipmentListResponse(
        items=[EquipmentResponse.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=EquipmentSummaryResponse, dependencies=[_VIEW])
async def equipment_summary_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentSummaryResponse:
    """M1 KPI'ları: DÖRT durum sayacı (K21) + cari ay çalışma maliyeti.

    Sayaçlar ve maliyet AYNI kapsam süzgecinden geçer — sayaç sızıntısı da bir
    sızıntıdır (görünmeyen projenin filo büyüklüğünü ele verir).
    """
    return EquipmentSummaryResponse.model_validate(await service.summarize(session, user))


@router.post(
    "",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Seçilen şantiye, operatör ya da tedarikçi bulunamadı"},
        422: {"description": "Sahip olunan ekipmanda alış bedeli zorunludur (K2)"},
    },
    dependencies=[_FULL],
)
async def create_equipment_endpoint(
    request: Request,
    data: EquipmentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentResponse:
    """M2 formunun kaydı. `site_id` verilmezse makine DEPODADIR (K4)."""
    equipment, detail = await service.create_equipment(session, user, data)
    await _audit(request, session, user, AuditAction.create, detail)
    return EquipmentResponse.model_validate(equipment)


@router.get("/{equipment_id}", response_model=EquipmentResponse, dependencies=[_VIEW])
async def get_equipment_endpoint(
    equipment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentResponse:
    """Görünmeyen kayıt var olmayanla AYNI 404'ü döner (spec §4)."""
    return EquipmentResponse.model_validate(
        await service.visible_equipment(session, user, equipment_id)
    )


@router.patch(
    "/{equipment_id}",
    response_model=EquipmentResponse,
    responses={422: {"description": "Sahip olunan ekipmanda alış bedeli zorunludur (K2)"}},
    dependencies=[_FULL],
)
async def update_equipment_endpoint(
    request: Request,
    equipment_id: uuid.UUID,
    data: EquipmentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentResponse:
    """Kısmi güncelleme. **Kullanımdan kaldırma da buradan geçer**
    (`{"is_active": false}`) — DELETE ucu yoktur (modül docstring'i).

    K2 burada da koşar ve MEVCUT SATIR + GÖVDE birleşimine bakar."""
    equipment = await service.visible_equipment(session, user, equipment_id)
    equipment, detail = await service.update_equipment(session, equipment, user, data)
    await _audit(request, session, user, AuditAction.update, detail)
    return EquipmentResponse.model_validate(equipment)
