"""TB5 T3 — saat ENJEKSIYONU: yerel takvim kusuru gercek saate birakilmaz.

`date.today()` sunucunun yerel saatini okur (Railway'de UTC). TR UTC+3 oldugu
icin kusur gunun yalnizca 21:00-24:00 UTC diliminde gorunur; gunduz kosulan her
test yesildir. Bu yuzden regresyon testleri saati BEKLEMEZ, ENJEKTE eder.

Enjeksiyon noktasi `app.core.timezone` modulundeki `datetime` ISMIDIR — cunku
`timezone.today()` tam olarak `datetime.now(DISPLAY_TIMEZONE).date()` yazar.
Bu secim RED->GREEN mekanizmasinin ta kendisidir: hala `date.today()` kullanan
bir kod yolu bu monkeypatch'ten ETKILENMEZ, dolayisiyla test kirmizi kalir.

`freezegun` DEPONUN BAGIMLILIGI DEGILDIR ve eklenmez; standart kutuphane
disinda hicbir sey gerekmiyor.
"""

from datetime import UTC, datetime, tzinfo

import pytest

from app.core import timezone as timezone_module

#: TR gecesi 00:30 = UTC'de bir ONCEKI gunun 21:30'u. `date.today()` (UTC)
#: burada DUNU dondurur; `timezone.today()` dogru TR gununu dondurur.
#: Ayrica DST disi bir tarih secildi — TR 2016'dan beri kalici UTC+3'tedir,
#: ama sabit ofset VARSAYILMAZ: donusumu `zoneinfo` yapar.
TR_GECE_YARISI_SONRASI_UTC = datetime(2026, 3, 10, 21, 30, tzinfo=UTC)

#: 1 Ocak 01:00 TSI = 31 Aralik 22:00 UTC. Yil bazli numara ureticileri icin
#: asil tuzak budur: UTC'de hala ESKI yil, TR'de YENI yil.
YIL_SINIRI_UTC = datetime(2027, 12, 31, 22, 0, tzinfo=UTC)


def sabit_saat(monkeypatch: pytest.MonkeyPatch, an: datetime) -> None:
    """`app.core.timezone`in okudugu saati sabit bir AWARE UTC anina baglar.

    `datetime` sinifinin kendisi degistirilir (alt sinif), yalnizca `now()`
    ezilir: `datetime.combine` gibi `day_start_utc`/`day_end_utc` icinde
    kullanilan diger uyeler CALISMAYA DEVAM EDER.
    """
    if an.tzinfo is None:
        raise ValueError("Enjekte edilen an AWARE olmalidir; naive an ofset belirsizligi tasir.")

    class _SabitDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            return an.astimezone(tz) if tz is not None else an.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(timezone_module, "datetime", _SabitDatetime)
