import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sites.models import Site
from app.modules.units.models import Block, Unit


async def list_blocks_for_project(
    session: AsyncSession, project_id: uuid.UUID
) -> list[tuple[Block, str]]:
    """Bir projenin bloklari + santiye adi, `sort_order` sonra `name` sirali (spec §6.1).

    Santiye adi JOIN ile ayni sorguda gelir: blok basliginda gosterilebilmesi
    icin (`BlockResponse.site_name`) blok basina ek `session.get(Site, ...)`
    cagrisi N+1 uretirdi.

    Gorunurluk suzgeci BURADA UYGULANMAZ: proje erisimi servis katmaninda
    `projects.service.visible_projects` ile cozulur (P2 `sites/repository.py`
    deseni) — yetki mantigi tek noktada kalir.
    """
    result = await session.execute(
        select(Block, Site.name)
        .join(Site, Block.site_id == Site.id)
        .where(Block.project_id == project_id)
        .order_by(Block.sort_order, Block.name)
    )
    return [(block, site_name) for block, site_name in result.all()]


async def get_block(session: AsyncSession, block_id: uuid.UUID) -> Block | None:
    return await session.get(Block, block_id)


async def get_block_by_name(
    session: AsyncSession,
    project_id: uuid.UUID,
    name: str,
    exclude_block_id: uuid.UUID | None = None,
) -> Block | None:
    """`uq_blocks_project_name` cakismasini IntegrityError'a DUSMEDEN once yakalar

    (spec §4.3): boylece kullanicija alanina ozel Turkce mesaj verilebilir.
    IntegrityError → 409 handler'i yaris-durumu emniyet agi olarak KALIR.
    PATCH'te blogun kendisini haric tutmak icin `exclude_block_id` verilir.
    """
    stmt = select(Block).where(Block.project_id == project_id, Block.name == name)
    if exclude_block_id is not None:
        stmt = stmt.where(Block.id != exclude_block_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_unit(session: AsyncSession, unit_id: uuid.UUID) -> Unit | None:
    return await session.get(Unit, unit_id)


async def get_unit_by_no(
    session: AsyncSession,
    block_id: uuid.UUID,
    unit_no: str,
    exclude_unit_id: uuid.UUID | None = None,
) -> Unit | None:
    """`uq_units_block_no` cakismasi icin `get_block_by_name` ile ayni gerekce."""
    stmt = select(Unit).where(Unit.block_id == block_id, Unit.unit_no == unit_no)
    if exclude_unit_id is not None:
        stmt = stmt.where(Unit.id != exclude_unit_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_units_for_block(session: AsyncSession, block_id: uuid.UUID) -> list[Unit]:
    """Tek blogun uniteleri — yazma yanitindaki `counts` icin (spec §6.1).

    Yeni acilan blokta bos doner; PATCH'te mevcut sayaci yeniden hesaplar.
    """
    result = await session.execute(
        select(Unit).where(Unit.block_id == block_id).order_by(Unit.sort_order, Unit.unit_no)
    )
    return list(result.scalars().all())


async def list_units_for_project(session: AsyncSession, project_id: uuid.UUID) -> list[Unit]:
    """Bir projenin TUM uniteleri TEK sorguda (spec §6.1 / plan B3 test 17).

    Bloklara dagitim Python'da yapilir; blok basina sorgu atmak 20 bloklu bir
    projede 20 gidis-donus demektir. `sort_order` once gelir: `unit_no` metin
    oldugu icin alfabetik sira "10 < 2" verir (SY 76-99).
    """
    result = await session.execute(
        select(Unit).where(Unit.project_id == project_id).order_by(Unit.sort_order, Unit.unit_no)
    )
    return list(result.scalars().all())
