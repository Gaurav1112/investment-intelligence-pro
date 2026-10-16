"""TA-2 graft (reference-tradingagents.md): half-open ``[start, end)`` windows, IST-aware date conversion (never
truncate an offset-aware timestamp), undated rows excluded from backtests, and an empty-after-filter result reported
explicitly instead of blank.  Covers engine/stats/series_grid.py and engine/backtest/walkforward.py.

All data is SYNTHETIC: fictional role keys, NAVs and rule ids only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from iip.engine.backtest import walkforward as wf
from iip.engine.errors import InsufficientHistory, InvalidInput
from iip.engine.stats.series_grid import IST, SeriesGrid, month_end_grid, to_ist_date

D = Decimal
RISK, LIQ = "fixture.risk", "fixture.liquid"
NEW_YORK_WINTER = timezone(timedelta(hours=-5))


# ============================================================================================== IST conversion


def test_ist_is_a_fixed_offset_of_five_thirty() -> None:
    assert IST.utcoffset(None) == timedelta(hours=5, minutes=30)


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        # 18:29:59Z is 23:59:59 IST on the same day; 18:30Z is already the next IST day.
        (datetime(2024, 1, 31, 18, 29, 59, tzinfo=UTC), date(2024, 1, 31)),
        (datetime(2024, 1, 31, 18, 30, tzinfo=UTC), date(2024, 2, 1)),
        (datetime(2024, 1, 31, 20, 0, tzinfo=UTC), date(2024, 2, 1)),
        # A US-evening timestamp is the next IST morning (truncating in its own zone would say 31 Jan).
        (datetime(2024, 1, 31, 19, 0, tzinfo=NEW_YORK_WINTER), date(2024, 2, 1)),
        # Already IST: just the date.
        (datetime(2024, 1, 31, 23, 59, tzinfo=IST), date(2024, 1, 31)),
        (date(2024, 1, 31), date(2024, 1, 31)),
        ("2024-01-31", date(2024, 1, 31)),
        ("2024-01-31T20:00:00Z", date(2024, 2, 1)),
        ("2024-01-31T20:00:00+00:00", date(2024, 2, 1)),
        ("2024-02-01T01:00:00+05:30", date(2024, 2, 1)),
    ],
)
def test_offset_aware_timestamps_are_converted_to_ist_never_truncated(stamp: object, expected: date) -> None:
    assert to_ist_date(stamp) == expected


@pytest.mark.parametrize(
    "bad",
    [datetime(2024, 1, 31, 20, 0), "2024-01-31T20:00:00", "2024-01-31 20:00", None, "", "31/01/2024", 20240131],
)
def test_naive_unparseable_or_missing_dates_are_refused(bad: object) -> None:
    with pytest.raises(InvalidInput):
        to_ist_date(bad)


def test_month_end_grid_buckets_an_aware_timestamp_by_its_ist_day() -> None:
    obs = [
        (date(2024, 1, 31), D("10")),
        (datetime(2024, 2, 29, 6, 0, tzinfo=UTC), D("11")),  # 29 Feb IST
        (datetime(2024, 3, 31, 20, 0, tzinfo=UTC), D("12")),  # 1 Apr IST, not 31 Mar
    ]
    grid = month_end_grid(obs)
    assert [(c.month_end, c.obs_date) for c in grid.cells] == [
        (date(2024, 1, 31), date(2024, 1, 31)),
        (date(2024, 2, 29), date(2024, 2, 29)),
    ]
    # March has no IST observation; April's only one is 29 days stale. Both are edge-trimmed, never filled.
    assert [g.month_end for g in grid.trimmed] == [date(2024, 3, 31), date(2024, 4, 30)]


def test_month_end_grid_still_refuses_naive_timestamps_and_undated_rows() -> None:
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2024, 1, 31), D(1)), (datetime(2024, 2, 29, 20, 0), D(1))])
    with pytest.raises(InvalidInput):
        month_end_grid([(date(2024, 1, 31), D(1)), (None, D(1))])  # type: ignore[list-item]


def test_two_timestamps_on_one_ist_day_are_a_duplicate() -> None:
    with pytest.raises(InvalidInput, match="strictly increasing"):
        month_end_grid(
            [
                (datetime(2024, 1, 30, 19, 0, tzinfo=UTC), D(1)),  # 31 Jan 00:30 IST
                (datetime(2024, 1, 31, 10, 0, tzinfo=UTC), D(2)),  # 31 Jan 15:30 IST
            ]
        )


def test_grid_rows_with_offset_timestamps_are_checked_on_their_ist_day() -> None:
    # Stored obs 2024-01-31T20:00Z is 1 Feb IST: it cannot be January's month-end value.
    with pytest.raises(InvalidInput, match="not in month"):
        SeriesGrid.from_rows([("2024-01-31", "2024-01-31T20:00:00+00:00", "10")])
    grid = SeriesGrid.from_rows([("2024-01-31", "2024-01-31T12:00:00+00:00", "10")])
    assert grid.cells[0].obs_date == date(2024, 1, 31)


# ============================================================================================== backtest panel


def test_nav_panel_refuses_timestamps() -> None:
    # 2024-01-31T20:00Z is 1 Feb IST; a panel holding it would count it as January's month-end.
    stamps = (datetime(2024, 1, 30, 12, tzinfo=UTC), datetime(2024, 1, 31, 20, tzinfo=UTC))
    with pytest.raises(InvalidInput, match="IST calendar dates"):
        wf.NavPanel(stamps, {RISK: (D(10), D(11))})  # type: ignore[arg-type]


def test_align_panel_excludes_and_counts_undated_rows() -> None:
    rows = {
        RISK: [(date(2024, 1, 1), "10"), (None, "99"), (date(2024, 1, 2), "11"), ("", "98"), (date(2024, 1, 3), "12")],
        LIQ: [(date(2024, 1, 1), "100"), (date(2024, 1, 2), "101"), (date(2024, 1, 3), "102"), (None, "97")],
    }
    out = wf.align_panel(rows)
    assert out.panel.dates == (date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3))
    assert out.panel.navs[RISK] == (D(10), D(11), D(12))  # no undated value leaked in
    assert dict(out.undated_excluded) == {RISK: 2, LIQ: 1}
    assert out.unaligned_dropped == 0


def test_align_panel_window_is_half_open() -> None:
    days = [date(2024, 1, d) for d in range(1, 8)]
    rows = {RISK: [(d, D(10) + i) for i, d in enumerate(days)], LIQ: [(d, D(100) + i) for i, d in enumerate(days)]}
    out = wf.align_panel(rows, start=date(2024, 1, 2), end=date(2024, 1, 5))
    assert out.panel.dates == (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))  # start in, end out
    assert dict(out.outside_window) == {RISK: 4, LIQ: 4}


def test_align_panel_converts_aware_timestamps_to_ist() -> None:
    rows = {
        RISK: [(datetime(2024, 1, 30, 20, tzinfo=UTC), "10"), (datetime(2024, 1, 31, 20, tzinfo=UTC), "11")],
        LIQ: [(date(2024, 1, 31), "100"), (date(2024, 2, 1), "101")],
    }
    out = wf.align_panel(rows)
    assert out.panel.dates == (date(2024, 1, 31), date(2024, 2, 1))
    assert out.panel.navs[RISK] == (D(10), D(11))
    with pytest.raises(InvalidInput, match="naive"):
        wf.align_panel({RISK: [(datetime(2024, 1, 31, 20), "10"), (date(2024, 2, 1), "11")]})


def test_align_panel_refuses_conflicting_navs_on_one_ist_day() -> None:
    rows = {RISK: [(datetime(2024, 1, 30, 20, tzinfo=UTC), "10"), (date(2024, 1, 31), "11"), (date(2024, 2, 1), "12")]}
    with pytest.raises(InvalidInput, match="conflicting"):
        wf.align_panel(rows)
    same = {RISK: [(datetime(2024, 1, 30, 20, tzinfo=UTC), "10"), (date(2024, 1, 31), "10"), (date(2024, 2, 1), "12")]}
    assert wf.align_panel(same).panel.dates == (date(2024, 1, 31), date(2024, 2, 1))


def test_align_panel_reports_a_role_emptied_by_filtering() -> None:
    rows = {RISK: [(date(2024, 1, 1), "10"), (date(2024, 1, 2), "11")], LIQ: [(None, "100"), (None, "101")]}
    with pytest.raises(InsufficientHistory, match=r"fixture.liquid.*2 undated"):
        wf.align_panel(rows)


def test_align_panel_reports_an_empty_window_and_an_empty_alignment() -> None:
    rows = {RISK: [(date(2024, 1, 1), "10"), (date(2024, 1, 2), "11")], LIQ: [(date(2024, 1, 3), "100")]}
    with pytest.raises(InsufficientHistory, match="0 date"):
        wf.align_panel(rows)
    with pytest.raises(InsufficientHistory, match="outside"):
        wf.align_panel({RISK: rows[RISK]}, start=date(2025, 1, 1))
    with pytest.raises(InvalidInput, match="empty window"):
        wf.align_panel({RISK: rows[RISK]}, start=date(2024, 1, 2), end=date(2024, 1, 2))


# ============================================================================================== regimes


def _setup(regimes: tuple[wf.RegimeSpec, ...], costs: wf.MfCostSchedule | None = None) -> wf.BacktestSetup:
    from iip.engine.backtest.ledger import CostBasisPolicy
    from iip.engine.backtest.tax_lots import TaxRateTable

    return wf.BacktestSetup(
        strategy=wf.RuleSpec(kind="trend_sma", params={"lookback_months": 3}, slots={"risk": RISK, "out": LIQ}),
        benchmark=wf.RuleSpec(kind="buy_and_hold", params={}, slots={"risk": RISK}),
        config=wf.WalkForwardConfig(
            lag=1, purge=1, embargo=1, fill_rule=wf.FillRule(name="t", nav_offset=1, switch_cash_gap=3)
        ),
        decision_every_months=1,
        initial_capital=D(100000),
        contribution=D(0),
        tax_classes={RISK: "EQUITY", LIQ: "DEBT"},
        costs=costs or wf.MfCostSchedule(rows=(), slippage_rate=D(0)),
        cost_policy=CostBasisPolicy(deductible_components=frozenset(), status="NOT VERIFIED"),
        tax_table=TaxRateTable(rows=()),
        vault=wf.VaultSpec(fraction=D("0.20"), min_months=12),
        regimes=regimes,
    )


def test_regime_window_is_half_open_on_the_day_after_its_declared_last_day() -> None:
    rg = wf.RegimeSpec(regime_id="a", start=date(2013, 4, 1), end=date(2019, 12, 31))
    assert rg.window == (date(2013, 4, 1), date(2020, 1, 1))
    assert not rg.contains(date(2013, 3, 31))
    assert rg.contains(date(2013, 4, 1))
    assert rg.contains(date(2019, 12, 31))  # the declared last day is inside
    assert not rg.contains(date(2020, 1, 1))


def test_adjacent_regimes_attribute_each_period_exactly_once() -> None:
    regimes = (
        wf.RegimeSpec(regime_id="a", start=None, end=date(2013, 3, 31)),
        wf.RegimeSpec(regime_id="b", start=date(2013, 4, 1), end=date(2019, 12, 31)),
        wf.RegimeSpec(regime_id="c", start=date(2020, 1, 1), end=None),
    )
    _setup(regimes)  # the rules-file layout is accepted
    d = date(2012, 1, 1)
    while d < date(2022, 1, 1):
        assert sum(rg.contains(d) for rg in regimes) == 1, d
        d += timedelta(days=1)


def test_overlapping_regimes_are_refused() -> None:
    shared_day = (
        wf.RegimeSpec(regime_id="a", start=None, end=date(2013, 4, 1)),
        wf.RegimeSpec(regime_id="b", start=date(2013, 4, 1), end=None),
    )
    with pytest.raises(InvalidInput, match="overlap"):
        _setup(shared_day)
    with pytest.raises(InvalidInput, match="unique"):
        _setup((wf.RegimeSpec(regime_id="a", start=None, end=None), wf.RegimeSpec(regime_id="a", start=None, end=None)))


def test_regime_bounds_must_be_ordered_calendar_dates() -> None:
    with pytest.raises(InvalidInput, match="before start"):
        wf.RegimeSpec(regime_id="x", start=date(2020, 1, 2), end=date(2020, 1, 1))
    with pytest.raises(InvalidInput, match="calendar date"):
        wf.RegimeSpec(regime_id="x", start=datetime(2020, 1, 1, tzinfo=UTC), end=None)


def test_an_empty_regime_is_reported_not_blank() -> None:
    edge = wf.PeriodRecord(
        start=date(2021, 1, 29), end=date(2021, 2, 26), strategy_return=D(0), benchmark_return=D(0), edge=D("0.01")
    )
    out = wf._regimes(
        (edge,),
        (
            wf.RegimeSpec(regime_id="before", start=None, end=date(2020, 12, 31)),
            wf.RegimeSpec(regime_id="after", start=date(2021, 1, 1), end=None),
        ),
    )
    assert out[0] == wf.RegimeEdge(regime_id="before", n_periods=0, mean_edge=None)  # None, never a 0 edge
    assert out[1].n_periods == 1 and out[1].mean_edge == D("0.01")


# ============================================================================================== cost rows


def _row(rule_id: str, start: date, last_day: date | None, rate: str, classes: frozenset[str]) -> wf.CostRateRow:
    return wf.CostRateRow(
        rule_id=rule_id,
        component="stamp_duty",
        side="buy",
        tax_classes=classes,
        rate=D(rate),
        effective_from=start,
        effective_to=last_day,
        status="VERIFIED-SECONDARY",
    )


def test_adjacent_cost_rows_switch_rate_on_the_new_rows_first_day() -> None:
    eq = frozenset({"EQUITY"})
    old = _row("FIC-OLD", date(2020, 1, 1), date(2024, 3, 31), "0.0001", eq)
    new = _row("FIC-NEW", date(2024, 4, 1), None, "0.0002", eq)
    sched = wf.MfCostSchedule(rows=(new, old), slippage_rate=D(0))  # row order must not matter
    assert sched.rate("buy", "EQUITY", date(2024, 3, 31), wf.NO_STRESS) == D("0.0001")
    assert sched.rate("buy", "EQUITY", date(2024, 4, 1), wf.NO_STRESS) == D("0.0002")


def test_overlapping_cost_rows_for_one_trade_are_refused() -> None:
    eq = frozenset({"EQUITY"})
    old = _row("FIC-OLD", date(2020, 1, 1), date(2024, 4, 1), "0.0001", eq)  # shares 1 Apr with the next row
    new = _row("FIC-NEW", date(2024, 4, 1), None, "0.0002", frozenset({"EQUITY", "DEBT"}))
    with pytest.raises(InvalidInput, match="overlapping"):
        wf.MfCostSchedule(rows=(old, new), slippage_rate=D(0))
    # Same dates but disjoint tax classes never price the same trade: allowed.
    debt = _row("FIC-DEBT", date(2020, 1, 1), None, "0.0003", frozenset({"DEBT"}))
    wf.MfCostSchedule(rows=(old, debt), slippage_rate=D(0))
