"""IK-1 T3 — personel BELGE alt-kaynagi (spec §2, §3, §5 K5)."""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.core.errors import (
    NotFoundError,
    PersonnelValidationError,
)
from app.modules.audit import messages
from app.modules.documents import service as documents_service
from app.modules.personnel import guards, repository, status
from app.modules.personnel.models import (
    PersonnelDocument,
    PersonnelDocumentType,
)
from app.modules.personnel.schemas import (
    PersonnelDocumentCreate,
    PersonnelDocumentResponse,
    PersonnelDocumentUpdate,
)
from app.modules.personnel.service.core import get_personnel
from app.modules.users.models import User


def _document_response(
    document: PersonnelDocument,
    type_obj: PersonnelDocumentType | None,
    today: date,
) -> PersonnelDocumentResponse:
    """ORM kaydı + tip künyesi → response; durum TEK KAYNAKTAN (`status.py`)."""
    return PersonnelDocumentResponse(
        id=document.id,
        personnel_id=document.personnel_id,
        type_id=document.type_id,
        type_name=None if type_obj is None else type_obj.name,
        is_mandatory=None if type_obj is None else type_obj.is_mandatory,
        validity_months=None if type_obj is None else type_obj.validity_months,
        free_label=document.free_label,
        document_id=document.document_id,
        issued_at=document.issued_at,
        valid_until=document.valid_until,
        note=document.note,
        status=status.derive_document_status(
            document.valid_until,
            None if type_obj is None else type_obj.validity_months,
            today=today,
        ),
        days_left=status.days_until(document.valid_until, today=today),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _document_label(document: PersonnelDocument, type_obj: PersonnelDocumentType | None) -> str:
    """Denetim metni için insan-okur ad — tip adı YA DA serbest etiket (XOR gereği
    tam biri doludur)."""
    return type_obj.name if type_obj is not None else (document.free_label or "belge")


def _assert_type_xor_label(type_id: uuid.UUID | None, free_label: str | None) -> None:
    """XOR korkuluğu SERVİSTE (pydantic + DB CHECK arasında üçüncü kat, spec §2).

    Boş/boşluklu `free_label` "yok" sayılır — çıplak CHECK bunu tutamazdı (DB'de
    boş string NULL değildir), bu yüzden kontrol burada da yapılır.
    """
    has_type = type_id is not None
    has_label = bool(free_label and free_label.strip())
    if has_type == has_label:
        raise PersonnelValidationError(guards.TYPE_XOR_LABEL)


async def _resolve_document_type(
    session: AsyncSession, type_id: uuid.UUID | None
) -> PersonnelDocumentType | None:
    """`type_id` verilmişse katalogda GERÇEKTEN var + AKTİF mi?

    * yok → 404 (gövde içi varlık ref, spec §4b);
    * pasif → 422 (kayıt var, durumu düzeltilebilir).
    """
    if type_id is None:
        return None
    type_obj = await repository.get_document_type(session, type_id)
    if type_obj is None:
        raise NotFoundError(guards.DOCUMENT_TYPE_MISSING)
    if not type_obj.is_active:
        raise PersonnelValidationError(guards.DOCUMENT_TYPE_INACTIVE)
    return type_obj


async def _assert_document_visible(
    session: AsyncSession, actor: User, document_id: uuid.UUID | None
) -> None:
    """BC bağı IDOR korkuluğu (spec §4b kanonu): kullanıcının GÖREMEYECEĞİ bir arşiv

    belgesine bağ kurdurulmaz. `documents.visible_document` görünmez/var olmayan
    belge için AYNI 404'ü (`documents.guards.DOCUMENT_MISSING`) fırlatır — metin
    oradan gelir, İK modülü kendi cümlesini üretmez (kimlik sızıntısı önlemi).
    """
    if document_id is None:
        return
    await documents_service.visible_document(session, actor, document_id)


async def list_personnel_documents(
    session: AsyncSession, personnel_id: uuid.UUID
) -> list[PersonnelDocumentResponse]:
    """O personelin belgeleri (tip künyeli, N+1 yok). Personel yok → 404."""
    await get_personnel(session, personnel_id)
    today = timezone.today()
    rows = await repository.list_personnel_documents(session, personnel_id)
    return [_document_response(document, type_obj, today) for document, type_obj in rows]


async def create_personnel_document(
    session: AsyncSession,
    actor: User,
    personnel_id: uuid.UUID,
    data: PersonnelDocumentCreate,
) -> tuple[PersonnelDocumentResponse, str]:
    """Belge kaydı ekler + denetim metni. Sıra: personel (404) → tip (404/422) →

    XOR (422) → BC görünürlük (404). Personel görünmez/yok İSE tip/BC hiç
    yoklanmaz — kaydın hangi personele ait olduğu ilk kapıdır.
    """
    personnel = await get_personnel(session, personnel_id)
    type_obj = await _resolve_document_type(session, data.type_id)
    _assert_type_xor_label(data.type_id, data.free_label)
    await _assert_document_visible(session, actor, data.document_id)

    document = PersonnelDocument(
        personnel_id=personnel.id,
        type_id=data.type_id,
        free_label=data.free_label.strip() if data.free_label else None,
        document_id=data.document_id,
        issued_at=data.issued_at,
        valid_until=data.valid_until,
        note=data.note,
    )
    await repository.add_personnel_document(session, document)
    detail = messages.personnel_document_added(
        personnel.full_name, _document_label(document, type_obj)
    )
    return _document_response(document, type_obj, timezone.today()), detail


async def update_personnel_document(
    session: AsyncSession,
    actor: User,
    document_id: uuid.UUID,
    data: PersonnelDocumentUpdate,
) -> tuple[PersonnelDocumentResponse, str]:
    """Kısmi güncelleme. Belge görünmez/yok → 404; `document_id` değişiyorsa (null

    dışında) BC görünürlük denetimi create ile AYNI korkuluktan geçer.
    """
    document = await repository.get_personnel_document(session, document_id)
    if document is None:
        raise NotFoundError(guards.PERSONNEL_DOCUMENT_MISSING)

    updates = data.model_dump(exclude_unset=True)
    if updates.get("document_id") is not None:
        await _assert_document_visible(session, actor, updates["document_id"])

    for field, value in updates.items():
        setattr(document, field, value)
    await session.flush()
    await session.refresh(document)

    type_obj = await _resolve_type_for_read(session, document.type_id)
    personnel = await get_personnel(session, document.personnel_id)
    detail = messages.personnel_document_updated(
        personnel.full_name, _document_label(document, type_obj)
    )
    return _document_response(document, type_obj, timezone.today()), detail


async def delete_personnel_document(session: AsyncSession, document_id: uuid.UUID) -> str:
    """İK takip kaydını siler (`admin`). SET NULL: bağlı BC arşiv künyesine

    DOKUNULMAZ — dosya arşivde kalır (spec §2). Denetim metni `session.delete`ten
    ÖNCE kurulur (`site_deleted` dersi): sonra kurulsaydı ad/etiket okunamazdı.
    """
    document = await repository.get_personnel_document(session, document_id)
    if document is None:
        raise NotFoundError(guards.PERSONNEL_DOCUMENT_MISSING)
    type_obj = await _resolve_type_for_read(session, document.type_id)
    personnel = await get_personnel(session, document.personnel_id)
    detail = messages.personnel_document_deleted(
        personnel.full_name, _document_label(document, type_obj)
    )
    await session.delete(document)
    await session.flush()
    return detail


async def _resolve_type_for_read(
    session: AsyncSession, type_id: uuid.UUID | None
) -> PersonnelDocumentType | None:
    """Response/denetim için tip künyesi — AKTİFLİK aranmaz (okuma yolu; pasif tip

    taşıyan eski kayıt da doğru künyeyle görünmeli). Yazma yolu `_resolve_document_type`
    aktiflik zorlar; okuma yolu yalnız var olanı getirir."""
    if type_id is None:
        return None
    return await repository.get_document_type(session, type_id)
