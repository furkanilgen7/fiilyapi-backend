"""Takvim saf fonksiyonu (spec §3.1): gün no · hafta no · kısmi ilk hafta · tatil."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.earned_value.engine import CalendarSettings, ProjectCalendar

FRIDAY = 4


def _cal(week_start_dow: int = 0) -> ProjectCalendar:
    # 2026-09-03 Perşembe → 2026-10-15
    return ProjectCalendar(CalendarSettings(date(2026, 9, 3), date(2026, 10, 15), week_start_dow))


def test_day_no_starts_at_one() -> None:
    cal = _cal()
    assert cal.day_no(date(2026, 9, 3)) == 1
    assert cal.day_no(date(2026, 10, 15)) == 43


def test_first_week_is_partial_with_monday_start() -> None:
    cal = _cal()
    assert cal.week_no(date(2026, 9, 3)) == 1
    assert cal.week_start(date(2026, 9, 6)) == date(2026, 9, 3)  # Pzt 31.08 DEĞİL
    assert cal.week_end(date(2026, 9, 3)) == date(2026, 9, 6)
    assert cal.week_no(date(2026, 9, 7)) == 2
    assert cal.week_start(date(2026, 9, 13)) == date(2026, 9, 7)
    assert cal.week_no(date(2026, 9, 14)) == 3


def test_week_start_dow_friday() -> None:
    cal = _cal(FRIDAY)
    assert cal.week_no(date(2026, 9, 3)) == 1  # Perşembe tek günlük 1. hafta
    assert cal.week_end(date(2026, 9, 3)) == date(2026, 9, 3)
    assert cal.week_no(date(2026, 9, 4)) == 2  # Cuma yeni hafta
    assert cal.week_start(date(2026, 9, 10)) == date(2026, 9, 4)
    assert cal.week_end(date(2026, 9, 10)) == date(2026, 9, 10)


def test_start_on_week_start_day_has_full_first_week() -> None:
    cal = ProjectCalendar(CalendarSettings(date(2026, 9, 7), date(2026, 9, 30)))  # Pazartesi
    assert cal.week_no(date(2026, 9, 13)) == 1
    assert cal.week_no(date(2026, 9, 14)) == 2


def test_window_closes_at_d() -> None:
    cal = _cal()
    assert cal.window(date(2026, 9, 9)) == (date(2026, 9, 7), date(2026, 9, 9))
    assert cal.window(date(2026, 9, 3)) == (date(2026, 9, 3), date(2026, 9, 3))


@pytest.mark.parametrize("d", [date(2026, 9, 2), date(2026, 10, 16)])
def test_outside_calendar_raises(d: date) -> None:
    with pytest.raises(ValueError, match="takvimi disinda"):
        _cal().day_no(d)


def test_invalid_settings_raise() -> None:
    with pytest.raises(ValueError):
        CalendarSettings(date(2026, 9, 3), date(2026, 9, 2))
    with pytest.raises(ValueError):
        CalendarSettings(date(2026, 9, 3), date(2026, 9, 4), week_start_dow=7)
