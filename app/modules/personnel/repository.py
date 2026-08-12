"""Personel veri erişimi — `customers/repository.py` + `users/repository.py`

(sayfalama) desenlerinin birleşimi.

**`visible_projects` süzgeci YOKTUR ama `?project_id=` süzgeci VARDIR** (İK-1 spec
§5 K4): `personnel` yine şirket-geneli bir İK varlığıdır ve tüm projelerde görünür;
İK-1 ile `assigned_project_id` ATAMA kolonu açıldığından `project_id` bir
DARALTMA süzgecidir (yetki genişletmez). Puantaj diliminin "proje süzgeci
eklenmesin" notu atama kolonu YOKKEN geçerliydi; §5 K4 kararı bunu güncelledi —
kolon açıldı, `?project_id=` meşru. IDOR unutulmuş DEĞİLDİR: süzgeç bir yetki
kapısı değildir, erişim yine `personnel` izin seviyesiyle (router kapıları)
denetlenir.
"""

import uuid
from datetime import date

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.personnel.models import (
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Personnel,
    PersonnelDocument,
    PersonnelDocumentType,
)
from app.modules.projects.models import Project
from app.modules.site_diary.models import WorkerSource


def _filtreli(
    stmt: Select,
    q: str | None,
    source: WorkerSource | None,
    subcontractor_id: uuid.UUID | None,
    is_active: bool | None,
    project_id: uuid.UUID | None,
    is_draft: bool | None,
) -> Select:
    """Liste ve sayım AYNI süzgeçleri kullanır — `total` gösterilen listeyle uyuşsun."""
    if q:
        stmt = stmt.where(Personnel.full_name.ilike(f"%{q}%"))
    if source is not None:
        stmt = stmt.where(Personnel.source == source)
    if subcontractor_id is not None:
        stmt = stmt.where(Personnel.subcontractor_id == subcontractor_id)
    if is_active is not None:
        stmt = stmt.where(Personnel.is_active.is_(is_active))
    # İK-1 §5 K4: atama kolonuna göre DARALTMA (yetki genişletmez).
    if project_id is not None:
        stmt = stmt.where(Personnel.assigned_project_id == project_id)
    if is_draft is not None:
        stmt = stmt.where(Personnel.is_draft.is_(is_draft))
    return stmt


async def list_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    project_id: uuid.UUID | None = None,
    is_draft: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Personnel]:
    """Arama YALNIZ `full_name` üzerindedir (spec §3) ve `ILIKE %q%` kısmi eşleşmedir.

    Sıralama DB'de (`ORDER BY full_name`) — sayfalama deterministik olsun.
    """
    stmt = _filtreli(
        select(Personnel), q, source, subcontractor_id, is_active, project_id, is_draft
    )
    stmt = stmt.order_by(Personnel.full_name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_personnel(
    session: AsyncSession,
    q: str | None = None,
    source: WorkerSource | None = None,
    subcontractor_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    project_id: uuid.UUID | None = None,
    is_draft: bool | None = None,
) -> int:
    stmt = _filtreli(
        select(func.count()).select_from(Personnel),
        q,
        source,
        subcontractor_id,
        is_active,
        project_id,
        is_draft,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_personnel(session: AsyncSession, personnel_id: uuid.UUID) -> Personnel | None:
    return await session.get(Personnel, personnel_id)


async def get_personnel_by_tc_no(
    session: AsyncSession, tc_no: str, exclude_id: uuid.UUID | None = None
) -> Personnel | None:
    """DOLU TCKN'nin başka bir kayıtta olup olmadığı (`customers` pre-SELECT deseni).

    Servis bunu `IntegrityError`a düşmeden ÇAĞIRIR ki kullanıcıya alanına özel
    Türkçe 409 verilebilsin; `uq_personnel_tc_no` YARIŞ DURUMU emniyet ağıdır.
    """
    stmt = select(Personnel).where(Personnel.tc_no == tc_no)
    if exclude_id is not None:
        stmt = stmt.where(Personnel.id != exclude_id)
    return (await session.execute(stmt)).scalars().first()


async def add_personnel(session: AsyncSession, personnel: Personnel) -> Personnel:
    session.add(personnel)
    await session.flush()
    await session.refresh(personnel)
    return personnel


# --- İK-1 T3: belge alt-kaynağı --------------------------------------------


async def list_personnel_documents(
    session: AsyncSession, personnel_id: uuid.UUID
) -> list[Row[tuple[PersonnelDocument, PersonnelDocumentType | None]]]:
    """Bir personelin belgeleri + tip künyesi — TEK JOIN'li sorgu (N+1 YOK).

    `OUTER JOIN`: serbest etiketli kayıtta (`type_id IS NULL`) tip satırı yoktur,
    bu yüzden `LEFT JOIN` ile o kayıtlar da listede kalır ve tip sütunları None
    gelir. Belge başına ayrı bir tip sorgusu (N+1) AÇILMAZ — kanıt:
    `test_liste_tek_join_sorgusu` tip tablosuna ekstra SELECT atılmadığını sayar.

    Sıralama DB'dedir (`created_at`) — liste her yenilendiğinde aynı sırada gelsin.
    """
    stmt = (
        select(PersonnelDocument, PersonnelDocumentType)
        .outerjoin(
            PersonnelDocumentType,
            PersonnelDocument.type_id == PersonnelDocumentType.id,
        )
        .where(PersonnelDocument.personnel_id == personnel_id)
        .order_by(PersonnelDocument.created_at)
    )
    return list((await session.execute(stmt)).all())


async def get_personnel_document(
    session: AsyncSession, document_id: uuid.UUID
) -> PersonnelDocument | None:
    return await session.get(PersonnelDocument, document_id)


async def get_document_type(
    session: AsyncSession, type_id: uuid.UUID
) -> PersonnelDocumentType | None:
    return await session.get(PersonnelDocumentType, type_id)


async def add_personnel_document(
    session: AsyncSession, document: PersonnelDocument
) -> PersonnelDocument:
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


# --- İK-1 T4: belge takibi özeti — AGGREGA sorgular (N+1 YOK, sabit sayı) ---
#
# Özet ucu (BT) SABİT SAYIDA sorgu kullanır (dashboard/progress_payments toplu
# çekim deseni): personel×tip döngüsünde per-row SELECT ATILMAZ. Aşağıdaki üç
# fonksiyon veri büyüklüğünden bağımsız 3 sorgu üretir; durum bucketleme +
# `missing` sayımı Python'da bu satırlar üzerinden yapılır (`status.py` tek
# kaynağı). Kanıt: `test_n_plus_1_sabit_sorgu` 2 vs 10 personelde aynı sayıyı ölçer.


async def list_document_types(session: AsyncSession) -> list[PersonnelDocumentType]:
    """Katalog tipleri (dağılım her tip için satır üretir) — `sort_order` sırasıyla."""
    stmt = select(PersonnelDocumentType).order_by(
        PersonnelDocumentType.sort_order, PersonnelDocumentType.name
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_active_published_personnel(session: AsyncSession) -> int:
    """AKTİF + YAYINDA personel sayısı — `missing` tabanı (spec §2/§3).

    Taslak (`is_draft=true`) ve pasif (`is_active=false`) personel SAYILMAZ:
    `missing` yalnız çalışan iş gücü için anlamlıdır.
    """
    stmt = (
        select(func.count())
        .select_from(Personnel)
        .where(Personnel.is_active.is_(True), Personnel.is_draft.is_(False))
    )
    return (await session.execute(stmt)).scalar_one()


async def list_active_published_document_rows(
    session: AsyncSession,
) -> list[Row[tuple]]:
    """AKTİF + YAYINDA personelin TÜM belgeleri + tip künyesi + proje adı — TEK sorgu.

    KPI (valid/expiring/expired), tip dağılımı kırılımı ve iki liste (süresi
    dolan/yaklaşan) hep bu tek çekimden Python'da türetilir; belge/tip/personel
    başına ek SELECT (N+1) YOKTUR.

    `INNER JOIN personnel` (+ WHERE aktif/yayın) taslak/pasif personelin
    belgelerini SQL'de eler — özet yalnız çalışan iş gücünü sayar. Tip ve proje
    `LEFT JOIN`'dir: serbest etiketli (`type_id NULL`) ya da projesi olmayan
    kayıtlar da listede kalır (tip/proje sütunları None gelir).
    """
    stmt = (
        select(
            PersonnelDocument.id,
            PersonnelDocument.personnel_id,
            PersonnelDocument.type_id,
            PersonnelDocument.free_label,
            PersonnelDocument.valid_until,
            Personnel.full_name,
            PersonnelDocumentType.name,
            PersonnelDocumentType.is_mandatory,
            PersonnelDocumentType.validity_months,
            Project.name,
        )
        .join(Personnel, PersonnelDocument.personnel_id == Personnel.id)
        .outerjoin(
            PersonnelDocumentType,
            PersonnelDocument.type_id == PersonnelDocumentType.id,
        )
        .outerjoin(Project, Personnel.assigned_project_id == Project.id)
        .where(Personnel.is_active.is_(True), Personnel.is_draft.is_(False))
    )
    return list((await session.execute(stmt)).all())


# --- İK-2 T2: izin tipi kataloğu + izin talepleri ---------------------------


async def list_leave_types(session: AsyncSession, only_active: bool = True) -> list[LeaveType]:
    """Katalog tipleri — talep formunun listesi (SALT OKUMA, spec §1).

    Varsayılan yalnız AKTİF: form pasif bir tipi hiç ÖNERMEMELİ. Okuma yolu
    (`_resolve_leave_type_for_read`) pasif tipi yine getirir, çünkü eski kayıtlar
    doğru künyeyle görünmelidir — `list_document_types` ile aynı ayrım.
    """
    stmt = select(LeaveType)
    if only_active:
        stmt = stmt.where(LeaveType.is_active.is_(True))
    return list(
        (await session.execute(stmt.order_by(LeaveType.sort_order, LeaveType.name))).scalars().all()
    )


async def get_leave_type(session: AsyncSession, type_id: uuid.UUID) -> LeaveType | None:
    return await session.get(LeaveType, type_id)


def _leave_filtreli(
    stmt: Select,
    status: LeaveStatus | None,
    personnel_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> Select:
    """Liste ve sayım AYNI süzgeçleri kullanır — `total` gösterilen listeyle uyuşsun.

    `project_id` PERSONELİN atandığı proje üzerindedir (`Personnel.assigned_project_id`);
    izin talebinin kendi proje kolonu YOKTUR ve açılmaz (iki gerçek kaynak doğardı).
    Bu bir DARALTMA süzgecidir, yetki genişletmez — kapsam yine `personnel` iznidir
    (liste ucundaki `?project_id=` ile aynı gerekçe, İK-1 §5 K4).
    """
    if status is not None:
        stmt = stmt.where(LeaveRequest.status == status)
    if personnel_id is not None:
        stmt = stmt.where(LeaveRequest.personnel_id == personnel_id)
    if project_id is not None:
        stmt = stmt.where(Personnel.assigned_project_id == project_id)
    return stmt


async def list_leave_requests(
    session: AsyncSession,
    status: LeaveStatus | None = None,
    personnel_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row[tuple[LeaveRequest, Personnel, LeaveType]]]:
    """Talepler + personel ve tip künyesi — TEK JOIN'li sorgu (N+1 YOK).

    İki JOIN de INNER'dır: `personnel_id` ve `leave_type_id` NOT NULL FK'dir, yani
    her talebin tam bir personeli ve tipi VARDIR — LEFT JOIN yanlış bir iyimserlik
    (None künye) ihtimali uydururdu. Kanıt: `test_liste_n_plus_1_yok` künye
    tablolarına standalone SELECT gitmediğini sayar.

    Sıralama DB'dedir: en yeni talep önce (`created_at DESC`), eşitlikte `id` —
    sayfalama deterministik olsun (aynı `created_at` iki satırda tekrar edebilir).
    """
    stmt = _leave_filtreli(
        select(LeaveRequest, Personnel, LeaveType)
        .join(Personnel, LeaveRequest.personnel_id == Personnel.id)
        .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id),
        status,
        personnel_id,
        project_id,
    )
    stmt = (
        stmt.order_by(LeaveRequest.created_at.desc(), LeaveRequest.id).limit(limit).offset(offset)
    )
    return list((await session.execute(stmt)).all())


async def count_leave_requests(
    session: AsyncSession,
    status: LeaveStatus | None = None,
    personnel_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> int:
    stmt = _leave_filtreli(
        select(func.count())
        .select_from(LeaveRequest)
        .join(Personnel, LeaveRequest.personnel_id == Personnel.id),
        status,
        personnel_id,
        project_id,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_leave_request(
    session: AsyncSession, request_id: uuid.UUID
) -> Row[tuple[LeaveRequest, Personnel, LeaveType]] | None:
    """Tek talep + künyesi — liste ile AYNI JOIN'i kullanır ki tek kayıt yanıtı
    listedeki satırdan farklı alan taşımasın."""
    stmt = (
        select(LeaveRequest, Personnel, LeaveType)
        .join(Personnel, LeaveRequest.personnel_id == Personnel.id)
        .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
        .where(LeaveRequest.id == request_id)
    )
    return (await session.execute(stmt)).first()


async def add_leave_request(session: AsyncSession, request: LeaveRequest) -> LeaveRequest:
    session.add(request)
    await session.flush()
    await session.refresh(request)
    return request


async def find_overlapping_approved_leave(
    session: AsyncSession,
    personnel_id: uuid.UUID,
    start_date: date,
    end_date: date,
    exclude_id: uuid.UUID | None = None,
) -> LeaveRequest | None:
    """Aynı personelin ÇAKIŞAN **onaylı** izni (spec §5 K3) — varsa ilk satır.

    Çakışma testi kapalı aralıklar üzerindedir: `mevcut.start <= yeni.end AND
    mevcut.end >= yeni.start`. Sınır bilinçlidir — 08'de biten iznin ardından
    09'da başlayan izin ÇAKIŞMAZ, ama 08'de başlayan ÇAKIŞIR (bir gün iki izne
    birden ait olamaz).

    YALNIZ `approved` sayılır: bekleyen talepler henüz bir taahhüt değildir ve
    ikisi birden reddedilebilir. `exclude_id` T3 içindir — onaylanmak istenen
    kaydın KENDİSİ (zaten onaylıysa, ör. yeniden değerlendirme) kendisiyle
    çakışmasın.

    T2'de HİÇBİR UÇ bunu 409'a çevirmez (spec §3: kural `approve`ta işler) —
    burada yalnız HAZIRLANIR ve `test_ik2_leave_service.py`de kanıtlanır.
    """
    stmt = select(LeaveRequest).where(
        LeaveRequest.personnel_id == personnel_id,
        LeaveRequest.status == LeaveStatus.approved,
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    )
    if exclude_id is not None:
        stmt = stmt.where(LeaveRequest.id != exclude_id)
    return (await session.execute(stmt.limit(1))).scalars().first()
