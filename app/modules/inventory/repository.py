"""Stok çekirdeği veri erişimi (T2) — yalnız SQL, yetki/kapsam KARARI yok.

Kapsam kararı (`visible_projects`) bu katmanda DEĞİL `service.py`dedir
(`documents/repository.py` deseninin kardeşi); buraya yalnız çözülmüş proje
kimlikleri gelir.

Liste ve sayım AYNI süzgeç yardımcısını paylaşır (`personnel` deseni): kopya
açılsaydı `total` ile gösterilen tablo zamanla ayrışırdı.
"""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import StockCategory, StockEntry, StockItem, Warehouse
from app.modules.sites.models import Site


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KAÇIRIR (`documents.repository` deseni).

    Kaçırılmazsa arama kutusuna `%` yazan kullanıcı TÜM kataloğu, `_` yazan ise
    beklemediği satırları görür — serbest metin aradığını sanarak. Kaçış
    karakterinin kendisi ÖNCE kaçırılır, yoksa sonraki değişimler onu ikinci kez
    bozardı.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- Malzeme kartı (katalog) ---


def _item_filtered(
    stmt: Select, category: StockCategory | None, q: str | None, is_active: bool | None
) -> Select:
    """E3'ün üç süzgeci: kategori select'i (99) · arama kutusu · aktiflik.

    Durum süzgeci (Kritik/Normal/Fazla) BURADA YOKTUR: durum bakiyeden TÜREVDİR
    (spec §3) ve hareket toplamı gerektirir — T3'ün işidir.
    """
    if category is not None:
        stmt = stmt.where(StockItem.category == category)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            StockItem.code.ilike(desen, escape="\\") | StockItem.name.ilike(desen, escape="\\")
        )
    if is_active is not None:
        stmt = stmt.where(StockItem.is_active.is_(is_active))
    return stmt


async def list_stock_items(
    session: AsyncSession,
    *,
    category: StockCategory | None,
    q: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> list[StockItem]:
    """Sıralama DB'de (`ORDER BY name, id`) — sayfalama deterministik olsun.

    İkinci ölçüt olmasaydı aynı adlı iki kart her istekte farklı sırada gelir ve
    sayfalar arasında satır kaybolup tekrarlanabilirdi.
    """
    stmt = _item_filtered(select(StockItem), category, q, is_active)
    stmt = stmt.order_by(StockItem.name, StockItem.id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_stock_items(
    session: AsyncSession,
    *,
    category: StockCategory | None,
    q: str | None,
    is_active: bool | None,
) -> int:
    stmt = _item_filtered(select(func.count()).select_from(StockItem), category, q, is_active)
    return (await session.execute(stmt)).scalar_one()


async def get_stock_item(session: AsyncSession, item_id: uuid.UUID) -> StockItem | None:
    return await session.get(StockItem, item_id)


async def find_stock_item_by_code(
    session: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> StockItem | None:
    """`exclude_id` PATCH içindir: kaydın KENDİSİ çakışma sayılmaz, aksi hâlde
    aynı kodla ikinci kez "Kaydet" basmak 409 verirdi."""
    stmt = select(StockItem).where(StockItem.code == code)
    if exclude_id is not None:
        stmt = stmt.where(StockItem.id != exclude_id)
    return (await session.execute(stmt.limit(1))).scalars().first()


# --- Depo ---


def _warehouse_scope(stmt: Select, project_ids: list[uuid.UUID]) -> Select:
    """Görünürlük süzgeci — spec §7 **S2b**.

    İKİ dallıdır ve dallar OR'ludur:
      * `site_id IS NULL` (MERKEZ depo) → kapsam süzgecine TABİ DEĞİL;
      * şantiyeli depo → şantiyesinin projesi görünen projeler içinde olmalı.

    Merkez dalı OR'dan çıkarılsaydı şirketin ana ambarı hiç kimseye görünmezdi
    (hiçbir projeye bağlı değildir). Şantiye dalı çıkarılsaydı başka projenin
    deposu sızardı.

    Alt sorgu tek seferliktir — depo başına sorgu (N+1) AÇILMAZ.
    """
    gorunen_santiyeler = select(Site.id).where(Site.project_id.in_(project_ids))
    return stmt.where(Warehouse.site_id.is_(None) | Warehouse.site_id.in_(gorunen_santiyeler))


async def list_warehouses(
    session: AsyncSession, project_ids: list[uuid.UUID], *, limit: int, offset: int
) -> list[Warehouse]:
    stmt = _warehouse_scope(select(Warehouse), project_ids)
    stmt = stmt.order_by(Warehouse.name, Warehouse.id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


async def count_warehouses(session: AsyncSession, project_ids: list[uuid.UUID]) -> int:
    """Sayım liste ile AYNI kapsam süzgecinden geçer: `total` görünen kümeyi
    sayar, tablonun tamamını değil."""
    stmt = _warehouse_scope(select(func.count()).select_from(Warehouse), project_ids)
    return (await session.execute(stmt)).scalar_one()


async def get_warehouse(session: AsyncSession, warehouse_id: uuid.UUID) -> Warehouse | None:
    return await session.get(Warehouse, warehouse_id)


async def find_warehouse_by_name(
    session: AsyncSession,
    site_id: uuid.UUID | None,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> Warehouse | None:
    """UQ ile BİREBİR aynı ikili üzerinden mevcut-ad kontrolü.

    NULL karşılaştırması `IS NULL` ile yazılır: `== None` SQL'de `= NULL`
    üretseydi MERKEZ depolarda kontrol HİÇBİR ŞEY bulamaz ve DB kısıtının zaten
    çalışmadığı tam o dalda tekillik tamamen kaybolurdu (`documents` dersi).
    """
    stmt = select(Warehouse).where(
        Warehouse.site_id.is_(None) if site_id is None else Warehouse.site_id == site_id,
        Warehouse.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(Warehouse.id != exclude_id)
    return (await session.execute(stmt.limit(1))).scalars().first()


async def lock_warehouse_for_update(session: AsyncSession, warehouse_id: uuid.UUID) -> None:
    """Silme yolunun DIŞLAYICI kilidi (`documents.lock_folder_for_update` deseni).

    "Hareketi var mı?" kontrolü ile `DELETE` arasına başka bir isteğin hareket
    yazmasını engeller. ⚠️ T3 NOTU: hareket yazan uç bu satırı `FOR SHARE` ile
    kilitlemelidir; yoksa yarış hareket ayağında açık kalır ve DB'nin RESTRICT'i
    kullanıcıya 500 olarak döner.
    """
    await session.execute(
        select(Warehouse.id).where(Warehouse.id == warehouse_id).with_for_update()
    )


async def warehouse_has_entries(session: AsyncSession, warehouse_id: uuid.UUID) -> bool:
    """HEDEF ve KAYNAK bacakların İKİSİ de sayılır (`guards` gerekçesi)."""
    stmt = (
        select(func.count())
        .select_from(StockEntry)
        .where(
            (StockEntry.warehouse_id == warehouse_id)
            | (StockEntry.source_warehouse_id == warehouse_id)
        )
    )
    return bool((await session.execute(stmt)).scalar_one())
