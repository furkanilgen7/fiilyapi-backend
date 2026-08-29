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
from app.modules.projects.service import project_matches_ref, visible_projects
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
    session: AsyncSession,
    actor: User,
    project_ref: uuid.UUID | str,
    missing: str = _PROJECT_MISSING,
) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz.

    URL-2: `project_ref` UUID ya da slug olabilir; eslestirme P1'in
    `project_matches_ref`inden GELIR (kopya slug mantigi yazilmaz).
    """
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if project_matches_ref(p, project_ref)), None)
    if project is None:
        raise NotFoundError(missing)
    return project


async def _visible_site(
    session: AsyncSession,
    actor: User,
    site_ref: uuid.UUID | str,
    missing: str = _SITE_MISSING,
    *,
    project_ref: uuid.UUID | str | None = None,
) -> tuple[Site, Project]:
    """Santiye -> proje cozumu, ardindan ayni gorunurluk suzgeci.

    ## URL-2 — slug yolu ve NEDEN KAPSAM PARAMETRESI VAR

    `sites.slug` PROJE ICINDE tekildir (`uq_sites_project_code` aynasi), ama bu
    UC DUZDUR: yolda ust katman YOKTUR (olculdu: 18 santiye yolunun tamami
    `/sites/...` altinda duz). Yani ciplak bir slug tek basina ANLAMLI DEGILDIR:
    iki projede birden `a-blok` bulunabilir. Bu yuzden istege bagli `project_ref`
    kapsami vardir — frontend URL'i (`/projeler/<p>/santiyeler/<s>`) zaten
    nested oldugu icin onu her zaman verebilir.

    Kapsam VERILMEZSE cozumleme GORUNUR kume icinde yapilir ve **tek aday**
    sartina baglanir: sifir ya da BIRDEN COK aday -> 404. FAIL-CLOSED. Rastgele
    birini secmek, kullaniciya yanlis santiyeyi ACARDI.

    🔴 IDOR: aday sorgusu SADECE gorunur proje kimlikleriyle sinirlidir. Slug
    tahmin edilebilir oldugu icin bu sinir, UUID yolundakiyle ayni kapinin slug
    yolundaki BAGIMSIZ karsiligidir — UUID dalinin `_visible_project` cagrisina
    GUVENMEZ, kendi suzgecini kurar.
    """
    if isinstance(site_ref, uuid.UUID):
        site = await repository.get_site(session, site_ref)
        if site is None:
            raise NotFoundError(missing)
        project = await _visible_project(session, actor, site.project_id, missing)
        return site, project

    visible = await visible_projects(session, actor)
    if project_ref is not None:
        visible = [p for p in visible if project_matches_ref(p, project_ref)]
    projects = {p.id: p for p in visible}
    candidates = await repository.list_sites_by_slug(session, list(projects), site_ref)
    if len(candidates) != 1:
        raise NotFoundError(missing)
    site = candidates[0]
    return site, projects[site.project_id]


async def _visible_section(
    session: AsyncSession,
    actor: User,
    section_ref: uuid.UUID | str,
    *,
    site_ref: uuid.UUID | str | None = None,
    project_ref: uuid.UUID | str | None = None,
) -> tuple[Section, Site]:
    """Bolum -> santiye -> proje. EN KOLAY ATLANACAK GUVENLIK NOKTASI (spec §5.2):
    bolum kimligi ile dolayli erisim de proje suzgecinden gecmek zorundadir.

    URL-2: `section_ref` slug ise kapsam ZINCIRI `_visible_site` uzerinden
    kurulur — yani bolum slug'i once GORUNUR santiye kumesine indirgenir, sonra
    o kume icinde aranir. `_visible_site`in tek-aday/fail-closed kurali burada
    da aynen gecerlidir.
    """
    if isinstance(section_ref, uuid.UUID):
        section = await repository.get_section(session, section_ref)
        if section is None:
            raise NotFoundError(_SECTION_MISSING)
        site, _ = await _visible_site(session, actor, section.site_id, _SECTION_MISSING)
        return section, site

    if site_ref is not None:
        site, _ = await _visible_site(
            session, actor, site_ref, _SECTION_MISSING, project_ref=project_ref
        )
        site_ids = [site.id]
    else:
        visible = await visible_projects(session, actor)
        if project_ref is not None:
            visible = [p for p in visible if project_matches_ref(p, project_ref)]
        site_ids = await repository.list_site_ids_for_projects(session, [p.id for p in visible])

    candidates = await repository.list_sections_by_slug(session, site_ids, section_ref)
    if len(candidates) != 1:
        raise NotFoundError(_SECTION_MISSING)
    section = candidates[0]
    owning_site = await repository.get_site(session, section.site_id)
    if owning_site is None:
        raise NotFoundError(_SECTION_MISSING)
    return section, owning_site
