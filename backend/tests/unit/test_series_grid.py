"""Tests for the month-end series grid (engine/stats/series_grid.py).  All data is SYNTHETIC.

Covers PLAN row A13: month-end selection, gaps (never filled), MDD and recovery durations in Decimal, the blended
path, and that a gold-style drawdown can be recomputed from a daily NAV history.
"""

from __future__ import annotations

import calendar
import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from iip.engine.errors import InsufficientHistory, InvalidInput, MissingData
from iip.engine.money import D, engine_context
from iip.engine.stats.series_grid import (
    DRAWDOWN_ONGOING,
    GAPS_PRESENT,
    MONTH_END_SAMPLING,
    PEAK_AT_SERIES_START,
    GapReason,
    Rebalance,
    SeriesGrid,
    blended_path,
    drawdown_episodes,
    grid_max_drawdown,
    max_drawdown_of_path,
    month_end_grid,
    months_between,
)


def me(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def month_path(levels: list[str], start: tuple[int, int] = (2001, 1)) -> list[tuple[date, Decimal]]:
    y, m = start
    out: list[tuple[date, Decimal]] = []
    for lv in levels:
        out.append((me(y, m), D(lv)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def daily(start: date, end: date, nav: str = "10") -> list[tuple[date, Decimal]]:
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append((d, D(nav)))
        d += timedelta(days=1)
    return out


# ----------------------------------------------------------------------------------------------- month-end selection


def test_selects_last_observation_in_each_month() -> None:
    obs = [
        (date(2020, 1, 2), "10"),
        (date(2020, 1, 30), "11"),
        (date(2020, 1, 31), "12"),
        (date(2020, 2, 3), "13"),
        (date(2020, 2, 28), "14"),  # Fri; 29-Feb-2020 is a Saturday
        (date(2020, 3, 31), "15"),
    ]
    g = month_end_grid(obs)
    assert [(c.month_end, c.obs_date, c.nav) for c in g.cells] == [
        (date(2020, 1, 31), date(2020, 1, 31), D("12")),
        (date(2020, 2, 29), date(2020, 2, 28), D("14")),
        (date(2020, 3, 31), date(2020, 3, 31), D("15")),
    ]
    assert g.gaps == () and g.trimmed == ()
    assert g.is_contiguous


def test_missing_month_is_a_gap_and_never_filled() -> None:
    obs = [(date(2020, 1, 31), "10"), (date(2020, 3, 31), "12")]
    g = month_end_grid(obs)
    assert [c.month_end for c in g.cells] == [date(2020, 1, 31), date(2020, 3, 31)]
    assert len(g.gaps) == 1
    gap = g.gaps[0]
    assert gap.month_end == date(2020, 2, 29)
    assert gap.reason is GapReason.NO_OBSERVATION
    assert gap.last_obs_date is None
    assert not g.is_contiguous


def test_stale_month_end_is_a_gap() -> None:
    # The last February observation is 10 days before month-end (> 7 default) → stale, not used.
    obs = [(date(2021, 1, 29), "10"), (date(2021, 2, 18), "11"), (date(2021, 3, 31), "12")]
    g = month_end_grid(obs)
    assert [c.month_end for c in g.cells] == [date(2021, 1, 31), date(2021, 3, 31)]
    assert g.gaps[0].reason is GapReason.STALE
    assert g.gaps[0].last_obs_date == date(2021, 2, 18)
    # A wider tolerance accepts it.
    g2 = month_end_grid(obs, max_staleness_days=10)
    assert g2.is_contiguous and g2.cells[1].nav == D("11")


def test_incomplete_final_month_is_trimmed_not_a_gap() -> None:
    obs = [(date(2022, 1, 31), "10"), (date(2022, 2, 28), "11"), (date(2022, 3, 10), "12")]
    g = month_end_grid(obs)
    assert [c.month_end for c in g.cells] == [date(2022, 1, 31), date(2022, 2, 28)]
    assert g.gaps == ()
    assert [(t.month_end, t.reason) for t in g.trimmed] == [(date(2022, 3, 31), GapReason.STALE)]


def test_leading_incomplete_month_is_trimmed() -> None:
    # Series starts on the 3rd and has nothing else in January after a pause → January stale at the edge.
    obs = [(date(2022, 1, 3), "10"), (date(2022, 2, 28), "11"), (date(2022, 3, 31), "12")]
    g = month_end_grid(obs)
    assert g.start_month == date(2022, 2, 28)
    assert [t.month_end for t in g.trimmed] == [date(2022, 1, 31)]


def test_rejects_unsorted_duplicate_nonpositive_and_float() -> None:
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2020, 2, 1), "1"), (date(2020, 1, 1), "1")])
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2020, 1, 31), "1"), (date(2020, 1, 31), "2")])
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2020, 1, 31), "0")])
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2020, 1, 31), 1.5)])  # type: ignore[list-item]
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2020, 1, 31), "1")], max_staleness_days=-1)


def test_no_valid_month_raises() -> None:
    with pytest.raises(InsufficientHistory):
        month_end_grid([(date(2020, 1, 2), "10")])
    with pytest.raises(InsufficientHistory):
        month_end_grid([])


def test_rows_roundtrip() -> None:
    obs = daily(date(2019, 12, 2), date(2020, 6, 30))
    g = month_end_grid(obs)
    rows = g.to_rows()
    assert rows[0] == ("2019-12-31", "2019-12-31", "10")
    g2 = SeriesGrid.from_rows(rows, max_staleness_days=g.max_staleness_days)
    assert g2.cells == g.cells and g2.gaps == g.gaps


def test_from_rows_records_interior_gaps_and_rejects_bad_rows() -> None:
    g = SeriesGrid.from_rows([("2020-01-31", "2020-01-31", "1"), ("2020-03-31", "2020-03-30", "2")])
    assert [x.month_end for x in g.gaps] == [date(2020, 2, 29)]
    with pytest.raises(InvalidInput):  # not a month-end key
        SeriesGrid.from_rows([("2020-01-30", "2020-01-30", "1")])
    with pytest.raises(InvalidInput):  # observation from another month
        SeriesGrid.from_rows([("2020-02-29", "2020-01-31", "1")])
    with pytest.raises(InvalidInput):  # staler than the tolerance
        SeriesGrid.from_rows([("2020-02-29", "2020-02-10", "1")])


def test_months_between() -> None:
    assert months_between(date(2000, 1, 31), date(2003, 10, 31)) == 45
    assert months_between(date(2008, 1, 31), date(2008, 1, 31)) == 0


# ----------------------------------------------------------------------------------------------- property tests

_obs_strategy = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=1500),
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=4),
    ),
    min_size=1,
    max_size=120,
    unique_by=lambda t: t[0],
)


def _build(raw: list[tuple[int, Decimal]]) -> list[tuple[date, Decimal]]:
    base = date(2005, 1, 1)
    return [(base + timedelta(days=k), v) for k, v in sorted(raw)]


@settings(max_examples=200, deadline=None)
@given(raw=_obs_strategy, tol=st.integers(min_value=0, max_value=20))
def test_property_month_end_selection(raw: list[tuple[int, Decimal]], tol: int) -> None:
    obs = _build(raw)
    try:
        g = month_end_grid(obs, max_staleness_days=tol)
    except InsufficientHistory:
        # Then no month's last observation is within tolerance of its month-end.
        by_month: dict[tuple[int, int], date] = {}
        for d, _ in obs:
            by_month[(d.year, d.month)] = d
        assert all((me(y, m) - d).days > tol for (y, m), d in by_month.items())
        return
    lookup = dict(obs)
    observed = set(lookup.values())
    for c in g.cells:
        # (1) the value is a real observation (never filled, never interpolated)
        assert lookup[c.obs_date] == c.nav and c.nav in observed
        # (2) it is the LAST observation of that calendar month
        later = [d for d, _ in obs if (d.year, d.month) == (c.month_end.year, c.month_end.month) and d > c.obs_date]
        assert later == []
        # (3) within tolerance of the calendar month-end
        assert 0 <= (c.month_end - c.obs_date).days <= tol
    # (4) cells + interior gaps cover every month between the first and last cell exactly once
    months = sorted([c.month_end for c in g.cells] + [x.month_end for x in g.gaps])
    assert months[0] == g.start_month and months[-1] == g.end_month
    assert len(months) == months_between(g.start_month, g.end_month) + 1
    assert len(set(months)) == len(months)
    # (5) every gap has a stated reason; a STALE gap names the real stale observation
    for x in g.gaps:
        if x.reason is GapReason.STALE:
            assert x.last_obs_date is not None and (x.month_end - x.last_obs_date).days > tol
        else:
            assert x.last_obs_date is None
    # (6) deterministic: rebuilding gives the identical grid
    assert month_end_grid(obs, max_staleness_days=tol) == g


@settings(max_examples=100, deadline=None)
@given(raw=_obs_strategy)
def test_property_earlier_intramonth_observations_do_not_change_month_end(raw: list[tuple[int, Decimal]]) -> None:
    obs = _build(raw)
    try:
        g = month_end_grid(obs)
    except InsufficientHistory:
        return
    last_per_month: dict[tuple[int, int], tuple[date, Decimal]] = {}
    for d, v in obs:
        last_per_month[(d.year, d.month)] = (d, v)
    thinned = sorted(last_per_month.values())
    assert month_end_grid(thinned) == g


# ----------------------------------------------------------------------------------------------- drawdown


def test_known_drawdown_and_recovery_durations() -> None:
    #           J     F     M     A     M     J     J
    path = month_path(["100", "120", "90", "60", "80", "120", "130"])
    dd = max_drawdown_of_path(path)
    assert dd.value == D("0.5")  # 1 − 60/120, exact in Decimal
    ep = dd.episode
    assert ep is not None
    assert ep.peak_month == me(2001, 2) and ep.trough_month == me(2001, 4)
    assert ep.recovery_month == me(2001, 6)
    assert (ep.peak_to_trough_months, ep.trough_to_recovery_months, ep.underwater_months) == (2, 2, 4)
    assert ep.recovered
    with engine_context():
        assert ep.recovery_years == D(4) / D(12)
    assert DRAWDOWN_ONGOING not in dd.caveats and MONTH_END_SAMPLING in dd.caveats


def test_ongoing_drawdown_has_no_recovery_and_counts_underwater_so_far() -> None:
    path = month_path(["100", "80", "70", "75"])
    dd = max_drawdown_of_path(path)
    ep = dd.episode
    assert ep is not None and not ep.recovered
    assert ep.recovery_month is None and ep.trough_to_recovery_months is None and ep.recovery_years is None
    assert ep.underwater_months == 3  # "at least 3 months" (ongoing)
    assert DRAWDOWN_ONGOING in dd.caveats and PEAK_AT_SERIES_START in dd.caveats


def test_monotone_rise_has_zero_drawdown() -> None:
    dd = max_drawdown_of_path(month_path(["1", "2", "2", "3"]))
    assert dd.value == D(0) and dd.episode is None and dd.episodes == ()


def test_multiple_episodes_listed_in_order_and_ties_pick_earliest() -> None:
    path = month_path(["100", "50", "100", "200", "100", "200"])
    eps = drawdown_episodes(path)
    assert [(e.peak_month, e.trough_month, e.recovery_month) for e in eps] == [
        (me(2001, 1), me(2001, 2), me(2001, 3)),
        (me(2001, 4), me(2001, 5), me(2001, 6)),
    ]
    assert max_drawdown_of_path(path).episode == eps[0]  # both 50 %; earliest wins


def test_equal_high_is_a_recovery() -> None:
    eps = drawdown_episodes(month_path(["10", "9", "10"]))
    assert len(eps) == 1 and eps[0].recovered and eps[0].recovery_month == me(2001, 3)


def test_path_validation() -> None:
    with pytest.raises(InsufficientHistory):
        max_drawdown_of_path(month_path(["1"]))
    with pytest.raises(InvalidInput):
        max_drawdown_of_path([(date(2001, 1, 15), D(1)), (date(2001, 2, 28), D(1))])
    with pytest.raises(InvalidInput):
        max_drawdown_of_path([(me(2001, 2), D(1)), (me(2001, 1), D(1))])
    with pytest.raises(InvalidInput):
        max_drawdown_of_path([(me(2001, 1), D(1)), (me(2001, 2), D(0))])


def test_grid_drawdown_fails_closed_on_interior_gap() -> None:
    obs = [(me(2001, 1), "100"), (me(2001, 3), "50"), (me(2001, 4), "100")]
    g = month_end_grid(obs)
    with pytest.raises(MissingData):
        grid_max_drawdown(g)
    dd = grid_max_drawdown(g, allow_gaps=True)
    assert GAPS_PRESENT in dd.caveats
    assert dd.value == D("0.5")
    ep = dd.episode
    assert ep is not None
    # Durations are calendar months, so a gap never shortens them.
    assert ep.peak_to_trough_months == 2 and ep.underwater_months == 3


def _brute_mdd(levels: list[Decimal]) -> Decimal:
    worst = Decimal(0)
    with engine_context():
        for j in range(len(levels)):
            peak = max(levels[: j + 1])
            worst = max(worst, 1 - levels[j] / peak)
    return worst


_levels = st.lists(st.decimals(min_value=Decimal("0.5"), max_value=Decimal("5000"), places=3), min_size=2, max_size=80)


@settings(max_examples=300, deadline=None)
@given(levels=_levels)
def test_property_mdd_and_recovery(levels: list[Decimal]) -> None:
    path = month_path([str(x) for x in levels])
    dd = max_drawdown_of_path(path)
    # (1) equals the brute-force definition, exactly (Decimal, no float)
    assert dd.value == _brute_mdd(levels)
    assert isinstance(dd.value, Decimal) and Decimal(0) <= dd.value < Decimal(1)
    eps = drawdown_episodes(path)
    if dd.value == 0:
        assert dd.episode is None and eps == ()
        return
    ep = dd.episode
    assert ep is not None and ep in eps
    assert ep.depth == dd.value
    idx = {d: i for i, (d, _) in enumerate(path)}
    pi, ti = idx[ep.peak_month], idx[ep.trough_month]
    # (2) peak is a running high, trough the lowest point after it before recovery
    assert levels[pi] == max(levels[: pi + 1])
    assert pi < ti and ep.trough_level == levels[ti] and ep.peak_level == levels[pi]
    with engine_context():
        assert 1 - ep.trough_level / ep.peak_level == ep.depth
    # (3) recovery is the FIRST month at or above the peak after the trough; none exists if ongoing
    after = [i for i in range(ti + 1, len(levels)) if levels[i] >= levels[pi]]
    if after:
        ri = after[0]
        assert ep.recovered and ep.recovery_month == path[ri][0]
        assert all(levels[i] < levels[pi] for i in range(pi + 1, ri))
        assert ep.underwater_months == ri - pi == ep.peak_to_trough_months + (ep.trough_to_recovery_months or 0)
        with engine_context():
            assert ep.recovery_years == Decimal(ri - pi) / Decimal(12)
    else:
        assert not ep.recovered and ep.recovery_month is None
        assert ep.underwater_months == len(levels) - 1 - pi
        assert DRAWDOWN_ONGOING in dd.caveats
    # (4) episodes are disjoint, ordered, and every depth ≤ MDD
    for a, b in itertools.pairwise(eps):
        assert a.recovery_month is not None and a.recovery_month <= b.peak_month
    assert all(e.depth <= dd.value for e in eps)
    # (5) scale invariance: multiplying the path by a constant leaves the MDD unchanged
    scaled = [(d, v * 7) for d, v in path]
    assert max_drawdown_of_path(scaled).value == dd.value


# ----------------------------------------------------------------------------------------------- blended path


def _grid(levels: list[str], start: tuple[int, int] = (2001, 1)) -> SeriesGrid:
    return month_end_grid(month_path(levels, start))


def test_blended_monthly_rebalance_exact() -> None:
    a = _grid(["100", "110", "99"])  # +10 %, −10 %
    b = _grid(["50", "50", "51"])  # 0 %, +2 %
    bp = blended_path({"eq": a, "debt": b}, {"eq": D("0.6"), "debt": D("0.4")}, rebalance=Rebalance.MONTHLY)
    assert [lv for _, lv in bp.path()] == [D(1), D("1.06"), D("1.06") * D("0.948")]
    assert bp.weights == (("debt", D("0.4")), ("eq", D("0.6")))


def test_blended_buy_and_hold_exact() -> None:
    a = _grid(["100", "110", "99"])
    b = _grid(["50", "50", "51"])
    bp = blended_path({"eq": a, "debt": b}, {"eq": D("0.6"), "debt": D("0.4")}, rebalance=Rebalance.NONE)
    assert [lv for _, lv in bp.path()] == [D(1), D("1.06"), D("0.6") * D("0.99") + D("0.4") * D("1.02")]


def test_blended_uses_common_window_only() -> None:
    a = _grid(["100", "110", "99", "120"], start=(2001, 1))
    b = _grid(["50", "51"], start=(2001, 2))
    bp = blended_path({"a": a, "b": b}, {"a": D("0.5"), "b": D("0.5")}, rebalance=Rebalance.MONTHLY)
    assert [d for d, _ in bp.path()] == [me(2001, 2), me(2001, 3)]


def test_blended_fails_closed() -> None:
    a = _grid(["100", "110", "99"])
    gappy = month_end_grid([(me(2001, 1), "1"), (me(2001, 3), "1")])
    w = {"a": D("0.5"), "b": D("0.5")}
    with pytest.raises(MissingData):
        blended_path({"a": a, "b": gappy}, w, rebalance=Rebalance.MONTHLY)
    with pytest.raises(InvalidInput):  # weights do not sum to 1
        blended_path({"a": a, "b": a}, {"a": D("0.5"), "b": D("0.6")}, rebalance=Rebalance.MONTHLY)
    with pytest.raises(InvalidInput):  # negative weight
        blended_path({"a": a, "b": a}, {"a": D("1.5"), "b": D("-0.5")}, rebalance=Rebalance.MONTHLY)
    with pytest.raises(InvalidInput):  # key mismatch
        blended_path({"a": a}, w, rebalance=Rebalance.MONTHLY)
    late = _grid(["1", "2"], start=(2005, 1))
    with pytest.raises(InsufficientHistory):  # no overlap
        blended_path({"a": a, "b": late}, w, rebalance=Rebalance.MONTHLY)


@settings(max_examples=100, deadline=None)
@given(levels=_levels, w=st.decimals(min_value=Decimal(0), max_value=Decimal(1), places=2))
def test_property_blend_with_itself_is_the_normalised_series(levels: list[Decimal], w: Decimal) -> None:
    g = _grid([str(x) for x in levels])
    for mode in (Rebalance.MONTHLY, Rebalance.NONE):
        bp = blended_path({"x": g, "y": g}, {"x": w, "y": 1 - w}, rebalance=mode)
        with engine_context():
            expected = [lv / levels[0] for lv in levels]
        got = [lv for _, lv in bp.path()]
        # Monthly compounding re-rounds each ratio at 34 digits, so compare with a relative tolerance.
        assert all(abs(a - b) <= Decimal("1e-28") * b for a, b in zip(got, expected, strict=True))
        mdd = max_drawdown_of_path(bp.path()).value
        assert abs(mdd - _brute_mdd(levels)) <= Decimal("1e-28")


def test_blended_drawdown_bounded_by_component_with_correlation_one() -> None:
    eq = _grid(["100", "60", "100"])  # −40 %
    cash = _grid(["10", "10", "10"])  # 0 %
    bp = blended_path({"eq": eq, "cash": cash}, {"eq": D("0.5"), "cash": D("0.5")}, rebalance=Rebalance.MONTHLY)
    assert max_drawdown_of_path(bp.path()).value == D("0.2")


# ----------------------------------------------------------------------------------------------- gold recompute


def test_gold_style_drawdown_recomputable_from_daily_navs() -> None:
    """A SYNTHETIC daily NAV history (AMFI-shaped: weekdays only, a holiday hole) reduces to a grid whose MDD and
    recovery match a hand computation.  No real gold values are used."""
    obs: list[tuple[date, Decimal]] = []
    month_nav = {
        (2012, 9): "100",
        (2012, 10): "104",  # peak
        (2012, 11): "95",
        (2012, 12): "88",
        (2013, 1): "80",
        (2013, 2): "78",  # trough: 1 − 78/104 = 0.25
        (2013, 3): "90",
        (2013, 4): "104",  # recovery (equal to the peak)
        (2013, 5): "110",
    }
    for (y, m), nav in month_nav.items():
        for d, _ in daily(date(y, m, 1), me(y, m)):
            obs.append((d, D(nav) - 1 if d.day < 15 else D(nav)))  # intra-month noise, below month-end value
    obs = [o for o in obs if o[0] != date(2013, 1, 31)]  # holiday on the last weekday: Jan uses the 30th
    g = month_end_grid(obs)
    assert g.is_contiguous and g.cells[4].obs_date == date(2013, 1, 30)
    dd = grid_max_drawdown(g)
    assert dd.value == D("0.25")
    ep = dd.episode
    assert ep is not None
    assert (ep.peak_month, ep.trough_month, ep.recovery_month) == (me(2012, 10), me(2013, 2), me(2013, 4))
    assert ep.underwater_months == 6 and ep.recovery_years == D("0.5")
    assert dd.path_start == me(2012, 9) and dd.path_end == me(2013, 5)
    assert dd.method_id == "MDD-GRID@1"
