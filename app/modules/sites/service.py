import re
import unicodedata
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.timezone import today
from app.modules.projects.models import Project

# Gorunurluk suzgeci P1'den GELIR (spec §5.2). Burada kopya bir erisim mantigi
# yazilmaz: iki ayri suzgec zamanla ayrisir ve ayrisan taraf sessiz bir yetki
# sizintisi olur.
from app.modules.projects.service import visible_projects
from app.modules.sites import repository
from app.modules.sites.models import Section, SectionStatus, Site, SiteStatus
from app.modules.sites.schemas import (
    CountPlaceholder,
    MetricPlaceholder,
    SectionCreate,
    SectionListResponse,
    SectionResponse,
    SectionStatusCounts,
    SectionUpdate,
    SiteCard,
    SiteCounts,
    SiteCreate,
    SiteDetailResponse,
    SiteListResponse,
    SiteListTotals,
    SiteProjectSummary,
    SiteUpdate,
)
from app.modules.users.models import User

# Spec §3: bos durum alanlari ve bagli olduklari dilim anahtarlari. Bunlar
# MODUL ANAHTARIDIR, kullaniciya gosterilecek metin degil (B6 §2.3).
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_PROJECT_COSTS = "project_costs"
_CONTRACTS = "contracts"
_BOQ = "boq"

_CODE_MAX_LENGTH = 50

# Turkce harfler NFKD ile ASCII'ye duzgun inmez (ı, ş, ğ) — once elle eslenir.
_TURKISH_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "I",
        "ş": "s",
        "Ş": "S",
        "ğ": "g",
        "Ğ": "G",
        "ç": "c",
        "Ç": "C",
        "ö": "o",
        "Ö": "O",
        "ü": "u",
        "Ü": "U",
    }
)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def derive_code(name: str) -> str:
    """Santiye adindan kod turetir (spec §8 acik soru 2, oneri uygulandi).

    Kod ZORUNLUDUR ama kullanicidan istenmez: ad ASCII'ye indirilir, buyuk
    harfe cevrilir, alfanumerik olmayan gruplar tek tireye duser. Turetilen kod
    kullanici tarafindan PATCH ile duzeltilebilir.
    """
    folded = unicodedata.normalize("NFKD", name.translate(_TURKISH_FOLD))
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-").upper()
    return slug[:_CODE_MAX_LENGTH] or "SANTIYE"


def _remaining_days(site: Site) -> int | None:
    """Spec §4.2. `completed` veya `end_date` yoksa null; gecmisse NEGATIF.

    Kirpma YAPILMAZ: gecikmeyi 0'a yuvarlamak backend'in gercegi bastirmasidir,
    gecikmeyi kirmizi gostermek frontend'in isidir.
    """
    if site.status is SiteStatus.completed or site.end_date is None:
        return None
    return (site.end_date - today()).days


def _resolve_city(site: Site, project: Project) -> tuple[str | None, bool]:
    """Spec §4.3: santiye sehri bossa PROJENIN sehri doldurulur ve bayraklanir.

    Boylece frontend "Kuyubasi Mah. Ankara" satirini her zaman basabilir, null
    dallanmasi tasimaz. Ikisi de bossa devralma YOKTUR — bayrak false kalir.
    """
    if site.city:
        return site.city, False
    if project.city:
        return project.city, True
    return None, False


def _section_counts(sections: list[Section]) -> SectionStatusCounts:
    return SectionStatusCounts(
        planned=sum(1 for s in sections if s.status is SectionStatus.planned),
        active=sum(1 for s in sections if s.status is SectionStatus.active),
        completed=sum(1 for s in sections if s.status is SectionStatus.completed),
    )


def to_section(section: Section) -> SectionResponse:
    return SectionResponse(
        id=section.id,
        code=section.code,
        name=section.name,
        status=section.status,
        manager_name=section.manager_name,
        start_date=section.start_date,
        end_date=section.end_date,
        sort_order=section.sort_order,
        progress_pct=_metric(_PROGRESS_PAYMENTS),
        boq_item_count=_count(_BOQ),
        budget=_metric(_BOQ),
        worker_count=_count(_TIMESHEET),
    )


def _card_fields(site: Site, project: Project) -> dict:
    city, city_inherited = _resolve_city(site, project)
    return {
        "id": site.id,
        "code": site.code,
        "name": site.name,
        "status": site.status,
        "address": site.address,
        "city": city,
        "city_inherited": city_inherited,
        "site_manager_name": site.site_manager_name,
        "start_date": site.start_date,
        "end_date": site.end_date,
        "delivery_date": site.delivery_date,
        "remaining_days": _remaining_days(site),
        "section_count": len(site.sections),
        "worker_count": _count(_TIMESHEET),
        "progress_pct": _metric(_PROGRESS_PAYMENTS),
    }


def to_card(site: Site, project: Project) -> SiteCard:
    return SiteCard(**_card_fields(site, project))


def to_detail(site: Site, project: Project) -> SiteDetailResponse:
    sections = list(site.sections)
    return SiteDetailResponse(
        **_card_fields(site, project),
        project=SiteProjectSummary.model_validate(project),
        section_status_counts=_section_counts(sections),
        sections=[to_section(s) for s in sections],
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        contract_amount=_metric(_CONTRACTS),
    )


def _totals() -> SiteListTotals:
    """Alt KPI seridi — bu dilimde TAMAMI yer tutucu (spec §4.1)."""
    return SiteListTotals(
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        subcontractor_count=_count(_SUBCONTRACTS),
        active_worker_count=_count(_TIMESHEET),
        average_margin=_metric(_PROJECT_COSTS),
    )


def _site_counts(sites: list[Site]) -> SiteCounts:
    return SiteCounts(
        all=len(sites),
        active=sum(1 for s in sites if s.status is SiteStatus.active),
        on_hold=sum(1 for s in sites if s.status is SiteStatus.on_hold),
        completed=sum(1 for s in sites if s.status is SiteStatus.completed),
    )


# --- Gorunurluk (spec §5.2) ---


async def _visible_project(session: AsyncSession, actor: User, project_id: uuid.UUID) -> Project:
    """Kullanici projeyi goremiyorsa 404 — 403 DEGIL: varligin kendisi sizdirilmaz."""
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return project


async def _visible_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> tuple[Site, Project]:
    """Santiye -> proje cozumu, ardindan ayni gorunurluk suzgeci."""
    site = await repository.get_site(session, site_id)
    if site is None:
        raise NotFoundError("Şantiye bulunamadı")
    project = await _visible_project(session, actor, site.project_id)
    return site, project


async def _visible_section(
    session: AsyncSession, actor: User, section_id: uuid.UUID
) -> tuple[Section, Site]:
    """Bolum -> santiye -> proje. EN KOLAY ATLANACAK GUVENLIK NOKTASI (spec §5.2):
    bolum kimligi ile dolayli erisim de proje suzgecinden gecmek zorundadir."""
    section = await repository.get_section(session, section_id)
    if section is None:
        raise NotFoundError("Bölüm bulunamadı")
    site, _ = await _visible_site(session, actor, section.site_id)
    return section, site


# --- Okuma uclari ---


async def list_sites_overview(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> SiteListResponse:
    project = await _visible_project(session, actor, project_id)
    sites = await repository.list_sites_for_project(session, project_id)
    return SiteListResponse(
        counts=_site_counts(sites),
        items=[to_card(site, project) for site in sites],
        totals=_totals(),
    )


async def get_site_detail(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> SiteDetailResponse:
    site, project = await _visible_site(session, actor, site_id)
    return to_detail(site, project)


async def list_sections_for_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID
) -> SectionListResponse:
    site, _ = await _visible_site(session, actor, site_id)
    sections = await repository.list_sections(session, site.id)
    return SectionListResponse(
        counts=_section_counts(sections), items=[to_section(s) for s in sections]
    )


# --- Yazma uclari ---


async def create_site(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: SiteCreate
) -> Site:
    await _visible_project(session, actor, project_id)
    site = Site(
        project_id=project_id,
        code=data.code or derive_code(data.name),
        name=data.name,
        status=data.status,
        address=data.address,
        city=data.city,
        site_manager_name=data.site_manager_name,
        start_date=data.start_date,
        end_date=data.end_date,
        delivery_date=data.delivery_date,
    )
    session.add(site)
    await session.flush()
    await session.refresh(site)
    return site


async def update_site(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: SiteUpdate
) -> Site:
    site, _ = await _visible_site(session, actor, site_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    await session.flush()
    await session.refresh(site)
    return site


async def create_section(
    session: AsyncSession, actor: User, site_id: uuid.UUID, data: SectionCreate
) -> Section:
    site, _ = await _visible_site(session, actor, site_id)
    section = Section(
        site_id=site.id,
        code=data.code,
        name=data.name,
        status=data.status,
        manager_name=data.manager_name,
        start_date=data.start_date,
        end_date=data.end_date,
        sort_order=data.sort_order,
    )
    session.add(section)
    await session.flush()
    await session.refresh(section)
    return section


async def update_section(
    session: AsyncSession, actor: User, section_id: uuid.UUID, data: SectionUpdate
) -> Section:
    section, _ = await _visible_section(session, actor, section_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(section, field, value)
    await session.flush()
    await session.refresh(section)
    return section
