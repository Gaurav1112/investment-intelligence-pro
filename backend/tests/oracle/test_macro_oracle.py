"""Independent cross-checks for the Track 1 formulas: horizon inflation, Fisher real return, the risk-free alignment
feeding Sharpe, the FD premature payout via a card-rate bucket, and the yield-carry horizon in days.

References use numpy / plain float math (a different code path from the engine's Decimal arithmetic). Inputs are
hand-made test numbers, not market data.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from iip.engine import macro
from iip.engine.deposits import CardRateBucket, card_rate_for_tenure, fd_premature_withdrawal
from iip.engine.forecasting.baselines import yield_carry_scenarios
from iip.engine.money import D
from iip.engine.scenarios import real_return
from iip.engine.stats.metrics import RiskFreeSeries, sharpe
from iip.engine.stats.series import Frequency, ReturnSeries

pytestmark = pytest.mark.oracle
TOL = 1e-12


@pytest.mark.parametrize(("annual", "days"), [("0.05", 182), ("0.0154", 91), ("-0.01", 400), ("0.07", 1)])
def test_horizon_inflation_matches_float_power(annual: str, days: int) -> None:
    ours = float(macro.horizon_inflation(D(annual), days))
    assert abs(ours - (math.pow(1 + float(annual), days / 365) - 1)) <= TOL


@pytest.mark.parametrize(("nominal", "pi"), [("0.07", "0.05"), ("0.04", "0.06"), ("0.0325", "0.0247")])
def test_fisher_real_return_matches_numpy(nominal: str, pi: str) -> None:
    ours = float(real_return(D(nominal), D(pi)).value)
    assert abs(ours - float(np.divide(1 + float(nominal), 1 + float(pi)) - 1)) <= TOL


def test_sharpe_with_aligned_weekly_risk_free_matches_numpy() -> None:
    """3+ years of daily prices; weekly auctions; the reference aligns and computes excess returns independently."""
    rng = np.random.default_rng(7)
    start = date(2022, 1, 3)
    dates, prices, p = [], [], 100.0
    d = start
    while d <= date(2025, 2, 28):
        if d.weekday() < 5:
            dates.append(d)
            prices.append(D(repr(round(p, 6))))
            p *= 1 + 0.0004 + 0.01 * float(rng.standard_normal())
        d += timedelta(days=1)
    series = ReturnSeries.from_observations(list(zip(dates, prices, strict=True)), Frequency.DAILY_BUSINESS)
    auctions = {}
    a = start - timedelta(days=5)
    k = 0
    while a <= dates[-1]:
        auctions[a] = D("0.05") + D(k % 7) / D(1000)
        a += timedelta(days=7)
        k += 1
    al = macro.align_risk_free(series.return_dates, auctions)
    res = sharpe(series, RiskFreeSeries(al.return_dates, al.effective_annual, Frequency.DAILY_BUSINESS))
    assert res.value is not None
    # reference: independent alignment by linear scan, numpy arithmetic
    auct = sorted(auctions.items())
    px = np.array([float(x) for x in prices])
    r = px[1:] / px[:-1] - 1
    y = []
    for rd in dates[1:]:
        y.append([v for ad, v in auct if ad <= rd][-1])
    yy = np.array([float(v) for v in y])
    y_eff = np.power(1 + yy * 91 / 365, 365 / 91) - 1
    factor = res.annualisation_factor
    ex = r - (np.power(1 + y_eff, 1 / factor) - 1)
    ref = ex.mean() / ex.std(ddof=1) * math.sqrt(factor)
    assert abs(float(res.value) - ref) <= 1e-9


def test_fd_premature_via_card_rate_bucket_matches_float_fixture_fd_p1() -> None:
    """calc §3.3 FD-P1: booked 2 years at 7.25 %, broken after one year; 1-year card rate 6.80 %, penalty 1 %."""
    table = [CardRateBucket(181, 364, D("0.0650")), CardRateBucket(365, 729, D("0.0680")),
             CardRateBucket(730, 1095, D("0.0725"))]  # fmt: skip
    start, broken = date(2025, 1, 1), date(2026, 1, 1)
    bucket = card_rate_for_tenure(table, (broken - start).days)
    res = fd_premature_withdrawal(D("100000"), D("0.0725"), start, date(2027, 1, 1), broken,
                                  period_card_rate=bucket.rate, penalty=D("0.01"))  # fmt: skip
    ref = 100000 * (1 + 0.058 / 4) ** 4
    assert bucket.rate == D("0.0680") and abs(float(res.payout) - ref) <= 1e-6
    assert res.payout_display == D("105927.37")


def test_yield_carry_in_days_matches_float() -> None:
    yc = yield_carry_scenarios(ytm=D("0.074"), expense_ratio=D("0.004"), modified_duration=D("3.0"), horizon_days=91,
                               as_of=date(2026, 10, 15), factsheet_published=date(2026, 9, 30))  # fmt: skip
    carry = (0.074 - 0.004) * 91 / 365
    assert abs(float(yc.carry) - carry) <= TOL
    for bp, r in yc.scenarios:
        assert abs(float(r) - (carry - 3.0 * bp / 10000)) <= TOL
