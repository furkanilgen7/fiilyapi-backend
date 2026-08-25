"""Bakım penceresinin TEK KAYNAĞI — saf, yan etkisiz fonksiyonlar (MK-4).

Mockup: `projedesign/Makine - Ekipman Detay.dc.html` 🔧 **Bakım Bilgileri**
kartı (MD:145-160) ve üstteki `Sonraki Bakım · 214 sa · 14.500'de` KPI'ı
(MD:46-48).

`cost.py` / `consumption.py` / `rental.py` kardeşidir: DB'ye DOKUNMAZ, kapsam
kararı VERMEZ, yalnız verilen sayılardan bakım penceresini üretir.

## Zincir

    son bakım okuması + periyot  →  sonraki bakım okuması
    hourmeter − son bakım okuması →  kullanılan saat  →  %kullanım
    sonraki bakım − hourmeter     →  kalan saat
    kalan saat ÷ günlük tempo     →  tahmini bakım tarihi

## Bu dosyanın taşıdığı kararlar

* 🔴 **Kart'ın ALTI sayısından yalnız İKİSİ saklanır** (`last_service_date`,
  `last_service_hourmeter`); geri kalan dördü (`sonraki bakım saati`, `kalan
  çalışma saati`, `tahmini bakım tarihi`, `%57 · 286/500` çubuğu) BURADA türer.
  Saklansalardı hourmeter her güncellendiğinde dördü birden bayatlar ve ekran
  sessizce yalan söylerdi (P10 "tek formül" kanonu).
* 🔴 **`monthly` periyot SAAT CİNSİNDEN DEĞİLDİR** ve bu bir eksiklik değil bir
  KAPIdır (MK-1 K16 fail-closed): aylık bakım yapan bir makinede "kalan saat"
  diye bir büyüklük YOKTUR. Uydurma bir saat karşılığı (720? 200?) türetmek,
  ekranda bir çubuğu doldurmak uğruna olmayan bir kuralı icat etmek olurdu.
* 🔴 **Tutarsız veri sessizce hesaplanmaz:** hourmeter son bakım okumasından
  KÜÇÜKSE (sayaç değişmiş ya da yanlış girilmiş) türevlerin hepsi `None`dur.
  Negatif "kullanılan saat" ile çizilen bir çubuk, hatayı GİZLEYEN bir çubuktur.
* **Kalan saat NEGATİF OLABİLİR ve kırpılmaz:** bakımı geçmiş bir makinenin
  `−30 sa`sı GERÇEKTİR; 0'a çekilseydi "tam zamanında" görünürdü.
* **Yuvarlama ikinci kez TANIMLANMAZ:** yüzde `consumption.quantize_ratio`dan
  geçer (bir ondalık, `ROUND_HALF_UP`) — modülün kendi `.quantize(...)` çağrısı
  ikinci bir yarım-kural doğururdu.
"""

import math
from datetime import date, timedelta
from decimal import Decimal

from app.modules.equipment.consumption import PERCENT_MULTIPLIER, quantize_ratio
from app.modules.equipment.models import EquipmentMaintenancePeriod

#: 🔴 Enum ÜYESİNİN saat karşılığı — TEK YERDE. `monthly` bilinçli olarak
#: `None`dır (modül docstring'i). Ada gömülü sayıyı ayrıştırmak
#: (`int(period.value.split("_")[1])`) aynı bilgiyi bir dize biçimine bağlar ve
#: `monthly` üyesinde patlardı.
PERIOD_HOURS: dict[EquipmentMaintenancePeriod, int | None] = {
    EquipmentMaintenancePeriod.hours_250: 250,
    EquipmentMaintenancePeriod.hours_500: 500,
    EquipmentMaintenancePeriod.hours_1000: 1000,
    EquipmentMaintenancePeriod.monthly: None,
}

#: Tahmini bakım tarihinin dayandığı ÇALIŞMA TEMPOSU penceresi (gün).
#:
#: Tek ay alınsaydı tempo, o ayın tatiline/duruşuna savrulurdu; ömür boyu
#: alınsaydı makinenin bugünkü şantiyesindeki temposunu HİÇ yansıtmazdı.
#: Doksan gün mockup'ın kendi üç aylık çalışma özetiyle (MD:125-133 Mayıs ·
#: Haziran · Temmuz) aynı pencereyi kullanır.
ESTIMATE_WINDOW_DAYS = 90


def period_hours(period: EquipmentMaintenancePeriod | None) -> int | None:
    """Periyodun SAAT karşılığı; `monthly` ve `None` için `None` (fail-closed)."""
    if period is None:
        return None
    return PERIOD_HOURS[period]


def used_hours(
    *, hourmeter_hours: Decimal | None, last_service_hourmeter: Decimal | None
) -> Decimal | None:
    """Son bakımdan bu yana çalışılan saat — MD:160 `286 / 500 saat çalışıldı`.

    Girdilerden biri yoksa `None`. Fark NEGATİFSE de `None`: sayacı geri giden
    bir makine bir ÖLÇÜM HATASIDIR ve negatif bir çubukla gizlenmez.
    """
    if hourmeter_hours is None or last_service_hourmeter is None:
        return None
    fark = hourmeter_hours - last_service_hourmeter
    return None if fark < 0 else fark


def next_service_hourmeter(
    *, last_service_hourmeter: Decimal | None, period: EquipmentMaintenancePeriod | None
) -> Decimal | None:
    """Sonraki bakımın HOURMETER hedefi — MD:153 `14.500 sa`."""
    saat = period_hours(period)
    if last_service_hourmeter is None or saat is None:
        return None
    return last_service_hourmeter + Decimal(saat)


def remaining_hours(
    *, next_service_hourmeter: Decimal | None, hourmeter_hours: Decimal | None
) -> Decimal | None:
    """Bakıma kalan saat — MD:155 `214 sa`. NEGATİF olabilir (bakım geçmiştir)."""
    if next_service_hourmeter is None or hourmeter_hours is None:
        return None
    return next_service_hourmeter - hourmeter_hours


def usage_pct(
    *, used_hours: Decimal | None, period: EquipmentMaintenancePeriod | None
) -> Decimal | None:
    """Bakım periyodu kullanımı — MD:159 `%57`. 100'ü AŞABİLİR (gecikmiş bakım)."""
    saat = period_hours(period)
    # `not saat` DEĞİL `is None`: mutasyon turunda ikisi AYNI davrandı, çünkü
    # `PERIOD_HOURS` KAPALI bir haritadır ve hiçbir üyesi 0 değildir — sıfıra
    # bölme burada yapısal olarak imkânsızdır. Ölçülemeyen bir korumayı
    # bırakmak, bekçisiz bir dal bırakmaktır.
    if used_hours is None or saat is None:
        return None
    return quantize_ratio(used_hours / Decimal(saat) * PERCENT_MULTIPLIER)


def daily_rate(*, window_hours: Decimal, window_days: int = ESTIMATE_WINDOW_DAYS) -> Decimal | None:
    """Penceredeki GÜNLÜK ortalama çalışma temposu.

    Hiç çalışmamış makinede `None` (K16): 0 tempoyla bölmek sonsuz bir tarih
    üretir, `as_of` basmak ise "bugün bakım" demek olurdu — ikisi de yalan.
    Payda TAKVİM GÜNÜdür, çalışılan gün sayısı değil: hafta sonu duran bir
    makinenin gerçek temposu takvimden okunur.
    """
    if window_days <= 0 or window_hours <= 0:
        return None
    return window_hours / Decimal(window_days)


def estimated_service_date(
    *, remaining_hours: Decimal | None, daily_rate: Decimal | None, as_of: date
) -> date | None:
    """Tahmini bakım tarihi — MD:157 `~05.09.2026`.

    Kalan saat 0 ya da NEGATİFSE tarih `as_of`tur: bakım zaten gelmiştir,
    geçmişe bir tarih uydurmak "ne zaman yapılmalıydı"yı değil "ne zaman
    yapılacak"ı soran alanı yanıltırdı.

    Gün sayısı YUKARI yuvarlanır: 37,3 günlük bir kalanı 37'ye indirmek bakımı
    makine eşiğe varmadan ÖNCEye koyardı.
    """
    if remaining_hours is None or daily_rate is None:
        return None
    if remaining_hours <= 0:
        return as_of
    return as_of + timedelta(days=math.ceil(remaining_hours / daily_rate))
