"""İşveren hakedişi hesap motoru (spec §6 tamamı, §8) — saf fonksiyonlar.

DB/ORM importu YOK (kasıtlı saflık — bu dosya `sqlalchemy` import ETMEZ, grep ile
doğrulanır). Yalnız `Decimal` girdi/çıktı: her fonksiyon çağıran katmandan (H4+)
zaten `Decimal`'e çevrilmiş değerler alır, yeni yuvarlama kuralı icat etmez.

Tüm parasal ara sonuçlar `Numeric(18,2)` ölçeğinde `ROUND_HALF_UP` ile
yuvarlanır (`quantize2`, `contracts/distribution.py:62` `_quantize_money`
deseninin genelleştirilmesi).

K5 (kullanıcı kararı, BAĞLAYICI): mockup'ın (OLU) düzeltilmiş birim fiyatı
tam-liraya yuvarlayıp o tam-lira üstünden çarpması **onaylı sapmadır** —
gösterim artefaktıdır. Burada kuruş hassasiyeti korunur: `adjusted_unit_price`
ÖNCE quantize2 edilir, `line_total` o quantize edilmiş değer üstünden yeniden
quantize2 edilir (§6.1 formül sırası — sıra bozulursa OLU 122/126 altın
sayıları tutmaz).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_MONEY = Decimal("0.01")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def quantize2(value: Decimal) -> Decimal:
    """`Numeric(18,2)` ölçeğine `ROUND_HALF_UP` ile yuvarlar (spec §6, K5)."""
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def adjusted_unit_price(contract_unit_price: Decimal, coefficient: Decimal) -> Decimal:
    """Düzeltilmiş birim fiyat (OLU 102 "Düz. B.F.") — spec §6.1.

    K5: kuruş hassasiyetinde yuvarlanır, tam liraya YUVARLANMAZ (OLU'nun
    ₺2.113 gösterimi onaylı sapmadır).
    """
    return quantize2(contract_unit_price * coefficient)


def line_total(contract_unit_price: Decimal, coefficient: Decimal, quantity: Decimal) -> Decimal:
    """Satır hakediş tutarı (OLU 106 "Hakediş Tutarı") — spec §6.1.

    `adjusted_unit_price` ÖNCE quantize2 edilir, sonuç quantity ile çarpılıp
    TEKRAR quantize2 edilir (formül sırası K5'in altın sayılarını üretir).
    """
    return quantize2(adjusted_unit_price(contract_unit_price, coefficient) * quantity)


def vat_amount(gross: Decimal, vat_pct: Decimal) -> Decimal:
    """KDV (OLU 183-184, E15 158-159) — spec §6.2."""
    return quantize2(gross * vat_pct / _HUNDRED)


def advance_deduction(
    gross: Decimal,
    advance_pct: Decimal,
    contract_amount: Decimal,
    advance_recovered: Decimal,
) -> Decimal:
    """Kümülatif tavanlı avans mahsubu — spec §6.3 (OLU 187, E14 85/136-137).

    Üç kenar:
    * tavana değmeyen: `gross × advance_pct / 100` tavan içinde kalır → tam kesinti
    * tam değen/aşan: kalan tavan (`advance_total − advance_recovered`) kesintiyi
      sınırlar, negatif kalıntı `max(...,0)` ile sıfıra kırpılır
    """
    advance_total = quantize2(contract_amount * advance_pct / _HUNDRED)
    remaining_cap = max(advance_total - advance_recovered, _ZERO)
    uncapped = quantize2(gross * advance_pct / _HUNDRED)
    return min(uncapped, remaining_cap)


def retention_amount(gross: Decimal, retainage_pct: Decimal) -> Decimal:
    """Teminat kesintisi (E15 166-167, OLU 191-192) — spec §6.4."""
    return quantize2(gross * retainage_pct / _HUNDRED)


def net_amount(gross: Decimal, vat: Decimal, advance: Decimal, retention: Decimal) -> Decimal:
    """Net ödeme (E15 170-171, OLU 195-196) — spec §6.4."""
    return quantize2(gross + vat - advance - retention)


def duration_pct(start: date | None, end: date | None, today: date | None) -> Decimal | None:
    """Süre ilerlemesi (E15 188) — kalıcı karar 9: uç-dahil, 0-100'e kırpılır.

    `(bugün − start + 1) / (end − start + 1) × 100`. Tarihlerden biri eksikse
    `None` (zarif düşüş, spec §8).
    """
    if start is None or end is None or today is None:
        return None
    total_days = (end - start).days + 1
    if total_days <= 0:
        return None
    elapsed_days = (today - start).days + 1
    pct = quantize2(Decimal(elapsed_days) * _HUNDRED / Decimal(total_days))
    return max(_ZERO, min(_HUNDRED, pct)).quantize(_MONEY, rounding=ROUND_HALF_UP)
