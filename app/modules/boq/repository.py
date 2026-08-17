import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BoqGroup, BoqItem, BoqItemSectionAllocation


async def list_groups_for_site(session: AsyncSession, site_id: uuid.UUID) -> list[BoqGroup]:
    """Bir santiyenin poz gruplari, sirali (spec §5.1: `sort_order, created_at`).

    Kalemler ayri bir sorgu ATILMAZ: `BoqGroup.items` iliskisi lazy="selectin"
    tanimlidir (T1), bu yuzden erisildiginde SQLAlchemy tum gruplarin kalemlerini
    TEK ek sorguda (IN listesi) toplu ceker — N+1 yoktur.
    """
    result = await session.execute(
        select(BoqGroup)
        .where(BoqGroup.site_id == site_id)
        .order_by(BoqGroup.sort_order, BoqGroup.created_at)
    )
    return list(result.scalars().all())


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> BoqGroup | None:
    return await session.get(BoqGroup, group_id)


async def group_has_items(session: AsyncSession, group_id: uuid.UUID) -> bool:
    """Grupta is kalemi var mi (`boq_items.group_id` -> CASCADE).

    `contracts/repository.py.employer_group_has_items` gerekcesinin aynisi: DB
    CASCADE ile korur ama korkuluksuz birakilirsa kalemler sessizce yok olur.
    `group.items` koleksiyonu YUKLENMEZ — tek EXISTS sorgusu yeter.
    """
    result = await session.execute(
        select(select(BoqItem.id).where(BoqItem.group_id == group_id).exists())
    )
    return bool(result.scalar())


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> BoqItem | None:
    return await session.get(BoqItem, item_id)


async def get_item_by_code(
    session: AsyncSession, site_id: uuid.UUID, code: str, exclude_item_id: uuid.UUID | None = None
) -> BoqItem | None:
    """(site_id, code) çakışmasını IntegrityError'a düşmeden ÖNCE yakalamak içindir

    (spec §5.4, DuplicateError deseni — `projects.service.create_employer` emsali).
    PATCH'te kalemin kendisini hariç tutmak için `exclude_item_id` verilir.
    """
    stmt = select(BoqItem).where(BoqItem.site_id == site_id, BoqItem.code == code)
    if exclude_item_id is not None:
        stmt = stmt.where(BoqItem.id != exclude_item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# --- BOQ-SEC: bolum tahsisleri -------------------------------------------


async def lock_item(session: AsyncSession, item_id: uuid.UUID) -> BoqItem | None:
    """🔴 Poz satirini `SELECT ... FOR UPDATE` ile KILITLER (K3, EŞİK = KİLİT).

    Toplam invarianti (`SUM(tahsis) <= boq_items.quantity`) DB'de zorlanamaz;
    kilitsiz okunursa iki eszamanli istek AYNI toplami gorur ve IKISI DE gecer.
    Kilit poz satirindadir cunku serilestirilmesi gereken sey PAYLASILAN KOTADIR
    — tahsis satirlarini kilitlemek yetmezdi: HENUZ VAR OLMAYAN satirlar
    kilitlenemez (UPSERT-SONRA-KİLİTLE, MU-2 dersi), oysa kotayi asan sey tam da
    yeni eklenen satirlardir. Poz satiri her zaman VARDIR ve `_visible_item`
    tarafindan zaten cozulmustur; kilidin dayanagi bu yuzden saglamdir.

    `populate_existing`: oturumda bayat bir `BoqItem` varsa kilitle birlikte
    TAZELENIR — kilit alip eski `quantity`yi okumak kilidi anlamsiz kilardi.
    """
    result = await session.execute(
        select(BoqItem)
        .where(BoqItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def allocated_total_for_item(session: AsyncSession, item_id: uuid.UUID) -> Decimal:
    """Bir pozun bolumlere dagitilmis toplami. Tahsis YOKSA `0.000` doner.

    `SUM` bos kumede `NULL` dondugu icin sifir DUSUSU ACIKTIR: `None` sizarsa
    karsilastirma `TypeError` atardi, "0 gibi davranir" DEGIL.
    """
    result = await session.execute(
        select(func.coalesce(func.sum(BoqItemSectionAllocation.quantity), 0)).where(
            BoqItemSectionAllocation.boq_item_id == item_id
        )
    )
    return Decimal(result.scalar_one())


async def list_allocations_for_item(
    session: AsyncSession, item_id: uuid.UUID
) -> list[BoqItemSectionAllocation]:
    result = await session.execute(
        select(BoqItemSectionAllocation)
        .where(BoqItemSectionAllocation.boq_item_id == item_id)
        .order_by(BoqItemSectionAllocation.created_at, BoqItemSectionAllocation.id)
    )
    return list(result.scalars().all())


async def allocated_totals_for_site(
    session: AsyncSession, site_id: uuid.UUID
) -> dict[uuid.UUID, Decimal]:
    """Santiyenin TUM pozlari icin tahsis toplamlari — TEK sorgu (N+1 yok).

    Donen sozlukte YALNIZ tahsisi olan pozlar bulunur; cagiran taraf eksigi
    `0`la doldurur (bkz. `service._allocation_view`).
    """
    result = await session.execute(
        select(
            BoqItemSectionAllocation.boq_item_id,
            func.sum(BoqItemSectionAllocation.quantity),
        )
        .join(BoqItem, BoqItem.id == BoqItemSectionAllocation.boq_item_id)
        .where(BoqItem.site_id == site_id)
        .group_by(BoqItemSectionAllocation.boq_item_id)
    )
    return {row[0]: Decimal(row[1]) for row in result.all()}


async def section_allocations_for_site(
    session: AsyncSession, site_id: uuid.UUID, section_id: uuid.UUID
) -> dict[uuid.UUID, Decimal]:
    """BIR bolume tahsis edilmis miktarlar, poz kimligine gore — TEK sorgu.

    `site_id` kosulu GEREKSIZ GORUNUR (bolum zaten santiyeye ait dogrulanir) ama
    kapsam kosulunun tek yerde durmasi, ileride bolum cozumlemesi degisirse
    baska santiyenin satirlarinin sizmasini yapisal olarak engeller.
    """
    result = await session.execute(
        select(BoqItemSectionAllocation.boq_item_id, BoqItemSectionAllocation.quantity)
        .join(BoqItem, BoqItem.id == BoqItemSectionAllocation.boq_item_id)
        .where(BoqItem.site_id == site_id, BoqItemSectionAllocation.section_id == section_id)
    )
    return {row[0]: Decimal(row[1]) for row in result.all()}
