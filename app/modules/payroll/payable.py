"""Dönemin ÖDENEBİLİR net toplamı — aynı kararın SQL tarafı (TB8).

`summary.build_period_summary` bu toplamı PYTHON'da üretir (`net_total`) ve
satır listesini bellekte ister. Hazine kartının `upcoming-payments` ucu ise
pencereye giren dönemleri TEK sorguda toplamak zorundadır: dönem başına satır
çekip Python'da toplamak `test_N_ARTI_1_YAPMAZ`ın ölçtüğü N+1'dir.

Bu modül o toplamın SQL hâlini taşır ve **`payroll` içinde yaşar**: hangi
satırın ödenecek paraya girdiği bordronun kararıdır, hazinenin değil.
`treasury/upcoming.py` içine yazılsaydı ikinci bir gerçek kaynak doğar ve
`_progress_payment_rows`un docstring'indeki kural ("Hesabın kendisi burada
İKİNCİ KEZ YAZILMAZ") bordro için çiğnenirdi.

## Küme İTHAL EDİLİR, yeniden yazılmaz

`PAYABLE_LINE_STATUSES` `summary.py`den gelir. Buraya `{pending, approved,
paid}` diye elle yazılsaydı iki liste zamanla ayrışır ve bordro ekranı ile
hazine kartı aynı dönem için farklı para basardı — kod tabanının en çok
korktuğu "iki gerçek kaynak" hâli. `summary.py`ye de EKLENMEZ: o modül SAFTIR
(docstring'i "DB'ye dokunmaz" der) ve bir `select` üreteci onu bozardı.

## `net_amount IS NOT NULL`

`summary`nin `line.net_amount is not None` şartının SQL karşılığıdır ve
gereklidir: `sum()` NULL'ı zaten atlar ama `pending` bir satırın neti NULL
olabilir (S4 kapısı satır DURUMUNU değil brütü ölçer) ve şart yazılmazsa küme
ile toplam farklı satırlar üzerinde tanımlanmış olurdu.

## Bu modülün ÜRETMEDİĞİ karar

Pencere (vade aralığı), dönem DURUMU (`approved`) ve "toplam > 0 olsun"
süzgeci burada YOKTUR: üçü de hazine kartının kuralıdır (faturadaki
`due_date` penceresi + `kalan > 0` ile birebir aynı yerde durur). Burada olan
yalnız HANGİ SATIRIN sayıldığıdır.
"""

from sqlalchemy import Subquery, func, literal, select

from app.modules.payroll.models import PayrollLine
from app.modules.payroll.summary import PAYABLE_LINE_STATUSES, ZERO_MONEY

__all__ = [
    "PAYABLE_STATUS_ORDER",
    "payable_net_sum",
    "payable_net_totals_by_period",
]

#: `PAYABLE_LINE_STATUSES` bir `frozenset`tir ve yineleme sırası çalıştırmadan
#: çalıştırmaya değişebilir. `IN (...)` listesinin sırası derlenmiş SQL metnini
#: değiştirir; sıralamak, hem sorgu önbelleğini hem de SQL'i denetleyen testleri
#: kararlı tutar.
PAYABLE_STATUS_ORDER = tuple(sorted(PAYABLE_LINE_STATUSES, key=lambda status: status.value))


def payable_net_sum():
    """Σ `net_amount` — hiç satır yoksa **0,00** (NULL değil).

    `repository.paid_sum` deseni: `coalesce` toplamın TEK yerinde durur, çağıran
    her yerde tekrar edilmez.
    """
    return func.coalesce(func.sum(PayrollLine.net_amount), literal(ZERO_MONEY))


def payable_net_totals_by_period() -> Subquery:
    """Dönem başına ödenebilir net toplam — kaç dönem olursa olsun TEK gruplu sorgu.

    `treasury/repository.paid_totals_by_invoice()`in kardeşidir ve aynı sebeple
    vardır: çağıran onu JOIN'ler, dönem başına ikinci bir sorgu açmaz.

    Sütunlar: `payroll_period_id` · `payable_net`.

    🔴 Ödenebilir satırı HİÇ olmayan dönem bu alt sorguda **YOKTUR** (grup
    oluşmaz). Çağıran INNER JOIN kullandığında dönem kendiliğinden düşer;
    "0,00 ödenecek" satırı üretilmez.
    """
    return (
        select(
            PayrollLine.payroll_period_id.label("payroll_period_id"),
            payable_net_sum().label("payable_net"),
        )
        .where(
            PayrollLine.status.in_(PAYABLE_STATUS_ORDER),
            PayrollLine.net_amount.is_not(None),
        )
        .group_by(PayrollLine.payroll_period_id)
        .subquery()
    )
