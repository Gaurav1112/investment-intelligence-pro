"""Independent cross-checks of the risk metrics and bond analytics against numpy / scipy / QuantLib.

Every reference is computed here with a different code path from the engine (library calls, not the
engine's own helpers).  Synthetic series come from a seeded RNG and are not market data.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
import QuantLib as ql
from scipy import stats as sps

from iip.engine.money import D
from iip.engine.scenarios import BulletBond, bond_analytics, bond_dirty_price
from iip.engine.stats.metrics import (
    Gates,
    ReturnKind,
    RiskFreeSeries,
    beta,
    correlation,
    correlation_matrix,
    downside_deviation,
    hhi,
    historical_cvar,
    historical_var,
    max_drawdown,
    sharpe,
    sortino,
    tracking_error,
    volatility,
)
from iip.engine.stats.series import Frequency, ReturnSeries

pytestmark = pytest.mark.oracle
FIX = Gates.relaxed_for_fixtures()
TOL = 1e-10  # float-vs-float agreement (engine output passes through repr → Decimal)


def bdays(n: int, start: date = date(2019, 1, 1)) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def synthetic(seed: int, n: int = 900, sigma: float = 0.012) -> ReturnSeries:
    rng = np.random.default_rng(seed)
    prices = [Decimal(100)]
    for r in rng.standard_t(4, n - 1) * sigma / math.sqrt(2):  # fat tails
        prices.append(prices[-1] * (1 + Decimal(repr(float(r)))))
    return ReturnSeries.from_observations(list(zip(bdays(n), prices, strict=True)), Frequency.DAILY_BUSINESS)


SERIES = [synthetic(s) for s in (101, 202, 303)]


def p(s: ReturnSeries) -> np.ndarray:
    return np.array([float(x) for x in s.prices])


@pytest.mark.parametrize("s", SERIES)
def test_volatility_vs_numpy(s: ReturnSeries) -> None:
    ref = np.std(np.diff(np.log(p(s))), ddof=1) * math.sqrt(252)
    assert math.isclose(float(volatility(s, annualisation=252).value), ref, rel_tol=TOL)


@pytest.mark.parametrize("s", SERIES)
@pytest.mark.parametrize("alpha", ["0.80", "0.90", "0.95", "0.975"])
@pytest.mark.parametrize("h", [1, 5, 21])
def test_var_cvar_vs_numpy_inverted_cdf(s: ReturnSeries, alpha: str, h: int) -> None:
    prices = p(s)
    rh = prices[h:] / prices[:-h] - 1
    q = np.quantile(rh, 1 - float(alpha), method="inverted_cdf")
    v = historical_var(s, D(alpha), horizon=h, gates=FIX)
    assert math.isclose(float(v.value), -q, rel_tol=TOL)
    c = historical_cvar(s, D(alpha), horizon=h, gates=FIX)
    assert math.isclose(float(c.value), -np.mean(np.sort(rh)[: v.k]), rel_tol=TOL)
    assert math.isclose(float(c.value), -np.mean(rh[rh <= q]), rel_tol=1e-9) or np.sum(rh == q) > 1


@pytest.mark.parametrize("s", SERIES)
def test_max_drawdown_vs_numpy(s: ReturnSeries) -> None:
    prices = p(s)
    dd = prices / np.maximum.accumulate(prices) - 1
    assert math.isclose(float(max_drawdown(s, gates=FIX).value), -dd.min(), rel_tol=1e-12)
    assert max_drawdown(s, gates=FIX).trough_date == s.dates[int(np.argmin(dd))]


@pytest.mark.parametrize("s", SERIES)
def test_sharpe_sortino_vs_numpy(s: ReturnSeries) -> None:
    r = np.diff(p(s)) / p(s)[:-1]
    rf_p = 1.065 ** (1 / 252) - 1
    ex = r - rf_p
    ref = ex.mean() / np.std(ex, ddof=1)
    res = sharpe(s, RiskFreeSeries.from_constant(s.return_dates, D("0.065"), s.frequency), annualisation=252)
    assert math.isclose(float(res.period_value), ref, rel_tol=1e-9)
    tau = 0.0002
    dd_ref = math.sqrt(np.mean(np.clip(r - tau, None, 0.0) ** 2))
    assert math.isclose(float(downside_deviation(s, D("0.0002")).value), dd_ref, rel_tol=1e-9)
    so = sortino(s, D("0.0002"), annualisation=252)
    assert math.isclose(float(so.value), (r.mean() - tau) / dd_ref * math.sqrt(252), rel_tol=1e-9)


@pytest.mark.parametrize(("a", "b"), [(SERIES[0], SERIES[1]), (SERIES[1], SERIES[2])])
def test_pairwise_vs_scipy(a: ReturnSeries, b: ReturnSeries) -> None:
    la, lb = np.diff(np.log(p(a))), np.diff(np.log(p(b)))
    lin = sps.linregress(lb, la)
    assert math.isclose(float(beta(a, b).value), lin.slope, rel_tol=1e-9)
    corr = correlation(a, b)
    assert math.isclose(float(corr.value), np.corrcoef(la, lb)[0, 1], rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(float(corr.spearman), sps.spearmanr(la, lb).statistic, rel_tol=1e-9, abs_tol=1e-12)
    sa, sb = np.diff(p(a)) / p(a)[:-1], np.diff(p(b)) / p(b)[:-1]
    te = tracking_error(a, b, annualisation=252)
    assert math.isclose(float(te.value), np.std(sa - sb, ddof=1) * math.sqrt(252), rel_tol=1e-9)
    mat = correlation_matrix({"a": a, "b": b})
    assert math.isclose(float(mat.matrix[0][1]), np.corrcoef(la, lb)[0, 1], rel_tol=1e-9, abs_tol=1e-12)


def test_fixture_r_beta_simple_vs_scipy() -> None:
    r = np.array([1, -1, 2, -1, -3, 1, 3, -1, 2, 1]) / 100
    bm = np.array([0.8, -1.2, 1.5, -0.5, -2.5, 1.2, 2.0, -0.8, 1.8, 0.6]) / 100
    dates = bdays(11, date(2025, 1, 6))

    def mk(x: np.ndarray) -> ReturnSeries:
        prices = [Decimal(100)]
        for v in x:
            prices.append(prices[-1] * (1 + Decimal(repr(float(v)))))
        return ReturnSeries.from_observations(list(zip(dates, prices, strict=True)), Frequency.DAILY_BUSINESS)

    res = beta(mk(r), mk(bm), returns=ReturnKind.SIMPLE, gates=FIX)
    assert math.isclose(float(res.value), sps.linregress(bm, r).slope, rel_tol=1e-9)


def test_hhi_vs_numpy() -> None:
    w = {"a": D("0.4"), "b": D("0.3"), "c": D("0.2"), "d": D("0.1")}
    ref = float(np.sum(np.square([0.4, 0.3, 0.2, 0.1])))
    snap = date(2025, 9, 30)
    assert math.isclose(float(hhi(w, snapshot_date=snap, as_of=snap).value), ref, rel_tol=1e-15)


# ---------------------------------------------------------------- bonds vs QuantLib


def _ql_bond(coupon: float, freq: int, years: int) -> tuple[ql.FixedRateBond, ql.DayCounter, int]:
    issue = ql.Date(15, 1, 2025)
    ql.Settings.instance().evaluationDate = issue
    period = {1: ql.Annual, 2: ql.Semiannual}[freq]
    schedule = ql.Schedule(
        issue,
        issue + ql.Period(years, ql.Years),
        ql.Period(period),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )
    dc = ql.Thirty360(ql.Thirty360.European)
    return ql.FixedRateBond(0, 100.0, schedule, [coupon], dc), dc, period


def _ql_dirty(bond: ql.FixedRateBond, rate: ql.InterestRate, settle: ql.Date) -> float:
    return float(ql.BondFunctions.cleanPrice(bond, rate, settle) + ql.BondFunctions.accruedAmount(bond, settle))


@pytest.mark.parametrize(
    ("coupon", "freq", "years", "y"),
    [(0.08, 2, 3, 0.08), (0.08, 2, 3, 0.09), (0.09, 1, 5, 0.08), (0.071, 2, 10, 0.065), (0.0, 2, 4, 0.07)],
)
def test_bond_analytics_vs_quantlib(coupon: float, freq: int, years: int, y: float) -> None:
    bond, dc, period = _ql_bond(coupon, freq, years)
    rate = ql.InterestRate(y, dc, ql.Compounded, period)
    settle = ql.Date(15, 1, 2025)
    ours = bond_analytics(
        BulletBond(coupon_rate=D(repr(coupon)), frequency=freq, periods_remaining=years * freq), D(repr(y))
    )
    assert math.isclose(float(ours.dirty_price), _ql_dirty(bond, rate, settle), rel_tol=1e-12)
    assert math.isclose(
        float(ours.macaulay_duration),
        ql.BondFunctions.duration(bond, rate, ql.Duration.Macaulay, settle),
        rel_tol=1e-10,
    )
    assert math.isclose(
        float(ours.modified_duration),
        ql.BondFunctions.duration(bond, rate, ql.Duration.Modified, settle),
        rel_tol=1e-10,
    )
    assert math.isclose(float(ours.convexity), ql.BondFunctions.convexity(bond, rate, settle), rel_tol=1e-10)


def test_d2_mid_period_vs_quantlib() -> None:
    """Y-2/D-2: 7.10 % semi-annual, maturity 15-Apr-2036, settle 16-Oct-2026 (A = 1, DSC = 179)."""
    ql.Settings.instance().evaluationDate = ql.Date(15, 10, 2026)
    schedule = ql.Schedule(
        ql.Date(15, 4, 2026),
        ql.Date(15, 4, 2036),
        ql.Period(ql.Semiannual),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )
    dc = ql.Thirty360(ql.Thirty360.European)
    bond = ql.FixedRateBond(0, 100.0, schedule, [0.071], dc)
    settle = ql.Date(16, 10, 2026)
    rate = ql.InterestRate(0.065, dc, ql.Compounded, ql.Semiannual)
    ours_bond = BulletBond(
        coupon_rate=D("0.071"), frequency=2, periods_remaining=19, first_period_fraction=D(179) / D(180)
    )
    ours = bond_analytics(ours_bond, D("0.065"))
    assert math.isclose(float(ours.clean_price), ql.BondFunctions.cleanPrice(bond, rate, settle), rel_tol=1e-12)
    assert math.isclose(
        float(ours.modified_duration), ql.BondFunctions.duration(bond, rate, ql.Duration.Modified, settle), rel_tol=1e-9
    )
    assert math.isclose(float(ours.convexity), ql.BondFunctions.convexity(bond, rate, settle), rel_tol=1e-9)
    shocked = ql.InterestRate(0.085, dc, ql.Compounded, ql.Semiannual)
    assert math.isclose(float(bond_dirty_price(ours_bond, D("0.085"))), _ql_dirty(bond, shocked, settle), rel_tol=1e-12)
