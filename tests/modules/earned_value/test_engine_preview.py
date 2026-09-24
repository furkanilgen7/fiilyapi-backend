"""PLN-B1.1 — bütçe ÖNİZLEMESİ: S-eğrisi + gereken işçi histogramı (spec §2.5, K10).

## Elle hesap — hafta başı Pazartesi · tatil Pazar · standart gün 9 sa

| yaprak | disiplin | bütçe | pencere           | dağılım  | yayma                               |
|--------|----------|-------|-------------------|----------|-------------------------------------|
| A      | KAB      | 90    | 03.09 Per – 05.09 | doğrusal | 3 iş günü × 30                      |
| B      | KAB      | 108   | 07.09 Pzt – 12.09 | doğrusal | 6 iş günü × 18                      |
| C      | MEK      | 54    | 10.09 Per – 15.09 | doğrusal | 10,11,12,14,15 (13 Pazar) × 10,8    |
| X      | MEK      | 40    | 03.09 – 15.09     | doğrusal | is_direct=False → EĞRİYE GİRMEZ (S3)|
| Z      | MEK      | 20    | 13.09 – 13.09 Paz | doğrusal | iş günü yok → `unspreadable`        |

Aralık = eğriye giren yaprak pencerelerinin birleşimi: 03.09 – 15.09.
Toplam doğrudan = 90 + 108 + 54 = 252 · KAB 198 (pay 11/14) · MEK 54 (pay 3/14) · dolaylı 40.

Günlük toplam: 03–05: 30 · 06: 0 · 07–09: 18 · 10–12: 28,8 · 13: 0 · 14–15: 10,8.
Kümülatif 09.09 = 90 + 3×18 = 144 → planned_pct_cum = 144/252 = 4/7.

Haftalık kova (ilk hafta kısmi: hafta başı aralık başından önce olmaz; son hafta aralık
sonuna kırpılır — `policy.WEEK_LOAD_CLIPPED_TO_RANGE_END`):

kişi = a-s ÷ (iş günü × 9):

| hafta | aralık        | iş günü | toplam a-s · kişi  | KAB a-s · kişi | MEK a-s · kişi |
|-------|---------------|---------|--------------------|----------------|----------------|
| 1     | 03.09 – 06.09 | 3       | 90 · 90/27 = 3,33… | 90 · 90/27     | 0 · 0          |
| 2     | 07.09 – 13.09 | 6       | 140,4 · 2,6        | 108 · 2        | 32,4 · 0,6     |
| 3     | 14.09 – 15.09 | 2       | 21,6 · 1,2         | 0 · 0          | 21,6 · 1,2     |

Tepe hafta: toplam H1 (3,33) · KAB H1 · MEK H3 (1,2 > 0,6).
Başlangıç/bitiş (sıfır olmayan en erken/en geç gün): KAB 03.09 – 12.09 · MEK 10.09 – 15.09.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    Distribution,
    SpreadLeaf,
    SpreadPreview,
    compute_spread_preview,
    preview_from_curves,
)

D = Decimal
LIN = Distribution.LINEAR


def d(day: int) -> date:
    return date(2026, 9, day)


def q(a: int | str, b: int | str) -> Decimal:
    return D(a) / D(b)


LEAVES = (
    SpreadLeaf("A", "KAB", D(90), d(3), d(5), LIN, is_direct=True),
    SpreadLeaf("B", "KAB", D(108), d(7), d(12), LIN, is_direct=True),
    SpreadLeaf("C", "MEK", D(54), d(10), d(15), LIN, is_direct=True),
    SpreadLeaf("X", "MEK", D(40), d(3), d(15), LIN, is_direct=False),
    SpreadLeaf("Z", "MEK", D(20), d(13), d(13), LIN, is_direct=True),
)


@pytest.fixture(scope="module")
def pv() -> SpreadPreview:
    return compute_spread_preview(LEAVES)


def test_leaf_curves_and_exclusions(pv: SpreadPreview) -> None:
    assert set(pv.leaf_curves) == {"A", "B", "C"}  # X dolaylı, Z iş günsüz
    assert pv.leaf_curves["A"] == {d(3): 30, d(4): 30, d(5): 30}
    assert pv.leaf_curves["C"] == {day: D("10.8") for day in (d(10), d(11), d(12), d(14), d(15))}
    assert pv.unspreadable == ("Z",)
    assert pv.indirect_budget_mhr == 40
    for leaf in LEAVES[:3]:
        assert sum(pv.leaf_curves[leaf.node_id].values()) == leaf.budget


def test_range_and_budgets(pv: SpreadPreview) -> None:
    assert (pv.start, pv.end) == (d(3), d(15))
    assert pv.total.budget_mhr == 252
    kab, mek = pv.disciplines["KAB"], pv.disciplines["MEK"]
    assert list(pv.disciplines) == ["KAB", "MEK"]
    assert (kab.series.budget_mhr, mek.series.budget_mhr) == (198, 54)
    assert (kab.share, mek.share) == (q(198, 252), q(54, 252))
    assert (kab.series.start, kab.series.end) == (d(3), d(12))
    assert (mek.series.start, mek.series.end) == (d(10), d(15))
    assert (pv.total.start, pv.total.end) == (d(3), d(15))


def test_daily_and_cumulative_series(pv: SpreadPreview) -> None:
    total = pv.total
    expected_daily = [30, 30, 30, 0, 18, 18, 18, "28.8", "28.8", "28.8", 0, "10.8", "10.8"]
    assert list(total.daily) == [d(n) for n in range(3, 16)]  # aralıkta her takvim günü
    assert list(total.daily.values()) == [D(v) for v in expected_daily]
    assert total.cumulative[d(9)] == 144
    assert total.cumulative[d(15)] == 252
    assert total.planned_pct_cum[d(9)] == q(144, 252)
    assert total.planned_pct_cum[d(15)] == 1
    mek = pv.disciplines["MEK"].series
    assert mek.daily[d(3)] == 0 and mek.cumulative[d(12)] == D("32.4")
    assert mek.planned_pct_cum[d(12)] == q("32.4", 54)


def test_sums_are_exact(pv: SpreadPreview) -> None:
    discipline_sum = sum((sum(p.series.daily.values()) for p in pv.disciplines.values()), D(0))
    leaf_sum = sum((sum(c.values()) for c in pv.leaf_curves.values()), D(0))
    assert discipline_sum == leaf_sum == sum(pv.total.daily.values()) == 252


def test_weekly_required_people(pv: SpreadPreview) -> None:
    weeks = pv.total.weeks
    assert [(w.week_no, w.week_start, w.week_end, w.working_days) for w in weeks] == [
        (1, d(3), d(6), 3),
        (2, d(7), d(13), 6),
        (3, d(14), d(15), 2),
    ]
    assert [w.mhr for w in weeks] == [90, D("140.4"), D("21.6")]
    assert [w.required_people for w in weeks] == [q(90, 27), D("2.6"), D("1.2")]
    kab = pv.disciplines["KAB"].series.weeks
    mek = pv.disciplines["MEK"].series.weeks
    assert [w.required_people for w in kab] == [q(90, 27), 2, 0]
    assert [w.required_people for w in mek] == [0, D("0.6"), D("1.2")]


def test_peak_weeks(pv: SpreadPreview) -> None:
    assert pv.total.peak_week is not None and pv.total.peak_week.week_no == 1
    kab_peak = pv.disciplines["KAB"].series.peak_week
    mek_peak = pv.disciplines["MEK"].series.peak_week
    assert kab_peak is not None and kab_peak.week_no == 1
    assert mek_peak is not None and mek_peak.week_no == 3
    assert mek_peak.required_people == D("1.2")


def test_standard_daily_hours_is_the_divisor() -> None:
    pv = compute_spread_preview(LEAVES, standard_daily_hours=D(8))
    assert pv.total.weeks[1].required_people == D("140.4") / D(48)


def test_peak_tie_takes_earliest_week() -> None:
    # iki tam hafta (Pzt–Cmt), her biri 54 a-s → 1 kişi; eşitlikte en erken
    leaves = (
        SpreadLeaf("A", "K", D(54), d(7), d(12), LIN, is_direct=True),
        SpreadLeaf("B", "K", D(54), d(14), d(19), LIN, is_direct=True),
    )
    pv = compute_spread_preview(leaves)
    assert [w.required_people for w in pv.total.weeks] == [1, 1]
    assert pv.total.peak_week is not None and pv.total.peak_week.week_no == 1


def test_week_without_working_day_has_none_people() -> None:
    # aralık Pazar başlıyor: 1. hafta yalnız 06.09 (tatil) → iş günü 0 → kişi None
    leaves = (SpreadLeaf("A", "K", D(18), d(6), d(8), LIN, is_direct=True),)
    pv = compute_spread_preview(leaves)
    first = pv.total.weeks[0]
    assert (first.week_start, first.week_end, first.working_days) == (d(6), d(6), 0)
    assert (first.mhr, first.required_people) == (0, None)
    assert pv.total.start == d(7)  # sıfır olmayan en erken gün


def test_week_start_dow_follows_setting() -> None:
    # hafta başı Perşembe (3): 03.09 Per – 09.09 Çar tam hafta
    pv = compute_spread_preview(LEAVES, week_start_dow=3)
    assert [(w.week_start, w.week_end) for w in pv.total.weeks] == [
        (d(3), d(9)),
        (d(10), d(15)),
    ]


def test_extra_holidays_are_zero_weight() -> None:
    pv = compute_spread_preview(LEAVES[:1], extra_holidays=frozenset({d(4)}))
    assert pv.leaf_curves["A"] == {d(3): 45, d(5): 45}
    assert pv.total.weeks[0].working_days == 2


def test_empty_preview() -> None:
    pv = compute_spread_preview(LEAVES[3:])  # yalnız dolaylı + iş günsüz
    assert pv.leaf_curves == {} and pv.disciplines == {}
    assert (pv.start, pv.end) == (None, None)
    assert pv.total.budget_mhr == 0 and pv.total.weeks == ()
    assert pv.total.peak_week is None and pv.total.start is None
    assert pv.unspreadable == ("Z",)


def test_share_is_none_when_total_is_zero() -> None:
    leaves = (SpreadLeaf("A", "K", D(0), d(7), d(8), LIN, is_direct=True),)
    pv = compute_spread_preview(leaves)
    assert pv.disciplines["K"].share is None
    assert pv.total.planned_pct_cum[d(7)] is None
    assert pv.total.peak_week is None


def test_duplicate_leaf_is_rejected() -> None:
    with pytest.raises(ValueError, match="tekrar"):
        compute_spread_preview((LEAVES[0], LEAVES[0]))


def test_spread_leaf_validation() -> None:
    with pytest.raises(TypeError):
        SpreadLeaf("A", "K", 1.5, d(3), d(4), LIN, is_direct=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SpreadLeaf("A", "K", D(1), d(4), d(3), LIN, is_direct=True)
    with pytest.raises(TypeError):
        SpreadLeaf("A", "K", D(1), d(3), d(4), "linear", is_direct=True)  # type: ignore[arg-type]


def test_standard_daily_hours_must_be_positive_decimal() -> None:
    with pytest.raises(ValueError):
        compute_spread_preview(LEAVES, standard_daily_hours=D(0))
    with pytest.raises(TypeError):
        compute_spread_preview(LEAVES, standard_daily_hours=9.0)  # type: ignore[arg-type]


def test_long_preview_sums_stay_exact() -> None:
    start = date(2026, 1, 1)
    leaves = tuple(
        SpreadLeaf(
            f"L{i}",
            f"D{i % 3}",
            D(1000 + 37 * i) * D("0.0125"),  # qty × oran: sonlu ondalık (DB Numeric)
            start + timedelta(days=i),
            start + timedelta(days=i + 90),
            list(Distribution)[i % 4],
            is_direct=True,
        )
        for i in range(40)
    )
    pv = compute_spread_preview(leaves)
    for leaf in leaves:
        assert sum(pv.leaf_curves[leaf.node_id].values()) == leaf.budget
    assert sum(pv.total.daily.values()) == sum((lf.budget for lf in leaves), D(0))
    assert sum((w.mhr for w in pv.total.weeks), D(0)) == pv.total.budget_mhr


# --- K8: donmuş revizyonun önizlemesi snapshot eğrisinden (yeniden YAYILMAZ) --------------


def _disciplines_of(leaves: tuple[SpreadLeaf, ...]) -> dict[str, str]:
    return {leaf.node_id: leaf.discipline for leaf in leaves}


def test_preview_from_curves_matches_spread_preview(pv: SpreadPreview) -> None:
    frozen = preview_from_curves(pv.leaf_curves, _disciplines_of(LEAVES), indirect_budget_mhr=D(40))
    assert frozen.disciplines == pv.disciplines
    assert frozen.total == pv.total
    assert (frozen.start, frozen.end) == (pv.start, pv.end)
    assert frozen.leaf_curves == pv.leaf_curves
    assert frozen.indirect_budget_mhr == 40
    assert frozen.unspreadable == ()


def test_preview_from_curves_matches_on_long_mixed_distributions() -> None:
    leaves = tuple(
        SpreadLeaf(
            f"L{i}",
            f"D{i % 3}",
            D(1000 + 37 * i) * D("0.0125"),
            date(2026, 1, 5) + timedelta(days=i),  # Pazartesi başlar → aralık uçları iş günü
            date(2026, 1, 5) + timedelta(days=i + 89),
            list(Distribution)[i % 4],
            is_direct=True,
        )
        for i in range(0, 42, 7)  # her pencere Pzt başlar, Cmt biter (uçlar iş günü)
    )
    pv = compute_spread_preview(leaves, week_start_dow=3, standard_daily_hours=D("7.5"))
    frozen = preview_from_curves(
        pv.leaf_curves,
        _disciplines_of(leaves),
        week_start_dow=3,
        standard_daily_hours=D("7.5"),
    )
    assert (frozen.disciplines, frozen.total) == (pv.disciplines, pv.total)


def test_preview_from_curves_range_can_be_given() -> None:
    # pencere Pazar başlıyor: eğri 07.09'dan başlar ama aralık 06.09 → range verilmeli
    leaves = (SpreadLeaf("A", "K", D(18), d(6), d(8), LIN, is_direct=True),)
    pv = compute_spread_preview(leaves)
    implied = preview_from_curves(pv.leaf_curves, {"A": "K"})
    assert implied.start == d(7)  # varsayılan: eğri günlerinin min/max'ı
    given = preview_from_curves(pv.leaf_curves, {"A": "K"}, start=d(6), end=d(8))
    assert (given.total, given.disciplines) == (pv.total, pv.disciplines)


def test_preview_from_curves_validation() -> None:
    with pytest.raises(ValueError, match="disiplin"):
        preview_from_curves({"A": {d(7): D(1)}}, {})
    with pytest.raises(TypeError):
        preview_from_curves({"A": {d(7): 1.0}}, {"A": "K"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="aralik"):
        preview_from_curves({"A": {d(7): D(1)}}, {"A": "K"}, start=d(8), end=d(9))


def test_preview_from_curves_empty() -> None:
    frozen = preview_from_curves({}, {}, indirect_budget_mhr=D(5))
    assert (frozen.start, frozen.disciplines, frozen.indirect_budget_mhr) == (None, {}, 5)
    assert frozen.total.weeks == ()
