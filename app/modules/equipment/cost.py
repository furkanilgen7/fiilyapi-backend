"""Makine maliyetinin TEK KAYNAĞI — saf, yan etkisiz fonksiyonlar (MK-1 T2).

Spec: `docs/superpowers/specs/2026-08-13-mk1-makine-cekirdegi-design.md`
(K16 · K18 · K19). `payroll/compute.py` ve `inventory/balance.py` kardeşidir:
DB'ye DOKUNMAZ, kapsam kararı VERMEZ (onu `service.py` verir), yalnız verilen
sayılardan parayı üretir. İkinci bir formül yazılsaydı M1 kartı, M3 tablosu ve
M5 hakedişi aynı makine için farklı bir maliyet gösterirdi.

## Zincir

    dönemsel bedel (rate_period) → SAATLİK bedel → × saat → maliyet

## Bu dosyanın taşıdığı bağlanmış kararlar

* **K18 — maliyet formülü TEK YERDEDİR:** `cost = hours × saatlik_bedel`.
  Saatlik bedel dönemden türer: `hourly` doğrudan · `daily` `/ DAILY_HOURS` ·
  `monthly` `/ monthly_capacity_hours`.
* **🔴 `DAILY_HOURS = 10`** — mockup'tan TERSİNE MÜHENDİSLİKLE bulundu ve
  aşağıda gerekçesiyle TEK YERDE durur.
* **K16 — fail-closed:** bedeli ya da dönemi bilinmeyen makinenin maliyeti
  `None`dır, **0 DEĞİL**. 0 basmak "bedava çalıştı" derdi.
  ⚠️ Bunun AYNADAKİ EŞİ: bedeli BİLİNEN bir makinenin `0` saati gerçek bir
  `0`dır (M3 Forklift satırı: 0 saat → ₺0) — bilinen sıfırı `None`a çevirmek
  de bir yalan olurdu.
* **K19 — `Decimal`, asla `float`.** Para TAM SAYIYA, `ROUND_HALF_UP`
  yuvarlanır (M4'ün dört satırında doğrulandı).
"""

from decimal import ROUND_HALF_UP, Decimal

from app.modules.equipment.models import EquipmentRatePeriod

#: Para adımı — M1/M3/M4 hiçbir yerde kuruş BASMAZ (₺59.520 · ₺1.787), makine
#: maliyeti tam liradır. `payroll`ün kuruş adımından (0,01) BİLEREK farklıdır:
#: orada net ücret kuruşuna kadar ödenir, burada türev bir maliyet raporlanır.
MONEY_QUANTUM = Decimal("1")

#: 🔴 K18 — bir "günlük" bedelin karşılığı olan ÇALIŞMA SAATİ.
#:
#: Mockup TERSİNE MÜHENDİSLİĞİNİN ürünüdür (M1 günlük kira ↔ M3 satır maliyeti)
#: ve DÖRT ekipmanda birden tutar:
#:     3.200 / 320 = 10   (Tower Crane TC-48 · 186 sa → ₺59.520)
#:     2.800 / 280 = 10   (Ekskavatör CAT 320 · 152 sa → ₺42.560)
#:     1.400 / 140 = 10   (Damperli Kamyon   · 168 sa → ₺23.520)
#:       650 /  65 = 10   (Kompresör SC-200  · 144 sa →  ₺9.360)
#:
#: Tek ekipmanda tutan bir sayı tesadüf olabilirdi; dördü birden bunun mockup'ın
#: örtük iş kuralı olduğunu gösterir. Sabit BURADA, tek yerde durur: ikinci bir
#: kopya, gün tanımı değiştiğinde iki ekranda iki maliyet üretirdi.
#: (Sekiz saatlik vardiyanın değil, 06:00–16:00 tam gün kullanımının karşılığı —
#: M3'ün Damperli Kamyon kaydı da tam olarak `06:00–16:00 · 10 Saat`tir.)
DAILY_HOURS = Decimal("10")


def quantize_money(value: Decimal) -> Decimal:
    """Para yuvarlamasının TEK tanımı: tam sayı, `ROUND_HALF_UP`.

    Python `Decimal`in varsayılanı `ROUND_HALF_EVEN`dir ve M4'ün ilk satırında
    1.786,5'i **1.786**'ya indirirdi — mockup ₺1.787 basıyor. Her para çıktısı
    BU fonksiyondan geçer; koda serpilecek ikinci bir `.quantize(...)` çağrısı
    iki yuvarlama kuralı doğurur.
    """
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def hourly_rate(
    *,
    rate_amount: Decimal | None,
    rate_period: EquipmentRatePeriod | None,
    monthly_capacity_hours: int | None = None,
) -> Decimal | None:
    """Dönemsel bedelin SAATLİK karşılığı — hesaplanamıyorsa `None` (K16).

    YUVARLANMAZ: yuvarlama zincirin SONUNDADIR (`compute_cost`). Saatlik bedel
    ara ara yuvarlansaydı 186 saatlik bir satırda hata 186 kat büyürdü.

    `monthly` dönemde payda `monthly_capacity_hours`tır (K7: VERİ, koda gömülü
    sabit değil) ve yoksa ya da 0 ise sonuç `None`dır — sıfıra bölmede 0 basmak
    maliyeti yok göstermek olurdu.
    """
    if rate_amount is None or rate_period is None:
        return None
    if rate_period is EquipmentRatePeriod.hourly:
        return rate_amount
    if rate_period is EquipmentRatePeriod.daily:
        return rate_amount / DAILY_HOURS
    if not monthly_capacity_hours:
        return None
    return rate_amount / Decimal(monthly_capacity_hours)


def compute_cost(
    *,
    hours: Decimal,
    rate_amount: Decimal | None,
    rate_period: EquipmentRatePeriod | None,
    monthly_capacity_hours: int | None = None,
) -> Decimal | None:
    """🔴 K18 — makine maliyetinin TEK formülü: `hours × saatlik_bedel`.

    M3'ün satır maliyeti de, M1'in aylık maliyet KPI'ı da, ileride M5'in
    hakedişi de buradan geçer.

    Bedeli/dönemi bilinmeyen makinede `None` döner (K16); saat 0 ise sonuç
    gerçek bir `0`dır — makine bilinen bir bedelle hiç çalışmamıştır.
    """
    saatlik = hourly_rate(
        rate_amount=rate_amount,
        rate_period=rate_period,
        monthly_capacity_hours=monthly_capacity_hours,
    )
    if saatlik is None:
        return None
    return quantize_money(hours * saatlik)


def fuel_amount(*, liters: Decimal, unit_price: Decimal) -> Decimal:
    """Yakıt satırının tutarı — `liters × unit_price` (spec §2.3).

    `amount` KOLON DEĞİLDİR: kolon açılsaydı iki gerçek kaynak doğar ve biri
    güncellenmediğinde para sessizce ayrışırdı (P10 "tek formül" kanonu).
    Fail-closed'a gerek YOK: iki alan da `NOT NULL` + `CHECK > 0`dır, yani
    hesaplanamayan bir yakıt satırı DB'de yapısal olarak var olamaz.
    """
    return quantize_money(liters * unit_price)
