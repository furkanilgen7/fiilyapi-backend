import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.errors import NotFoundError
from app.modules.projects import repository
from app.modules.projects.models import Project, ProjectStatus, ProjectType
from app.modules.projects.schemas import (
    ContractingCard,
    CountPlaceholder,
    InvestmentCard,
    LandShareCard,
    MetricPlaceholder,
    ProjectCounts,
    ProjectDetailResponse,
    ProjectListItem,
    ProjectListResponse,
    ShareholderResponse,
)
from app.modules.roles.repository import get_permission
from app.modules.users.models import User

# Spec §2: bos durum alanlari ve bagli olduklari dilim anahtarlari.
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_UNITS = "units"
_PROJECT_COSTS = "project_costs"

_LAND_COST_FIXED = Decimal("0")  # kat karsiliginda tanim geregi 0 (spec §3.3)


def _metric(pending_module: str) -> MetricPlaceholder:
    return MetricPlaceholder(pending_module=pending_module)


def _count(pending_module: str) -> CountPlaceholder:
    return CountPlaceholder(pending_module=pending_module)


def _contracting_card() -> ContractingCard:
    return ContractingCard(
        spent=_metric(_PROGRESS_PAYMENTS),
        physical_progress=_metric(_PROGRESS_PAYMENTS),
        final_progress_payment=_metric(_PROGRESS_PAYMENTS),
        worker_count=_count(_TIMESHEET),
        subcontractor_count=_count(_SUBCONTRACTS),
    )


def _investment_card(project: Project) -> InvestmentCard:
    investment = project.investment
    return InvestmentCard(
        sales_target=investment.sales_target if investment else None,
        land_cost=investment.land_cost if investment else None,
        sold_amount=_metric(_UNITS),
        sales_ratio=_metric(_UNITS),
        unit_summary=_count(_UNITS),
        total_cost=_metric(_PROJECT_COSTS),
        estimated_profit=_metric(_PROJECT_COSTS),
        margin=_metric(_PROJECT_COSTS),
    )


def _land_share_card(project: Project) -> LandShareCard | None:
    land_share = project.land_share
    if land_share is None:
        return None
    return LandShareCard(
        landowner_name=land_share.landowner_name,
        our_share_pct=land_share.our_share_pct,
        owner_share_pct=land_share.owner_share_pct,
        land_cost=_LAND_COST_FIXED,
        contract_no=land_share.contract_no,
        notary_date=land_share.notary_date,
        land_area_m2=land_share.land_area_m2,
        construction_area_m2=land_share.construction_area_m2,
        delivery_date=land_share.delivery_date,
        daily_penalty=land_share.daily_penalty,
        guarantee_amount=land_share.guarantee_amount,
        shareholder_count=len(project.shareholders),
        shareholders=[ShareholderResponse.model_validate(s) for s in project.shareholders],
        our_unit_count=_count(_UNITS),
        owner_unit_count=_count(_UNITS),
        our_share_value=_metric(_UNITS),
        construction_cost=_metric(_PROJECT_COSTS),
        estimated_profit=_metric(_PROJECT_COSTS),
        margin=_metric(_PROJECT_COSTS),
        construction_progress=_metric(_PROGRESS_PAYMENTS),
    )


def _to_item(project: Project) -> ProjectListItem:
    """ProjectListItem.model_validate(project) calisamaz: ORM nesnesinde
    contracting/investment/land_share alanlari (bunlar turetilmis karttir, DB
    sutunu degil) yok — bu yuzden ortak alanlar elle cikarilir."""
    is_contracting = project.project_type is ProjectType.taahhut
    is_investment = project.project_type is ProjectType.kendi_yatirim
    is_land_share = project.project_type is ProjectType.kat_karsiligi
    return ProjectListItem(
        id=project.id,
        code=project.code,
        name=project.name,
        project_type=project.project_type,
        category=project.category,
        city=project.city,
        status=project.status,
        start_date=project.start_date,
        end_date=project.end_date,
        contract_no=project.contract_no,
        contract_amount=project.contract_amount,
        employer_name=project.employer_name,
        budget=project.budget,
        progress_pct=project.progress_pct,
        contracting=_contracting_card() if is_contracting else None,
        investment=_investment_card(project) if is_investment else None,
        land_share=_land_share_card(project) if is_land_share else None,
    )


def to_detail(project: Project) -> ProjectDetailResponse:
    return ProjectDetailResponse(**_to_item(project).model_dump())


async def _visible_projects(session: AsyncSession, actor: User) -> list[Project]:
    """Spec §5.2: user_project_access suzgeci; projects=admin suzgeci atlar.

    Admin istisnasi Ayarlar kilitlenme korumasidir: erisim vermek icin tum
    projeleri listeleyebilmek gerekir.
    """
    permission = await get_permission(session, actor.role_id, "projects")
    if permission is not None and permission.access_level is AccessLevel.admin:
        return await repository.list_projects(session)
    return await repository.list_projects_for_user(session, actor.id)


def _counts(projects: list[Project]) -> ProjectCounts:
    return ProjectCounts(
        all=len(projects),
        taahhut=sum(1 for p in projects if p.project_type is ProjectType.taahhut),
        kendi_yatirim=sum(1 for p in projects if p.project_type is ProjectType.kendi_yatirim),
        kat_karsiligi=sum(1 for p in projects if p.project_type is ProjectType.kat_karsiligi),
        completed=sum(1 for p in projects if p.status is ProjectStatus.completed),
    )


async def list_projects_overview(
    session: AsyncSession,
    actor: User,
    type_filter: ProjectType | str | None,
    status_filter: ProjectStatus | str | None,
) -> ProjectListResponse:
    """Sayaclar filtreden ETKILENMEZ — mockup sekmeleri hep tum kumeyi sayar (spec §5.1)."""
    visible = await _visible_projects(session, actor)
    selected = visible
    if type_filter is not None:
        wanted_type = ProjectType(type_filter)
        selected = [p for p in selected if p.project_type is wanted_type]
    if status_filter is not None:
        wanted_status = ProjectStatus(status_filter)
        selected = [p for p in selected if p.status is wanted_status]
    return ProjectListResponse(counts=_counts(visible), items=[_to_item(p) for p in selected])


async def get_project_detail(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ProjectDetailResponse:
    """Gorunur kumede olmayan proje 404 — varligi sizdirilmaz (spec §5.6)."""
    visible = await _visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return to_detail(project)
