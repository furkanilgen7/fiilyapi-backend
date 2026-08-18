"""FIN-1 K2/K8 — TUREV katmani. Kolonlasan tek bir sey YOKTUR.

## Neden burada, neden TEK dosyada

Emrin K2 karari nettir: *"mockup'in 'Vadede' rozeti bir enum uyesi DEGIL,
TUREVDIR"*. Enum'a konsaydi her gun bir cron'un satirlari guncellemesi gerekirdi
ve **zamanla degisen bir olguyu kalici kolona yazmak BAYATLAR** — ertesi gun
yanlis rozet basar, kimse fark etmez (`bank_accounts.balance`in saklanmama
gerekcesinin ayni sinifi).

Turev burada BIR KEZ yazilir. Iki yere yazilsaydi kart ile rozet zamanla
ayrisirdi ve hicbir kolon farki ele vermezdi.

## Pencerenin USTU nereden olculdu (mockup, icat DEGIL)

E10'un tablosu ayrimi kendisi cizer:

| satir | vade | rozet |
|---|---|---|
| E10:119 | `25.07.2026` | **Vadede** (turuncu) |
| E10:146 | `20.07.2026` | **Vadede** (turuncu) |
| E10:128 | `15.08.2026` | Portfoyde (yesil) |
| E10:137 | `30.09.2026` | Portfoyde (yesil) |

Ayrim tam olarak **AY** sinirindadir. "Bugunden N gun" secilseydi N icin bir
sayi UYDURMAK gerekirdi ve 15.08 de rozeti alirdi — mockup onu yesil basiyor.
Ayrica K8'in "Bu Ay Vadeli" karti da AYNI takvim ayini kullanir; iki pencere
ayni yardimciden (`month_bounds`) gecsin diye ust sinir AY SONUDUR.

## `is_due`in ALT siniri YOKTUR — bilincli

Vadesi GECMIS ama hala portfoyde duran cek de "Vadede"dir; alt sinir konsaydi
gecikmis cekler sessizce yesil rozet alirdi. Bu, "Bu Ay Vadeli" KARTINDAN
(K8: takvim ayi, iki tarafi da kapali) ayrildigi noktadir ve ikisi kasitli
olarak farkli tanimlardir.

## Saat dilimi

"Bugun" `app.core.timezone.today()`dir, `date.today()` DEGIL: ikincisi sunucunun
yerel saatini (Railway'de UTC) okur ve TR gecesi 00:00-03:00 arasinda bir gun
geride kalir — ayin ilk gecesinde rozet BIR AY birden kayardi. `tests/
test_local_calendar_guard.py` bunu yapisal olarak da yasaklar.
"""

import calendar
from datetime import date

from app.core.timezone import today
from app.modules.treasury.models import FinancialInstrumentStatus

__all__ = ["as_of_today", "is_due", "month_bounds"]


def as_of_today() -> date:
    """Turevlerin okudugu "bugun" — TEK giris noktasi.

    Uc ve servis dogrudan `timezone.today()` cagirmaz: cagirsalardi biri
    gelecekte `date.today()`ye kayabilir ve fark yalnizca gece yarisindan sonra
    gorunurdu.
    """
    return today()


def month_bounds(day: date) -> tuple[date, date]:
    """Verilen gunun icinde bulundugu TAKVIM ayinin ilk ve son gunu (IKISI DE DAHIL).

    `calendar.monthrange` kullanilir; `28`/`30`/`31` gomulseydi artik yil (29
    Subat) ve 30 gunluk aylar sessizce yanlis pencere uretirdi.

    Aralik ayinda ust sinir yil DEGISTIRMEZ (`31.12`), yani "bir sonraki ayin
    ilk gunu"nu hesaplayip bir gun cikarmak gibi bir ara adim yoktur.
    """
    _, son_gun = calendar.monthrange(day.year, day.month)
    return date(day.year, day.month, 1), date(day.year, day.month, son_gun)


def is_due(status: FinancialInstrumentStatus, due_date: date, *, as_of: date) -> bool:
    """E10:121,148 turuncu **Vadede** rozetinin TEK kaynagi.

    IKI kosuludur ve ikisi de gereklidir:

    1. `status` PORTFOYDE olmali — tahsil/odenmis/iade/iptal edilmis bir evrak
       vadesi gecse bile "Vadede" DEGILDIR (E10:155 tahsil edilmis satirin vade
       tarihini GRI basar, turuncu degil);
    2. vade, icinde bulunulan takvim ayinin SON gununu ASMAMALI (ust sinir
       DAHIL; alt sinir yok — modul docstring'i).
    """
    if status is not FinancialInstrumentStatus.portfolio:
        return False
    return due_date <= month_bounds(as_of)[1]
