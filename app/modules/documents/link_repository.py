"""BC-3 bağ sorguları — sahip-parametrik, kapsam süzgeci BURADA DEĞİL serviste.

`documents/repository.py` deseni: bu katman `visible_projects` bilmez; sahip
görünürlüğü `link_service._visible_owner` kapısındadır.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.link_owners import OwnerContext, OwnerSpec
from app.modules.documents.models.core import Document
from app.modules.documents.models.links import EntityDocumentScope, EntityDocumentType


class LinkRow(NamedTuple):
    """Bağ satırı + slot tipi + (varsa) arşiv künyesi — liste ve tekil yanıtın
    ORTAK malzemesi; iki yerde ayrı ayrı JOIN yazılmaz."""

    link: object
    doc_type: EntityDocumentType
    document: Document | None


async def list_slot_types(
    session: AsyncSession, scope: EntityDocumentScope | None
) -> list[EntityDocumentType]:
    stmt = select(EntityDocumentType).order_by(
        EntityDocumentType.scope, EntityDocumentType.sort_order, EntityDocumentType.code
    )
    if scope is not None:
        stmt = stmt.where(EntityDocumentType.scope == scope)
    return list((await session.execute(stmt)).scalars().all())


async def get_slot_type(
    session: AsyncSession, type_id: uuid.UUID, scope: EntityDocumentScope
) -> EntityDocumentType | None:
    """Tip VE bölme birlikte: başka bölmenin tipi "yok" sayılır (guard kanonu —
    var olmayan ile yanlış kapsam AYNI sonucu alır)."""
    stmt = select(EntityDocumentType).where(
        EntityDocumentType.id == type_id, EntityDocumentType.scope == scope
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_owner_context(
    session: AsyncSession, spec: OwnerSpec, owner_id: uuid.UUID
) -> OwnerContext | None:
    row = (await session.execute(spec.context_stmt(owner_id))).one_or_none()
    if row is None:
        return None
    return OwnerContext(project_id=row[0], display=str(row[1]))


def _rows_stmt(spec: OwnerSpec):
    link = spec.link_model
    return (
        select(link, EntityDocumentType, Document)
        .join(EntityDocumentType, EntityDocumentType.id == link.type_id)
        .outerjoin(Document, Document.id == link.document_id)
    )


async def list_links(session: AsyncSession, spec: OwnerSpec, owner_id: uuid.UUID) -> list[LinkRow]:
    stmt = (
        _rows_stmt(spec)
        .where(spec.owner_column == owner_id)
        .order_by(EntityDocumentType.sort_order, spec.link_model.created_at, spec.link_model.id)
    )
    return [LinkRow(*row) for row in (await session.execute(stmt)).all()]


async def get_link_row(
    session: AsyncSession, spec: OwnerSpec, link_id: uuid.UUID
) -> LinkRow | None:
    stmt = _rows_stmt(spec).where(spec.link_model.id == link_id)
    row = (await session.execute(stmt)).one_or_none()
    return None if row is None else LinkRow(*row)


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
