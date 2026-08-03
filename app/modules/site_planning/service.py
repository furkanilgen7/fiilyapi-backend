"""Planlama kapsam kararları ve hafta korkuluğu (planlama spec §3).

İKİ KATMANLI koruma (`timesheet/service.py` deseninin birebiri): **`site_diary`**
izni router'da YETKİYİ verir (spec §6 S1 — planlama kendi izin modülünü AÇMAZ),
bu modül `projects.service.visible_projects` ile KAPSAMI belirler. Görünmeyen
projedeki GERÇEK şantiye ile var OLMAYAN kimlik AYIRT EDİLEMEZ 404 döner.

T3 yazma uçları da bu iki yardımcıyı ÇAĞIRIR, kopyalamaz: hafta korkuluğu ile
kapsam kararı okuma ve yazmada ayrışırsa, yazma kullanıcının görmediği bir
haftayı DEĞİŞTİRME semantiğiyle süpürebilir.
"""

import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, SiteValidationError
from app.modules.projects.models import Project
from app.modules.projects.service import visible_projects
from app.modules.site_planning import guards, repository
from app.modules.sites import repository as sites_repository
from app.modules.sites.models import Site
from app.modules.users.models import User

PERMISSION_MODULE = "site_diary"
"""Spec §6 S1 (ONAYLI): planlama günlük kaydın izniyle korunur — bölüm emsali.

Yeni bir izin modülü AÇILMAZ: matris seed'de sabittir, planlama için ayrı bir
satır açmak hem seed migration'ı hem de 14 modüllük izin ekranını değiştirirdi.
Sonucu: şef + saha mühendisi (`_F`) yazar, proje müdürü (`_V`) okur, İK (`_N`)
hiç göremez.
"""


class SiteContext(NamedTuple):
    """Kapsam süzgecinden geçmiş şantiye + projesi."""

    site: Site
    project: Project


def assert_week_start(week_start: date) -> date:
    """`week_start` Pazartesi DEĞİLSE 422 — sessiz kaydırma YOK.

    Gerekçe `guards.WEEK_START_NOT_MONDAY` yanındadır. Fonksiyon değeri geri
    döner ki çağıran "doğrulanmış hafta" ile devam ettiğini tipten görsün.
    """
    if not repository.is_monday(week_start):
        raise SiteValidationError(guards.WEEK_START_NOT_MONDAY)
    return week_start


async def visible_site(session: AsyncSession, actor: User, site_id: uuid.UUID) -> SiteContext:
    """Şantiye → proje. Görünmeyen projenin şantiyesi ile var olmayan şantiye AYNI
    404 gövdesini döner; metin `sites` modülünün TEK cümlesidir (kopya üretilmez)."""
    site = await sites_repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError(guards.SITE_MISSING)
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == site.project_id), None)
    if project is None:
        raise NotFoundError(guards.SITE_MISSING)
    return SiteContext(site=site, project=project)
