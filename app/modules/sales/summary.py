"""Satış özetinin SAF toplama çekirdeği — P8 T5 (mockup S55-59, S218-234).

`units/summary.py` ile aynı gerekçe: "34 satışın cirosu ne eder", "hangi taksit
gecikmiş sayılır", "gecikme faizi kaç lira gösterilir" soruları veritabanına,
oturuma ve yetkiye DOKUNMADAN test edilebilsin diye servisten ayrı durur.
Burada `AsyncSession` YOKTUR ve olmamalıdır.

## "Bugün" hep DIŞARIDAN gelir

Hiçbir fonksiyon `date.today()` çağırmaz (`repository.installment_stats` ve
`plan.build_plan` ile aynı kural): gecikme bir TARİH KARŞILAŞTIRMASIDIR ve
fonksiyonun içinde saati okumak testi çalıştığı güne bağımlı kılardı.

## Gecikme faizi (§8 S5) — YALNIZ GÖSTERİM

Mockup satır 223 "Gecikme faizi: ₺4.200" yalnız SONUCU gösterir, oranı vermez;
formül F163'ün tanımından ("aylık gecikme faizi %") türetilir:

    kalan tutar × aylık oran ÷ 100 × (gecikme günü ÷ 30)

Gün ORANTILIDIR: "başlayan ay tam sayılır" seçilseydi 1 günlük gecikme bir aylık
faiz doğururdu ve kullanıcı ödediği gün ile bir gün sonrası arasında sıçrama
görürdü. Sonuç HİÇBİR YERE YAZILMAZ — ne taksit tutarına eklenir, ne yeni satır
açar, ne de bir kolona düşer (§8 S5 onaylı karar). Faiz gerçekten tahakkuk
ettirilecekse doğru yer bir muhasebe/hazine dilimidir.

## Rezervasyon "süresi doldu" (§8 S4) — YALNIZ GÖSTERGE

`reservation_due_date` geçmiş kayıtlar listelenir; OTOMATİK İPTAL YOKTUR ve
zamanlanmış iş altyapısı da yoktur. Kayıt `reservation` KALIR; kullanıcı elle
iptal eder ya da aktifleştirir.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Row

from app.modules.sales.models import SaleInstallment, UnitSaleStatus
from app.modules.sales.plan import quantize2
from app.modules.sales.schemas import (
    AvailableUnitsKpi,
    CollectionKpi,
    ExpiredReservation,
    OverdueKpi,
    ReservedKpi,
    SalesSummaryResponse,
    SoldKpi,
    UpcomingCollection,
    unit_label,
)
from app.modules.units.models import Unit, UnitSalesStatus

__all__ = ["UPCOMING_WINDOW_DAYS", "build_summary", "late_fee_amount"]

_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")
# F163 oranı AYLIKTIR; gün orantısının paydası (modül notundaki formül).
_DAYS_PER_MONTH = Decimal("30")

#: S219 başlığı: "Yaklaşan Tahsilatlar (30 Gün)".
UPCOMING_WINDOW_DAYS = 30

#: S55: "Satılan" = gerçekleşmiş satış. Rezervasyon henüz satış DEĞİLDİR.
_SOLD_STATUSES = (UnitSaleStatus.active, UnitSaleStatus.deed_transferred)


def late_fee_amount(remaining: Decimal, monthly_pct: Decimal | None, days_overdue: int) -> Decimal:
    """S223'ün GÖSTERİM tutarı. Oran boşsa (F163 girilmemişse) faiz UYGULANMAZ."""
    if monthly_pct is None or days_overdue <= 0 or remaining <= _ZERO:
        return _ZERO
    return quantize2(remaining * monthly_pct / _HUNDRED * Decimal(days_overdue) / _DAYS_PER_MONTH)


def _remaining(row: SaleInstallment) -> Decimal:
    return row.amount - row.paid_amount


def _is_settled(row: SaleInstallment) -> bool:
    """TAM ödenmiş satır ne gecikir ne de "yaklaşan tahsilat"tır."""
    return row.paid_amount >= row.amount


def _days_overdue(row: SaleInstallment, today: date) -> int:
    return max((today - row.due_date).days, 0)


def build_summary(
    *,
    project_id: uuid.UUID,
    sale_rows: list[Row],
    installments: list[SaleInstallment],
    units: list[Unit],
    today: date,
) -> SalesSummaryResponse:
    """S55-59 + S218-234'ü tek yanıtta kurar.

    `sale_rows` İPTAL EDİLMEMİŞ satışlardır (`(UnitSale, Unit, Block, Customer)`
    dörtlüsü, `repository.list_sale_rows(exclude_cancelled=True)`); `units` ise
    projenin TÜM üniteleridir — "Boş Ünite" (S57) satış tablosundan sayılamaz,
    çünkü boş ünitenin satış kaydı yoktur.
    """
    sales = [row[0] for row in sale_rows]
    etiketler = {
        sale.id: (unit_label(block.name, unit.unit_no), customer.name)
        for sale, unit, block, customer in sale_rows
    }

    sold = [sale for sale in sales if sale.status in _SOLD_STATUSES]
    reserved = [sale for sale in sales if sale.status is UnitSaleStatus.reservation]
    listed = [unit for unit in units if unit.sales_status is UnitSalesStatus.listed]

    collected = sum((row.paid_amount for row in installments), start=_ZERO)
    contracted = sum((sale.sale_price for sale in sales), start=_ZERO)
    overdue_rows = [row for row in installments if row.due_date < today and not _is_settled(row)]
    faiz_orani = {sale.id: sale.late_fee_monthly_pct for sale in sales}

    ufuk = today + timedelta(days=UPCOMING_WINDOW_DAYS)
    # S220-223'ün ilk satırı "Vadesi 15 gün geçti" der: pencere yalnız ileriye
    # DEĞİL geriye de bakar — gecikmiş tahsilat en yakın tahsilattır.
    upcoming = sorted(
        (row for row in installments if not _is_settled(row) and row.due_date <= ufuk),
        key=lambda row: (row.due_date, row.sequence_no),
    )

    expired = [
        sale
        for sale in reserved
        if sale.reservation_due_date is not None and sale.reservation_due_date < today
    ]

    return SalesSummaryResponse(
        project_id=project_id,
        as_of=today,
        sold=SoldKpi(
            count=len(sold),
            deed_transferred_count=sum(
                1 for sale in sold if sale.status is UnitSaleStatus.deed_transferred
            ),
            amount=quantize2(sum((sale.sale_price for sale in sold), start=_ZERO)),
        ),
        reserved=ReservedKpi(
            count=len(reserved),
            expired_count=len(expired),
            amount=quantize2(sum((sale.sale_price for sale in reserved), start=_ZERO)),
        ),
        available_units=AvailableUnitsKpi(
            count=len(listed),
            # NULL liste fiyatı 0 SAYILIR (`units/summary._sum` kuralı): fiyatı
            # girilmemiş ünite stoktan düşmez, yalnız değere katkı vermez.
            list_price_total=quantize2(
                sum(
                    (unit.list_price for unit in listed if unit.list_price is not None), start=_ZERO
                )
            ),
        ),
        collection=CollectionKpi(
            collected_amount=quantize2(collected),
            contracted_amount=quantize2(contracted),
            collection_pct=(
                quantize2(collected * _HUNDRED / contracted) if contracted > _ZERO else None
            ),
        ),
        overdue=OverdueKpi(
            installment_count=len(overdue_rows),
            amount=quantize2(sum((_remaining(row) for row in overdue_rows), start=_ZERO)),
            late_fee_amount=quantize2(
                sum(
                    (
                        late_fee_amount(
                            _remaining(row), faiz_orani.get(row.sale_id), _days_overdue(row, today)
                        )
                        for row in overdue_rows
                    ),
                    start=_ZERO,
                )
            ),
        ),
        upcoming_collections=[
            UpcomingCollection(
                installment_id=row.id,
                sale_id=row.sale_id,
                unit_label=etiketler[row.sale_id][0],
                customer_name=etiketler[row.sale_id][1],
                sequence_no=row.sequence_no,
                label=row.label,
                due_date=row.due_date,
                amount=row.amount,
                paid_amount=row.paid_amount,
                remaining_amount=_remaining(row),
                is_overdue=row.due_date < today,
                days_overdue=_days_overdue(row, today),
                late_fee_amount=late_fee_amount(
                    _remaining(row), faiz_orani.get(row.sale_id), _days_overdue(row, today)
                ),
            )
            for row in upcoming
        ],
        expired_reservations=[
            ExpiredReservation(
                sale_id=sale.id,
                unit_label=etiketler[sale.id][0],
                customer_name=etiketler[sale.id][1],
                # `expired` süzgeci `None` olmayanları seçti; koşul tip
                # daraltmasıdır, sessiz bir düşüş değildir.
                reservation_due_date=sale.reservation_due_date,  # type: ignore[arg-type]
                days_expired=(today - sale.reservation_due_date).days,  # type: ignore[operator]
                reservation_deposit=sale.reservation_deposit,
            )
            for sale in expired
        ],
    )
