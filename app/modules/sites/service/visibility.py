"""Gorunurluk suzgeci (spec §5.2) — 404 zinciri.

🔴 Suzgec P1'den GELIR; burada kopya erisim mantigi YAZILMAZ.
`_visible_site` `boq.service` tarafindan da yeniden kullanilir."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.projects.models import Project

# Gorunurluk suzgeci P1'den GELIR (spec §5.2). Burada kopya bir erisim mantigi
# yazilmaz: iki ayri suzgec zamanla ayrisir ve ayrisan taraf sessiz bir yetki
# sizintisi olur.
from app.modules.projects.service import visible_projects
from app.modules.sites import guards, repository
from app.modules.sites.models import Section, Site
from app.modules.users.models import User

# 404 GOVDESI DE AYIRT EDICI OLMAMALIDIR. Durum kodunun 404 olmasi tek basina
# yetmez: gorunmeyen bir projedeki GERCEK santiye icin "Proje bulunamadı",
# var olmayan santiye icin "Şantiye bulunamadı" donerse, elinde bir UUID olan
# kullanici kaydin hala var oldugunu ve baska bir projeye ait oldugunu ayirt
# edebilir. Bu yuzden ISTENEN kaynagin mesaji zincir boyunca TASINIR: santiye
# ucunda hem "yok" hem "gormuyorsun" ayni cevabi verir.
#
# Metinler T5'te `guards.py`'ye TASINDI (spec §7.2 tablosu tek yerde durur);
# burada yalniz yerel takma adlar kalir — iki kopya metin zamanla ayrisir.
_PROJECT_MISSING = guards.PROJECT_MISSING
_SITE_MISSING = guards.SITE_MISSING
_SECTION_MISSING = guards.SECTION_MISSING


async def _visible_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, missing: str = _PROJECT_MISSING
) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError(missing)
    return project


async def _visible_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID, missing: str = _SITE_MISSING
) -> tuple[Site, Project]:
    """Santiye -> proje cozumu, ardindan ayni gorunurluk suzgeci."""
    site = await repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError(missing)
    project = await _visible_project(session, actor, site.project_id, missing)
    return site, project


async def _visible_section(
    session: AsyncSession, actor: User, section_id: uuid.UUID
) -> tuple[Section, Site]:
    """Bolum -> santiye -> proje. EN KOLAY ATLANACAK GUVENLIK NOKTASI (spec §5.2):
    bolum kimligi ile dolayli erisim de proje suzgecinden gecmek zorundadir."""
    section = await repository.get_section(session, section_id)
    if section is None:
        raise NotFoundError(_SECTION_MISSING)
    site, _ = await _visible_site(session, actor, section.site_id, _SECTION_MISSING)
    return section, site
