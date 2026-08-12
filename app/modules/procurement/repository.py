"""Satinalma veri erisimi (T2) — yalniz SQL, yetki/kapsam KARARI yok.

Kapsam karari (`visible_projects`) bu katmanda DEGIL `service.py`dedir
(`inventory/repository.py` deseninin kardesi); buraya yalniz cozulmus proje
kimlikleri gelir.

Liste ve sayim AYNI suzgec yardimcisini paylasir (`personnel` deseni): kopya
acilsaydi `total` ile gosterilen tablo zamanla ayrisirdi.

## N+1 YASAKTIR — uc turev de TOPLU sorgudur

* "Bu Yil Toplam Siparis" → tedarikci basina degil, `GROUP BY supplier_id` ile
  TEK alt sorgu (`supplier_order_totals`).
* Talebin tahmini toplami + kalem sayisi → talep basina degil,
  `GROUP BY request_id` ile TEK alt sorgu (`request_totals`).
* Kalemlerin "Mevcut Stok"u → kalem basina degil, sayfadaki TUM kart
  kimlikleri tek `IN` ile (`current_stock_by_item`).

## ST'ye TEK YONLU import

Bu modul `inventory`den `balance.legs` ve `StockItem`i okur; `inventory` ise
`procurement`i **ASLA** import etmez. Ters yon acilsaydi P10'un `cost_cards`
import cemberi tekrarlanirdi (T1 modul docstring'i).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Row, Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from app.modules.inventory import balance as stock_balance
from app.modules.inventory import repository as inventory_repository
from app.modules.inventory.models import StockItem
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchasePriority,
    PurchaseRequest,
    PurchaseRequestLine,
    PurchaseRequestStatus,
    Supplier,
)


def _like_escape(deger: str) -> str:
    """LIKE joker karakterlerini KACIRIR (`inventory.repository` deseni).

    Kacirilmazsa arama kutusuna `%` yazan kullanici TUM katalogu, `_` yazan ise
    beklemedigi satirlari gorur. Kacis karakterinin kendisi ONCE kacirilir.
    """
    return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- Tedarikci (TED) ---


def _supplier_filtered(
    stmt: Select, *, q: str | None, category: str | None, is_active: bool | None
) -> Select:
    """TED'in uc suzgeci: arama kutusu · kategori · aktiflik.

    `q` AD ve KATEGORI uzerinde kismi arar: TED karti ikisini ust uste basar,
    tek alanda aramak kullaniciyi "Demirsan yok" sanisina dusururdu.

    `is_active` GONDERILMEZSE suzgec uygulanmaz — pasif tedarikci sessizce
    gizlenmez; ekran hangi kumeyi istedigini acikca soyler (`personnel` karari).
    """
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            Supplier.name.ilike(desen, escape="\\") | Supplier.category.ilike(desen, escape="\\")
        )
    if category is not None:
        stmt = stmt.where(Supplier.category == category)
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    return stmt


def supplier_order_totals(project_ids: list[uuid.UUID], year: int) -> Subquery:
    """ "Bu Yil Toplam Siparis" (TED 52) — tedarikci basina TEK GRUPLU alt sorgu.

    **YIL OLCUTU `created_at`tir:** `purchase_orders`ta ayri bir siparis TARIHI
    kolonu YOKTUR (spec §2) ve uydurulmaz. Sinirlar `>= 1 Ocak` / `< 1 Ocak
    (yil+1)` seklinde YARI ACIKTIR: `EXTRACT(year …)` yazilsaydi kolondaki
    indeks kullanilamazdi.

    **KAPSAM:** yalnizca GORUNEN projelerin siparisleri. Katalog globaldir ama
    PARA degildir — suzgec olmasaydi satinalma sorumlusu, erisimi olmayan bir
    projenin harcama hacmini tedarikci kartindan okuyabilirdi.
    """
    baslangic = datetime(year, 1, 1, tzinfo=UTC)
    bitis = datetime(year + 1, 1, 1, tzinfo=UTC)
    return (
        select(
            PurchaseOrder.supplier_id.label("supplier_id"),
            func.sum(PurchaseOrder.total_amount).label("orders_total"),
            func.count().label("orders_count"),
        )
        .where(
            PurchaseOrder.project_id.in_(project_ids),
            PurchaseOrder.created_at >= baslangic,
            PurchaseOrder.created_at < bitis,
        )
        .group_by(PurchaseOrder.supplier_id)
        .subquery()
    )


def _supplier_with_totals(base: Select, totals: Subquery) -> Select:
    """`OUTER JOIN`: hic siparis almamis tedarikci listede KALIR ve turevi
    `COALESCE` ile sifirlanir — `INNER JOIN` yeni acilan tedarikciyi gizlerdi."""
    return base.outerjoin(totals, totals.c.supplier_id == Supplier.id)


async def list_suppliers(
    session: AsyncSession,
    totals: Subquery,
    *,
    q: str | None,
    category: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> list[Row]:
    """Siralama DB'de (`ORDER BY name, id`) — sayfalama deterministik olsun.

    Ikinci olcut olmasaydi ayni adli iki tedarikci her istekte farkli sirada
    gelir ve sayfalar arasinda satir kaybolup tekrarlanabilirdi.
    """
    stmt = _supplier_with_totals(
        select(
            Supplier,
            func.coalesce(totals.c.orders_total, literal(Decimal("0"))).label("orders_total"),
            func.coalesce(totals.c.orders_count, literal(0)).label("orders_count"),
        ),
        totals,
    )
    stmt = _supplier_filtered(stmt, q=q, category=category, is_active=is_active)
    stmt = stmt.order_by(Supplier.name, Supplier.id).limit(limit).offset(offset)
    return list((await session.execute(stmt)).all())


async def count_suppliers(
    session: AsyncSession, *, q: str | None, category: str | None, is_active: bool | None
) -> int:
    """Sayim liste ile AYNI suzgecten gecer; siparis alt sorgusuna GIREKMEZ
    (`OUTER JOIN` satir sayisini degistirmez, gereksiz is yapilmaz)."""
    stmt = _supplier_filtered(
        select(func.count()).select_from(Supplier), q=q, category=category, is_active=is_active
    )
    return (await session.execute(stmt)).scalar_one()


async def get_supplier(session: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    return await session.get(Supplier, supplier_id)


async def get_supplier_with_totals(
    session: AsyncSession, totals: Subquery, supplier_id: uuid.UUID
) -> Row | None:
    """Detay ucu liste ile AYNI turetmeyi kullanir — kart iki ekranda ayni
    tutari gostersin diye ikinci bir formul YAZILMAZ."""
    stmt = _supplier_with_totals(
        select(
            Supplier,
            func.coalesce(totals.c.orders_total, literal(Decimal("0"))).label("orders_total"),
            func.coalesce(totals.c.orders_count, literal(0)).label("orders_count"),
        ),
        totals,
    ).where(Supplier.id == supplier_id)
    return (await session.execute(stmt)).one_or_none()


# --- Talep (FST + SAT) ---


def _request_filtered(
    stmt: Select,
    project_ids: list[uuid.UUID],
    *,
    status: PurchaseRequestStatus | None,
    project_id: uuid.UUID | None,
    priority: PurchasePriority | None,
    q: str | None,
) -> Select:
    """SAT filtre cubugu + KAPSAM. Suzgecler AND'lidir.

    Kapsam suzgeci (`project_id IN gorunenler`) HER ZAMAN uygulanir ve
    kullanicinin verdigi `project_id` onun YERINE degil USTUNE gecer: gorunmeyen
    bir proje kimligi verildiginde kesisim BOSTUR, yani sizinti olmaz.

    `q` TALEP NUMARASI ve GEREKCE uzerinde kismi arar — SAT tablosu ikisini de
    gosterir.
    """
    stmt = stmt.where(PurchaseRequest.project_id.in_(project_ids))
    if status is not None:
        stmt = stmt.where(PurchaseRequest.status == status)
    if project_id is not None:
        stmt = stmt.where(PurchaseRequest.project_id == project_id)
    if priority is not None:
        stmt = stmt.where(PurchaseRequest.priority == priority)
    if q:
        desen = f"%{_like_escape(q)}%"
        stmt = stmt.where(
            PurchaseRequest.request_no.ilike(desen, escape="\\")
            | PurchaseRequest.justification.ilike(desen, escape="\\")
        )
    return stmt


def request_totals() -> Subquery:
    """Talep basina tahmini toplam + kalem sayisi — TEK GRUPLU alt sorgu.

    Fiyatsiz kalem toplama GIRMEZ (`SUM` NULL'lari atlar) ve bu bilinclidir:
    sessizce 0 sayilsaydi "tahmini toplam neden dusuk" sorusu cevapsiz kalirdi.
    Kalem SAYISI ise fiyattan bagimsiz sayilir.
    """
    return (
        select(
            PurchaseRequestLine.request_id.label("request_id"),
            func.sum(PurchaseRequestLine.quantity * PurchaseRequestLine.estimated_unit_price).label(
                "estimated_total"
            ),
            func.count().label("line_count"),
        )
        .group_by(PurchaseRequestLine.request_id)
        .subquery()
    )


async def list_requests(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    totals: Subquery,
    *,
    status: PurchaseRequestStatus | None,
    project_id: uuid.UUID | None,
    priority: PurchasePriority | None,
    q: str | None,
    limit: int,
    offset: int,
) -> list[Row]:
    """Siralama en yeniden eskiye; son olcut TALEP NUMARASI.

    ⚠️ Numara, `id` yerine bilincli olarak secildi: `created_at`in varsayilani
    `now()`dur ve Postgres'te `now()` ISLEM BOYU SABITTIR — ayni transaction'da
    acilan iki talep BIREBIR AYNI damgayi alir. Son olcut rastgele bir UUID
    olsaydi siralama o eslikte KARARSIZ kalir, sayfalar arasinda satir
    kaybolup tekrarlanabilirdi (fiilen goruldu: ayni test iki kosuda iki farkli
    sira verdi). `request_no` hem TEKIL hem de artan bir dizidir.
    """
    stmt = select(
        PurchaseRequest,
        func.coalesce(totals.c.estimated_total, literal(Decimal("0"))).label("estimated_total"),
        func.coalesce(totals.c.line_count, literal(0)).label("line_count"),
    ).outerjoin(totals, totals.c.request_id == PurchaseRequest.id)
    stmt = _request_filtered(
        stmt, project_ids, status=status, project_id=project_id, priority=priority, q=q
    )
    stmt = (
        stmt.order_by(
            PurchaseRequest.request_date.desc(),
            PurchaseRequest.created_at.desc(),
            PurchaseRequest.request_no.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).all())


async def count_requests(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
    *,
    status: PurchaseRequestStatus | None,
    project_id: uuid.UUID | None,
    priority: PurchasePriority | None,
    q: str | None,
) -> int:
    stmt = _request_filtered(
        select(func.count()).select_from(PurchaseRequest),
        project_ids,
        status=status,
        project_id=project_id,
        priority=priority,
        q=q,
    )
    return (await session.execute(stmt)).scalar_one()


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> PurchaseRequest | None:
    return await session.get(PurchaseRequest, request_id)


async def list_request_lines(
    session: AsyncSession, request_id: uuid.UUID
) -> list[tuple[PurchaseRequestLine, StockItem | None]]:
    """Kalemler + BAGLI KART tek sorguda (`OUTER JOIN`) gelir.

    Kart adi/kodu/birimi icin kalem basina `session.get(StockItem, …)`
    kosulsaydi 40 kalemlik bir talep 40 sorgu acardi. `OUTER JOIN` katalogsuz
    kalemleri de tasir (kart tarafi `None` gelir).

    Siralama kimlige gore SABITTIR: FST kalem tablosu satirlarini her aciliste
    AYNI sirada gostermelidir.

    ⚠️ **BILINEN SINIR — kullanicinin girdigi SIRA korunmaz.** `id` bir UUID4'tur,
    yani siralama deterministik ama ekleme sirasindan BAGIMSIZDIR: kullanicinin
    once yazdigi kalem tabloda ikinci gorunebilir. Duzeltmek bir `sort_order`
    kolonu (yani migration) ister; T1 semasinda yoktur ve T2 sema
    DEGISTIRMEZ. Emsal de bu yondedir: ST'nin `stock_entry_lines`i satirlarini
    hic siralamaz (`selectinload`, keyfi sira) — buradaki durum ondan DAHA
    iyidir cunku en azindan kararlidir. SA T3/T5'e devredilen aday borctur.
    """
    stmt = (
        select(PurchaseRequestLine, StockItem)
        .outerjoin(StockItem, StockItem.id == PurchaseRequestLine.stock_item_id)
        .where(PurchaseRequestLine.request_id == request_id)
        .order_by(PurchaseRequestLine.id)
    )
    return [(satir, kart) for satir, kart in (await session.execute(stmt)).all()]


async def load_request_lines(
    session: AsyncSession, request_id: uuid.UUID
) -> list[PurchaseRequestLine]:
    """Yalniz satir nesneleri (yazma yolunun REPLACE adimi icindir)."""
    stmt = (
        select(PurchaseRequestLine)
        .where(PurchaseRequestLine.request_id == request_id)
        .order_by(PurchaseRequestLine.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def existing_stock_item_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Kalemlerdeki kartlarin TAMAMI TEK sorguda dogrulanir — ve YAZIMDAN ONCE.

    Atomikligin tasiyicisi budur: kart basina `session.get` ile ilerlenseydi
    hem N sorgu acilir hem de ilk satirlar yazildiktan sonra hata cikardi
    (ST `_assert_items_exist` deseni).
    """
    if not item_ids:
        return set()
    stmt = select(StockItem.id).where(StockItem.id.in_(item_ids))
    return set((await session.execute(stmt)).scalars().all())


async def current_stock_by_item(
    session: AsyncSession, project_ids: list[uuid.UUID], item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """ "Mevcut Stok" (FST 75) — TEK toplu sorgu, kalem basina sorgu ACILMAZ.

    Bakiye formulu KOPYALANMAZ: ST'nin kanonik kaynagi (`inventory.balance.legs`,
    CIFT BACAK dahil) cagrilir. Ikinci bir formul yazilsaydi FST'deki "Mevcut
    Stok" ile stok ekranindaki bakiye ayni kalem icin farkli sayi gosterirdi.

    **KAPSAM:** ST genel ozetiyle AYNI — gorunen TUM depolar (merkez dahil,
    spec ST §7 S2b). Talebin santiyesine daraltilmadi cunku santiye ISTEGE
    BAGLIDIR (FST 57) ve satinalma karari sirket genelindeki stogu bilerek
    verilir: merkez ambardaki 40 ton demir icin yeni talep acilmamalidir.
    """
    if not item_ids:
        return {}
    warehouse_ids = inventory_repository.visible_warehouse_ids(project_ids)
    bacaklar = stock_balance.legs(warehouse_ids)
    stmt = (
        select(bacaklar.c.item_id, func.sum(bacaklar.c.quantity).label("balance"))
        .where(bacaklar.c.item_id.in_(item_ids))
        .group_by(bacaklar.c.item_id)
    )
    return {row.item_id: row.balance for row in (await session.execute(stmt)).all()}


__all__ = [
    "count_requests",
    "count_suppliers",
    "current_stock_by_item",
    "existing_stock_item_ids",
    "get_request",
    "get_supplier",
    "get_supplier_with_totals",
    "list_request_lines",
    "list_requests",
    "list_suppliers",
    "load_request_lines",
    "request_totals",
    "supplier_order_totals",
]

# NOT: `selectinload` bu modulde HIC kullanilmaz cunku `PurchaseRequest`in kalem
# ILISKISI T1'de tanimlanmadi (async oturumda tembel iliskiye dokunmak
# `MissingGreenlet` = 500 uretir — P11 dersi). Kalemler her zaman ACIK sorguyla
# okunur; sonraki okuyucu buraya `relationship` eklemesin.
