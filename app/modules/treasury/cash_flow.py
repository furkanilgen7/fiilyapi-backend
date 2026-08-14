"""Nakit akışı serisi (HZ-1 T5) — spec §4 uç 10, E9:90-106.

`GET /treasury/cash-flow`: seçilen ayın GÜNLÜK giriş/çıkış serisi + iki toplam
(E9:104-105 `Giriş ₺4,12M` · `Çıkış ₺3,84M`).

## 🔴 Yön: `balance.py`den TÜRETİLİR, yeniden yazılmaz

İşaretin tek kaynağı `balance.inflow_condition()`tır (K2/K4): giden faturaya
yapılan ödeme GİRİŞ, gelen faturaya yapılan ödeme ÇIKIŞ. Burada ikinci bir kez
`direction == outgoing` yazılsaydı iki gerçek kaynak olur, biri bir gün
değişir ve bakiye kartı ile nakit akışı grafiği TERS işaret basardı — ikisi de
"bir sayı" gösterdiği için kusur ekranda görünmezdi.

Bakiye (T2) aynı ödemelerin NET toplamıdır; bu uç aynı ödemeleri GÜNE ve YÖNE
göre ayırır. Yani seri, kullanıcının aynı ekranda okuduğu bakiyenin zaman
içindeki dökümüdür — üçüncü bir para tanımı DEĞİL.

## 🔴 Boş ay: seri BOŞ, toplamlar SIFIR (NULL değil)

Seri SEYREKTİR: yalnız hareket görmüş günler satır üretir. Ayın 31 gününü
sıfırla doldurmak, veri olmayan bir günü "0 TL hareket oldu" diye gösterirdi
ve boş ayın 31 satırlık yanıtı "boş" görünmezdi.

Toplamlar AYRI bir toplu sorgudan gelir ve `coalesce` ŞARTTIR: ödemesiz bir
ayda `SUM()` NULL döner, 0 değil (`balance.py`nin NULL yutması tuzağı). İki
sorgu AYNI `WHERE` gövdesini paylaşır (`_kosullar`) — süzgeç kopyası açılsaydı
grafik ile altındaki iki rakam zamanla ayrışırdı.

## Ay penceresi

Sınırlar `DISPLAY_TIMEZONE`de kurulur ve KAPALIDIR (ilk gün ve son gün dahil).
Son gün "bir sonraki ayın 1'inden bir gün önce" olarak bulunur: `month + 1`
aritmetiği Aralık'ta yılı taşırdı ve ay uzunluklarını (28/29/30/31) elle
bilmek gerekirdi (`invoicing.summary.current_month_bounds` emsali).

`payments.paid_on` zaten bir `date` kolonudur, yani gün sınırı için saat
dilimi çevrimi GEREKMEZ; varsayılan ayın SEÇİMİ ise TR takvimindedir
(`core.timezone.today`) — sunucunun UTC yerel saati TR gecesi 00:00-03:00
arasında ayı bir gün geriden gösterirdi.

## 🔴 Kapsam: proje süzgeci UYGULANMAZ (bilinçli karar)

`upcoming-payments`in TERSİ. Gerekçe: nakit akışı ŞİRKET GENELİ banka
hesaplarının (K3) hareketidir ve aynı kullanıcı aynı ekranda o hesapların TAM
bakiyesini zaten okur (uç 1). Süzülseydi grafik, üstündeki kartlarla çelişirdi
ve hangisinin doğru olduğu anlaşılamazdı. Sızıntı yüzeyi de yoktur: seri
yalnız GÜNLÜK TOPLAM taşır — karşı taraf, evrak, proje adı YOK.
`upcoming-payments` süzülür çünkü orada her satır kimlik sızdırır.

## N+1

İki sorgu, GÜN sayısından bağımsız. Gün başına döngü kuran bir uygulama 31
sorgu koşar ve `test_N_ARTI_1_YAPMAZ`ı geçemez.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Select, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import today
from app.modules.invoicing.models import Invoice
from app.modules.treasury.balance import ZERO, inflow_condition
from app.modules.treasury.models import Payment
from app.modules.treasury.schemas import CashFlowBucket, CashFlowResponse

__all__ = [
    "MAX_YEAR",
    "MIN_YEAR",
    "build_cash_flow",
    "current_year_month",
    "month_bounds",
    "series_statement",
    "totals_statement",
]

#: Router'ın `Query(ge=…, le=…)` sınırları. `timesheet`/`equipment` emsali dar
#: aralık: serbest bir yıl değeri ay sınırı hesabını anlamsız tarihlere taşır
#: ve aşım **422**dir (sessiz düzeltme DEĞİL).
MIN_YEAR = 2000
MAX_YEAR = 2200


def current_year_month() -> tuple[int, int]:
    """Varsayılan pencere: `DISPLAY_TIMEZONE`deki İÇİNDE BULUNULAN ay."""
    bugun = today()
    return bugun.year, bugun.month


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Ayın ilk ve son günü (İKİSİ DE DAHİL) — bkz. modül docstring'i."""
    ilk = date(year, month, 1)
    sonraki_ay = (ilk + timedelta(days=32)).replace(day=1)
    return ilk, sonraki_ay - timedelta(days=1)


def _giris_tutari():
    """Giriş bacağı: yön koşulu sağlanıyorsa tutar, aksi hâlde 0.

    `else_=0` ŞART: `else_` yazılmasaydı `CASE` NULL üretir, `SUM` onu yutar ve
    yalnız ÇIKIŞ içeren bir gün girişte NULL basardı.
    """
    return case((inflow_condition(), Payment.amount), else_=literal(ZERO))


def _cikis_tutari():
    """Çıkış bacağı — giriş koşulunun TAM TÜMLEYENİ.

    Ayrı bir `direction == incoming` koşulu yazılsaydı iki bacak birbirinin
    tümleyeni OLMAYABİLİRDİ (yeni bir yön değeri eklendiğinde tutar sessizce
    hiçbir bacağa girmez, toplamlar bakiyeden sapardı).
    """
    return case((inflow_condition(), literal(ZERO)), else_=Payment.amount)


def _kosullar(ilk: date, son: date):
    """İKİ sorgunun PAYLAŞTIĞI `WHERE` gövdesi (seri + toplamlar).

    Kopya açılsaydı grafik ile E9:104-105'in iki rakamı farklı kümeleri
    özetler ve fark yalnız sınır günlerinde ortaya çıkardı.
    """
    return (Payment.paid_on >= ilk, Payment.paid_on <= son)


def _joined(stmt):
    """`payments` → `invoices` INNER join.

    INNER'dır ve öyle kalır (`balance.signed_legs` gerekçesi): `invoice_id`
    NOT NULL + RESTRICT FK olduğu için faturasız ödeme YAPISAL OLARAK
    imkânsızdır; OUTER yapmak var olmayan bir satır sınıfı için YÖNSÜZ bir dal
    açardı ve o dal hiçbir bacağa girmeden toplamdan düşerdi.
    """
    return stmt.join(Invoice, Invoice.id == Payment.invoice_id)


def series_statement(ilk: date, son: date) -> Select:
    """Günlük kovalar. Sıralama SQL'dedir ve BURADA test edilebilir olmalıdır.

    ⚠️ Kayıp bir `ORDER BY` uçtan KANITLANAMAZ: PostgreSQL sıralamasız bir
    `GROUP BY`ın satırlarını çoğu zaman yine artan verir (küçük kümede
    `GroupAggregate`), yani kara kutu testi yeşil kalır ve garanti sessizce
    kaybolur. Bu yüzden ifade dışarı açıktır ve
    `test_seri_sorgusu_ORDER_BY_TASIR` derlenmiş SQL'i denetler.
    """
    return (
        _joined(
            select(
                Payment.paid_on.label("day"),
                func.sum(_giris_tutari()).label("inflow"),
                func.sum(_cikis_tutari()).label("outflow"),
            )
        )
        .where(*_kosullar(ilk, son))
        .group_by(Payment.paid_on)
        .order_by(Payment.paid_on)
    )


def totals_statement(ilk: date, son: date) -> Select:
    """İki toplam — seriyle AYNI `WHERE` gövdesinden (`_kosullar`).

    `coalesce` ŞARTTIR: ödemesiz ayda `SUM()` NULL döner ve yanıt `0` yerine
    `null` basardı.
    """
    return _joined(
        select(
            func.coalesce(func.sum(_giris_tutari()), literal(ZERO)),
            func.coalesce(func.sum(_cikis_tutari()), literal(ZERO)),
        )
    ).where(*_kosullar(ilk, son))


async def build_cash_flow(session: AsyncSession, *, year: int, month: int) -> CashFlowResponse:
    """Günlük seri + iki toplam. `actor` PARAMETRESİ YOKTUR.

    Kapsam süzgeci uygulanmadığı için (modül docstring'i) burada bir kullanıcı
    nesnesine ihtiyaç yoktur; imzaya "ileride lazım olur" diye eklenseydi,
    okuyan kişi bir süzgeç varmış sanırdı.
    """
    ilk, son = month_bounds(year, month)
    satirlar = (await session.execute(series_statement(ilk, son))).all()
    giris_toplam, cikis_toplam = (await session.execute(totals_statement(ilk, son))).one()
    return CashFlowResponse(
        year=year,
        month=month,
        series=[
            CashFlowBucket(day=gun, inflow=Decimal(giris), outflow=Decimal(cikis))
            for gun, giris, cikis in satirlar
        ],
        inflow_total=Decimal(giris_toplam),
        outflow_total=Decimal(cikis_toplam),
    )
