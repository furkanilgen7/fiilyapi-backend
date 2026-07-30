import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sites.models import Section, Site
from app.modules.users.models import User, UserStatus


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


async def get_site_by_code(
    session: AsyncSession,
    project_id: uuid.UUID,
    code: str,
    exclude_site_id: uuid.UUID | None = None,
) -> Site | None:
    """(project_id, code) cakismasini IntegrityError'a DUSMEDEN once yakalar.

    `boq/repository.get_item_by_code` deseninin birebiri (spec §7.2): servis once
    acik bir SELECT ile bakar ki kullaniciya alanina ozel Turkce mesaj verilsin
    ("Bu şantiye kodu bu projede zaten kullanılıyor"), genel "Veri bütünlüğü
    hatası" degil. `uq_sites_project_code` -> IntegrityError -> 409 handler'i
    YARIS DURUMU emniyet agi olarak KALIR (spec §8.3).

    Cakisma yakalanmazsa istisna FLUSH aninda, yani santiye satiri eklendikten
    SONRA atilir; oradan geri donmek transaction'a birakilir. Erken yakalamak
    atomikligi kolaylastirir: hicbir satir session'a girmeden reddedilir.
    """
    stmt = select(Site).where(Site.project_id == project_id, Site.code == code)
    if exclude_site_id is not None:
        stmt = stmt.where(Site.id != exclude_site_id)
    return (await session.execute(stmt)).scalar_one_or_none()


# Sef / ISG / bolum sorumlusu olarak ATANABILIR kullanici durumlari
# (karar 2026-07-30). `passive` bilincli olarak DISARIDA: kalici bir
# kullanilamazliktir, gecici degil.
_ASSIGNABLE_USER_STATUSES = (UserStatus.active, UserStatus.on_leave)


async def get_assignable_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Sef / ISG / bolum sorumlusu FK'leri icin: kullanici VAR MI ve ATANABILIR MI (spec §9).

    "Bu kullaniciyi gorme yetkin var mi" ARANMAZ: kullanici listesi `sites:full`
    sahibi icin zaten `GET /users` ile erisilebilir; burada ikinci bir gorunurluk
    kurali icat etmek iki ayri yetki mantigi uretir ve zamanla ayrisir.

    **`deps.py`'deki aktif-only kuralindan BILINCLI OLARAK AYRILIR** (karar
    2026-07-30). Iki soru ayni degildir:

    * `app/core/deps.py:36` **OTURUM ACMA YETKISI** sorar — "bu kullanici su an
      sisteme istek atabilir mi?". Izinli personel atamaz, dolayisiyla orada
      `active` disindaki her durum reddedilir ve reddedilmeye devam eder.
    * Burasi **VERI ATAMASI** sorar — "bu kisi bu santiyenin sefi mi?". Izin
      GECICI bir durumdur; yillik izindeki sef hâlâ o santiyenin sefidir.
      `on_leave` reddedilseydi sef tatildeyken santiye ACILAMAZDI.

    Bu yuzden yalniz gercekten kullanilamaz durum (`passive`) reddedilir; spec
    §7.2'nin "yok veya pasif" ifadesiyle birebir ortusur.
    """
    stmt = select(User).where(User.id == user_id, User.status.in_(_ASSIGNABLE_USER_STATUSES))
    return (await session.execute(stmt)).scalar_one_or_none()
