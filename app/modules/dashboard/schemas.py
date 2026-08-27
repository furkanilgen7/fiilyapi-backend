import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.projects.models import ProjectStatus

# Yer tutucu sozlesmesi TEK yerde tanimlidir (B6/P1, spec §2.3): kopyalanmaz,
# projects modulunden import edilir (`boq/schemas.py:11` emsali).
#
# 🔴 NICIN BIRLESTIRILDI (DASH-1): panelin KENDI kopyasi `pending_module`u
# ZORUNLU tutuyordu ve dogrulayicisi YOKTU — yani zarf UC hâlden yalnizca
# IKISINI ifade edebiliyordu. `portfolio` baglandiginda ucuncu hâl gerekti:
#   * `available=True`  + `pending_module is None`  -> DOLU
#   * `available=False` + `pending_module` dolu     -> soru hic sorulmadi
#   * `available=False` + `pending_module is None`  -> ROLUN IZNI YOK (ILR-1/2,
#     kullanici karari 2026-08-27; yalnizca `restricted()` fabrikasindan kurulur)
# Kopya zarf ucuncu hâli KURAMAZDI (`pending_module` zorunlu) ve ilkini de
# DOGRULAYAMAZDI. Iki tanim yerine tek tanim: kural bir kez yazilir.
#
# 🔴 `ListPlaceholder` / `PendingApprovalsPlaceholder` BILINCLI olarak DISARIDA:
# orada dolu zarfin `pending_module` tasimasi emsaldir (`CountPlaceholder`
# notu) — "dolu ⇒ modul yok" kurali YALNIZ `MetricPlaceholder`indir.
from app.modules.projects.schemas import MetricPlaceholder

__all__ = [
    "MetricPlaceholder",
    "ListPlaceholder",
    "PendingApprovalsPlaceholder",
    "DashboardProjectCard",
    "DashboardSummaryResponse",
]


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
