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
