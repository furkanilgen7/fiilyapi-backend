"""PLN-B3.1 — TEK GEÇİŞLİ seri (`compute_series`): panel/rapor trendleri tek çağrıda.

Girdi: `_fixture.py` (B0 kabul fikstürü, 10 gün, gün 4 = 06.09 Pazar tatil). as_of = gün 8
(2026-09-10): gün 9–10 GELECEK → gerçekleşen alanlar None, planlı dolu (gün 9'daki L2
girişi seriye GİRMEZ). Tolerans 0.

## Overall (yalnız direct; bütçe 500; eğri modu: KAB + MEK, Σ 500)
Gün başına earned = Σ qty × oran (L1–L4) · spent = T1 prorata payları + T1 unallocated
(gün 6) + D2 başlığı (direct). pf_roll_N = t'de biten son N İŞ günü Σearned / Σspent
(tatil = gün 4 pencereye GİRMEZ; takvim başında pencere eldeki iş günleriyle kısalır).

| gün  | e g | s g | e küm | s küm | pl g | pl küm | roll_7  | roll_3 | durum  |
|------|-----|-----|-------|-------|------|--------|---------|--------|--------|
| 1    | 20  | 22  | 20    | 22    | 30   | 30     | 20/22   | 20/22  | Late   |
| 2    | 18  | 18  | 38    | 40    | 30   | 60     | 38/40   | 38/40  | Late   |
| 3    | 30  | 32  | 68    | 72    | 30   | 90     | 68/72   | 68/72  | Late   |
| 4 T  | 0   | 0   | 68    | 72    | 0    | 90     | 68/72   | 68/72  | Late   |
| 5    | 42  | 32  | 110   | 104   | 35   | 125    | 110/104 | 90/82  | Late   |
| 6    | 30  | 28  | 140   | 132   | 35   | 160    | 140/132 | 102/92 | Late   |
| 7    | 60  | 36  | 200   | 168   | 40   | 200    | 200/168 | 132/96 | Normal |
| 8    | 20  | 10  | 220   | 178   | 90   | 290    | 220/178 | 110/74 | Late   |
| 9 G  | –   | –   | –     | –     | 100  | 390    | –       | –      | –      |
| 10 G | –   | –   | –     | –     | 110  | 500    | –       | –      | –      |
e = earned, s = spent, pl = plan, roll_N = pf_rolling (N iş günü).
plan % = pl / 500 · progress = earned küm / 500 · variance = progress − plan küm %.
pf_roll_3 gün 5 = gün {2, 3, 5} = (18+30+42)/(18+32+32); gün 4 (tatil) sayılsaydı {3, 4, 5}
= 72/64. pf_roll_7 gün 8 = iş günleri {1,2,3,5,6,7,8} = küm; 7 TAKVİM günü olsaydı {2..8} = 200/156.

## D1–own (D1 kökü, contractor own; direct: L1, L3, T1 unallocated; bütçe 300)
S1: KAB own payı 300/400 = ¾ → plan = ¾·KAB / (¾·400) = KAB / 400.
| gün  | e g | s g | e küm | s küm | pl g | pl küm | roll_7  | roll_3 | durum |
|------|-----|-----|-------|-------|------|--------|---------|--------|-------|
| 1    | 20  | 12  | 20    | 12    | 30   | 30     | 20/12   | 20/12  | Late  |
| 2    | 10  | 10  | 30    | 22    | 30   | 60     | 30/22   | 30/22  | Late  |
| 3    | 30  | 20  | 60    | 42    | 30   | 90     | 60/42   | 60/42  | Late  |
| 4 T  | 0   | 0   | 60    | 42    | 0    | 90     | 60/42   | 60/42  | Late  |
| 5    | 20  | 20  | 80    | 62    | 30   | 120    | 80/62   | 60/50  | Late  |
| 6    | 20  | 8   | 100   | 70    | 30   | 150    | 100/70  | 70/48  | Late  |
| 7    | 40  | 24  | 140   | 94    | 30   | 180    | 140/94  | 80/52  | Ahead |
| 8    | 20  | 10  | 160   | 104   | 70   | 250    | 160/104 | 80/42  | Late  |
| 9 G  | –   | –   | –     | –     | 70   | 320    | –       | –      | –     |
| 10 G | –   | –   | –     | –     | 80   | 400    | –       | –      | –     |
Gün 7 = B0 tablosu (`test_engine_fixture.py` §6): D1–own 140/300 − 180/400 = +1/60.

## K9 yaprak modu (`_fixture_leaf.py`) — planlı = kapsamdaki YAPRAK eğrilerinin toplamı
Overall (L1–L4, Σ 500): gün 45 55 55 0 65 40 40 70 70 60 · küm 45 100 155 155 220 260 300 370
440 500. D1–own (L1+L3, Σ 300): gün 45 45 45 0 45 20 20 30 30 20 · küm 45 90 135 135 180 200
220 250 280 300. (Eğri modunda D1–own KAB/400 olurdu — mod yanlış seçilirse ayrışır.)

## Tatilde giriş (varyant): gün 4'e L1 +10 m3 (earned 20) ve D2 direct +5 sa
Overall gün 4: earned/spent g 20/5 · küm 88/77 · pf_roll_3 = {1,2,3} = 68/72 (tatil değeri
pencereye GİRMEZ) · gün 5 pf_roll_3 = {2,3,5} = 90/82 (değişmez).

## BEKÇİ — birebir tutarlılık
Her gün t ve `compute_daily_report(t)`un HER KPI satırı için `scope_for_row(satır)` serisinin
t değeri satırla `==` (fikstür eğri/yaprak/karışık × tolerans 0/2 + rastgele ağaçlar).
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.earned_value.engine import (
    AllocationRule,
    CalendarSettings,
    ContractorType,
    EngineInput,
    HoursEntry,
    Node,
    PlannedMhr,
    QtyEntry,
    RowKind,
    Scope,
    ScopeSeries,
    SeriesResult,
    Status,
    compute_daily_report,
    compute_series,
    scope_for_row,
)

from ._fixture import END, START, build_input, day
from ._fixture_leaf import build_leaf_input

D = Decimal
OWN, SUBCON = ContractorType.OWN, ContractorType.SUBCON
LATE, NORMAL, AHEAD = Status.LATE, Status.NORMAL, Status.AHEAD
AS_OF = day(8)
OVERALL = Scope(label="overall")
D1_OWN = Scope(root="D1", contractor=OWN, label="d1-own")


def q(a: int | str, b: int | str) -> Decimal:
    return D(a) / D(b)


def _series(
    inp: EngineInput, scope: Scope, *, rolling: int = 7, as_of: date | None = AS_OF
) -> ScopeSeries:
    result = compute_series(inp, START, END, [scope], as_of=as_of, rolling_working_days=rolling)
    return result.get(scope)


# gün: earned g, spent g, earned küm, spent küm, plan g, plan küm, roll7 (a, b), roll3, durum
OVERALL_TABLE = {
    1: (20, 22, 20, 22, 30, 30, (20, 22), (20, 22), LATE),
    2: (18, 18, 38, 40, 30, 60, (38, 40), (38, 40), LATE),
    3: (30, 32, 68, 72, 30, 90, (68, 72), (68, 72), LATE),
    4: (0, 0, 68, 72, 0, 90, (68, 72), (68, 72), LATE),
    5: (42, 32, 110, 104, 35, 125, (110, 104), (90, 82), LATE),
    6: (30, 28, 140, 132, 35, 160, (140, 132), (102, 92), LATE),
    7: (60, 36, 200, 168, 40, 200, (200, 168), (132, 96), NORMAL),
    8: (20, 10, 220, 178, 90, 290, (220, 178), (110, 74), LATE),
}
D1_OWN_TABLE = {
    1: (20, 12, 20, 12, 30, 30, (20, 12), (20, 12), LATE),
    2: (10, 10, 30, 22, 30, 60, (30, 22), (30, 22), LATE),
    3: (30, 20, 60, 42, 30, 90, (60, 42), (60, 42), LATE),
    4: (0, 0, 60, 42, 0, 90, (60, 42), (60, 42), LATE),
    5: (20, 20, 80, 62, 30, 120, (80, 62), (60, 50), LATE),
    6: (20, 8, 100, 70, 30, 150, (100, 70), (70, 48), LATE),
    7: (40, 24, 140, 94, 30, 180, (140, 94), (80, 52), AHEAD),
    8: (20, 10, 160, 104, 70, 250, (160, 104), (80, 42), LATE),
}
#: scope, tablo, bütçe, planlı payda, gelecek günlerin (plan g, plan küm)
HAND = {
    "overall": (OVERALL, OVERALL_TABLE, 500, 500, {9: (100, 390), 10: (110, 500)}),
    "d1-own": (D1_OWN, D1_OWN_TABLE, 300, 400, {9: (70, 320), 10: (80, 400)}),
}


def _ratio(pair: tuple[int, int]) -> Decimal | None:
    a, b = pair
    return None if b == 0 else q(a, b)


@pytest.mark.parametrize("name", list(HAND))
@pytest.mark.parametrize("n", sorted(OVERALL_TABLE))
def test_hand_table_actual_days(name: str, n: int) -> None:
    scope, table, budget, plan_total, _ = HAND[name]
    ed, sd, ec, sc, pd, pc, roll7, roll3, status = table[n]
    p = _series(build_input(), scope).at(day(n))
    assert (p.day, p.is_holiday, p.is_future) == (day(n), n == 4, False)
    assert p.budget_mhr == budget
    assert (p.earned_day, p.spent_day, p.earned_cum, p.spent_cum) == (ed, sd, ec, sc)
    assert p.progress_pct_cum == q(ec, budget)
    assert (p.planned_pct_day, p.planned_pct_cum) == (q(pd, plan_total), q(pc, plan_total))
    assert p.variance == q(ec, budget) - q(pc, plan_total)
    assert p.status is status
    assert (p.pf_day, p.pf_cum) == (_ratio((ed, sd)), _ratio((ec, sc)))
    assert p.pf_rolling == _ratio(roll7)
    p3 = _series(build_input(), scope, rolling=3).at(day(n))
    assert p3.pf_rolling == _ratio(roll3)


@pytest.mark.parametrize("name", list(HAND))
@pytest.mark.parametrize("n", [9, 10])
def test_hand_table_future_days_have_plan_but_no_actuals(name: str, n: int) -> None:
    scope, _, budget, plan_total, future = HAND[name]
    p = _series(build_input(), scope).at(day(n))
    assert (p.is_future, p.budget_mhr) == (True, budget)
    actual = (p.earned_day, p.spent_day, p.earned_cum, p.spent_cum, p.progress_pct_cum)
    assert actual == (None,) * 5
    derived = (p.variance, p.status, p.pf_day, p.pf_cum, p.pf_rolling)
    assert derived == (None,) * 5
    pd, pc = future[n]
    assert (p.planned_pct_day, p.planned_pct_cum) == (q(pd, plan_total), q(pc, plan_total))


def test_as_of_none_means_no_future_and_day9_entry_counts() -> None:
    p = _series(build_input(), OVERALL, as_of=None).at(day(9))
    assert p.is_future is False
    assert (p.earned_day, p.earned_cum) == (10, 230)  # L2 gün 9: 5 × 2


LEAF_PLAN = {
    # scope: (gün serisi, Σ)
    "overall": (OVERALL, (45, 55, 55, 0, 65, 40, 40, 70, 70, 60), 500),
    "d1-own": (D1_OWN, (45, 45, 45, 0, 45, 20, 20, 30, 30, 20), 300),
}


@pytest.mark.parametrize("name", list(LEAF_PLAN))
def test_leaf_mode_plan_is_sum_of_leaf_curves_in_scope(name: str) -> None:
    scope, per_day, total = LEAF_PLAN[name]
    series = _series(build_leaf_input(), scope)
    cum = 0
    for n, mhr in enumerate(per_day, start=1):
        cum += mhr
        p = series.at(day(n))
        assert (p.planned_pct_day, p.planned_pct_cum) == (q(mhr, total), q(cum, total)), n


def _with_holiday_entries() -> EngineInput:
    base = build_input()
    return replace(
        base,
        qty_entries=(*base.qty_entries, QtyEntry("L1", day(4), D(10))),
        hours_entries=(
            *base.hours_entries,
            HoursEntry("D2", day(4), D(5), AllocationRule.DIRECT),
        ),
    )


def test_rolling_window_skips_holiday_even_with_entries() -> None:
    series = _series(_with_holiday_entries(), OVERALL, rolling=3)
    p4, p5 = series.at(day(4)), series.at(day(5))
    assert (p4.earned_day, p4.spent_day, p4.earned_cum, p4.spent_cum) == (20, 5, 88, 77)
    assert p4.pf_day == 4
    assert p4.pf_rolling == q(68, 72)  # {1, 2, 3}: tatil değeri pencereye girmez
    assert p5.pf_rolling == q(90, 82)  # {2, 3, 5}


def test_window_bounds_and_order() -> None:
    result = compute_series(build_input(), day(3), day(6), [OVERALL, D1_OWN], as_of=AS_OF)
    assert isinstance(result, SeriesResult)
    assert [s.scope for s in result.series] == [OVERALL, D1_OWN]
    assert [p.day for p in result.get(OVERALL).points] == [day(3), day(4), day(5), day(6)]
    # pencere başlangıcı kümülatifi SIFIRLAMAZ: küm takvim başından
    assert result.get(OVERALL).at(day(3)).earned_cum == 68
    with pytest.raises(KeyError):
        result.get(OVERALL).at(day(7))


def test_scope_label_does_not_change_identity() -> None:
    assert Scope(label="a") == Scope(label="b") == Scope()
    result = compute_series(build_input(), START, END, [Scope(label="x")])
    assert result.get(Scope()).scope.label == "x"


def test_empty_scope_gives_zero_budget_and_none_ratios() -> None:
    scope = Scope(root="D2", contractor=SUBCON)  # D2'de subcon yaprağı yok
    p = _series(build_input(), scope).at(day(7))
    assert (p.budget_mhr, p.earned_cum, p.spent_cum) == (0, 0, 0)
    assert (p.progress_pct_cum, p.pf_cum, p.pf_rolling, p.status) == (None,) * 4


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"start": day(5), "end": day(4)}, "start"),
        ({"start": START - timedelta(days=1), "end": END}, "takvim"),
        ({"start": START, "end": END + timedelta(days=1)}, "takvim"),
        ({"start": START, "end": END, "rolling_working_days": 0}, "rolling"),
        ({"start": START, "end": END, "scopes": [Scope(root="T1")]}, "kök"),
        ({"start": START, "end": END, "scopes": [Scope(root="ZZ")]}, "kök"),
    ],
)
def test_invalid_arguments_are_rejected(kwargs: dict[str, object], match: str) -> None:
    args: dict[str, object] = {"scopes": [OVERALL], **kwargs}
    with pytest.raises(ValueError, match=match):
        compute_series(build_input(), **args)  # type: ignore[arg-type]


def test_scope_rejects_contradictory_directness() -> None:
    with pytest.raises(ValueError, match="indirect_only"):
        Scope(direct_only=True, indirect_only=True)
    with pytest.raises(TypeError, match="contractor"):
        Scope(contractor="own")  # type: ignore[arg-type]


def test_scope_for_row_maps_every_kpi_row() -> None:
    report = compute_daily_report(build_input(), day(7))
    got = {(r.kind, r.node_id): scope_for_row(r) for r in report.rows}
    assert got == {
        (RowKind.OVERALL, None): Scope(),
        (RowKind.OVERALL_OWN, None): Scope(contractor=OWN),
        (RowKind.OVERALL_SUBCON, None): Scope(contractor=SUBCON),
        (RowKind.DISCIPLINE, "D1"): Scope(root="D1"),
        (RowKind.DISCIPLINE_OWN, "D1"): Scope(root="D1", contractor=OWN),
        (RowKind.DISCIPLINE_SUBCON, "D1"): Scope(root="D1", contractor=SUBCON),
        (RowKind.DISCIPLINE, "D2"): Scope(root="D2"),
        (RowKind.NON_DIRECT, None): Scope(direct_only=False, indirect_only=True),
    }


# --- BEKÇİ: seri == günlük rapor, her gün × her KPI satırı -----------------------------

ROW_FIELDS = (
    "budget_mhr",
    "earned_day",
    "spent_day",
    "earned_cum",
    "spent_cum",
    "progress_pct_cum",
    "planned_pct_day",
    "planned_pct_cum",
    "variance",
    "status",
    "pf_day",
    "pf_cum",
)


def _assert_series_matches_daily_reports(inp: EngineInput) -> int:
    first, last = inp.calendar.start_date, inp.calendar.end_date
    scopes = [scope_for_row(r) for r in compute_daily_report(inp, first).rows]
    result = compute_series(inp, first, last, scopes)
    checked = 0
    t = first
    while t <= last:
        report = compute_daily_report(inp, t)
        assert len(report.rows) == len(scopes)
        for row in report.rows:
            p = result.get(scope_for_row(row)).at(t)
            assert p.is_holiday is report.position.is_holiday
            for name in ROW_FIELDS:
                assert getattr(p, name) == getattr(row, name), (t, row.kind, row.node_id, name)
                checked += 1
        t += timedelta(days=1)
    return checked


@pytest.mark.parametrize("tolerance", [D(0), D(2)])
@pytest.mark.parametrize("mode", ["egri", "yaprak", "karisik"])
def test_series_equals_daily_report_on_fixture(mode: str, tolerance: Decimal) -> None:
    inp = (
        build_input(tolerance)
        if mode == "egri"
        else build_leaf_input(mixed=mode == "karisik", tolerance_points=tolerance)
    )
    assert _assert_series_matches_daily_reports(inp) == 10 * 8 * len(ROW_FIELDS)


def _random_input(seed: int, plan_mode: str) -> EngineInput:
    rng = random.Random(seed)
    start = date(2026, 3, 2)
    days = 45
    nodes: list[Node] = []
    leaves: list[str] = []
    headers: list[str] = []
    curves = ("K", "M", None)

    def grow(parent: str | None, depth: int, prefix: str) -> None:
        for k in range(rng.randint(1, 3) if depth else rng.randint(2, 4)):
            node_id = f"{prefix}{k}"
            kind = rng.choice(tuple(ContractorType))
            if depth >= 3 or (depth > 0 and rng.random() < 0.35):
                rate = None if rng.random() < 0.05 else D(rng.randint(5, 300)) / 100
                nodes.append(
                    Node(
                        node_id,
                        parent,
                        uom=rng.choice(("m3", "m3", "t")),
                        planned_qty=D(rng.randint(10, 500)),
                        unit_mhr=rate,
                        contractor_type=kind,
                        is_direct=rng.random() > 0.15,
                    )
                )
                leaves.append(node_id)
            else:
                curve = rng.choice(curves) if depth == 0 else None
                is_direct = rng.random() > 0.2
                nodes.append(
                    Node(
                        node_id,
                        parent,
                        contractor_type=kind,
                        is_direct=is_direct,
                        curve_discipline=curve,
                    )
                )
                headers.append(node_id)
                grow(node_id, depth + 1, node_id + ".")

    grow(None, 0, "N")

    def when() -> date:
        return start + timedelta(days=rng.randrange(days))

    qty = [
        QtyEntry(leaf, when(), D(rng.randint(-5, 40)) / 4)
        for leaf in leaves
        for _ in range(rng.randint(0, 15))
    ]
    hours = [
        HoursEntry(
            rng.choice(leaves + headers),
            when(),
            D(rng.randint(1, 120)) / 10,
            rng.choice(tuple(AllocationRule)),
        )
        for _ in range(200)
    ]
    curve_points = [
        PlannedMhr(c, when(), D(rng.randint(0, 60)) / 2) for c in ("K", "M") for _ in range(30)
    ]
    leaf_points = [
        PlannedMhr.for_leaf(leaf, when(), D(rng.randint(1, 60)) / 2)
        for leaf in leaves
        if rng.random() < 0.8
        for _ in range(rng.randint(1, 8))
    ]
    planned = {
        "egri": curve_points,
        "yaprak": leaf_points,
        "karisik": [*curve_points, *leaf_points],
    }[plan_mode]
    calendar = CalendarSettings(
        start,
        start + timedelta(days=days - 1),
        week_start_dow=rng.randrange(7),
        weekly_holidays=frozenset({5, 6}) if seed % 2 else None,
        extra_holidays=frozenset({when(), when()}),
    )
    return EngineInput(
        calendar=calendar,
        nodes=tuple(nodes),
        qty_entries=tuple(qty),
        hours_entries=tuple(hours),
        planned_mhr=tuple(planned),
        tolerance_points=D(rng.choice((0, 1, 2))),
    )


@pytest.mark.parametrize("plan_mode", ["egri", "yaprak", "karisik"])
@pytest.mark.parametrize("seed", range(8))
def test_series_equals_daily_report_on_random_trees(seed: int, plan_mode: str) -> None:
    inp = _random_input(seed, plan_mode)
    assert _assert_series_matches_daily_reports(inp) > 45 * 3 * len(ROW_FIELDS)


def test_random_generator_exercises_the_interesting_cases() -> None:
    """Bekçi kör olmasın: rastgele ağaçlar karma disiplin, dolaylı satır, tatil girişi taşır."""
    kinds: set[RowKind] = set()
    holiday_entries = 0
    for seed in range(8):
        inp = _random_input(seed, "egri")
        report = compute_daily_report(inp, inp.calendar.end_date)
        kinds |= {r.kind for r in report.rows}
        extra = inp.calendar.extra_holidays
        holiday_entries += sum(e.day in extra for e in inp.qty_entries)
    assert kinds == set(RowKind)
    assert holiday_entries > 0


def test_rolling_equals_bruteforce_on_random_tree() -> None:
    """pf_rolling = son N iş günü (tatil hariç) Σearned_day / Σspent_day — kaba kuvvetle."""
    inp = _random_input(3, "egri")
    first, last = inp.calendar.start_date, inp.calendar.end_date
    for n in (1, 5, 7):
        series = compute_series(inp, first, last, [Scope()], rolling_working_days=n).get(Scope())
        work = [p for p in series.points if not p.is_holiday]
        for p in series.points:
            window = [w for w in work if w.day <= p.day][-n:]
            earned = sum((w.earned_day for w in window if w.earned_day is not None), D(0))
            spent = sum((w.spent_day for w in window if w.spent_day is not None), D(0))
            expected = None if not window or spent == 0 else earned / spent
            assert p.pf_rolling == expected, (n, p.day)
