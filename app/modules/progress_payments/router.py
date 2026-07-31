"""İşveren hakedişi (P7) uçları — task H4 yalnız CRUD: liste/detay/oluştur/düzenle.

`contracts/router.py` deseninin aynısı: kapı sabitleri modül düzeyinde tanımlanır,
sonraki task'lar (H5-H9) `_VIEW`/`_DRAFT`/`_APPROVE`/`_ADMIN`'i buradan import eder.
Denetim günlüğü (`record_audit`) BİLİNÇLİ OLARAK YOK — mesaj aileleri H10'da
`app/modules/audit/messages.py`de merkezileşir (plan Task H10).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.openapi import COMMON_ERROR_RESPONSES
from app.core.permissions import require_permission
from app.modules.progress_payments import service, transitions
from app.modules.progress_payments.models import ProgressPaymentStatus
from app.modules.progress_payments.schemas import (
    ProgressPaymentCreate,
    ProgressPaymentDetail,
    ProgressPaymentLinesSave,
    ProgressPaymentListResponse,
    ProgressPaymentUpdate,
    RefreshPricesResponse,
    RejectBody,
)
from app.modules.users.models import User

router = APIRouter(tags=["progress-payments"], responses=COMMON_ERROR_RESPONSES)

_VIEW = require_permission("progress_payments", AccessLevel.view)
_DRAFT = require_permission("progress_payments", AccessLevel.draft)
_APPROVE = require_permission("progress_payments", AccessLevel.approve)
_ADMIN = require_permission("progress_payments", AccessLevel.admin)


@router.get(
    "/progress-payments",
    response_model=ProgressPaymentListResponse,
    dependencies=[_VIEW],
)
async def list_progress_payments_endpoint(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status_filter: Annotated[ProgressPaymentStatus | None, Query(alias="status")] = None,
) -> ProgressPaymentListResponse:
    return await service.list_payments(
        session, user, project_id=project_id, site_id=site_id, status_filter=status_filter
    )


@router.get(
    "/progress-payments/{payment_id}",
    response_model=ProgressPaymentDetail,
    dependencies=[_VIEW],
)
async def get_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    return await service.get_detail(session, user, payment_id)


@router.post(
    "/projects/{project_id}/progress-payments",
    response_model=ProgressPaymentDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_DRAFT],
)
async def create_progress_payment_endpoint(
    project_id: uuid.UUID,
    data: ProgressPaymentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """D8/K9: sözleşmede açık hakediş varsa 409; sözleşme yoksa 422 (spec §9.2).

    Yanıt hesap türevleri (`calculation`/`progress`/`groups`) taşıdığı için
    `create` sonrası `get_detail` ÜZERİNDEN yeniden okunur — tek bir detay
    inşa yolu olur (`contracts/router.py.to_item_response_single` deseninin
    aynısı), iki kopya hesap mantığı riski taşınmaz.
    """
    payment, _ = await service.create(session, user, project_id, data)
    return await service.get_detail(session, user, payment.id)


@router.patch(
    "/progress-payments/{payment_id}",
    response_model=ProgressPaymentDetail,
    dependencies=[_DRAFT],
)
async def update_progress_payment_endpoint(
    payment_id: uuid.UUID,
    data: ProgressPaymentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """Yalnız `status=draft` (spec §7); aksi 409 `INVALID_STATUS_TRANSITION`."""
    payment, _ = await service.update(session, user, payment_id, data)
    return await service.get_detail(session, user, payment.id)


@router.put(
    "/progress-payments/{payment_id}/lines",
    response_model=ProgressPaymentDetail,
    dependencies=[_DRAFT],
)
async def save_progress_payment_lines_endpoint(
    payment_id: uuid.UUID,
    data: ProgressPaymentLinesSave,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """OLU formunun tek "Taslak Kaydet" gövdesi — **DEĞİŞTİRME** semantiği.

    ⚠️ Gövdede geçmeyen satır SİLİNİR. P5'in `PUT …/contract/distribution`
    **BİRLEŞTİRME** ucunun TERSİDİR (orada gövdede geçmeyen hücre KORUNUR) —
    frontend'de ikisi yan yana kullanılacağı için karıştırılmamalıdır (spec §10/2).

    Yalnız `status=draft` (409 `INVALID_STATUS_TRANSITION`); §6.5 korkulukları
    (dağıtım ön şartı, kota tavanı, sahiplik, FF kilidi) her yazımda koşar.

    Kalemi silinmiş satırlar gövdeden adreslenemediği için düşer; sayıları
    yanıtın `dropped_orphan_count` alanında BİLDİRİLİR (spec §10/7, sessiz
    atlama yok). `get_detail` bu bilgiyi bilemez — `model_copy` ile üzerine
    yazılır (mutasyon yok, yeni nesne).
    """
    payment, dropped_orphan_count = await service.save_lines(session, user, payment_id, data)
    detail = await service.get_detail(session, user, payment.id)
    return detail.model_copy(update={"dropped_orphan_count": dropped_orphan_count})


@router.post(
    "/progress-payments/{payment_id}/refresh-prices",
    response_model=RefreshPricesResponse,
    dependencies=[_DRAFT],
)
async def refresh_progress_payment_prices_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RefreshPricesResponse:
    """§5.1/§9.3: yalnız `draft`'ta bağı kopmamış satırların snapshot beşlisini
    + hakedişin yüzde üçlüsünü kalemden/sözleşmeden bilinçli tazeler.

    Yanıt YALNIZ `{refreshed_count}`'tur (plan Adım 1'in test şeması) — güncel
    ekran ayrı bir `GET /progress-payments/{id}` ile okunur; `PUT …/lines`'ın
    aksine burada tek gövdede iki bilgi (sayaç + tam detay) BİRLEŞTİRİLMEZ,
    çünkü tazeleme sonrası frontend zaten ekranı yeniden çizmek için detayı
    ayrıca çeker (spec §9.3, `RefreshPricesResponse`)."""
    _, refreshed_count = await service.refresh_prices(session, user, payment_id)
    return RefreshPricesResponse(refreshed_count=refreshed_count)


# --- Durum geçişleri (spec §7, §9.4) ---
#
# Beş uç da TEK yoldan (`transitions.perform`) geçer; geçiş tablosu ve kilit
# orada TEK kopyadır. Router'ın tek işi KAPIYI seçmektir (§7 tablosunun "asgari
# seviye" kolonu) — durum kontrolü BURADA TEKRARLANMAZ.


@router.post(
    "/progress-payments/{payment_id}/submit",
    response_model=ProgressPaymentDetail,
    dependencies=[_DRAFT],
)
async def submit_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """E15 71 / OLU 25 "Onaya Gönder" — `draft → pending_approval`.

    Zorunluluk kuralları (dönem, satır/Σ>0, sözleşme bedeli) YALNIZ burada koşar
    (§7): taslak eksik veriyle serbestçe saklanır (kalıcı karar 4).
    """
    payment = await transitions.perform(session, user, payment_id, transitions.PaymentAction.submit)
    return await service.get_detail(session, user, payment.id)


@router.post(
    "/progress-payments/{payment_id}/approve",
    response_model=ProgressPaymentDetail,
    dependencies=[_APPROVE],
)
async def approve_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """`pending_approval → approved`; kota kilit altında YENİDEN doğrulanır."""
    payment = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.approve
    )
    return await service.get_detail(session, user, payment.id)


@router.post(
    "/progress-payments/{payment_id}/reject",
    response_model=ProgressPaymentDetail,
    dependencies=[_APPROVE],
)
async def reject_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    data: RejectBody | None = None,
) -> ProgressPaymentDetail:
    """`pending_approval → draft` — ret sonrası taslak yeniden düzenlenebilir.

    Gövde İSTEĞE BAĞLIDIR (K12: mockup'ta ret formu yok). `reason` bugün hiçbir
    kolona yazılmaz; denetim günlüğüne H10'da taşınacaktır — o güne kadar
    kabul edilip yok sayılması bilinçlidir (frontend kontratı §10 ile sabit).
    """
    payment = await transitions.perform(session, user, payment_id, transitions.PaymentAction.reject)
    return await service.get_detail(session, user, payment.id)


@router.post(
    "/progress-payments/{payment_id}/mark-paid",
    response_model=ProgressPaymentDetail,
    dependencies=[_APPROVE],
)
async def mark_paid_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """`approved → paid` (K11: onay seviyesi). Ödeme detayı formu mockup'ta YOK
    → tek tıkla işaretleme, yalnız `paid_at` damgalanır."""
    payment = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.mark_paid
    )
    return await service.get_detail(session, user, payment.id)


@router.post(
    "/progress-payments/{payment_id}/unapprove",
    response_model=ProgressPaymentDetail,
    dependencies=[_ADMIN],
)
async def unapprove_progress_payment_endpoint(
    payment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressPaymentDetail:
    """`approved → pending_approval` (geri çek) — YALNIZ `admin` (§7 tablosu).

    `paid` kaynak DEĞİLDİR (K7): ödenmiş hakedişin geri dönüşü yoktur, denemesi
    409'dur.
    """
    payment = await transitions.perform(
        session, user, payment_id, transitions.PaymentAction.unapprove
    )
    return await service.get_detail(session, user, payment.id)
