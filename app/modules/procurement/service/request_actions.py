"""T3 onay akisi — submit / approve / reject icin TEK yol.

Gecis matrisi `transitions.py`dedir; burada `if status` YOKTUR. Denetim metni
gecisten SONRA kurulur cunku metin YENI durumu adlandirir.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals import service as approvals_service
from app.modules.audit import messages
from app.modules.procurement import transitions
from app.modules.procurement.models import PurchaseRequest
from app.modules.users.models import User


async def perform_request_action(
    session: AsyncSession,
    actor: User,
    request: PurchaseRequest,
    action: transitions.RequestAction,
    *,
    reason: str | None = None,
) -> tuple[PurchaseRequest, str]:
    """Uc gecisin TEK yolu — matris `transitions.py`dedir, burada `if status` YOK.

    Denetim metni gecisten SONRA kurulur cunku metin YENI durumu adlandirir;
    kayit yok olmadigi icin `purchase_request_deleted` dersi (once kur) burada
    GECERLI DEGILDIR.

    🔴 OK-1A T3: metin zincirin kararyla BIRLESTIRILIR ve birlestirme kurali
    `approvals.service`te TEK kopyadir (uc evrak ailesi ayni sozlukten okur):
    ARA adimda YALNIZ adim metni yazilir (talebin durumu DEGISMEDI, "onaylandi"
    demek gunluge OLMAMIS bir olguyu yazmak olurdu), SON adimda ve rette IKISI
    DE yazilir.
    """
    decision = await transitions.apply_request_transition(
        session, actor, request, action, reason=reason
    )
    detail = _TRANSITION_MESSAGES[action](request.request_no)
    if action is transitions.RequestAction.reject:
        return request, approvals_service.rejection_audit_detail(detail, decision)
    # Talebin KIMLIGI zaten numarasidir; ara adim metni onu ayrica tasir.
    return request, approvals_service.audit_detail(
        detail, decision, document_label=request.request_no
    )


_TRANSITION_MESSAGES = {
    transitions.RequestAction.submit: messages.purchase_request_submitted,
    transitions.RequestAction.approve: messages.purchase_request_approved,
    transitions.RequestAction.reject: messages.purchase_request_rejected,
}
