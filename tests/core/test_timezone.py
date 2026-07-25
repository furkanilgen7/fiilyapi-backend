"""Goruntuleme saat dilimi yardimcilari (B5 takip maddesi #1-#2).

Kullaniciya donuk TUM zaman ve gun sinirlari `Europe/Istanbul` semantigindedir.
Donusum `zoneinfo` ile yapilir; sabit +03:00 ofset VARSAYILMAZ.
"""

from datetime import UTC, date, datetime, timedelta

from app.core.timezone import DISPLAY_TIMEZONE, day_end_utc, day_start_utc, to_display


def test_display_timezone_europe_istanbul():
    assert str(DISPLAY_TIMEZONE) == "Europe/Istanbul"


def test_to_display_utc_gece_yarisi_oncesini_ertesi_gune_tasir():
    """UTC 21:30 → TR ertesi gun 00:30 (gun DEGISIR)."""
    tr = to_display(datetime(2026, 7, 17, 21, 30, tzinfo=UTC))
    assert (tr.year, tr.month, tr.day, tr.hour, tr.minute) == (2026, 7, 18, 0, 30)


def test_to_display_naive_girdiyi_utc_sayar():
    naive = datetime(2026, 7, 17, 21, 30)
    assert to_display(naive) == to_display(datetime(2026, 7, 17, 21, 30, tzinfo=UTC))


def test_to_display_zoneinfo_kullanir_sabit_ofset_varsayilmaz():
    """Turkiye 2016'da kalici +03'e gecti; oncesinde kis saati +02 idi.

    Sabit +3 gomulmus olsaydi bu tarih 3 saat kayardi; `ZoneInfo` gercek IANA
    verisini kullandigi icin +02 cikar.
    """
    kis_2016 = to_display(datetime(2016, 1, 15, 12, 0, tzinfo=UTC))
    assert kis_2016.utcoffset() == timedelta(hours=2)
    assert kis_2016.hour == 14

    yaz_2026 = to_display(datetime(2026, 1, 15, 12, 0, tzinfo=UTC))
    assert yaz_2026.utcoffset() == timedelta(hours=3)


def test_day_start_utc_tr_gununun_basini_utc_ye_cevirir():
    """TR 00:00 = bir onceki gun UTC 21:00."""
    assert day_start_utc(date(2026, 7, 17)) == datetime(2026, 7, 16, 21, 0, tzinfo=UTC)


def test_day_end_utc_tr_gununun_sonunu_utc_ye_cevirir():
    """TR 23:59:59.999999 = ayni gun UTC 20:59:59.999999."""
    assert day_end_utc(date(2026, 7, 17)) == datetime(2026, 7, 17, 20, 59, 59, 999999, tzinfo=UTC)


def test_gun_sinirlari_tam_bir_tr_gununu_kapsar():
    start = day_start_utc(date(2026, 7, 17))
    end = day_end_utc(date(2026, 7, 17))
    assert end - start == timedelta(days=1) - timedelta(microseconds=1)
