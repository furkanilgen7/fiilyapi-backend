"""Puantaj matris uçları — T3 (spec §3).

`site_diary/router.py` deseninin kardeşi: kapı sabitleri modül düzeyinde
tanımlanır, denetim metinleri `audit/messages.py`den gelir, kesin kararlar
`service.py` + `matrix.py`dedir ve burada TEKRARLANMAZ.

Kapılar `timesheet` iznidir (seed satır 171, matris DEĞİŞMEZ): okuma `view`,
yazma `full`. Bu ayrım **saha mühendisini SALT OKUR** yapar (`timesheet=_V`) —
matrisi şantiye şefi (`_F`) doldurur. Proje müdürü (`_N`) okuyamaz bile.

Genel ekran (E5 `Ekran 5 - Puantaj.dc.html`) AYRI uç GEREKTİRMEZ (spec §3):
aynı iki uç bir şantiye seçicisiyle (E5 78) kullanılır.

Kapsam DIŞI: `export.xlsx` (T4) — bu dosyaya EKLENMEZ.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
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
from app.modules.timesheet import matrix, service
from app.modules.timesheet.schemas import TimesheetMatrix, TimesheetSave
from app.modules.users.models import User

router = APIRouter(tags=["timesheet"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission(service.PERMISSION_MODULE, AccessLevel.view)
_FULL = require_permission(service.PERMISSION_MODULE, AccessLevel.full)

# Donem ZORUNLUDUR (`site_diary`nin opsiyonel `year`/`month`undan bilincli fark):
# gunluk kayit LISTELENIR, puantaj bir AY MATRISIDIR ve mockup'ta ay secici her
# zaman doludur (SP 96 "Temmuz 2026"). Donemsiz matrisin sutun iskeleti bile yok.
_YEAR = Annotated[int, Query(ge=2000, le=2100)]
_MONTH = Annotated[int, Query(ge=1, le=12)]


@router.get("/sites/{site_id}/timesheet", response_model=TimesheetMatrix, dependencies=[_VIEW])
async def get_site_timesheet_endpoint(
    site_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    year: _YEAR,
    month: _MONTH,
    section_id: uuid.UUID | None = None,
) -> TimesheetMatrix:
    """ŞP/E5 puantaj matrisi: kişi satırları + gün hücreleri + türev toplamlar.

    `section_id` ŞP 99'un "Tüm Bölümler / Kat 6–10" seçicisidir. Başka şantiyenin
    bölümü boş matris DEĞİL 404 alır (kesin karar `service.visible_section`).
    """
    site, project = await service.visible_site(session, user, site_id)
    section = await service.visible_section(session, site, section_id)
    return await matrix.build(session, site, project, section, year=year, month=month)


@router.put("/sites/{site_id}/timesheet", response_model=TimesheetMatrix, dependencies=[_FULL])
async def save_site_timesheet_endpoint(
    request: Request,
    site_id: uuid.UUID,
    data: TimesheetSave,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    year: _YEAR,
    month: _MONTH,
) -> TimesheetMatrix:
    """ŞP 101 "Kaydet" — **DEĞİŞTİRME** semantiği (spec §7 S4).

    ⚠️ Gövde dönem+şantiye kapsamının TAM kümesidir: gövdede geçmeyen hücre
    SİLİNİR. Başka ayın ya da başka şantiyenin hücrelerine DOKUNULMAZ (kesin
    karar `service.save`).

    Denetim TEK dönem-özeti olayıdır; hücre başına olay yazmak 31×48'lik bir
    kaydetmede denetim günlüğünü kullanılamaz hâle getirirdi (spec §3).

    Yanıt GÜNCEL matristir (bölüm süzgeci UYGULANMAZ — kaydedilen kapsam
    şantiyenin tamamıdır, ekran kaydettiğinin tamamını geri görmelidir).
    """
    context = await service.visible_site(session, user, site_id)
    cell_count = await service.save(session, user, context, data, year=year, month=month)
    await record_audit(
        session,
        action=AuditAction.update,
        detail=messages.timesheet_saved(
            context.project.name, context.site.name, year, month, cell_count
        ),
        actor_user_id=user.id,
        ip_address=client_ip(request),
    )
    return await matrix.build(session, context.site, context.project, None, year=year, month=month)
