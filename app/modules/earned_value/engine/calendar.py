"""Proje takvimi — saf fonksiyon (spec §3.1; §2.6: `project_calendar` tablosu YOK).

* `day_no(d)`: baslangictan 1..n.
* Hafta 7 gundur ve `week_start_dow` gunu baslar; ILK hafta KISMI olabilir: hafta
  basi hicbir zaman proje baslangicindan once olmaz.
* `week_no(d)`: ilk (kismi) hafta 1.
* Hafta penceresi `W(d) = [week_start(d), min(week_end(d), d)]` — pencere d'de KAPANIR.

Yayma (B1) takvim ARALIGINDAN bagimsiz bir is gunu yuklemi ister (yaprak penceresi proje
araligi henuz belli degilken de yayilir, K7): `working_day_predicate`. Tatil listesi ayarda
TARIH ARALIGI olarak tutulur; `expand_holiday_ranges` onu gunlere acar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .policy import DEFAULT_WEEKLY_HOLIDAYS
from .types import SUNDAY, CalendarSettings

_WEEK = 7


@dataclass(frozen=True, slots=True)
class CalendarPosition:
    day_no: int
    week_no: int
    week_start: date
    week_end: date
    window_start: date
    window_end: date
    is_holiday: bool


class ProjectCalendar:
    def __init__(self, settings: CalendarSettings) -> None:
        self._settings = settings
        self._is_working_day = working_day_predicate(
            DEFAULT_WEEKLY_HOLIDAYS
            if settings.weekly_holidays is None
            else settings.weekly_holidays,
            settings.extra_holidays,
        )
        self._first_nominal_start = self._nominal_week_start(settings.start_date)

    @property
    def start_date(self) -> date:
        return self._settings.start_date

    @property
    def end_date(self) -> date:
        return self._settings.end_date

    def contains(self, d: date) -> bool:
        return self._settings.start_date <= d <= self._settings.end_date

    def _check(self, d: date) -> None:
        if not self.contains(d):
            raise ValueError(
                f"{d} proje takvimi disinda "
                f"({self._settings.start_date} – {self._settings.end_date})"
            )

    def _nominal_week_start(self, d: date) -> date:
        return d - timedelta(days=(d.weekday() - self._settings.week_start_dow) % _WEEK)

    def day_no(self, d: date) -> int:
        self._check(d)
        return (d - self._settings.start_date).days + 1

    def week_start(self, d: date) -> date:
        self._check(d)
        return max(self._nominal_week_start(d), self._settings.start_date)

    def week_end(self, d: date) -> date:
        self._check(d)
        return self._nominal_week_start(d) + timedelta(days=_WEEK - 1)

    def week_no(self, d: date) -> int:
        self._check(d)
        return (self._nominal_week_start(d) - self._first_nominal_start).days // _WEEK + 1

    def is_holiday(self, d: date) -> bool:
        self._check(d)
        return not self._is_working_day(d)

    def window(self, d: date) -> tuple[date, date]:
        """W(d) = [week_start(d), min(week_end(d), d)]."""
        return self.week_start(d), min(self.week_end(d), d)

    def position(self, d: date) -> CalendarPosition:
        window_start, window_end = self.window(d)
        return CalendarPosition(
            day_no=self.day_no(d),
            week_no=self.week_no(d),
            week_start=self.week_start(d),
            week_end=self.week_end(d),
            window_start=window_start,
            window_end=window_end,
            is_holiday=self.is_holiday(d),
        )


def working_day_predicate(
    weekly_holidays: frozenset[int] = DEFAULT_WEEKLY_HOLIDAYS,
    extra_holidays: frozenset[date] = frozenset(),
) -> Callable[[date], bool]:
    """Is gunu yuklemi (S5: haftanin gunleri kumesi + elle liste). Takvim araligi YOK."""
    if not all(0 <= dow <= SUNDAY for dow in weekly_holidays):
        raise ValueError(f"weekly_holidays 0..6 olmali: {sorted(weekly_holidays)}")
    weekly, extra = frozenset(weekly_holidays), frozenset(extra_holidays)

    def is_working_day(d: date) -> bool:
        return d.weekday() not in weekly and d not in extra

    return is_working_day


def expand_holiday_ranges(ranges: Iterable[tuple[date, date]]) -> frozenset[date]:
    """Tatil araliklarini ([bas, bit], iki uc dahil) gun kumesine acar."""
    days: set[date] = set()
    for first, last in ranges:
        if first > last:
            raise ValueError(f"Tatil araligi ters: {first} > {last}")
        days.update(first + timedelta(days=i) for i in range((last - first).days + 1))
    return frozenset(days)
