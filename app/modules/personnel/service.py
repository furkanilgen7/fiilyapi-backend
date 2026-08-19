"""Personel servisi (puantaj spec §1, §2, §3, §5 + İK-1 spec §1, §5).

`customers/service.py`nin kardeşi: proje-bağımsız kartoteks, `NotFoundError` -> 404,
alanlar-arası kural servis korkuluğunda (`guards`) -> 422, benzersizlik -> 409.

**Silme ucu YOK** (spec §3): `timesheet_entries.personnel_id` FK'si RESTRICT'tir —
puantajı olan bir işçi silinemez. Kartoteksten çıkarma `is_active=false` PATCH'idir.

**İK-1 kart genişlemesi (spec §5):** yeni kart kolonları HEPSİ opsiyoneldir; taslak
(`is_draft=true`) gevşektir, yayın (`is_draft=false`) PE ✱ kümesini zorunlu kılar.
Zorunluluk BİRLEŞİK kayıt üzerinde koşar (P6 `_merged` deseni): PATCH kısmi gövde
gönderdiğinden yalnız gövdeye bakmak, yayın kaydını eksik alana düşürürdü. TCKN
checksum + UQ (`DuplicateError` -> 409) ve atama alanlarının (`assigned_project_id`/
`assigned_section_id`) varlık/kapsam doğrulaması da burada.
"""

import calendar
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone
from app.core.access import AccessLevel, satisfies
from app.core.errors import (
    ConflictError,
    DeleteNotAllowedError,
    DuplicateError,
    NotFoundError,
    PersonnelValidationError,
)
from app.modules.audit import messages
from app.modules.documents import service as documents_service
from app.modules.personnel import guards, leave, repository, status
from app.modules.personnel.models import (
    LeaveBalance,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Personnel,
    PersonnelDocument,
    PersonnelDocumentType,
)
from app.modules.personnel.schemas import (
    HrDocumentsSummaryResponse,
    HrDocumentTypeBreakdown,
    HrExpiredDocument,
    HrExpiringDocument,
    HrLeavesSummaryResponse,
    LeaveBalanceResponse,
    LeaveBalanceUpdate,
    LeaveRejectRequest,
    LeaveRequestCreate,
    LeaveRequestResponse,
    LeaveRequestUpdate,
    PersonnelCreate,
    PersonnelDocumentCreate,
    PersonnelDocumentResponse,
    PersonnelDocumentUpdate,
    PersonnelUpdate,
    SelfLeaveRequestCreate,
)
from app.modules.projects import repository as projects_repository
from app.modules.roles.repository import get_permission
from app.modules.sites import repository as sites_repository
from app.modules.users.models import User

PERMISSION_MODULE = "personnel"

# Yeni kart kolonları — tek yerde durur ki create/patch ORM ataması KOPYALANMASIN.
_CARD_FIELDS: tuple[str, ...] = (
    "tc_no",
    "birth_date",
    "gender",
    "marital_status",
    "phone",
    "email",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "hire_date",
    "wage_type",
    "wage_amount",
    "payment_method",
    "iban",
    "sgk_no",
    "assigned_project_id",
    "assigned_section_id",
)


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel:
    personnel = await repository.get_personnel(session, personnel_id)
    if personnel is None:
        raise NotFoundError(guards.PERSONNEL_MISSING)
    return personnel


async def _validate_tckn(
    session: AsyncSession, tc_no: str | None, exclude_id: uuid.UUID | None = None
) -> None:
    """DOLU TCKN: checksum (422) + benzersizlik (409). Boş/NULL → ATLANIR (taslak serbest)."""
    if not tc_no:
        return
    guards.validate_tckn(tc_no)
    if await repository.get_personnel_by_tc_no(session, tc_no, exclude_id):
        raise DuplicateError(guards.DUPLICATE_TCKN)


async def _validate_assignment_scope(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    section_id: uuid.UUID | None,
) -> None:
    """Atama alanları BİRLEŞİK değerler üzerinde doğrulanır (spec §5 K4).

    * proje verilmiş ve YOK → 404 (gövde içi varlık ref);
    * bölüm verilmiş ama proje yok → 422 (bölüm projesiz olamaz);
    * bölüm verilmiş ve YOK → 404;
    * bölüm o projeye ait DEĞİL → 422 (`documents.SITE_NOT_IN_PROJECT` deseni).
    """
    if project_id is not None:
        project = await projects_repository.get_project(session, project_id)
        if project is None:
            raise NotFoundError(guards.PROJECT_NOT_FOUND)
    if section_id is not None:
        if project_id is None:
            raise PersonnelValidationError(guards.SECTION_REQUIRES_PROJECT)
        section = await sites_repository.get_section(session, section_id)
        if section is None:
            raise NotFoundError(guards.SECTION_NOT_FOUND)
        site = await sites_repository.get_site(session, section.site_id)
        if site is None or site.project_id != project_id:
            raise PersonnelValidationError(guards.SECTION_NOT_IN_PROJECT)


def _assert_publish_ready(merged: object) -> None:
    """Yayın (`is_draft=false`) için PE ✱ kümesi TAM olmalı — eksikse 422."""
    eksik = guards.missing_publish_fields(merged)
    if eksik:
        raise PersonnelValidationError(guards.PUBLISH_MISSING.format(", ".join(eksik)))


async def create_personnel(session: AsyncSession, data: PersonnelCreate) -> Personnel:
    guards.validate_personnel_source(data.source, data.subcontractor_id)
    await _validate_tckn(session, data.tc_no)
    await _validate_assignment_scope(session, data.assigned_project_id, data.assigned_section_id)
    if not data.is_draft:
        _assert_publish_ready(data)

    personnel = Personnel(
        full_name=data.full_name,
        trade=data.trade,
        source=data.source,
        subcontractor_id=data.subcontractor_id,
        user_id=data.user_id,
        is_active=data.is_active,
        is_draft=data.is_draft,
        **{field: getattr(data, field) for field in _CARD_FIELDS},
    )
    return await repository.add_personnel(session, personnel)


async def update_personnel(
    session: AsyncSession, personnel_id: uuid.UUID, data: PersonnelUpdate
) -> Personnel:
    """Kısmi güncelleme (`model_dump(exclude_unset=True)`) — gönderilmeyen alan değişmez.

    Tüm kurallar BİRLEŞİK kayıt üzerinde koşar (`customers`/`sites` P6 deseni):
    gövdedeki değerler DB'dekilerin üstüne bindirilir, sonra doğrulanır. Yalnız
    gövdeye bakmak yayın kaydını eksik alana düşürür ya da `subcontractor -> company`
    geçişinde eski taşeron bağını kayıtta bırakırdı.
    """
    personnel = await get_personnel(session, personnel_id)
    updates = data.model_dump(exclude_unset=True)

    efektif_kaynak = updates.get("source", personnel.source)
    efektif_taseron = updates.get("subcontractor_id", personnel.subcontractor_id)
    guards.validate_personnel_source(efektif_kaynak, efektif_taseron)

    # TCKN yalnız GÖNDERİLDİĞİNDE doğrulanır; benzersizlikte kendini hariç tut.
    if "tc_no" in updates:
        await _validate_tckn(session, updates["tc_no"], exclude_id=personnel.id)

    # Atama alanları yalnız biri bile değiştiyse birleşik değerlerle doğrulanır.
    if "assigned_project_id" in updates or "assigned_section_id" in updates:
        efektif_proje = updates.get("assigned_project_id", personnel.assigned_project_id)
        efektif_bolum = updates.get("assigned_section_id", personnel.assigned_section_id)
        await _validate_assignment_scope(session, efektif_proje, efektif_bolum)

    # Yayın zorunluluğu: sonuçta yayın olacaksa (zaten yayın ya da bu PATCH yayına
    # çeviriyorsa) birleşik kayıt TAM olmalı — aksi hâlde 422 ve satır YAZILMAZ.
    efektif_taslak = updates.get("is_draft", personnel.is_draft)
    if not efektif_taslak:
        merged = SimpleNamespace(
            **{
                attr: updates.get(attr, getattr(personnel, attr))
                for attr, _ in guards.PUBLISH_REQUIRED_FIELDS
            }
        )
        _assert_publish_ready(merged)

    for field, value in updates.items():
        setattr(personnel, field, value)
    await session.flush()
    await session.refresh(personnel)
    return personnel


# --- İK-1 T3: belge alt-kaynağı (spec §2, §3, §5 K5) -----------------------


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


# --- İK-1 T4: belge takibi özeti (spec §2, §3 — BT mockup birebir) ----------

# İki liste tavanı (spec §3): en kritik 50 satır gösterilir, gerisi ekranı boğmaz.
SUMMARY_LIST_LIMIT = 50


async def build_hr_documents_summary(
    session: AsyncSession, *, today: date | None = None
) -> HrDocumentsSummaryResponse:
    """BT özeti: 5 KPI + tip dağılımı + iki liste — SABİT sorgu sayısı (N+1 yok).

    Üç AGGREGA sorgu (katalog tipleri · aktif+yayın personel sayısı · aktif+yayın
    personelin tüm belgeleri) çekilir; durum türevi, dağılım kırılımı, `missing`
    sayımı ve iki listenin sıralama+kırpması Python'da bu satırlar üzerinden
    yapılır. Sorgu sayısı VERİ BÜYÜKLÜĞÜNDEN BAĞIMSIZDIR (`test_n_plus_1_sabit_sorgu`).

    `today` ENJEKTE EDİLİR (servis sınırı `timezone.today()` verir, test sabit tarih):
    sınır günleri deterministik olsun. Durum `status.derive_document_status` TEK
    KAYNAĞINDAN gelir — eşik (30 gün) burada TEKRARLANMAZ.

    Kapsam: yalnız AKTİF (`is_active=true`) + YAYINDA (`is_draft=false`) personel.
    `missing` KPI toplamı YALNIZ zorunlu (`is_mandatory=true`) tipler üzerinden;
    opsiyonel tipler dağılımda gösterilir ama KPI'ya girmez.
    """
    today = today or timezone.today()

    types = await repository.list_document_types(session)
    active_published_count = await repository.count_active_published_personnel(session)
    rows = await repository.list_active_published_document_rows(session)

    total_documents = len(rows)
    valid = expiring = expired = 0
    # Tip başına belge durum sayaçları (kırılım) + o tipte kaydı olan personel kümesi.
    per_type_counts: dict[uuid.UUID, dict[str, int]] = {
        t.id: {"valid": 0, "expiring": 0, "expired": 0} for t in types
    }
    personnel_with_type: dict[uuid.UUID, set[uuid.UUID]] = {t.id: set() for t in types}
    expired_rows: list[HrExpiredDocument] = []
    expiring_rows: list[HrExpiringDocument] = []

    for row in rows:
        (
            doc_id,
            personnel_id,
            type_id,
            free_label,
            valid_until,
            full_name,
            type_name,
            _is_mandatory,
            validity_months,
            project_name,
        ) = row
        state = status.derive_document_status(valid_until, validity_months, today=today)
        if state == status.STATUS_VALID:
            valid += 1
        elif state == status.STATUS_EXPIRING:
            expiring += 1
        elif state == status.STATUS_EXPIRED:
            expired += 1

        if type_id is not None and type_id in per_type_counts:
            per_type_counts[type_id][state] += 1
            personnel_with_type[type_id].add(personnel_id)

        label = type_name if type_name is not None else (free_label or "belge")
        if state == status.STATUS_EXPIRED:
            expired_rows.append(
                HrExpiredDocument(
                    id=doc_id,
                    personnel_id=personnel_id,
                    personnel_name=full_name,
                    document_label=label,
                    project_name=project_name,
                    valid_until=valid_until,
                    days_overdue=(today - valid_until).days,
                )
            )
        elif state == status.STATUS_EXPIRING:
            expiring_rows.append(
                HrExpiringDocument(
                    id=doc_id,
                    personnel_id=personnel_id,
                    personnel_name=full_name,
                    document_label=label,
                    project_name=project_name,
                    valid_until=valid_until,
                    days_left=(valid_until - today).days,
                )
            )

    by_type: list[HrDocumentTypeBreakdown] = []
    missing_total = 0
    for t in types:
        counts = per_type_counts[t.id]
        have = len(personnel_with_type[t.id])
        # Bu tipte kaydı OLMAYAN aktif+yayın personel = eksik (kişi tabanı).
        missing_for_type = max(active_published_count - have, 0)
        if t.is_mandatory:
            missing_total += missing_for_type
        by_type.append(
            HrDocumentTypeBreakdown(
                type_id=t.id,
                type_name=t.name,
                is_mandatory=t.is_mandatory,
                validity_months=t.validity_months,
                total_documents=counts["valid"] + counts["expiring"] + counts["expired"],
                valid=counts["valid"],
                expiring=counts["expiring"],
                expired=counts["expired"],
                missing=missing_for_type,
            )
        )

    # En çok geciken önce (valid_until en eski) · en yakın biten önce (days_left en küçük).
    expired_rows.sort(key=lambda r: r.days_overdue, reverse=True)
    expiring_rows.sort(key=lambda r: r.days_left)

    return HrDocumentsSummaryResponse(
        total_documents=total_documents,
        valid=valid,
        expiring=expiring,
        expired=expired,
        missing=missing_total,
        by_type=by_type,
        expired_documents=expired_rows[:SUMMARY_LIST_LIMIT],
        expiring_documents=expiring_rows[:SUMMARY_LIST_LIMIT],
    )


# --- İK-2 T2: izin talebi CRUD (spec §3, §5 K2/K3) -------------------------


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
    return await _create_leave_request_for(session, actor, personnel, data)


async def _create_leave_request_for(
    session: AsyncSession,
    actor: User,
    personnel: Personnel,
    data: LeaveRequestCreate | SelfLeaveRequestCreate,
) -> tuple[LeaveRequestResponse, str]:
    """İzin talebi yazmanın TEK gövdesi — İK yolu ve self-servis yolu bunu ÇAĞIRIR.

    İki yol yalnız **personelin NASIL belirlendiğinde** ayrışır (gövdeden mi,
    `user_id` köprüsünden mi); kuralların geri kalanı (tip 404/422, tarih 422,
    BC görünürlüğü 404, `days` sunucu hesabı, `status=pending`) TEK KOPYADIR.
    Kopyalansaydı iki yol zamanla ayrışır ve dar olması gereken self yüzeyi
    farkında olmadan gevşerdi.
    """
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


# --- İK-2.1: self-servis izin talebi (kullanıcı kararı 2026-08-19) ----------
#
# 🔴 Bu YETKİ YÜZEYİDİR ve genişleme DAR tutulmuştur: aktörün `user_id`siyle
# eşleşen **TEK** personel kaydına, **YALNIZ** izin talebi OLUŞTURMA ve **kendi**
# taleplerini OKUMA açılır. Onay/red/düzenleme/silme kapıları DEĞİŞMEDİ.


async def resolve_self_personnel(session: AsyncSession, actor: User) -> Personnel:
    """Aktörün KENDİ personel kaydı — self-servis yüzeyinin TEK yetki kaynağı.

    Üç hâl, üçü de AÇIK (500 YOK):
    * 0 kayıt → 404 (K3). `user_id` yalnız opsiyonel bir köprüdür; saha
      personelinin çoğunun login'i yoktur, bu yüzden yokluğu normal bir durumdur.
    * 1 kayıt → o kayıt.
    * >1 kayıt → 409 FAIL-CLOSED (K4). `personnel.user_id` üzerinde UNIQUE kısıt
      **YOKTUR** (ölçüldü: yalnız tekil olmayan `ix_personnel_user_id`), bu yüzden
      belirsizlik gerçekten mümkündür ve sunucu TAHMİN YÜRÜTMEZ — hiçbir şey yazmaz.

    Yazma ve okuma AYNI çözümü kullanır: ekranda görülen küme ile yazılan kayıt
    ASLA farklı bir personele ait olamaz.
    """
    kayitlar = await repository.list_personnel_by_user(session, actor.id)
    if not kayitlar:
        raise NotFoundError(guards.SELF_PERSONNEL_MISSING)
    if len(kayitlar) > 1:
        raise ConflictError(guards.SELF_PERSONNEL_AMBIGUOUS)
    return kayitlar[0]


async def create_self_leave_request(
    session: AsyncSession, actor: User, data: SelfLeaveRequestCreate
) -> tuple[LeaveRequestResponse, str]:
    """Personelin KENDİ izin talebi.

    Hedef personel gövdeden ALINMAZ, `user_id` köprüsünden ÇÖZÜLÜR — `data`
    şemasında `personnel_id` alanı YOKTUR (`extra="forbid"` gönderilmesini de
    reddeder). Başkasının adına talep bu yüzden bir yetki denetimiyle değil
    YAPISAL OLARAK engellenir.

    Denetim metni İK yolundan AYRIDIR (`AuditAction` üyesi AÇILMAZ — ayrım
    `messages.*` metnindedir): günlükte "kim kimin adına açtı" karışmasın.
    """
    personnel = await resolve_self_personnel(session, actor)
    response, _ = await _create_leave_request_for(session, actor, personnel, data)
    detail = messages.leave_request_self_created(
        personnel.full_name, response.leave_type_name, response.start_date, response.end_date
    )
    return response, detail


async def list_self_leave_requests(
    session: AsyncSession, actor: User, status: LeaveStatus | None, limit: int, offset: int
) -> tuple[list[LeaveRequestResponse], int]:
    """Aktörün KENDİ talepleri (K6): yazma açılıp okuma açılmazsa kullanıcı
    gönderdiği talebi hiç göremezdi.

    Süzgeç `personnel_id`si SUNUCU tarafından KONUR — istemci gönderemez, yani
    bu uç başka bir personelin listesine ASLA çevrilemez. `project_id` süzgeci
    de yoktur: kendi kayıtlarında daraltmanın anlamı yok, yüzey dar kalır.
    """
    personnel = await resolve_self_personnel(session, actor)
    return await list_leave_requests(
        session,
        status=status,
        personnel_id=personnel.id,
        project_id=None,
        limit=limit,
        offset=offset,
    )


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


# --- İK-2 T3: onay/red + bakiye türevleri (spec §2, §3, §5 K3/K4/K5) -------


async def _leave_balance_parts(
    session: AsyncSession, personnel: Personnel, year: int, today: date
) -> tuple[int | None, Decimal, int]:
    """(hak, devreden, kullanılan) üçlüsü — bakiye ucunun ve onay kapısının ORTAK
    tabanı.

    İki yol da AYNI üçlüden beslenir ki ekranda görülen "kalan" ile onayı
    engelleyen "kalan" ASLA ayrışmasın: ayrı hesaplanan bir eşik, kullanıcının
    ekranda 4 gün görüp onayda 409 yediği (ya da tersi) bir dünya üretirdi.

    Bakiye satırı YOKSA `carried_over` sıfırdır — satır MANUEL devreden içindir
    (İZ 137) ve yokluğu "devreden yok" demektir, veri eksikliği değil.
    """
    reference = leave.balance_reference_date(year, today)
    entitlement = leave.annual_entitlement(personnel.hire_date, reference)
    balance = await repository.get_leave_balance(session, personnel.id, year)
    carried_over = balance.carried_over if balance is not None else Decimal("0")
    used = await repository.sum_deductible_approved_days(session, personnel.id, year)
    return entitlement, carried_over, used


def _balance_response(
    personnel: Personnel,
    year: int,
    today: date,
    entitlement: int | None,
    carried_over: Decimal,
    used: int,
) -> LeaveBalanceResponse:
    """Üçlü → İZ bakiye satırı. TÜM türevler `leave.py` tek kaynağından gelir —
    formül burada TEKRARLANMAZ."""
    reference = leave.balance_reference_date(year, today)
    months = leave.completed_service_months(personnel.hire_date, reference)
    return LeaveBalanceResponse(
        personnel_id=personnel.id,
        personnel_name=personnel.full_name,
        year=year,
        hire_date=personnel.hire_date,
        seniority_years=None if months is None else months // 12,
        seniority_months=None if months is None else months % 12,
        annual_entitlement=entitlement,
        carried_over=carried_over,
        used=used,
        remaining=leave.remaining_leave(entitlement, carried_over, used),
        usage_pct=leave.usage_pct(entitlement, carried_over, used),
    )


async def get_leave_balance(
    session: AsyncSession, personnel_id: uuid.UUID, year: int, *, today: date | None = None
) -> LeaveBalanceResponse:
    """Bakiye görünümü. Personel yok → 404; BAKİYE SATIRI yoksa 404 DEĞİL —
    türevler yine hesaplanabilir (devreden 0)."""
    today = today or timezone.today()
    personnel = await get_personnel(session, personnel_id)
    entitlement, carried_over, used = await _leave_balance_parts(session, personnel, year, today)
    return _balance_response(personnel, year, today, entitlement, carried_over, used)


async def upsert_leave_balance(
    session: AsyncSession,
    personnel_id: uuid.UUID,
    year: int,
    data: LeaveBalanceUpdate,
    *,
    today: date | None = None,
) -> tuple[LeaveBalanceResponse, str]:
    """Devreden günü yazar (UPSERT) — YALNIZ `carried_over` (spec §3, §5 K1).

    PUT'tur çünkü kaynak (personel, yıl) çiftiyle ADRESLENİR ve tek alanlıdır:
    aynı isteği iki kez göndermek aynı sonucu verir, ikinci satır AÇILMAZ
    (`uq_leave_balances_personnel_year` yarış emniyet ağı olarak kalır).

    **Kilit neden burada da var:** UQ tek başına yalnız ikinci SATIRI engeller —
    iki eşzamanlı PUT ikisi de "satır yok" görüp INSERT ederse ikincisi
    `IntegrityError`a düşer ve kullanıcı 409 alır; oysa PUT'un sözleşmesi
    "gönderdiğin değer yazılır"dır, ikinci istek UPDATE'e DÜŞMELİDİR. Ayrıca
    `carried_over` onay eşiğinin (K5) girdisidir: kilit `approve` ile AYNI
    personel satırında olduğundan devreden gün, onay hesabının ortasında
    kayamaz. Sıra `_lock_decision_scope` ile aynıdır (personel önce).

    Türev alanlar gövdede KABUL EDİLMEZ (`extra="forbid"`) — `annual_entitlement`
    kolon değildir (K1) ve gönderilmesi sessizce yutulsaydı istemci hakkı
    değiştirdiğini sanırdı.
    """
    today = today or timezone.today()
    personnel = await get_personnel(session, personnel_id)
    await repository.lock_personnel_for_update(session, personnel.id)

    balance = await repository.get_leave_balance(session, personnel.id, year)
    if balance is None:
        balance = LeaveBalance(personnel_id=personnel.id, year=year, carried_over=data.carried_over)
        await repository.add_leave_balance(session, balance)
    else:
        balance.carried_over = data.carried_over
        await session.flush()
        await session.refresh(balance)

    entitlement, carried_over, used = await _leave_balance_parts(session, personnel, year, today)
    detail = messages.leave_balance_updated(personnel.full_name, year, balance.carried_over)
    return _balance_response(personnel, year, today, entitlement, carried_over, used), detail


async def _lock_decision_scope(
    session: AsyncSession, request: LeaveRequest, personnel: Personnel
) -> None:
    """Karar yolunun SERİLEŞTİRME kilidi — TÜM denetimlerden ÖNCE (spec §5 K3/K5).

    **Sıra sabittir: önce `personnel`, sonra `leave_requests`.** Kilit alan üç yol
    (`approve`, `reject`, `upsert_leave_balance`) AYNI sırayı izler; ters sırada
    kilitleyen bir yol eklenirse karşılıklı kilitlenme (deadlock) doğar.

    * **Personel satırı** eşiğin ortak kaynağıdır: çakışma (K3) ve kalan hak (K5)
      denetimleri o personelin TÜM onaylı izinleri üzerinden okunur. Kilit
      alındıktan sonra yapılan okumalar (READ COMMITTED) rakip transaction'ın
      COMMIT'ini görür — "ikisi de eşiği geçti" yarışı burada kapanır.
    * **Talep satırı** çift-karar yarışına karşıdır: `populate_existing` ile durum
      kilit ALTINDA yeniden okunur, yoksa `_assert_decidable` atlatılabilirdi.

    Talep kilit alınana kadar SİLİNMİŞ olabilir (`delete_leave_request` yalnız
    `pending` satırı siler) — o hâlde 404, kayıt yokmuş gibi.
    """
    await repository.lock_personnel_for_update(session, personnel.id)
    if await repository.get_leave_request_locked(session, request.id) is None:
        raise NotFoundError(guards.LEAVE_REQUEST_MISSING)


def _assert_decidable(request: LeaveRequest) -> None:
    """Karara YALNIZ `pending` talep açıktır → aksi 409 (spec §5 K4: onay TEK adım).

    Onaylanmış talebi yeniden onaylamak bakiyeyi ikinci kez tüketmez ama karar
    damgasını (kim, ne zaman) sessizce EZERDİ; reddedilmişi onaylamak ise
    reddin denetim izini yok ederdi. Düzeltme yolu yeni talep açmaktır.
    """
    if request.status is not LeaveStatus.pending:
        raise ConflictError(guards.LEAVE_DECISION_NOT_PENDING)


async def _assert_approvable(
    session: AsyncSession,
    request: LeaveRequest,
    personnel: Personnel,
    leave_type: LeaveType,
    today: date,
) -> None:
    """`approve`ın İKİ iş kuralı kapısı (spec §5 K3, K5) — ikisi de 409.

    **Sıra bilinçlidir:** önce ÇAKIŞMA (K3), sonra hak aşımı (K5). Çakışma kaydın
    kendisiyle ilgili mutlak bir engeldir (bir gün iki izne birden ait olamaz) ve
    tipten bağımsızdır; hak aşımı ise yalnız `deducts_from_annual` tiplerde
    anlamlıdır. Ters sırada, çakışan bir hastalık izni için önce hesap yapılıp
    sonra çakışmaya düşülürdü — kullanıcı da daha az bilgilendirici hatayı görürdü.

    **RED bu kapılardan GEÇMEZ** (İZ 98-99: hak aşan satırda ✓ pasif, ✗ aktif).
    """
    overlapping = await find_overlapping_approved_leave(
        session,
        personnel.id,
        request.start_date,
        request.end_date,
        exclude_id=request.id,
    )
    if overlapping is not None:
        raise ConflictError(guards.LEAVE_OVERLAPPING_APPROVED)

    # Yıllık haktan DÜŞMEYEN tip (hastalık/mazeret) eşiğe HİÇ girmez — kıdemsiz
    # personel de rapor izni alabilmelidir (İZ 87).
    if not leave_type.deducts_from_annual:
        return

    year = leave.leave_year(request.start_date, request.end_date)
    entitlement, carried_over, used = await _leave_balance_parts(session, personnel, year, today)
    remaining = leave.remaining_leave(entitlement, carried_over, used)
    # 🔴 NULL-EŞİK KANONU (fail-closed): kalan HESAPLANAMIYORSA onay ENGELLİDİR.
    # "Bilinmeyen = küçük" varsayımı burada `used=0` + `hak=0` üretip tam hakkı
    # açardı; bilinmeyen BÜYÜK/engelleyici sayılır ve ayrı bir metinle söylenir
    # (kullanıcı "hak aşımı" değil "kıdem/işe giriş eksik" olduğunu görsün).
    if remaining is None:
        raise ConflictError(guards.LEAVE_ENTITLEMENT_UNKNOWN)
    if Decimal(request.days) > remaining:
        raise ConflictError(guards.LEAVE_ENTITLEMENT_EXCEEDED)


def _stamp_decision(
    request: LeaveRequest, actor: User, status: LeaveStatus, reason: str | None
) -> None:
    """Karar damgası SUNUCUDANDIR (istemci gönderemez, şema `extra="forbid"`).

    `reject_reason` onayda AÇIKÇA temizlenir: bir talep yalnız `pending`ken karara
    açıldığından bugün dolu gelemez, ama alan boş bırakılırsa ileride bir "karara
    geri döndürme" yolu açıldığında eski red gerekçesi onaylı kayıtta ASILI KALIRDI.
    """
    request.status = status
    request.decided_by = actor.id
    request.decided_at = datetime.now(UTC)
    request.reject_reason = reason


async def approve_leave_request(
    session: AsyncSession, actor: User, request_id: uuid.UUID, *, today: date | None = None
) -> tuple[LeaveRequestResponse, str]:
    """Talebi onaylar — TEK adım (spec §5 K4), kapı `personnel` **full+**.

    Sıra: kayıt (404) → **satır kilidi** → durum (409) → çakışma (409) → hak aşımı
    / fail-closed (409) → damga. TÜM denetimler yazmadan ÖNCE koşar: yarı
    onaylanmış bir kayıt bırakılmaz.

    Kilit denetimlerden ÖNCE ve AYNI transaction içinde alınır
    (`_lock_decision_scope`): kilitsiz hâlde iki eşzamanlı onay aynı `used`
    toplamını okuyup ikisi de K5 eşiğini geçerdi.
    """
    today = today or timezone.today()
    request, personnel, leave_type = await get_leave_request_row(session, request_id)
    await _lock_decision_scope(session, request, personnel)
    _assert_decidable(request)
    await _assert_approvable(session, request, personnel, leave_type, today)

    _stamp_decision(request, actor, LeaveStatus.approved, None)
    await session.flush()
    await session.refresh(request)

    detail = messages.leave_request_approved(
        personnel.full_name, leave_type.name, request.start_date, request.end_date
    )
    return _leave_response(request, personnel, leave_type), detail


async def reject_leave_request(
    session: AsyncSession, actor: User, request_id: uuid.UUID, data: LeaveRejectRequest
) -> tuple[LeaveRequestResponse, str]:
    """Talebi reddeder — gerekçe ZORUNLU; **red HER ZAMAN serbesttir**.

    Hak aşımı ve çakışma kapıları BİLİNÇLİ olarak çağrılmaz (İZ 98-99: onaylanamaz
    satırın ✗ butonu aktiftir). Onaylanamayan bir talebin reddedilememesi onu
    sonsuza dek `pending` bırakır ve İZ'in "Bekleyen" sayacını kalıcı kirletirdi.

    Sıra: kayıt (404) → **satır kilidi** → durum (409) → damga. Gerekçe boşluk
    denetimi şemadadır (422).

    Red iş kuralı kapılarından geçmese de karar damgası bir DURUM GEÇİŞİDİR:
    kilitsiz hâlde eşzamanlı bir `approve` ile aynı talep hem onaylanıp hem
    reddedilebilir, ikinci damga birincinin izini EZERDİ. Kilit `approve` ile
    AYNI sırayı (personel → talep) izler.
    """
    request, personnel, leave_type = await get_leave_request_row(session, request_id)
    await _lock_decision_scope(session, request, personnel)
    _assert_decidable(request)

    reason = data.reason.strip()
    _stamp_decision(request, actor, LeaveStatus.rejected, reason)
    await session.flush()
    await session.refresh(request)

    detail = messages.leave_request_rejected(
        personnel.full_name, leave_type.name, request.start_date, request.end_date, reason
    )
    return _leave_response(request, personnel, leave_type), detail


# --- İK-2 T4: izin özeti (spec §3, §4 — İZ mockup birebir) ------------------


def _month_window(today: date) -> tuple[date, date]:
    """İZ 48'in "bu ay" penceresi: `today`nin ayının ilk ve son günü.

    Ay sonu `calendar.monthrange` ile bulunur — `+30 gün` yaklaşık bir pencere
    açar ve Şubat'ta bir sonraki ayın günlerini KPI'ya sokardı.
    """
    son_gun = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, son_gun)


def _balance_sort_key(row: LeaveBalanceResponse) -> tuple[int, Decimal, str]:
    """İZ 133-168 sırası: **kalan AZALAN**, hakkı bilinmeyenler EN SONDA.

    Mockup satırları 11 · 9 · 8 · "Hak yok" sırasındadır — ekranın önce en çok
    izni biriken kişiyi göstermesi izin planlamasının işidir. `None` kalanı
    sıfırmış gibi sıralamak, hakkı olmayan personeli kullanmayanların ARASINA
    serpiştirirdi; ayrı bir bayrakla sona alınır. Eşitlik ada göre çözülür ki
    sıra istekten isteğe OYNAMASIN.
    """
    if row.remaining is None:
        return (1, Decimal("0"), row.personnel_name)
    return (0, -row.remaining, row.personnel_name)


async def build_hr_leaves_summary(
    session: AsyncSession, *, year: int | None = None, today: date | None = None
) -> HrLeavesSummaryResponse:
    """İZ özeti: 5 KPI + bakiye tablosu — SABİT sorgu sayısı (N+1 yok).

    BEŞ aggrega sorgu çekilir (bekleyen sayısı · bugün izinli · bu ay kullanılan ·
    personel+devreden satırları · personel bazlı yıllık kullanım group-by'ı);
    hak/kalan/kıdem/yüzde türevleri Python'da `leave.py` TEK KAYNAĞINDAN hesaplanır
    ve satır kurulumu bakiye ucuyla AYNI `_balance_response`tan geçer — ekranda iki
    farklı "kalan" doğamaz. Sorgu sayısı VERİ BÜYÜKLÜĞÜNDEN BAĞIMSIZDIR
    (`test_n_plus_1_sabit_sorgu`).

    `year` verilmezse İÇİNDE BULUNULAN yıl (İZ 120 seçicisinin varsayılanı);
    `today` enjekte edilir (servis sınırı `timezone.today()` verir, test sabit tarih).

    KPI'lar TÜM personeli sayar, tablo `SUMMARY_LIST_LIMIT` satırda kırpılır
    (İK-1 emsali): kırpma bir GÖRÜNTÜ sınırıdır, sayaçları eksiltmez.
    """
    today = today or timezone.today()
    year = year or today.year
    ay_baslangic, ay_bitis = _month_window(today)

    pending_requests = await repository.count_pending_leave_requests(session)
    on_leave_today = await repository.count_personnel_on_leave(session, today)
    days_used_this_month = await repository.sum_deductible_approved_days_between(
        session, ay_baslangic, ay_bitis
    )
    rows = await repository.list_active_published_personnel_with_balance(session, year)
    used_by_personnel = await repository.sum_deductible_approved_days_by_personnel(session, year)

    reference = leave.balance_reference_date(year, today)
    balances: list[LeaveBalanceResponse] = []
    total_debt = Decimal("0")
    carryover_risk = 0
    unknown = 0

    for personnel, carried_over_raw in rows:
        # Bakiye satırı YOKSA devreden sıfırdır (satır yalnız MANUEL devreden içindir).
        carried_over = carried_over_raw if carried_over_raw is not None else Decimal("0")
        used = used_by_personnel.get(personnel.id, 0)
        entitlement = leave.annual_entitlement(personnel.hire_date, reference)
        satir = _balance_response(personnel, year, today, entitlement, carried_over, used)
        balances.append(satir)

        if satir.remaining is None:
            # 🔴 fail-closed: hesaplanamayan hak toplama 0 olarak KARIŞMAZ, sayılır.
            unknown += 1
            continue
        # Borç = personele HÂLÂ borçlu olunan gün. Negatif kalan (fazla kullanılmış
        # izin) ters yönlü bir alacaktır; netleştirilseydi ekrandaki toplam bir
        # başkasının borcunu sessizce yutardı.
        if satir.remaining > 0:
            total_debt += satir.remaining
        # İZ 50 "Devreden Risk · Yıl sonu yanacak": devredeni VAR ve kalanı DURUYOR.
        # Kalanı tükenmiş kişide yanacak gün kalmamıştır; devredeni olmayan zaten
        # riskte değildir.
        if carried_over > 0 and satir.remaining > 0:
            carryover_risk += 1

    balances.sort(key=_balance_sort_key)

    return HrLeavesSummaryResponse(
        year=year,
        pending_requests=pending_requests,
        on_leave_today=on_leave_today,
        days_used_this_month=days_used_this_month,
        total_leave_debt=total_debt,
        carryover_risk_personnel=carryover_risk,
        unknown_entitlement_personnel=unknown,
        balances=balances[:SUMMARY_LIST_LIMIT],
    )
