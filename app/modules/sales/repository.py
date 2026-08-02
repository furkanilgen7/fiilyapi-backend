"""Ünite satışı veri erişimi (P8 spec §4).

Liste ucu satırı tek sorguda ÜNİTE + BLOK + ALICI ile birlikte çeker: S150-151
kolonları ("A · Daire 12", alıcı adı + TCKN) bu üç tablodan beslenir ve satır
başına ek SELECT atmak N+1 demek olurdu.

Tahsilat türevleri (S153-155) AYRI ve TEK bir toplama sorgusundan gelir; satış
kaydında `paid_amount`/`remaining` KOLONU AÇILMAZ (T1 model notu: her ödemede
senkron kayması demek olurdu).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.sales.models import SaleInstallment, UnitSale, UnitSaleStatus
from app.modules.units.models import Block, Unit

_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class InstallmentStats:
    """Bir satışın plan satırlarından türeyen sayaçlar (S153-155, S180).

    `installment_total`/`installment_paid_count` PEŞİNATI SAYMAZ (`sequence_no=0`):
    S155 "12 taksit · 8/12" etiketi taksitleri sayar, peşinat ayrı bir satırdır
    (F117). `overdue_count` ise TÜM satırları kapsar — vadesi geçmiş peşinat da
    gecikmedir (S180 "⚠ 2 taksit gecikmiş" uyarısının kaynağı).
    """

    paid_amount: Decimal = _ZERO
    installment_total: int = 0
    installment_paid_count: int = 0
    overdue_count: int = 0


def _sale_rows_stmt():
    """`UnitSale` + `Unit` + `Block` + `Customer` — liste ve detayın ORTAK gövdesi."""
    return (
        select(UnitSale, Unit, Block, Customer)
        .join(Unit, UnitSale.unit_id == Unit.id)
        .join(Block, Unit.block_id == Block.id)
        .join(Customer, UnitSale.customer_id == Customer.id)
    )


async def get_sale(session: AsyncSession, sale_id: uuid.UUID) -> UnitSale | None:
    return await session.get(UnitSale, sale_id)


async def get_sale_locked(session: AsyncSession, sale_id: uuid.UUID) -> UnitSale | None:
    """Durum geçişleri (T5) için `SELECT … FOR UPDATE`.

    `ORDER BY` YOK: kilit kümesi TEK satırdır (birincil anahtar eşitliği);
    deadlock riski yalnız çok satırlı kilitlerde doğar (`lock_installments`).

    `populate_existing`: satır session'da zaten yüklüyse kimlik haritasından
    ESKİ durumla dönerdi ve kilit ALTINDA yeniden okuma amacı boşa çıkardı —
    iki eşzamanlı `activate` denemesinde ikincisi birincinin yazdığı durumu
    GÖRMEK ZORUNDADIR.
    """
    stmt = (
        select(UnitSale)
        .where(UnitSale.id == sale_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_open_sale_for_unit(
    session: AsyncSession, unit_id: uuid.UUID, exclude_sale_id: uuid.UUID | None = None
) -> UnitSale | None:
    """`uq_unit_sales_open_unit` kısmi indeksinin SORGU ikizi: `cancelled` HARİÇ.

    İki koşul (indeks ve bu sorgu) BİRLİKTE değişmelidir; ayrışırlarsa servis
    "boş" görüp yazmayı dener ve kullanıcı anlamsız bir bütünlük 409'u alır.
    """
    stmt = select(UnitSale).where(
        UnitSale.unit_id == unit_id, UnitSale.status != UnitSaleStatus.cancelled
    )
    if exclude_sale_id is not None:
        stmt = stmt.where(UnitSale.id != exclude_sale_id)
    return (await session.execute(stmt)).scalars().first()


async def get_sale_row(session: AsyncSession, sale_id: uuid.UUID) -> Row | None:
    stmt = _sale_rows_stmt().where(UnitSale.id == sale_id)
    return (await session.execute(stmt)).first()


async def list_sale_rows(
    session: AsyncSession, project_id: uuid.UUID, *, exclude_cancelled: bool = False
) -> list[Row]:
    """Sıralama DB'de: blok adı, sonra ünite sıra numarası (S158-200 tablo düzeni).

    `exclude_cancelled` YALNIZ özet (T5) içindir: liste ucu iptalleri GÖSTERİR
    (kullanıcı neyin iptal edildiğini görmelidir), KPI'lar ise göstermez —
    iptal edilmiş bir satış ne cirodur ne alacaktır.
    """
    stmt = _sale_rows_stmt().where(UnitSale.project_id == project_id)
    if exclude_cancelled:
        stmt = stmt.where(UnitSale.status != UnitSaleStatus.cancelled)
    return list(
        (
            await session.execute(
                stmt.order_by(Block.sort_order, Block.name, Unit.sort_order, Unit.unit_no)
            )
        ).all()
    )


async def list_installments_for_sales(
    session: AsyncSession, sale_ids: list[uuid.UUID]
) -> list[SaleInstallment]:
    """Özetin (T5) TÜM plan satırlarını TEK sorguda okur — satış başına SELECT yok.

    `installment_stats`ten farkı: orası satış başına TOPLAM döner, burası ham
    SATIRLARI döner çünkü "yaklaşan tahsilatlar" (S218-234) listesi tek tek
    taksitleri gösterir ve toplamdan geri üretilemez.
    """
    if not sale_ids:
        return []
    stmt = (
        select(SaleInstallment)
        .where(SaleInstallment.sale_id.in_(sale_ids))
        .order_by(SaleInstallment.due_date, SaleInstallment.sequence_no)
    )
    return list((await session.execute(stmt)).scalars().all())


async def installment_stats(
    session: AsyncSession, sale_ids: list[uuid.UUID], today: date
) -> dict[uuid.UUID, InstallmentStats]:
    """Tüm satışların türevlerini TEK `GROUP BY` sorgusunda toplar.

    `today` DIŞARIDAN verilir: "gecikmiş" bir TARİH KARŞILAŞTIRMASIDIR ve
    fonksiyonun içinde `date.today()` çağırmak testi saate bağımlı kılardı.
    """
    if not sale_ids:
        return {}
    odenmis = SaleInstallment.paid_amount >= SaleInstallment.amount
    stmt = (
        select(
            SaleInstallment.sale_id,
            func.coalesce(func.sum(SaleInstallment.paid_amount), _ZERO),
            func.count().filter(SaleInstallment.sequence_no > 0),
            func.count().filter(and_(SaleInstallment.sequence_no > 0, odenmis)),
            func.count().filter(and_(SaleInstallment.due_date < today, ~odenmis)),
        )
        .where(SaleInstallment.sale_id.in_(sale_ids))
        .group_by(SaleInstallment.sale_id)
    )
    return {
        sale_id: InstallmentStats(
            paid_amount=Decimal(paid),
            installment_total=total,
            installment_paid_count=paid_count,
            overdue_count=overdue,
        )
        for sale_id, paid, total, paid_count, overdue in (await session.execute(stmt)).all()
    }


# --- Ödeme planı (T4) ---


async def get_installment_locked(
    session: AsyncSession, installment_id: uuid.UUID
) -> SaleInstallment | None:
    """TEK taksit satırını `SELECT … FOR UPDATE` ile okur (tahsilat serileştirme).

    Kilit, doğrulamayı besleyen okumanın KENDİSİDİR: ayrı bir kilitsiz `SELECT`
    ile okunup sonra kilitlenseydi TOCTOU penceresi açık kalırdı
    (`contracts/repository.lock_employer_items` dersi).

    `ORDER BY` YOK çünkü kilit kümesi TEK satırdır (birincil anahtar eşitliği);
    deadlock riski yalnız çok satırlı kilit kümelerinde doğar — orada
    (`lock_installments`) sıra ZORUNLUDUR.
    """
    stmt = select(SaleInstallment).where(SaleInstallment.id == installment_id).with_for_update()
    return (await session.execute(stmt)).scalars().first()


async def lock_installments(session: AsyncSession, sale_id: uuid.UUID) -> None:
    """Bir satışın TÜM plan satırlarını `SELECT … FOR UPDATE` ile kilitler.

    `PUT installments` yazmadan ÖNCE, doğrulamayı besleyen okumalardan da ÖNCE
    çağrılmak ZORUNDA: aksi hâlde eşzamanlı bir `pay` isteği, plan düzenlemesi
    tahsilat kontrolünü yaptıktan sonra araya girer ve tutarı düşürülen satır
    aşırı ödenmiş hâlde kalırdı.

    `ORDER BY sequence_no` OPSİYONEL DEĞİLDİR (TB1 dersi): kilit kümesi çok
    satırlı olduğu için sıra tutarsız olursa iki eşzamanlı istek karşılıklı
    kilitlenir (A satır-1'i, B satır-2'yi tutarken ikisi de diğerini bekler).
    `sequence_no` bu tablo için (sale_id ile birlikte) BENZERSİZDİR, dolayısıyla
    küresel ve deterministik bir sıra verir.
    """
    stmt = (
        select(SaleInstallment.id)
        .where(SaleInstallment.sale_id == sale_id)
        .order_by(SaleInstallment.sequence_no)
        .with_for_update()
    )
    await session.execute(stmt)


async def list_installments(session: AsyncSession, sale_id: uuid.UUID) -> list[SaleInstallment]:
    """Plan satırları, ekrandaki sırayla (peşinat önce — `sequence_no=0`)."""
    stmt = (
        select(SaleInstallment)
        .where(SaleInstallment.sale_id == sale_id)
        .order_by(SaleInstallment.sequence_no)
    )
    return list((await session.execute(stmt)).scalars().all())
