"""Ekipman belgesi veri erişimi (MK-2 T4) — yalnız SQL, yetki/kapsam kararı YOK.

Kapsam kararı (`visible_equipment`, K9/K20) `document_service.py`dedir
(`repository.py` deseninin kardeşi). `content` (bytea) kolonu liste/özet
sorgularına BİLEREK GİRMEZ — yalnız `get_document_with_content` onu seçer
(TOAST şişmesini liste sorgusundan izole tutan `documents`/`document_blobs`
ayrımının aynı gerekçesi).
"""

import uuid

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, EquipmentDocument, EquipmentDocumentType

# Liste/detay/özet uçlarının PAYLAŞTIĞI kolon kümesi — `content` HARİÇ.
_DOCUMENT_LIST_COLUMNS = (
    EquipmentDocument.id,
    EquipmentDocument.equipment_id,
    EquipmentDocument.type_id,
    EquipmentDocumentType.code.label("type_code"),
    EquipmentDocumentType.name.label("type_name"),
    EquipmentDocument.filename,
    EquipmentDocument.mime_type,
    EquipmentDocument.size_bytes,
    EquipmentDocument.valid_until,
    EquipmentDocument.created_at,
)


async def list_document_types(session: AsyncSession) -> list[EquipmentDocumentType]:
    stmt = select(EquipmentDocumentType).order_by(EquipmentDocumentType.sort_order)
    return list((await session.scalars(stmt)).all())


async def get_document_type(
    session: AsyncSession, type_id: uuid.UUID
) -> EquipmentDocumentType | None:
    return await session.scalar(
        select(EquipmentDocumentType).where(EquipmentDocumentType.id == type_id)
    )


async def list_documents_for_equipment(session: AsyncSession, equipment_id: uuid.UUID) -> list[Row]:
    """`content` HARİÇ — liste ekranı baytlara dokunmaz (spec §2 kanonu)."""
    stmt = (
        select(*_DOCUMENT_LIST_COLUMNS)
        .join(EquipmentDocumentType, EquipmentDocumentType.id == EquipmentDocument.type_id)
        .where(EquipmentDocument.equipment_id == equipment_id)
        .order_by(EquipmentDocumentType.sort_order, EquipmentDocument.created_at)
    )
    return list((await session.execute(stmt)).all())


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> EquipmentDocument | None:
    """Künye — `content` DAHİL. Yalnız indirme ucu ve silme ucu bunu çağırır."""
    return await session.scalar(
        select(EquipmentDocument).where(EquipmentDocument.id == document_id)
    )


async def create_document(session: AsyncSession, document: EquipmentDocument) -> EquipmentDocument:
    session.add(document)
    await session.flush()
    return document


async def delete_document(session: AsyncSession, document: EquipmentDocument) -> None:
    await session.delete(document)


async def list_active_equipment_ids(session: AsyncSession) -> list[uuid.UUID]:
    """K7/İK-1 `missing` semantiği: yalnız AKTİF (`is_active=true`) ekipman."""
    stmt = select(Equipment.id).where(Equipment.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def list_active_document_rows_for_summary(session: AsyncSession) -> list[Row]:
    """Özet ucunun TEK toplu sorgusu — N+1 yok (İK-1 `build_hr_documents_summary`
    deseninin birebiri). Yalnız AKTİF ekipmanın belgeleri döner; `content` HARİÇ."""
    stmt = (
        select(
            EquipmentDocument.id,
            EquipmentDocument.equipment_id,
            Equipment.name.label("equipment_name"),
            EquipmentDocument.type_id,
            EquipmentDocumentType.name.label("type_name"),
            EquipmentDocumentType.is_required,
            EquipmentDocument.valid_until,
        )
        .join(Equipment, Equipment.id == EquipmentDocument.equipment_id)
        .join(EquipmentDocumentType, EquipmentDocumentType.id == EquipmentDocument.type_id)
        .where(Equipment.is_active.is_(True))
    )
    return list((await session.execute(stmt)).all())


async def list_active_equipment_type_pairs(
    session: AsyncSession,
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """`(equipment_id, type_id)` çiftleri — en az bir belgesi olan AKTİF ekipman.

    `missing` hesabının TEK sorgusu (İK-1 `personnel_with_type` deseninin
    birebiri): "bu tipte kaydı OLMAYAN aktif ekipman" bu kümenin TÜMLEYENİdir.
    """
    stmt = (
        select(EquipmentDocument.equipment_id, EquipmentDocument.type_id)
        .join(Equipment, Equipment.id == EquipmentDocument.equipment_id)
        .where(Equipment.is_active.is_(True))
        .distinct()
    )
    return {(row.equipment_id, row.type_id) for row in (await session.execute(stmt)).all()}
