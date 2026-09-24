"""Planlama (EV) izin kapilari ve santiye kapsami (PLANLAMA-SPEC §3.8 K17, §3.9 B1-8).

Seviye eslemesi `progress_payments` emsalidir (`AccessLevel` sirali:
none < view < draft < request < approve < full < admin):

| kapi        | seviye  | ne acar |
|-------------|---------|---------|
| `VIEW`      | view    | butun okumalar, onizleme |
| `WRITE`     | draft   | ayarlar, butce girdileri (oran/esleme/dagilim/pencere), taslak ac |
| `APPROVE`   | approve | baseline dondur, taslak sil (B3: rapor onayi + kilit acma) |
| `CATALOG`   | full    | sirket katalogu + disiplin yazma, "gerceklesen standart yap" |
| `ADMIN`     | admin   | disiplin silme (B1-9) |

Kapsam maskesi BAGLANMAZ (adam-saat para degil): router duz `APIRoute`dir,
`roles/service.py` limited/finance atamasini bu modulde zaten reddeder.
Santiye gorunurlugu iki katmanlidir (`site_planning/service.py` deseni): izin YETKIYI,
`visible_projects` KAPSAMI verir; gorunmeyen santiye ile olmayan santiye AYNI 404'u alir.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.errors import NotFoundError
from app.core.permissions import require_permission
from app.modules.projects.models import Project
from app.modules.projects.service import visible_projects
from app.modules.sites import repository as sites_repository
from app.modules.sites.guards import SITE_MISSING
from app.modules.sites.models import Site
from app.modules.users.models import User

PERMISSION_MODULE = "earned_value"

VIEW = require_permission(PERMISSION_MODULE, AccessLevel.view)
WRITE = require_permission(PERMISSION_MODULE, AccessLevel.draft)
APPROVE = require_permission(PERMISSION_MODULE, AccessLevel.approve)
CATALOG = require_permission(PERMISSION_MODULE, AccessLevel.full)
ADMIN = require_permission(PERMISSION_MODULE, AccessLevel.admin)


class SiteContext(NamedTuple):
    site: Site
    project: Project


async def visible_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> SiteContext:
    site = await sites_repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError(SITE_MISSING)
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == site.project_id), None)
    if project is None:
        raise NotFoundError(SITE_MISSING)
    return SiteContext(site=site, project=project)
