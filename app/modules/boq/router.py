import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.boq import service
from app.modules.boq.schemas import BoqListResponse
from app.modules.users.models import User

# Spec §4 karari: BOQ okuma/yazma uclari "sites" degil kendi "boq" iznine
# baglidir — site_chief/field_engineer'i ayirmanin tek yolu budur. Yazma
# uclari (T5/T6) icin "_FULL" burada tanimlanip o task'larda kullanilir.
# Uc kokleri bilincli karisiktir (plan §Frontend notu): bu ucun kendisi
# `/sites/...` altinda, T5/T6'daki bazi PATCH uclari `/boq/...` kokunde olacak.
router = APIRouter(tags=["boq"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("boq", AccessLevel.view)


@router.get("/sites/{site_id}/boq", response_model=BoqListResponse, dependencies=[_VIEW])
async def get_boq_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BoqListResponse:
    return await service.get_boq_for_site(session, user, site_id)
