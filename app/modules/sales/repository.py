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


async def list_sale_rows(session: AsyncSession, project_id: uuid.UUID) -> list[Row]:
    """Sıralama DB'de: blok adı, sonra ünite sıra numarası (S158-200 tablo düzeni)."""
    stmt = (
        _sale_rows_stmt()
        .where(UnitSale.project_id == project_id)
        .order_by(Block.sort_order, Block.name, Unit.sort_order, Unit.unit_no)
    )
    return list((await session.execute(stmt)).all())


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
