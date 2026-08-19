"""ORM satiri -> Pydantic yanit donusumleri + yer tutucu sayaclar.

DB'ye YAZMAZ, gorunurluk suzmez: yalnizca bir satiri ekranin gordugu
sekle cevirir. Yer tutucu zarflari (`MetricPlaceholder`/`CountPlaceholder`)
burada kurulur — alan TIPI degismesin diye zarf korunur, yalnizca doldurulur."""

import uuid
from collections.abc import Mapping

from app.core.timezone import today
from app.modules.projects.models import Project
from app.modules.sites.models import Section, SectionMilestone, SectionStatus, Site, SiteStatus
from app.modules.sites.schemas import (
    CountPlaceholder,
    MetricPlaceholder,
    SectionDetailResponse,
    SectionMilestoneResponse,
    SectionResponse,
    SectionStatusCounts,
    SiteCard,
    SiteCounts,
    SiteDetailResponse,
    SiteFacilities,
    SiteListTotals,
    SiteProjectSummary,
)

# Spec §3: bos durum alanlari ve bagli olduklari dilim anahtarlari. Bunlar
# MODUL ANAHTARIDIR, kullaniciya gosterilecek metin degil (B6 §2.3).
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_PROJECT_COSTS = "project_costs"
_CONTRACTS = "contracts"
_BOQ = "boq"


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def _worker_count(value: int) -> CountPlaceholder:
    """T4 — `_TIMESHEET` yer tutucusunun BAGLANMIS hali (spec §4).

    Zarf (`CountPlaceholder`) KORUNUR, yalnizca doldurulur: `available=True` +
    gercek `count`. Kartin diger sayaclari (`boq_item_count`, `subcontractor_count`,
    `progress_pct`...) hâlâ yer tutucudur; alanin TIPINI degistirmek ekranin ayni
    seridinde iki farkli sozlesme birakirdi. `pending_module` kaynak modulu
    isaretlemeye devam eder — artik "bekleyen" degil "besleyen" moduldur.
    """
    return CountPlaceholder(available=True, count=value, pending_module=_TIMESHEET)


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


def _facilities(site: Site) -> SiteFacilities:
    """DB'deki 8 duz Boolean kolonu API'nin GRUPLU sozlesmesine cevirir (§4.1).

    Donusum SERVIS katmanindadir: sema kendi basina DB bilmez.
    """
    return SiteFacilities(
        closed_warehouse=site.has_closed_warehouse,
        open_storage=site.has_open_storage,
        cold_storage=site.has_cold_storage,
        site_office=site.has_site_office,
        canteen=site.has_canteen,
        changing_room_wc=site.has_changing_room_wc,
        dormitory=site.has_dormitory,
        infirmary=site.has_infirmary,
    )


def _to_milestone(row: SectionMilestone) -> SectionMilestoneResponse:
    return SectionMilestoneResponse(
        id=row.id,
        title=row.title,
        milestone_date=row.milestone_date,
        sort_order=row.sort_order,
    )


def to_section(section: Section, worker_count: int) -> SectionResponse:
    return SectionResponse(
        id=section.id,
        code=section.code,
        name=section.name,
        status=section.status,
        manager_user_id=section.manager_user_id,
        manager_name=section.manager_name,
        start_date=section.start_date,
        end_date=section.end_date,
        sort_order=section.sort_order,
        progress_pct=_metric(_PROGRESS_PAYMENTS),
        boq_item_count=_count(_BOQ),
        budget=_metric(_BOQ),
        worker_count=_worker_count(worker_count),
        # P11 (spec §3): iki alan da TEK donusturucuden gectigi icin bolum basan
        # UC yuzeyde (detay, liste, santiye detayi) ayni anda dogar. Milestone
        # sirasi DETERMINISTIKTIR — `Section.milestones` iliskisi
        # `(sort_order, id)` ile siralidir, burada yeniden siralanmaz.
        depends_on_section_id=section.depends_on_section_id,
        milestones=[_to_milestone(row) for row in section.milestones],
    )


def to_section_detail(section: Section, worker_count: int) -> SectionDetailResponse:
    """P6 §5 — bolum detay govdesi: `to_section`in TUM alanlari + T1 kolonlari.

    Yer tutucular `to_section`ten AYNEN devralinir (yeniden kurulmaz): dort
    `pending_module` degeri tek yerde tanimli kalir, aksi hâlde liste ve detay
    ekranlari zamanla farkli modul anahtarlari gosterirdi.
    """
    return SectionDetailResponse(
        **to_section(section, worker_count).model_dump(),
        site_id=section.site_id,
        section_type=section.section_type,
        description=section.description,
        deputy_manager_user_id=section.deputy_manager_user_id,
        deputy_manager_name=section.deputy_manager_name,
        planned_worker_count=section.planned_worker_count,
        budget_amount=section.budget_amount,
        is_draft=section.is_draft,
        created_at=section.created_at,
        updated_at=section.updated_at,
    )


def _card_fields(site: Site, project: Project, worker_count: int) -> dict:
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
        "worker_count": _worker_count(worker_count),
        "progress_pct": _metric(_PROGRESS_PAYMENTS),
        # --- Santiye formu genislemesi (§6.2): YALNIZ EKLEME ---
        "is_draft": site.is_draft,
        "site_manager_user_id": site.site_manager_user_id,
        "safety_officer_user_id": site.safety_officer_user_id,
        "safety_officer_name": site.safety_officer_name,
        "safety_officer_is_outsourced": site.safety_officer_is_outsourced,
        "neighborhood": site.neighborhood,
        "parcel": site.parcel,
        "gps_coordinates": site.gps_coordinates,
        "land_area_m2": site.land_area_m2,
        "construction_area_m2": site.construction_area_m2,
        "floor_info": site.floor_info,
        "budget": site.budget,
        "facilities": _facilities(site),
        "electricity_subscription_no": site.electricity_subscription_no,
        "water_subscription_no": site.water_subscription_no,
        "planned_worker_count": site.planned_worker_count,
    }


def to_card(site: Site, project: Project, worker_count: int) -> SiteCard:
    return SiteCard(**_card_fields(site, project, worker_count))


def to_detail(
    site: Site,
    project: Project,
    worker_count: int,
    section_worker_counts: Mapping[uuid.UUID, int],
) -> SiteDetailResponse:
    sections = list(site.sections)
    return SiteDetailResponse(
        **_card_fields(site, project, worker_count),
        project=SiteProjectSummary.model_validate(project),
        section_status_counts=_section_counts(sections),
        sections=[to_section(s, section_worker_counts.get(s.id, 0)) for s in sections],
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        contract_amount=_metric(_CONTRACTS),
    )


def _totals(active_worker_count: int) -> SiteListTotals:
    """Alt KPI seridi. T4'te YALNIZ `active_worker_count` baglandi; gerisi hâlâ
    yer tutucudur (spec §4.1) ve kendi dilimlerini bekler."""
    return SiteListTotals(
        total_progress_payment=_metric(_PROGRESS_PAYMENTS),
        subcontractor_count=_count(_SUBCONTRACTS),
        active_worker_count=_worker_count(active_worker_count),
        average_margin=_metric(_PROJECT_COSTS),
    )


def _site_counts(sites: list[Site]) -> SiteCounts:
    return SiteCounts(
        all=len(sites),
        active=sum(1 for s in sites if s.status is SiteStatus.active),
        on_hold=sum(1 for s in sites if s.status is SiteStatus.on_hold),
        completed=sum(1 for s in sites if s.status is SiteStatus.completed),
        # §5.2: TEK ekleme. Taslaklar durum sayaclarindan DUSULMEZ — durumlari
        # ne ise o sayilir; bu sayac ayrica artar.
        draft=sum(1 for s in sites if s.is_draft),
    )
