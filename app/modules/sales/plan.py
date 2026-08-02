"""Ödeme planı hesap motoru — P8 T4 (spec §2, mockup F99-F147). Saf fonksiyonlar.

DB/ORM importu YOK (`progress_payments/calculations.py` deseni): bu dosya yalnız
`Decimal`/`date` alır ve `Decimal`/`date` döner, böylece plan aritmetiği HTTP
katmanı olmadan tek başına test edilebilir.

## Kuruş dengeleme SON taksitte

Taksit tutarı `ROUND_DOWN` ile kuruşa indirilir ve bölünmeden artan kısım SON
taksite eklenir. Alternatif (her satırı `ROUND_HALF_UP` ile yuvarlamak) planı
`sale_price`tan birkaç kuruş saptırırdı; oysa **Σ amount == sale_price** hem
spec §2'nin sunucu doğrulaması hem de mockup satır 143'ün TOPLAM ₺1.440.000
değeridir (= F86 satış bedeli, satır 84-87). Fark hep SON satıra biner: ilk
satıra binseydi "Peşinat" tutarı kullanıcının F103'e yazdığı değerden sapardı.

## Vade farkı (F106) neden tutarları ŞİŞİRMEZ — BAĞLAYICI KARAR

Mockup satır 106'da vade farkı `0`dır ve satır 143'teki TOPLAM tam olarak F86
satış bedeline eşittir; yani mockup'ta vade farkının HESAPLANMIŞ bir örneği
YOKTUR. Vade farkı taksit toplamına EKLENSEYDİ plan toplamı `sale_price`ı aşar,
bu da iki şeyi birden kırardı: (1) spec §2'nin "plan toplamı = `sale_price`"
kuralı, (2) T3'ün `remaining_amount = sale_price − paid_amount` türevi (tam
ödenmiş bir plan NEGATİF kalan gösterirdi). Bu yüzden vade farkı satış BEDELİNE
(F86) kullanıcı tarafından yansıtılır; sunucu `term_interest_pct`i saklar ve
plan yanıtında `term_interest_amount` olarak GÖSTERİM türevi hâlinde döndürür —
tıpkı gecikme faizinin (§8 S5) yalnız gösterim türevi olması gibi. Tahakkuk
kaydı YAZILMAZ, kolon AÇILMAZ.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

__all__ = [
    "DOWN_PAYMENT_LABEL",
    "PlannedRow",
    "build_plan",
    "quantize2",
    "term_interest_amount",
]

_MONEY = Decimal("0.01")
_ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")

# F118 peşinat satırının etiketi (mockup satır 118 "Peşinat").
DOWN_PAYMENT_LABEL = "Peşinat"

# F124/133 taksit etiketi: "1 / 12", "2 / 12" …
_INSTALLMENT_LABEL = "{sequence_no} / {count}"

# `sequence_no = 0` PEŞİNAT satırıdır (T1 model notu); taksitler 1'den başlar.
DOWN_PAYMENT_SEQUENCE = 0


@dataclass(frozen=True)
class PlannedRow:
    """Üretilmiş plan satırı — henüz hiçbir şey YAZILMADI (`lines._ResolvedLine` deseni)."""

    sequence_no: int
    label: str
    due_date: date
    amount: Decimal


def quantize2(value: Decimal) -> Decimal:
    """`Numeric(18,2)` ölçeği, `ROUND_HALF_UP` (`calculations.quantize2` ile aynı kural)."""
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def term_interest_amount(
    sale_price: Decimal, down_payment: Decimal, pct: Decimal | None
) -> Decimal:
    """F106 vade farkının GÖSTERİM tutarı — plana YAZILMAZ (yukarıdaki karar).

    Taksitlendirilen bakiye üzerinden hesaplanır: peşinat vadeli değildir.
    """
    if pct is None:
        return _ZERO
    return quantize2((sale_price - down_payment) * pct / _HUNDRED)


def add_months(start: date, months: int) -> date:
    """Aylık vade ilerlemesi (F126 01.09 → F135 01.10 …).

    Ayın son gününe düşen tarih kısa aylarda KAYDIRILMAZ, o ayın son gününe
    KIRPILIR (31 Ocak + 1 ay = 28/29 Şubat): kaydırmak bir sonraki taksiti bir
    gün öne alır ve zincir boyunca birikirdi. `dateutil` bağımlılığı bu tek
    kural için projeye EKLENMEZ.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def build_plan(
    *,
    sale_price: Decimal,
    down_payment: Decimal,
    installment_count: int,
    first_installment_date: date | None,
    down_payment_due_date: date,
) -> list[PlannedRow]:
    """F103-106 girdilerinden F117-139 tablosunu üretir. Σ amount == `sale_price`.

    Girdi doğrulaması (peşinat > bedel, taksit sayısı yok, ilk taksit tarihi yok)
    ÇAĞIRANDA yapılır (`installments.generate_plan`) — Türkçe hata metinleri ve
    HTTP eşlemesi servis katmanının işidir, hesap motoru saf kalır.

    `down_payment_due_date` DIŞARIDAN verilir: peşinatın vadesi "Sözleşme
    imzasında"dır (mockup satır 119) ve ayrı bir sözleşme tarihi kolonu yoktur;
    çağıran satış kaydının açılış tarihini geçirir. `date.today()`yi burada
    çağırmak fonksiyonu saate bağımlı ve test edilemez kılardı.
    """
    rows: list[PlannedRow] = []
    if down_payment > _ZERO:
        rows.append(
            PlannedRow(
                sequence_no=DOWN_PAYMENT_SEQUENCE,
                label=DOWN_PAYMENT_LABEL,
                due_date=down_payment_due_date,
                amount=quantize2(down_payment),
            )
        )

    financed = quantize2(sale_price - down_payment)
    if installment_count <= 0 or first_installment_date is None:
        return rows

    # ROUND_DOWN: her satır AŞAĞI kırpılır ki artan kuruşlar son satıra kalsın.
    # Yukarı yuvarlanan satırlar toplamı `sale_price`ın ÜSTÜNE taşırdı.
    unit = (financed / installment_count).quantize(_MONEY, rounding=ROUND_DOWN)
    for index in range(installment_count):
        sequence_no = index + 1
        is_last = sequence_no == installment_count
        amount = financed - unit * (installment_count - 1) if is_last else unit
        rows.append(
            PlannedRow(
                sequence_no=sequence_no,
                label=_INSTALLMENT_LABEL.format(sequence_no=sequence_no, count=installment_count),
                due_date=add_months(first_installment_date, index),
                amount=quantize2(amount),
            )
        )
    return rows
