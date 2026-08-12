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

import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DuplicateError, NotFoundError, PersonnelValidationError
from app.modules.audit import messages
from app.modules.documents import service as documents_service
from app.modules.personnel import guards, repository, status
from app.modules.personnel.models import (
    Personnel,
    PersonnelDocument,
    PersonnelDocumentType,
)
from app.modules.personnel.schemas import (
    HrDocumentsSummaryResponse,
    HrDocumentTypeBreakdown,
    HrExpiredDocument,
    HrExpiringDocument,
    PersonnelCreate,
    PersonnelDocumentCreate,
    PersonnelDocumentResponse,
    PersonnelDocumentUpdate,
    PersonnelUpdate,
)
from app.modules.projects import repository as projects_repository
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
    today = date.today()
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
    return _document_response(document, type_obj, date.today()), detail


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
    return _document_response(document, type_obj, date.today()), detail


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

    `today` ENJEKTE EDİLİR (endpoint `date.today()` verir, test sabit tarih):
    sınır günleri deterministik olsun. Durum `status.derive_document_status` TEK
    KAYNAĞINDAN gelir — eşik (30 gün) burada TEKRARLANMAZ.

    Kapsam: yalnız AKTİF (`is_active=true`) + YAYINDA (`is_draft=false`) personel.
    `missing` KPI toplamı YALNIZ zorunlu (`is_mandatory=true`) tipler üzerinden;
    opsiyonel tipler dağılımda gösterilir ama KPI'ya girmez.
    """
    today = today or date.today()

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
