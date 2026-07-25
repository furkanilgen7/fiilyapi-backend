import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.projects.models import ProjectStatus


class MetricPlaceholder(BaseModel):
    """Tek degerli KPI karti. v1'de veri kaynagi olmayan kartlar icin.

    available alani bilincli olarak vardir: frontend sabite degil veriye dallanir,
    ilgili alt-proje geldiginde backend true dondurmeye baslar (spec §2.3).
    """

    available: bool = False
    value: Decimal | None = None
    pending_module: str


class ListPlaceholder(BaseModel):
    """Liste tipli kart (risk uyarilari)."""

    available: bool = False
    items: list[str] = Field(default_factory=list)
    pending_module: str


class PendingApprovalsPlaceholder(ListPlaceholder):
    """Onay bekleyenler karti — rozet sayaci tasir."""

    count: int = 0


class DashboardProjectCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    budget: Decimal
    progress_pct: Decimal


class DashboardSummaryResponse(BaseModel):
    role_name: str
    active_project_count: int
    projects: list[DashboardProjectCard]
    portfolio: MetricPlaceholder
    receivables: MetricPlaceholder
    average_margin: MetricPlaceholder
    pending_approvals: PendingApprovalsPlaceholder
    risks: ListPlaceholder
