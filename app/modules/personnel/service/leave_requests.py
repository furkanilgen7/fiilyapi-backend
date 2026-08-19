"""IK-2 T2 — izin talebi CRUD (spec §3, §5 K2/K3)."""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import AccessLevel, satisfies
from app.core.errors import (
    ConflictError,
    DeleteNotAllowedError,
    NotFoundError,
    PersonnelValidationError,
)
from app.modules.audit import messages
from app.modules.personnel import guards, leave, repository
from app.modules.personnel.models import (
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Personnel,
)
from app.modules.personnel.schemas import (
    LeaveRequestCreate,
    LeaveRequestResponse,
    LeaveRequestUpdate,
)
from app.modules.personnel.service.core import PERMISSION_MODULE, get_personnel
from app.modules.personnel.service.documents import _assert_document_visible
from app.modules.roles.repository import get_permission
from app.modules.users.models import User


def _leave_response(
    request: LeaveRequest, personnel: Personnel, leave_type: LeaveType
) -> LeaveRequestResponse:
    """ORM kaydı + personel/tip künyesi → İZ tablosu satırı (tek yer, tek biçim)."""
    return LeaveRequestResponse(
        id=request.id,
        personnel_id=request.personnel_id,
        personnel_name=personnel.full_name,
        personnel_trade=personnel.trade,
        leave_type_id=request.leave_type_id,
        leave_type_name=leave_type.name,
        leave_type_color=leave_type.color,
        deducts_from_annual=leave_type.deducts_from_annual,
        start_date=request.start_date,
        end_date=request.end_date,
        days=request.days,
        note=request.note,
        document_id=request.document_id,
        status=request.status,
        decided_by=request.decided_by,
        decided_at=request.decided_at,
        reject_reason=request.reject_reason,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


async def _resolve_leave_type(session: AsyncSession, type_id: uuid.UUID) -> LeaveType:
    """Yazma yolu: tip GERÇEKTEN var mı (404) + AKTİF mi (422)?

    `_resolve_document_type` ile bire bir aynı ayrım — yeni talep pasif bir tiple
    açılamaz ama pasif tip taşıyan ESKİ kayıt okuma yolunda künyesiyle görünür
    (liste JOIN'i aktiflik aramaz).
    """
    leave_type = await repository.get_leave_type(session, type_id)
    if leave_type is None:
        raise NotFoundError(guards.LEAVE_TYPE_MISSING)
    if not leave_type.is_active:
        raise PersonnelValidationError(guards.LEAVE_TYPE_INACTIVE)
    return leave_type


def _assert_date_order(start_date: date, end_date: date) -> None:
    """Tarih sırası BİRLEŞİK değerler üzerinde (P6 `_merged` deseni): PATCH tek uç
    gönderebilir, kural ancak DB'deki kayıtla birleştirilince anlamlıdır."""
    if end_date < start_date:
        raise PersonnelValidationError(guards.LEAVE_DATE_ORDER)


def _assert_pending(request: LeaveRequest) -> None:
    """Karara bağlanmış talep DÜZENLENEMEZ/SİLİNEMEZ (spec §3) → 409.

    Onaylı izin bakiyeyi ETKİLEMİŞTİR (kullanılan gün toplamı `approved` üzerinden
    türer, spec §2); geriye dönük tarih düzeltmesi bakiyeyi sessizce kaydırırdı.
    Reddedilen talep de tarihsel kayıttır — düzeltme yeni talep açmaktır.
    """
    if request.status is not LeaveStatus.pending:
        raise ConflictError(guards.LEAVE_NOT_PENDING)


async def find_overlapping_approved_leave(
    session: AsyncSession,
    personnel_id: uuid.UUID,
    start_date: date,
    end_date: date,
    exclude_id: uuid.UUID | None = None,
) -> LeaveRequest | None:
    """Çakışan ONAYLI izin (spec §5 K3) — T3'ün `approve` 409'unun tek kaynağı.

    T2'de BİLİNÇLİ olarak hiçbir uçtan çağrılmaz: kural `approve`ta işler (spec
    §3). POST/PATCH'te 409'a çevrilseydi, İK bir talebi kaydedemez ve çakışmayı
    ancak onay anında değerlendirme imkânını kaybederdi. Yardımcı burada durur ki
    T3 kuralı yeniden yazmasın; davranışı `test_ik2_leave_service.py`de kanıtlanır.
    """
    return await repository.find_overlapping_approved_leave(
        session, personnel_id, start_date, end_date, exclude_id=exclude_id
    )


async def list_leave_types(session: AsyncSession) -> list[LeaveType]:
    """Talep formunun tip listesi — YALNIZ AKTİF. Katalog CRUD'u AÇILMAZ (spec §1)."""
    return await repository.list_leave_types(session)


async def list_leave_requests(
    session: AsyncSession,
    status: LeaveStatus | None,
    personnel_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[LeaveRequestResponse], int]:
    rows = await repository.list_leave_requests(
        session,
        status=status,
        personnel_id=personnel_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    total = await repository.count_leave_requests(
        session, status=status, personnel_id=personnel_id, project_id=project_id
    )
    return [_leave_response(r, p, t) for r, p, t in rows], total


async def get_leave_request_row(
    session: AsyncSession, request_id: uuid.UUID
) -> tuple[LeaveRequest, Personnel, LeaveType]:
    """Talep + künyesi ya da 404 (görünmeyen kayıt var olmayandan AYIRT EDİLEMEZ)."""
    row = await repository.get_leave_request(session, request_id)
    if row is None:
        raise NotFoundError(guards.LEAVE_REQUEST_MISSING)
    return row[0], row[1], row[2]


async def get_leave_request(session: AsyncSession, request_id: uuid.UUID) -> LeaveRequestResponse:
    request, personnel, leave_type = await get_leave_request_row(session, request_id)
    return _leave_response(request, personnel, leave_type)


async def create_leave_request(
    session: AsyncSession, actor: User, data: LeaveRequestCreate
) -> tuple[LeaveRequestResponse, str]:
    """Yeni talep + denetim metni. Sıra: personel (404) → tip (404/422) → tarih
    (422) → BC görünürlük (404) — `create_personnel_document` ile aynı kapı sırası.

    `days` SUNUCU hesabıdır (spec §5 K2) ve `status` HER ZAMAN `pending` başlar;
    ikisi de gövdeden ALINMAZ (şema `extra="forbid"` ile açıkça reddeder).
    Çakışma (K3) BURADA DENETLENMEZ — `approve` kapısıdır (T3).
    """
    personnel = await get_personnel(session, data.personnel_id)
    leave_type = await _resolve_leave_type(session, data.leave_type_id)
    _assert_date_order(data.start_date, data.end_date)
    await _assert_document_visible(session, actor, data.document_id)

    request = LeaveRequest(
        personnel_id=personnel.id,
        leave_type_id=leave_type.id,
        start_date=data.start_date,
        end_date=data.end_date,
        days=leave.calculate_leave_days(data.start_date, data.end_date),
        note=data.note,
        document_id=data.document_id,
        status=LeaveStatus.pending,
    )
    await repository.add_leave_request(session, request)
    detail = messages.leave_request_created(
        personnel.full_name, leave_type.name, request.start_date, request.end_date
    )
    return _leave_response(request, personnel, leave_type), detail


async def update_leave_request(
    session: AsyncSession, actor: User, request_id: uuid.UUID, data: LeaveRequestUpdate
) -> tuple[LeaveRequestResponse, str]:
    """Kısmi güncelleme — YALNIZ `pending` (409). Tarih değişirse `days` YENİDEN
    sunucu hesabıdır; `days`i istemci PATCH'te de gönderemez (şema reddeder).

    Kural sırası create ile aynıdır: durum (409) → tip (404/422) → tarih (422) →
    BC görünürlük (404). Doğrulamaların HEPSİ yazmadan ÖNCE koşar — yarım
    güncellenmiş satır bırakılmaz.
    """
    request, personnel, leave_type = await get_leave_request_row(session, request_id)
    _assert_pending(request)

    updates = data.model_dump(exclude_unset=True)
    if "leave_type_id" in updates and updates["leave_type_id"] is not None:
        leave_type = await _resolve_leave_type(session, updates["leave_type_id"])

    efektif_baslangic = updates.get("start_date") or request.start_date
    efektif_bitis = updates.get("end_date") or request.end_date
    _assert_date_order(efektif_baslangic, efektif_bitis)

    if updates.get("document_id") is not None:
        await _assert_document_visible(session, actor, updates["document_id"])

    for field, value in updates.items():
        setattr(request, field, value)
    # Tarih kolonlarına dokunulmasa bile TEK KAYNAKTAN yeniden hesaplanır: iki
    # yol (POST/PATCH) aynı formülü çağırsın, kopya kural doğmasın.
    request.days = leave.calculate_leave_days(request.start_date, request.end_date)
    await session.flush()
    await session.refresh(request)

    detail = messages.leave_request_updated(
        personnel.full_name, leave_type.name, request.start_date, request.end_date
    )
    return _leave_response(request, personnel, leave_type), detail


async def delete_leave_request(session: AsyncSession, actor: User, request_id: uuid.UUID) -> str:
    """Talebi siler — YALNIZ `pending` (409) ve YALNIZ `admin` YA DA SAHİBİ (403).

    Spec §3 "pending, sahibi ya da admin": `full` TEK BAŞINA yetmez
    (`app/core/access.py`: full silmeyi KAPSAMAZ — İK-1 belge silme emsali), ama
    kişinin KENDİ bekleyen talebini geri çekmesi meşrudur. Sahiplik personelin
    `user_id` köprüsünden okunur (işçilerin çoğunun login'i yoktur; o hâlde tek
    kapı `admin`dir).

    Sıra: kayıt (404) → durum (409) → yetki (403). Var olmayan kayıt için önce
    404 dönmek kimlik sızdırmaz — talep kimliği zaten tahmin edilemez UUID'dir ve
    yetkiyi önce denetlemek `view` sahibine "bu kayıt VAR" bilgisini verirdi.

    Denetim metni `session.delete`ten ÖNCE kurulur (`site_deleted` dersi).
    """
    request, personnel, leave_type = await get_leave_request_row(session, request_id)
    _assert_pending(request)
    if not await _can_delete_leave_request(session, actor, personnel):
        raise DeleteNotAllowedError(guards.LEAVE_DELETE_NOT_ALLOWED)

    detail = messages.leave_request_deleted(
        personnel.full_name, leave_type.name, request.start_date, request.end_date
    )
    await session.delete(request)
    await session.flush()
    return detail


async def _can_delete_leave_request(
    session: AsyncSession, actor: User, personnel: Personnel
) -> bool:
    """`admin` seviyesi YA DA talebin sahibi (personelin bağlı kullanıcısı).

    Seviye router kapısında DEĞİL burada okunur: router kapısı tek bir asgari
    seviye zorlar, oysa buradaki kural İKİ ayrı yoldan açılır (seviye VEYA
    sahiplik) — kapıyı `admin`e çekmek sahibi dışarıda bırakır, `view`de bırakmak
    yabancıya silme verirdi.
    """
    permission = await get_permission(session, actor.role_id, PERMISSION_MODULE)
    if permission is not None and satisfies(permission.access_level, AccessLevel.admin):
        return True
    return personnel.user_id is not None and personnel.user_id == actor.id
