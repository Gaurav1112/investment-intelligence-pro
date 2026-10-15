"""Property tests for risk metrics and scenarios (hypothesis).  All generated data is synthetic."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from iip.engine.determinism import content_hash
from iip.engine.money import D
from iip.engine.scenarios import (
    BulletBond,
    bond_rate_shock,
    bond_spread_shock,
    equity_drawdown_shock,
    inflation_scenario,
    liquidity_deterioration,
    rate_shock_duration,
    spread_shock_duration,
)
from iip.engine.stats.metrics import (
    Gates,
    RiskFreeSeries,
    historical_cvar,
    historical_var,
    max_drawdown,
    sharpe,
    volatility,
)
from iip.engine.stats.series import Frequency, ReturnSeries

FIX = Gates.relaxed_for_fixtures()


def bdays(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


prices_st = st.lists(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=4, allow_nan=False),
    min_size=3,
    max_size=60,
)
alpha_st = st.sampled_from([D("0.80"), D("0.90"), D("0.95"), D("0.975"), D("0.99")])
rate_st = st.decimals(min_value=Decimal("0.0"), max_value=Decimal("0.15"), places=4)
dy_st = st.decimals(min_value=Decimal("-0.03"), max_value=Decimal("0.05"), places=4)


def mk(prices: list[Decimal]) -> ReturnSeries:
    return ReturnSeries.from_observations(list(zip(bdays(len(prices)), prices, strict=True)), Frequency.DAILY_BUSINESS)


@settings(max_examples=150, deadline=None)
@given(prices_st)
def test_max_drawdown_in_unit_interval(prices: list[Decimal]) -> None:
    res = max_drawdown(mk(prices), gates=FIX)
    assert Decimal(0) <= res.value <= Decimal(1)
    assert Decimal(0) <= res.largest_one_period_loss < Decimal(1)
    if res.value > 0:
        assert res.peak_date is not None and res.trough_date is not None and res.peak_date < res.trough_date


@settings(max_examples=150, deadline=None)
@given(prices_st, alpha_st, st.integers(min_value=1, max_value=3))
def test_cvar_at_least_var_positive_loss_convention(prices: list[Decimal], alpha: Decimal, h: int) -> None:
    s = mk(prices)
    if h > s.n_returns:
        return
    v = historical_var(s, alpha, horizon=h, gates=FIX)
    c = historical_cvar(s, alpha, horizon=h, gates=FIX)
    # Losses are positive (risk-methodology §5): the tail mean is at least as bad as the quantile.
    # In return space this is the task's "CVaR ≤ VaR".
    assert c.value >= v.value


@settings(max_examples=100, deadline=None)
@given(prices_st, st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3))
def test_scaling_prices_leaves_returns_invariant(prices: list[Decimal], k: Decimal) -> None:
    a = mk(prices)
    b = mk([p * k for p in prices])
    assert np.allclose(a.simple_returns(), b.simple_returns(), rtol=1e-12, atol=1e-15)
    assert np.allclose(a.log_returns(), b.log_returns(), rtol=1e-12, atol=1e-15)
    assert max_drawdown(a, gates=FIX).value == max_drawdown(b, gates=FIX).value
    va = volatility(a, annualisation=252, gates=FIX).value
    vb = volatility(b, annualisation=252, gates=FIX).value
    assert abs(va - vb) <= Decimal("1e-10") * max(Decimal(1), va)


@settings(max_examples=50, deadline=None)
@given(prices_st)
def test_metrics_deterministic(prices: list[Decimal]) -> None:
    s1, s2 = mk(prices), mk(list(prices))
    rf1 = RiskFreeSeries.from_constant(s1.return_dates, D("0.065"), s1.frequency)
    rf2 = RiskFreeSeries.from_constant(s2.return_dates, D("0.065"), s2.frequency)
    for f in (
        lambda s, rf: volatility(s, annualisation=252, gates=FIX),
        lambda s, rf: max_drawdown(s, gates=FIX),
        lambda s, rf: historical_var(s, D("0.9"), gates=FIX),
        lambda s, rf: sharpe(s, rf, annualisation=252, gates=FIX),
    ):
        assert content_hash(f(s1, rf1)) == content_hash(f(s2, rf2))


# ---------------------------------------------------------------- scenarios

bond_st = st.builds(
    lambda c, f, n: BulletBond(coupon_rate=c, frequency=f, periods_remaining=n),
    rate_st,
    st.sampled_from([1, 2, 4]),
    st.integers(min_value=1, max_value=60),
)


@settings(max_examples=100, deadline=None)
@given(
    st.decimals(min_value=Decimal("1"), max_value=Decimal("1e9"), places=2),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("30"), places=4),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("500"), places=4),
    bond_st,
    rate_st,
)
def test_zero_shock_zero_impact(value: Decimal, dur: Decimal, conv: Decimal, bond: BulletBond, y: Decimal) -> None:
    assert rate_shock_duration(value, dur, D(0), convexity=conv).impact == 0
    assert spread_shock_duration(value, dur, D(0)).impact == 0
    assert equity_drawdown_shock(value, D(0), beta=D("1.3")).impact == 0
    assert liquidity_deterioration(value, exit_cost=D(0), haircut=D(0)).impact == 0
    assert inflation_scenario(value, nominal_return=y, base_inflation=D("0.05"), delta_inflation=D(0)).impact == 0
    assert bond_rate_shock(bond, y, D(0), position_value=value).impact == 0
    assert bond_spread_shock(bond, gsec_yield=y, spread=D("0.01"), delta_spread=D(0), position_value=value).impact == 0


@settings(max_examples=150, deadline=None)
@given(bond_st, rate_st, dy_st, dy_st)
def test_larger_rate_shock_larger_loss_full_repricing(bond: BulletBond, y: Decimal, a: Decimal, b: Decimal) -> None:
    lo, hi = sorted((a, b))
    if lo == hi:
        return
    small = bond_rate_shock(bond, y, lo, position_value=D(1000))
    large = bond_rate_shock(bond, y, hi, position_value=D(1000))
    assert large.impact < small.impact  # positive duration: price strictly decreasing in yield


@settings(max_examples=150, deadline=None)
@given(
    st.decimals(min_value=Decimal("0.1"), max_value=Decimal("30"), places=4),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("0.05"), places=4),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("0.05"), places=4),
)
def test_larger_rate_shock_larger_loss_duration(dur: Decimal, a: Decimal, b: Decimal) -> None:
    lo, hi = sorted((a, b))
    if lo == hi:
        return
    assert rate_shock_duration(D(1000), dur, hi).impact < rate_shock_duration(D(1000), dur, lo).impact


@settings(max_examples=50, deadline=None)
@given(bond_st, rate_st, dy_st)
def test_scenarios_deterministic(bond: BulletBond, y: Decimal, dy: Decimal) -> None:
    r1 = bond_rate_shock(bond, y, dy, position_value=D(1000))
    r2 = bond_rate_shock(bond, y, dy, position_value=D(1000))
    assert content_hash(r1) == content_hash(r2)
