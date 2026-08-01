import uuid

from sqlalchemy import func, select
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


async def get_block_by_code(
    session: AsyncSession,
    project_id: uuid.UUID,
    code: str,
    exclude_block_id: uuid.UUID | None = None,
) -> Block | None:
    """`uq_blocks_project_code` cakismasini `get_block_by_name` ile ayni gerekceyle
    IntegrityError'a DUSMEDEN yakalar (spec §3.2): kullanici alanina ozel Turkce
    mesaj (`DUPLICATE_BLOCK_CODE`) gorur, "Veri butunlugu hatasi" degil."""
    stmt = select(Block).where(Block.project_id == project_id, Block.code == code)
    if exclude_block_id is not None:
        stmt = stmt.where(Block.id != exclude_block_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def project_block_codes(session: AsyncSession, project_id: uuid.UUID) -> set[str]:
    """Projede KULLANILAN blok kodlari — kod uretiminin tek sorgusu (spec §3.2).

    `codes.resolve_block_code` saf kalabilsin diye kume BURADA toplanir. NULL
    kodlar disarida kalir: `None` bir kod degildir ve cakisma kontrolunu
    kirletirdi (canli bloklarin kodu NULL dogar ve NULL kalir — karar 8).
    """
    result = await session.execute(
        select(Block.code).where(Block.project_id == project_id, Block.code.is_not(None))
    )
    return {code for code in result.scalars().all() if code}


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


async def block_has_units(session: AsyncSession, block_id: uuid.UUID) -> bool:
    """Blok DELETE korkulugunun (spec §7.9) tek sorgusu.

    `count(*)` yerine `EXISTS`: kac unite oldugu KULLANILMAZ (hata mesajinda adet
    verilmez — gorunurluk disi bilgi sizdirmaz), 24 satiri saymanin anlami yok.
    """
    result = await session.execute(
        select(select(Unit.id).where(Unit.block_id == block_id).exists())
    )
    return bool(result.scalar_one())


async def existing_unit_nos(
    session: AsyncSession, block_id: uuid.UUID, unit_nos: list[str]
) -> set[str]:
    """Toplu uretimin (spec §7.7) hep-ya-hic on kontrolu — TEK sorgu.

    Uretilecek numaralari tek tek sorgulamak 500 gidis-donus ve yaris penceresi
    demektir; kesisim burada bir kerede alinir ve YAZMADAN ONCE degerlendirilir.
    """
    if not unit_nos:
        return set()
    result = await session.execute(
        select(Unit.unit_no).where(Unit.block_id == block_id, Unit.unit_no.in_(unit_nos))
    )
    return set(result.scalars().all())


async def get_units_by_ids(session: AsyncSession, unit_ids: list[uuid.UUID]) -> list[Unit]:
    """Paylasim ucunun (spec §7.10) TEK sorgusu — `existing_unit_nos` ile ayni gerekce.

    42 uniteyi tek tek `session.get` ile cekmek 42 gidis-donus demektir; dahasi
    dogrulama YAZMADAN ONCE bitmek zorundadir, bu yuzden tum satirlar once TEK
    `SELECT` ile alinir. Proje eslesmesi SERVISTE denetlenir: burada suzmek,
    "baska projenin unitesi" ile "hic olmayan unite" ayrimini repository'ye
    tasirdi ve iki durum icin ayni 404'u uretmek zorlasirdi (IDOR-7/IDOR-8).
    """
    if not unit_ids:
        return []
    result = await session.execute(select(Unit).where(Unit.id.in_(unit_ids)))
    return list(result.scalars().all())


async def max_sort_order(session: AsyncSession, block_id: uuid.UUID) -> int:
    """Blokta kullanilan en buyuk `sort_order`; blok bossa **-1**.

    Toplu uretim, yeni satirlari mevcutlarin ARDINA ekler. Sifirdan baslasaydi
    yari dolu bir blokta eski ve yeni uniteler ic ice gecerdi (`unit_no` metin
    oldugu icin ikincil sira "10 < 2" verir — spec §4.2).
    """
    result = await session.execute(
        select(func.max(Unit.sort_order)).where(Unit.block_id == block_id)
    )
    highest = result.scalar_one()
    return -1 if highest is None else int(highest)
