import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sites.models import Section, Site


async def list_sites_for_project(session: AsyncSession, project_id: uuid.UUID) -> list[Site]:
    """Bir projenin santiyeleri, kod artan.

    Gorunurluk suzgeci BURADA UYGULANMAZ: proje erisimi servis katmaninda
    P1'in _visible_projects'i ile cozulur (spec §5.2), repository yalniz veri
    okur. Bu ayrim, yetki mantiginin tek noktada kalmasini saglar.
    """
    result = await session.execute(
        select(Site).where(Site.project_id == project_id).order_by(Site.code)
    )
    return list(result.scalars().all())


async def list_codes_with_prefix(session: AsyncSession, prefix: str) -> list[str]:
    """Verilen onekle baslayan TUM santiye kodlari (otomatik kod uretimi, spec §3.2).

    KAPSAM SUZGECI YOKTUR: `project_id` bilincli olarak sorulmaz. `PRJ-` emsalinin
    (`projects/repository.list_codes_with_prefix`) birebiri — santiye kodu evrakta
    (irsaliye, puantaj, hakedis) kurumsal kimlik gibi kullanildigi icin sayac
    sirket genelidir. Kisit ise proje ici tekil kalir (`uq_sites_project_code`).
    """
    stmt = select(Site.code).where(Site.code.like(f"{prefix}%"))
    return list((await session.execute(stmt)).scalars().all())


async def get_site(session: AsyncSession, site_id: uuid.UUID) -> Site | None:
    """Santiye + bolumleri + bagli proje (iliskiler lazy="selectin")."""
    return await session.get(Site, site_id)


async def list_sections(session: AsyncSession, site_id: uuid.UUID) -> list[Section]:
    result = await session.execute(
        select(Section).where(Section.site_id == site_id).order_by(Section.sort_order)
    )
    return list(result.scalars().all())


async def get_section(session: AsyncSession, section_id: uuid.UUID) -> Section | None:
    return await session.get(Section, section_id)
