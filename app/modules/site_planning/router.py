"""Şantiye planlama uçları (T2) — haftalık ızgara OKUMA.

Kapı **`site_diary`** iznidir (spec §6 S1; yeni izin modülü AÇILMAZ): okuma
`view`, yazma (T3) `full`. Bu ayrım proje müdürünü (matriste `site_diary=_V`)
SALT OKUR yapar — planı görür, T3'ün `PUT`larında 403 alır.

Okuma ucudur: `record_audit` ÇAĞIRMAZ (WORKFLOW kuralı — okumalar denetlenmez).

Kapsam DIŞI: yazma uçları (T3) · gün özeti (T4) · malzeme planı (spec §5).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.site_planning import read, service
from app.modules.site_planning.schemas import SitePlanWeek
from app.modules.users.models import User

router = APIRouter(tags=["site-planning"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)


@router.get("/sites/{site_id}/plan", response_model=SitePlanWeek, dependencies=[_VIEW])
async def get_site_plan_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    week_start: Annotated[date, Query()],
) -> SitePlanWeek:
    """P (Planlama) ızgarasının bir haftası: gruplar + hücreler + hedefler + sprint.

    `week_start` ZORUNLUDUR (puantajın `year`/`month`u gibi): haftasız bir
    ızgaranın sütun iskeleti bile yoktur. Pazartesi değilse 422 — sessiz kaydırma
    ekranın başka bir haftayı gösterdiğini fark etmesini engellerdi.
    """
    return await read.get_week(session, user, site_id, week_start)
