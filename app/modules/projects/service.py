import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.errors import DuplicateError, NotFoundError, ProjectTypeMismatchError
from app.modules.projects import repository
from app.modules.projects.models import (
    Employer,
    LandShareShareholder,
    Project,
    ProjectInvestment,
    ProjectLandShare,
    ProjectStatus,
    ProjectType,
)
from app.modules.projects.schemas import (
    ContractingCard,
    CountPlaceholder,
    EmployerCreate,
    InvestmentCard,
    LandShareCard,
    MetricPlaceholder,
    ProjectCounts,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectInvestmentInput,
    ProjectLandShareInput,
    ProjectListItem,
    ProjectListResponse,
    ProjectUpdate,
    ShareholderResponse,
)
from app.modules.roles.repository import get_permission

# Project.sites ters iliskisi sites.models icinde backref ile tanimlanir; sayaci
# okuyabilmek icin o modulun yuklenmis olmasi sarttir. Dongusel import YOK:
# sites.models yalniz projects.models'i import eder, projects.service'i degil.
from app.modules.sites.models import Site  # noqa: F401
from app.modules.users.models import User

# Spec §2: bos durum alanlari ve bagli olduklari dilim anahtarlari.
_PROGRESS_PAYMENTS = "progress_payments"
_TIMESHEET = "timesheet"
_SUBCONTRACTS = "subcontracts"
_UNITS = "units"
_PROJECT_COSTS = "project_costs"

_LAND_COST_FIXED = Decimal("0")  # kat karsiliginda tanim geregi 0 (spec §3.3)

_DUPLICATE_TAX_NUMBER = "Bu VKN ile kayıtlı bir işveren zaten var."
_EMPLOYER_NOT_FOUND = "İşveren bulunamadı"


# --- İşveren (employers) servisi (spec §3.1, §3.2) ---


async def list_employers(session: AsyncSession, q: str | None, active_only: bool) -> list[Employer]:
    return await repository.list_employers(session, q, active_only)


async def create_employer(session: AsyncSession, data: EmployerCreate) -> Employer:
    """Yinelenen VKN -> DuplicateError (409). Servis ONCE SELECT ile bakar ki
    kullaniciya alanina ozel Turkce mesaj verilsin; IntegrityError -> 409 handler'i
    yaris durumu emniyet agi olarak KALIR (spec §3.2)."""
    if data.tax_number is not None:
        existing = await repository.get_employer_by_tax_number(session, data.tax_number)
        if existing is not None:
            raise DuplicateError(_DUPLICATE_TAX_NUMBER)
    employer = Employer(
        name=data.name,
        tax_number=data.tax_number,
        contact_person=data.contact_person,
    )
    return await repository.add_employer(session, employer)


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
    return ProjectDetailResponse(**_to_item(project).model_dump(), site_count=len(project.sites))


async def visible_projects(session: AsyncSession, actor: User) -> list[Project]:
    """Spec §5.2: user_project_access suzgeci; projects=admin suzgeci atlar.

    Admin istisnasi Ayarlar kilitlenme korumasidir: erisim vermek icin tum
    projeleri listeleyebilmek gerekir.

    PUBLIC: P2 santiye/bolum uclari da bu suzgecten gecer (P2 spec §5.2) ve
    kendi kopya gorunurluk mantigini YAZMAZ. Tek kaynak burasidir.
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
    visible = await visible_projects(session, actor)
    selected = visible
    if type_filter is not None:
        wanted_type = ProjectType(type_filter)
        selected = [p for p in selected if p.project_type is wanted_type]
    if status_filter is not None:
        wanted_status = ProjectStatus(status_filter)
        selected = [p for p in selected if p.status is wanted_status]
    return ProjectListResponse(counts=_counts(visible), items=[_to_item(p) for p in selected])


async def _visible_project(session: AsyncSession, actor: User, project_id: uuid.UUID) -> Project:
    """Gorunur kumede olmayan proje 404 — varligi sizdirilmaz (spec §5.6).

    TEK kimlik-ile-erisim kapisi burasidir. Hem OKUMA hem YAZMA uclari bundan
    gecmek ZORUNDA: yalnizca okumayi suzmek, listede hic gorunmeyen bir projeyi
    UUID'sini bilen kullanicinin PATCH ile degistirebilmesi demektir.
    """
    visible = await visible_projects(session, actor)
    project = next((p for p in visible if p.id == project_id), None)
    if project is None:
        raise NotFoundError("Proje bulunamadı")
    return project


async def get_project_detail(
    session: AsyncSession, actor: User, project_id: uuid.UUID
) -> ProjectDetailResponse:
    return to_detail(await _visible_project(session, actor, project_id))


def _ensure_type_consistency(
    project_type: ProjectType,
    investment: ProjectInvestmentInput | None,
    land_share: ProjectLandShareInput | None,
) -> None:
    """Spec §3.5 korkulugu. Tek yazma yolu burasi oldugu icin kontrol tek noktada."""
    if investment is not None and project_type is not ProjectType.kendi_yatirim:
        raise ProjectTypeMismatchError(
            "Yatırım alanları yalnızca kendi yatırım projelerine girilebilir"
        )
    if land_share is not None and project_type is not ProjectType.kat_karsiligi:
        raise ProjectTypeMismatchError(
            "Arsa payı alanları yalnızca kat karşılığı projelerine girilebilir"
        )


def _apply_investment(project: Project, data: ProjectInvestmentInput) -> None:
    if project.investment is None:
        project.investment = ProjectInvestment(project_id=project.id)
    project.investment.sales_target = data.sales_target
    project.investment.land_cost = data.land_cost


def _apply_land_share(project: Project, data: ProjectLandShareInput) -> None:
    if project.land_share is None:
        project.land_share = ProjectLandShare(project_id=project.id)
    land_share = project.land_share
    land_share.landowner_name = data.landowner_name
    land_share.our_share_pct = data.our_share_pct
    land_share.owner_share_pct = data.owner_share_pct
    land_share.contract_no = data.contract_no
    land_share.notary_date = data.notary_date
    land_share.land_area_m2 = data.land_area_m2
    land_share.construction_area_m2 = data.construction_area_m2
    land_share.delivery_date = data.delivery_date
    land_share.daily_penalty = data.daily_penalty
    land_share.guarantee_amount = data.guarantee_amount
    # Hissedar listesi BUTUNUYLE degistirilir (spec §5.5) — parca parca CRUD yok.
    project.shareholders = [
        LandShareShareholder(name=s.name, share_pct=s.share_pct) for s in data.shareholders
    ]


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    _ensure_type_consistency(data.project_type, data.investment, data.land_share)
    project = Project(
        code=data.code,
        name=data.name,
        project_type=data.project_type,
        status=data.status,
        category=data.category,
        city=data.city,
        start_date=data.start_date,
        end_date=data.end_date,
        contract_no=data.contract_no,
        contract_amount=data.contract_amount,
        employer_name=data.employer_name,
    )
    session.add(project)
    await session.flush()
    # Yeni flush edilmis nesnenin investment/land_share/shareholders iliskileri
    # henuz sync eslenmemis: asagidaki senkron `is None` erisimleri async ortamda
    # MissingGreenlet patlatir. `refresh` ile async-guvenli yukleyip bosalttik.
    await session.refresh(project, attribute_names=["investment", "land_share", "shareholders"])
    if data.investment is not None:
        _apply_investment(project, data.investment)
    if data.land_share is not None:
        _apply_land_share(project, data.land_share)
    await session.flush()
    await session.refresh(project)
    return project


async def update_project(
    session: AsyncSession, actor: User, project_id: uuid.UUID, data: ProjectUpdate
) -> Project:
    project = await _visible_project(session, actor, project_id)
    _ensure_type_consistency(project.project_type, data.investment, data.land_share)
    changes = data.model_dump(exclude_unset=True, exclude={"investment", "land_share"})
    for field, value in changes.items():
        setattr(project, field, value)
    if data.investment is not None:
        _apply_investment(project, data.investment)
    if data.land_share is not None:
        _apply_land_share(project, data.land_share)
    await session.flush()
    await session.refresh(project)
    return project
