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

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple, Protocol

_MONEY = Decimal("0.01")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class LineLike(Protocol):
    """Bir hakediş satırının hesaba giren ÜÇ alanı.

    Somut modele BAĞLANMAZ (`guards._PaymentLike` deseninin aynısı): işveren
    `ProgressPaymentLine` ile taşeron `SubcontractorProgressPaymentLine` aynı
    üçlüyü taşır, hesap zinciri ikisi için de TEK kopyadır (taşeron modülü bu
    dosyayı KOPYALAMAZ, ÇAĞIRIR — plan T3 "kopya kod T7 bulgusudur").
    """

    contract_unit_price: Decimal
    coefficient: Decimal
    quantity: Decimal


class PaymentLike(Protocol):
    """`cumulative_state`in okuduğu hakediş alanları (§6.3 zinciri)."""

    advance_pct: Decimal
    retainage_pct: Decimal
    lines: list  # list[LineLike] — invariant `list` ile somut modeller kabul edilsin


class CumulativeState(NamedTuple):
    """Tamamlanmış hakediş zincirinin biriktirdiği durum (spec §6.3, §8, §9.6)."""

    gross: Decimal
    advance_recovered: Decimal
    retention: Decimal


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


def posting_base(gross: Decimal, advance: Decimal, retention: Decimal) -> Decimal:
    """🔴 MU-3D — hakediş fişinin KDV'SİZ tabanı: `brüt − avans − teminat`.

    ## Neden `net` DEĞİL

    `net_amount` KDV'yi İÇERİR (`gross + vat − advance − retention`). Hakediş
    fişi KDV'SİZDİR (kullanıcı kararı 2026-08-26) ve gerekçesi ölçülmüştür:
    `accounting.vat_return` beyannameyi YALNIZ `invoices`tan türetir ve kaynak
    süzgeci yoktur; hakedişe bir KDV bacağı yazılsaydı MU-3B'nin *"beyanname ==
    yevmiye"* kimliği kuruş toleransı olmadan ve SESSİZCE bozulurdu. KDV yalnız
    FATURADA doğar.

    ## Neden `gross` DE DEĞİL

    Bu büyüklük `invoicing.amounts`ın 4. adımıyla — yani `invoices.tax_base` ile
    — BİREBİR AYNI şekildedir (`subtotal − advance_amount − retention_amount`).
    Aynı olması ZORUNLUDUR ve İŞ 2'nin bütün mantığı buna dayanır: hakedişten
    fatura kesildiğinde hakediş fişi STORNO edilir ve faturanın fişi aynı
    hesaba AYNI tutarı yazar. Taban `gross` seçilseydi, storno ile faturanın
    gider/hasılat bacağı `advance + retention` kadar AYRIŞIR ve mizan her
    faturalanan hakedişte sessizce kayardı — hiçbir kolon farkı bunu ele
    vermezdi (MU-3C kanonu: bakiye SAKLANMAZ).

    🔴 Sonuç NEGATİF OLAMAZ: `advance` `gross`un yüzdesiyle ve kümülatif tavanla
    sınırlıdır, `retention` da `gross`un yüzdesidir; ikisinin toplamı `gross`u
    ancak `advance_pct + retainage_pct > 100` iken aşardı ve o oranlar DB'de
    `0..100` ile sınırlıdır. Yine de fiş yazan taraf sıfır/negatif tabanı
    FİŞLEMEZ (bacak `ck_journal_lines_single_side`ı ihlal ederdi).
    """
    return quantize2(gross - advance - retention)


def gross_total(payment_lines: Iterable[LineLike]) -> Decimal:
    """Satır tutarlarının brüt toplamı — `line_total`'ın TEK toplama kopyası.

    İki hakediş ailesi de buradan okur (T3, plan "paylaş, kopyalama").
    """
    return sum(
        (
            line_total(line.contract_unit_price, line.coefficient, line.quantity)
            for line in payment_lines
        ),
        Decimal("0.00"),
    )


def advance_or_uncapped(
    gross: Decimal,
    advance_pct: Decimal,
    contract_amount: Decimal | None,
    advance_recovered: Decimal,
) -> Decimal:
    """`contract_amount` NULL iken (taslak sözleşme) tavan uygulanamaz — görüntüleme
    amaçlı TAVANSIZ kesinti döner (spec §6.3: bu durumda hakediş zaten onaya
    GÖNDERİLEMEZ, `CONTRACT_AMOUNT_REQUIRED`; burada yalnız taslak görüntülemesi
    için zarif düşüş).

    Taşeron ucunda sözleşme bedeli kalemlerden TÜREDİĞİ için pratikte hiç `None`
    olmaz; ortak zincirin tek gövdesi olsun diye imza korunur.
    """
    if contract_amount is None:
        return quantize2(gross * advance_pct / _HUNDRED)
    return advance_deduction(gross, advance_pct, contract_amount, advance_recovered)


def cumulative_state(
    payments: Iterable[PaymentLike], contract_amount: Decimal | None
) -> CumulativeState:
    """Avans mahsubu zincirinin TEK kopyası — SORGUSUZ, saf.

    `payments` **`sequence_no`'ya göre ARTAN sırada** verilmelidir: her adımın
    tavanı bir öncekinin kurtardığı avansa bağlıdır (§6.3), basit toplam
    DEĞİLDİR. Zincir ikinci bir yerde kopyalansaydı tavan matematiği zamanla iki
    farklı sonuç üretirdi — bu yüzden işveren `service.py`, işveren `summary.py`
    ve taşeron `amounts.py` üçü de BURAYA gelir.
    """
    gross_sum = _ZERO
    recovered = _ZERO
    retention_total = _ZERO
    for prior in payments:
        gross_i = gross_total(prior.lines)
        gross_sum += gross_i
        recovered += advance_or_uncapped(gross_i, prior.advance_pct, contract_amount, recovered)
        retention_total += retention_amount(gross_i, prior.retainage_pct)
    return CumulativeState(gross=gross_sum, advance_recovered=recovered, retention=retention_total)


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
