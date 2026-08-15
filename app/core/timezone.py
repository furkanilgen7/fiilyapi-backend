"""Kullaniciya donuk zaman ve gun sinirlari icin TEK saat dilimi kaynagi.

Bu tek sirketli bir Turk insaat ERP'sidir: arayuz Turkce, mockup'lar TR saatiyle
okunur, "bugun"/"bu ay" filtreleri TR takvimini ifade eder. UTC birakilirsa gece
00:00-03:00 arasindaki kayitlar yanlis gune duser ve ayni kayit ekranda baska,
Excel'de baska saatte gorunur.

Saat dilimi adi `settings.display_timezone`'da TEK yerde tanimlidir; modullere
ayri ayri string GOMULMEZ.

Donusum `zoneinfo` (IANA tz veritabani) ile yapilir — sabit +03:00 ofset
VARSAYILMAZ; tarihsel DST donemleri de dogru cevrilir.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings

#: Kullaniciya gosterilen tum zamanlarin saat dilimi.
DISPLAY_TIMEZONE = ZoneInfo(settings.display_timezone)

#: Kullaniciya gosterilen tarih-saat damgasinin TEK bicimi (TR gun.ay.yil saat:dk).
#: Ayri ayri yazilirsa bir yuzey `to_display` cagirmayi unutup ham UTC basar —
#: bicim ve cevirinin ayni modulden okunmasi bunu gorunur kilar (TB5 T4 bulgusu).
DISPLAY_TIMESTAMP_FORMAT = "%d.%m.%Y %H:%M"


def to_display(value: datetime) -> datetime:
    """`timestamptz` degerini goruntuleme saat dilimine cevirir.

    Naive (tz'siz) girdi UTC varsayilir: DB sutunlari timestamptz oldugu icin
    normalde tz-farkindadir, ama bellekte kurulmus bir nesne naive gelirse
    sessizce yerel saat sayilmasi yanlis gun/saat uretir.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(DISPLAY_TIMEZONE)


def today() -> date:
    """Goruntuleme saat dilimindeki BUGUN.

    `date.today()` sunucunun yerel saatini (Railway'de UTC) kullanir; TR gecesi
    00:00-03:00 arasinda bir gun geride kalir ve "kalan gun" hesabi bir gun
    kayar. Gun sinirlari tek kaynaktan okunmalidir.
    """
    return datetime.now(DISPLAY_TIMEZONE).date()


def day_start_utc(day: date) -> datetime:
    """Verilen TR gununun 00:00:00'ini UTC'ye cevirir (sinir DAHIL)."""
    return datetime.combine(day, time.min, tzinfo=DISPLAY_TIMEZONE).astimezone(UTC)


def day_end_utc(day: date) -> datetime:
    """Verilen TR gununun 23:59:59.999999'unu UTC'ye cevirir (sinir DAHIL)."""
    return datetime.combine(day, time.max, tzinfo=DISPLAY_TIMEZONE).astimezone(UTC)
