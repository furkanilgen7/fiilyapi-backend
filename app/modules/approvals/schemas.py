"""Onay motorunun okuma/yazma semalari (sozlesme Y5, Y7)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.approvals.models import ApprovalDocumentType, ApprovalRole
from app.modules.approvals.service import PendingChainView

__all__ = [
    "ApprovalInboxItem",
    "ApprovalInboxResponse",
    "ApprovalRoleAssignmentListResponse",
    "ApprovalRoleAssignmentRead",
    "ApprovalRoleAssignmentUpdate",
    "ApprovalSettingsRead",
    "ApprovalSettingsUpdate",
    "ApprovalStepRead",
]


class ApprovalSettingsRead(BaseModel):
    approval_threshold_try: Decimal


class ApprovalSettingsUpdate(BaseModel):
    """Esik ayari. Kolonun kendisi `Numeric(18, 2)`dir; sema onunla BIREBIR.

    🔴 Bu alan `CompanyUpdate`e EKLENMEZ (R7): `PUT /company` "Sirket Bilgileri"
    formudur ve `settings: full` seviyesine acikken esik `approvals: admin`
    ister. Tek govdede birlesselerdi dusuk kapidan gecen istek yuksek kapinin
    ardindaki degeri yazardi.
    """

    model_config = ConfigDict(extra="forbid")

    approval_threshold_try: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class ApprovalRoleAssignmentRead(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    approval_roles: list[ApprovalRole]


class ApprovalRoleAssignmentUpdate(BaseModel):
    """TAM KUME yazar: gonderilmeyen rol KALKAR (kismi ekleme ucu YOKTUR)."""

    model_config = ConfigDict(extra="forbid")

    approval_roles: list[ApprovalRole]


class ApprovalRoleAssignmentListResponse(BaseModel):
    items: list[ApprovalRoleAssignmentRead]
    total: int
    limit: int
    offset: int


class ApprovalStepRead(BaseModel):
    """Adim SERIDI (mockup `Onay Kutusu.dc.html:129-135`).

    🔴 "bekliyor / onaylandi" bir DURUM ALANI olarak DONMEZ: `decided_at`
    NULL'sa adim beklemededir ve bunu ekran soyler (KANON E).
    """

    step_no: int
    approval_role: ApprovalRole
    decided_at: datetime | None
    decided_by_name: str | None


class ApprovalInboxItem(BaseModel):
    """Onay kutusu satiri — MOTORUN bildigi olgular.

    ⚠️ T4 EKLER: `title` / `subtitle` ve `gross_amount` / `net_amount`. Bunlar
    evrak ailelerinden okunur ve evraklar zincire T3'te baglanir; bugun
    uretilseydi UYDURULMUS olurlardi.
    """

    chain_id: uuid.UUID
    document_type: ApprovalDocumentType
    document_id: uuid.UUID
    created_by_name: str | None
    created_at: datetime
    threshold_snapshot: Decimal
    amount_snapshot: Decimal | None
    current_step_no: int
    steps: list[ApprovalStepRead]

    @classmethod
    def from_view(cls, view: PendingChainView) -> "ApprovalInboxItem":
        return cls(
            chain_id=view.chain_id,
            document_type=view.document_type,
            document_id=view.document_id,
            created_by_name=view.created_by_name,
            created_at=view.created_at,
            threshold_snapshot=view.threshold_snapshot,
            amount_snapshot=view.amount_snapshot,
            current_step_no=view.current_step_no,
            steps=[
                ApprovalStepRead(
                    step_no=adim.step_no,
                    approval_role=adim.approval_role,
                    decided_at=adim.decided_at,
                    decided_by_name=adim.decided_by_name,
                )
                for adim in view.steps
            ],
        )


class ApprovalInboxResponse(BaseModel):
    """🔴 KANON E: `can_approve` gibi bir KARAR ALANI YOKTUR.

    `my_approval_roles` OLGUSU doner; "bu satiri onaylayabilir miyim" kararini
    ekran, adim rolu ile bu kume uzerinden TEK yardimcida birlestirir.
    🔴 ACILIYET/RENK de SUNUCUDA URETILMEZ (K10 kanonu).
    """

    items: list[ApprovalInboxItem]
    total: int
    limit: int
    offset: int
    my_approval_roles: list[ApprovalRole]
