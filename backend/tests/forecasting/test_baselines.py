"""Forecast baselines B1–B4 (validation-methodology.md §2).

Price paths here are SYNTHETIC (seeded random walks) used only to exercise mechanics; they are not market data.
"""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from iip.engine.errors import InsufficientHistory, InvalidInput, StaleData
from iip.engine.forecasting.baselines import (
    SCENARIO_LABEL,
    derive_seed,
    empirical_horizon_distribution,
    historical_mean_baseline,
    stationary_bootstrap,
    yield_carry_scenarios,
    zero_drift_baseline,
)

AS_OF = date(2026, 9, 30)


def _synthetic_prices(n: int, seed: int = 11) -> tuple[list[date], list[float]]:
    rng = np.random.default_rng(seed)
    logret = rng.normal(0.0004, 0.01, n - 1)
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(logret)]))
    start = AS_OF - timedelta(days=n - 1)
    return [start + timedelta(days=i) for i in range(n)], [float(p) for p in prices]


# ---------------------------------------------------------------- bootstrap determinism
def test_same_seed_identical_and_different_seed_differs() -> None:
    dates, prices = _synthetic_prices(1500)
    a = stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=10, seed=42, n_paths=2000)
    b = stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=10, seed=42, n_paths=2000)
    c = stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=10, seed=43, n_paths=2000)
    assert a.quantiles == b.quantiles
    assert a.mc_standard_errors == b.mc_standard_errors
    assert a.quantiles != c.quantiles
    assert a.seed == 42 and a.meta.label == SCENARIO_LABEL


def test_bootstrap_block_length_one_is_iid_and_validated() -> None:
    dates, prices = _synthetic_prices(600)
    r = stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=1, seed=1, n_paths=500)
    assert "BLOCK_LENGTH_OUTSIDE_5_63" in r.meta.warnings
    with pytest.raises(InvalidInput):
        stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=0.5, seed=1)


def test_derive_seed_is_stable() -> None:
    s1 = derive_seed("INF0001", date(2026, 10, 15), "B2@1")
    assert s1 == derive_seed("INF0001", date(2026, 10, 15), "B2@1")
    assert s1 != derive_seed("INF0001", date(2026, 10, 16), "B2@1")
    assert 0 <= s1 < 2**64


# ---------------------------------------------------------------- monotonicity
@pytest.mark.parametrize("method", ["linear", "inverted_cdf"])
def test_empirical_quantiles_monotone(method: str) -> None:
    dates, prices = _synthetic_prices(1200)
    r = empirical_horizon_distribution(dates, prices, horizon=21, as_of=AS_OF, interpolation=method)
    values = [v for _, v in r.quantiles]
    levels = [lv for lv, _ in r.quantiles]
    assert levels == sorted(levels)
    assert values == sorted(values)
    assert r.interpolation == method
    assert levels[0] == 0.05 and levels[-1] == 0.95  # n_eff = ⌊1199/21⌋ = 57 ≥ 20


def test_bootstrap_quantiles_monotone() -> None:
    dates, prices = _synthetic_prices(800)
    r = stationary_bootstrap(dates, prices, horizon=63, as_of=AS_OF, mean_block_length=20, seed=5, n_paths=3000)
    values = [v for _, v in r.quantiles]
    assert values == sorted(values)


def test_empirical_matches_direct_overlapping_windows() -> None:
    dates, prices = _synthetic_prices(400)
    h = 21
    r = empirical_horizon_distribution(dates, prices, horizon=h, as_of=AS_OF)
    p = np.array(prices)
    windows = p[h:] / p[:-h] - 1
    assert r.n_windows == len(windows)
    for lv, v in r.quantiles:
        assert v == pytest.approx(float(np.quantile(windows, lv, method="linear")))


def test_empirical_gating_drops_tails() -> None:
    dates, prices = _synthetic_prices(300)  # n_eff = ⌊299/21⌋ = 14 → 10/90 allowed, 5/95 not
    r = empirical_horizon_distribution(dates, prices, horizon=21, as_of=AS_OF)
    levels = [lv for lv, _ in r.quantiles]
    assert 0.05 not in levels and 0.10 in levels and 0.90 in levels
    assert "LOW_CONFIDENCE" in r.meta.warnings


def test_point_in_time_cutoff() -> None:
    dates, prices = _synthetic_prices(600)
    r1 = empirical_horizon_distribution(dates, prices, horizon=21, as_of=dates[500])
    future = [*dates, dates[-1] + timedelta(days=1)]
    r2 = empirical_horizon_distribution(future, [*prices, 1e9], horizon=21, as_of=dates[500])
    assert r1.quantiles == r2.quantiles
    assert r1.meta.data_cutoff == dates[500]


# ---------------------------------------------------------------- insufficient history
def test_horizon_longer_than_history_raises() -> None:
    dates, prices = _synthetic_prices(100)
    with pytest.raises(InsufficientHistory):
        empirical_horizon_distribution(dates, prices, horizon=252, as_of=AS_OF)
    with pytest.raises(InsufficientHistory):
        stationary_bootstrap(dates, prices, horizon=252, as_of=AS_OF, mean_block_length=10, seed=1)
    with pytest.raises(InsufficientHistory):
        historical_mean_baseline(dates, prices, horizon_months=12, as_of=AS_OF)


def test_too_few_independent_windows_raises() -> None:
    dates, prices = _synthetic_prices(200)  # n_eff = ⌊199/21⌋ = 9 < 10 → suppressed
    with pytest.raises(InsufficientHistory):
        empirical_horizon_distribution(dates, prices, horizon=21, as_of=AS_OF)


# ---------------------------------------------------------------- B3
def test_zero_drift_and_historical_mean() -> None:
    z = zero_drift_baseline(horizon_months=3, as_of=AS_OF)
    assert z.point == 0.0
    start = date(2016, 9, 30)
    dates = [start, date(2021, 9, 30), AS_OF]
    prices = [100.0, 130.0, 200.0]
    m = historical_mean_baseline(dates, prices, horizon_months=12, as_of=AS_OF)
    years = (AS_OF - start).days / 365
    cagr = 2.0 ** (1 / years) - 1
    assert m.point == pytest.approx(cagr)
    for out in (z, m):
        assert out.meta.label == SCENARIO_LABEL
        assert out.meta.unreliable_when and out.meta.assumptions and out.meta.limitations


# ---------------------------------------------------------------- B4 fixtures YC-1, YC-2
def test_yield_carry_yc1() -> None:
    r = yield_carry_scenarios(
        ytm=Decimal("0.074"),
        expense_ratio=Decimal("0.004"),
        modified_duration=Decimal("3.0"),
        horizon_months=3,
        as_of=date(2026, 10, 15),
        factsheet_published=date(2026, 10, 10),
    )
    s = dict(r.scenarios)
    assert r.carry == Decimal("0.0175")
    assert s[0] == Decimal("0.0175")
    assert s[50] == Decimal("0.0025")
    assert s[-50] == Decimal("0.0325")
    assert s[100] == Decimal("-0.0125")
    assert dict(r.stress_scenarios)[200] == Decimal("-0.0425")
    assert r.meta.label == SCENARIO_LABEL
    assert r.meta.baseline_comparator


def test_yield_carry_yc2() -> None:
    r = yield_carry_scenarios(
        ytm=Decimal("0.074"),
        expense_ratio=Decimal("0.004"),
        modified_duration=Decimal("3.0"),
        horizon_months=12,
        as_of=date(2026, 10, 15),
        factsheet_published=date(2026, 10, 10),
    )
    s = dict(r.scenarios)
    assert r.carry == Decimal("0.07")
    assert (s[100], s[-100]) == (Decimal("0.04"), Decimal("0.10"))


def test_yield_carry_stale_factsheet() -> None:
    with pytest.raises(StaleData):
        yield_carry_scenarios(
            ytm=Decimal("0.074"),
            expense_ratio=Decimal("0.004"),
            modified_duration=Decimal("3.0"),
            horizon_months=3,
            as_of=date(2026, 10, 15),
            factsheet_published=date(2026, 8, 1),
        )


def test_outputs_never_use_probability_language() -> None:
    dates, prices = _synthetic_prices(1200)
    outs = [
        empirical_horizon_distribution(dates, prices, horizon=21, as_of=AS_OF).meta,
        stationary_bootstrap(dates, prices, horizon=21, as_of=AS_OF, mean_block_length=10, seed=1).meta,
        zero_drift_baseline(horizon_months=1, as_of=AS_OF).meta,
    ]
    for meta in outs:
        for text in (meta.label, *meta.assumptions, *meta.limitations, *meta.unreliable_when):
            assert "probabilit" not in text.lower()
