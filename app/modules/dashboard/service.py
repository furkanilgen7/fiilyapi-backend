from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.schemas import (
    DashboardProjectCard,
    DashboardSummaryResponse,
    ListPlaceholder,
    MetricPlaceholder,
    PendingApprovalsPlaceholder,
)
from app.modules.projects.models import ProjectStatus
from app.modules.projects.repository import list_projects_for_user
from app.modules.roles.models import Role
from app.modules.users.models import User

# Spec §7: veri kaynagi olmayan kartlar ve bagli olduklari modul anahtarlari.
# Ilgili alt-proje geldiginde bu kartlar gercek deger dondurmeye baslar.
_PORTFOLIO_MODULE = "progress_payments"
_RECEIVABLES_MODULE = "invoicing"
_MARGIN_MODULE = "progress_payments"
_APPROVALS_MODULE = "approvals"
_RISKS_MODULE = "inventory"


async def build_summary(session: AsyncSession, user: User) -> DashboardSummaryResponse:
    """Gosterge paneli ozeti. Projeler gercek, bes kart bos durum (spec §7)."""
    projects = await list_projects_for_user(session, user.id)
    role = await session.get(Role, user.role_id)

    return DashboardSummaryResponse(
        role_name=role.name if role is not None else "",
        # Spec §5.5: taslaklar aktif proje sayacına GİRMEZ — status active AND NOT is_draft.
        active_project_count=sum(
            1 for p in projects if p.status is ProjectStatus.active and not p.is_draft
        ),
        projects=[DashboardProjectCard.model_validate(p) for p in projects],
        portfolio=MetricPlaceholder(pending_module=_PORTFOLIO_MODULE),
        receivables=MetricPlaceholder(pending_module=_RECEIVABLES_MODULE),
        average_margin=MetricPlaceholder(pending_module=_MARGIN_MODULE),
        pending_approvals=PendingApprovalsPlaceholder(pending_module=_APPROVALS_MODULE),
        risks=ListPlaceholder(pending_module=_RISKS_MODULE),
    )
