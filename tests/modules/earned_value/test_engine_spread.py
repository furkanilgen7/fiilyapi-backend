"""PLN-B1.1 — yaprak bütçesinin günlere YAYILMASI (PLANLAMA-SPEC §2.5, §3.9 B1-1).

## Elle hesap: pencere 2026-09-03 (Per) … 2026-09-07 (Pzt), bütçe 100, tatil Pazar
s = 03.09 · e = 07.09 · e − s = 4 takvim günü → u = (t − s) / 4.
06.09 Pazar tatil → w = 0 (sözlüğe girmez).

| gün   | u    | doğrusal | çan 6u(1−u)+0,05 | ön 2(1−u)+0,05 | arka 2u+0,05 |
|-------|------|----------|------------------|----------------|--------------|
| 03.09 | 0    | 1        | 0,05             | 2,05           | 0,05         |
| 04.09 | 0,25 | 1        | 1,175            | 1,55           | 0,55         |
| 05.09 | 0,5  | 1        | 1,55             | 1,05           | 1,05         |
| 06.09 | tatil| 0        | 0                | 0              | 0            |
| 07.09 | 1    | 1        | 0,05             | 0,05           | 2,05         |
| Σw    |      | 4        | 2,825            | 4,70           | 3,70         |

Pay = 100 × w / Σw → EN BÜYÜK KALAN (Hamilton, `policy.largest_remainder`): önce 1e-6'ya
AŞAĞI yuvarla; eksik tam kuantumları kesirli kalanı en büyük günlere birer birer dağıt
(eşitlikte en erken gün); kuantum-altı artık en büyük paylı güne (eşitlikte en erken).

(kesir = ham payın 1e-6 altı, kuantum biriminde)

| gün   | doğr. | çan taban · kesir | ön taban · kesir | arka taban · kesir |
|-------|-------|-------------------|------------------|--------------------|
| 03.09 | 25    | 1,769911 · ,504   | 43,617021 · ,277 | 1,351351 · ,351    |
| 04.09 | 25    | 41,592920 · ,354  | 32,978723 · ,404 | 14,864864 · ,865   |
| 05.09 | 25    | 54,867256 · ,637  | 22,340425 · ,532 | 28,378378 · ,378   |
| 07.09 | 25    | 1,769911 · ,504   | 1,063829 · ,787  | 55,405405 · ,405   |
Σ taban = 99,999998 → her dağılımda 2 kuantum eksik → kesri en büyük iki güne +1e-6:
çan 05.09 (,637) + 03.09 (,504; 07.09 ile EŞİT → en erken) · ön 07.09, 05.09 · arka 04.09, 07.09.

| gün   | doğr. | çan      | ön        | arka      |
|-------|-------|----------|-----------|-----------|
| 03.09 | 25    | 1,769912 | 43,617021 | 1,351351  |
| 04.09 | 25    | 41,592920| 32,978723 | 14,864865 |
| 05.09 | 25    | 54,867257| 22,340426 | 28,378378 |
| 07.09 | 25    | 1,769911 | 1,063830  | 55,405406 |
(Bu örnekte sonuç eski "kalan son güne" yöntemiyle aynı; fark küçük bütçede — aşağıda.)

## Neden en büyük kalan (ölçüldü, 2026-09-25; 200 günlük pencere 01.01–19.07, 171 iş günü)
Eski yöntem (HALF_EVEN + kalan son güne):
* bütçe 0,00001234: her ara pay 0 → BÜTÜN bütçe son güne (eksi yok ama eğri bozuk);
* bütçe 0,0001026: ara paylar 0,0000006 → 0,000001'e yukarı; son gün doğrusal −0,0000674,
  çan −0,0000124 (EKSİ pay). Yeni yöntemde her gün >= 0 ve Σ == bütçe TAM.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    Distribution,
    NoWorkingDayError,
    expand_holiday_ranges,
    spread_leaf,
    working_day_predicate,
)
from app.modules.earned_value.engine.numeric import SPREAD_QUANTUM

D = Decimal
S, E = date(2026, 9, 3), date(2026, 9, 7)
WORKDAYS = (date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 7))
SUNDAY_OFF = working_day_predicate(frozenset({6}), frozenset())

EXPECTED = {
    Distribution.LINEAR: ("25", "25", "25", "25"),
    Distribution.BELL: ("1.769912", "41.592920", "54.867257", "1.769911"),
    Distribution.FRONT: ("43.617021", "32.978723", "22.340426", "1.063830"),
    Distribution.BACK: ("1.351351", "14.864865", "28.378378", "55.405406"),
}


@pytest.mark.parametrize("distribution", list(Distribution), ids=lambda d: d.value)
def test_spread_matches_hand_table(distribution: Distribution) -> None:
    shares = spread_leaf(D(100), S, E, distribution, SUNDAY_OFF)
    expected = dict(zip(WORKDAYS, map(D, EXPECTED[distribution]), strict=True))
    assert shares == expected
    assert sum(shares.values()) == 100  # TAM (kuantum + kalan)


def test_spread_values_are_on_quantum() -> None:
    shares = spread_leaf(D(100), S, E, Distribution.BELL, SUNDAY_OFF)
    assert all(v == v.quantize(SPREAD_QUANTUM) for v in shares.values())
    assert SPREAD_QUANTUM == D("0.000001")


def test_holiday_is_not_in_result() -> None:
    shares = spread_leaf(D(100), S, E, Distribution.LINEAR, SUNDAY_OFF)
    assert date(2026, 9, 6) not in shares


def test_single_day_window_takes_whole_budget() -> None:
    # e − s = 0 → payda max(1, 0) = 1 → u = 0; tek gün bütün bütçeyi alır
    for distribution in Distribution:
        assert spread_leaf(D("7.5"), S, S, distribution, SUNDAY_OFF) == {S: D("7.5")}


def test_zero_budget_is_empty() -> None:
    assert spread_leaf(D(0), S, E, Distribution.BELL, SUNDAY_OFF) == {}


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValueError, match="start"):
        spread_leaf(D(100), E, S, Distribution.LINEAR, SUNDAY_OFF)


def test_window_without_working_day_raises_no_working_day() -> None:
    sunday = date(2026, 9, 6)
    with pytest.raises(NoWorkingDayError):
        spread_leaf(D(100), sunday, sunday, Distribution.LINEAR, SUNDAY_OFF)
    assert issubclass(NoWorkingDayError, ValueError)


def test_float_budget_is_rejected() -> None:
    with pytest.raises(TypeError):
        spread_leaf(100.0, S, E, Distribution.LINEAR, SUNDAY_OFF)  # type: ignore[arg-type]


def test_distribution_must_be_enum() -> None:
    with pytest.raises(TypeError):
        spread_leaf(D(100), S, E, "linear", SUNDAY_OFF)  # type: ignore[arg-type]
    assert Distribution("bell") is Distribution.BELL


def test_long_window_sum_is_exact_for_awkward_budget() -> None:
    # 1e-6 kuantumlu paylar + kalan: 200 günlük pencerede de Σ == bütçe TAM
    budget = D("1234.567891")
    for distribution in Distribution:
        shares = spread_leaf(budget, date(2026, 1, 1), date(2026, 7, 19), distribution, SUNDAY_OFF)
        assert sum(shares.values()) == budget
        assert len(shares) == 171  # 200 gün − 29 Pazar (son gün 19.07 de Pazar)


def test_working_day_predicate_weekly_and_extra() -> None:
    pred = working_day_predicate(frozenset({5, 6}), frozenset({date(2026, 9, 9)}))
    assert pred(date(2026, 9, 8)) is True  # Salı
    assert pred(date(2026, 9, 9)) is False  # elle tatil
    assert pred(date(2026, 9, 12)) is False  # Cumartesi
    assert pred(date(2026, 9, 13)) is False  # Pazar


def test_working_day_predicate_defaults_to_sunday_and_has_no_range() -> None:
    pred = working_day_predicate()
    assert pred(date(1999, 1, 3)) is False  # Pazar, herhangi bir takvim aralığı yok
    assert pred(date(2100, 1, 2)) is True  # Cumartesi


def test_working_day_predicate_rejects_bad_dow() -> None:
    with pytest.raises(ValueError):
        working_day_predicate(frozenset({7}))


def test_expand_holiday_ranges() -> None:
    days = expand_holiday_ranges(
        [(date(2026, 5, 26), date(2026, 5, 30)), (date(2026, 7, 15), date(2026, 7, 15))]
    )
    assert days == frozenset([date(2026, 5, d) for d in range(26, 31)] + [date(2026, 7, 15)])
    assert expand_holiday_ranges([]) == frozenset()


def test_expand_holiday_ranges_rejects_reversed_range() -> None:
    with pytest.raises(ValueError):
        expand_holiday_ranges([(date(2026, 5, 30), date(2026, 5, 26))])


def test_spread_with_expanded_holidays() -> None:
    extra = expand_holiday_ranges([(date(2026, 9, 4), date(2026, 9, 5))])
    pred = working_day_predicate(frozenset({6}), extra)
    assert spread_leaf(D(100), S, E, Distribution.LINEAR, pred) == {
        date(2026, 9, 3): D(50),
        date(2026, 9, 7): D(50),
    }


def test_remainder_tie_goes_to_earliest_day() -> None:
    # 0,00001 / 4 = 0,0000025 → taban 0,000002 × 4 · 2 kuantum eksik · kesirler EŞİT
    shares = spread_leaf(D("0.00001"), S, E, Distribution.LINEAR, SUNDAY_OFF)
    assert list(shares.values()) == [D("0.000003"), D("0.000003"), D("0.000002"), D("0.000002")]


def test_sub_quantum_residue_goes_to_largest_share() -> None:
    # 100,0000005 (7 ondalık): artık 0,0000005 en büyük paya — doğrusalda eşit → en erken
    linear = spread_leaf(D("100.0000005"), S, E, Distribution.LINEAR, SUNDAY_OFF)
    assert list(linear.values()) == [D("25.0000005"), D(25), D(25), D(25)]
    # arkada en büyük pay son gün: ham ×1,000000005 → kesir 04.09 ,939 · 07.09 ,676 → +1e-6
    back = spread_leaf(D("100.0000005"), S, E, Distribution.BACK, SUNDAY_OFF)
    assert list(back.values()) == [
        D("1.351351"),
        D("14.864865"),
        D("28.378378"),
        D("55.4054065"),
    ]
    assert sum(back.values()) == D("100.0000005")


LONG_S, LONG_E = date(2026, 1, 1), date(2026, 7, 19)


@pytest.mark.parametrize("budget", ["0.00001234", "0.0001026"])
@pytest.mark.parametrize("distribution", list(Distribution), ids=lambda d: d.value)
def test_tiny_budget_never_gives_negative_share(budget: str, distribution: Distribution) -> None:
    shares = spread_leaf(D(budget), LONG_S, LONG_E, distribution, SUNDAY_OFF)
    assert len(shares) == 171
    assert min(shares.values()) >= 0
    assert sum(shares.values()) == D(budget)


def test_tiny_linear_budget_is_spread_not_dumped_on_last_day() -> None:
    # 0,00001234 / 171 gün → taban 0 · 12 kuantum eksik → EN ERKEN 12 iş günü (eşit kesir);
    # artık 0,00000034 en büyük (eşit) paylı en erken güne → 01.01 = 0,00000134
    shares = spread_leaf(D("0.00001234"), LONG_S, LONG_E, Distribution.LINEAR, SUNDAY_OFF)
    nonzero = [t for t, v in shares.items() if v]
    assert len(nonzero) == 12 and nonzero == sorted(shares)[:12]
    assert shares[LONG_S] == D("0.00000134")
    assert shares[max(shares)] == 0  # eski yöntem bütün bütçeyi buraya yığıyordu


def test_negative_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="negatif"):
        spread_leaf(D("-1"), S, E, Distribution.LINEAR, SUNDAY_OFF)
