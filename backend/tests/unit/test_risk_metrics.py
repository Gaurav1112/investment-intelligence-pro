"""Risk-metric fixtures from docs/finance/risk-methodology.md plus edge cases.

Fixture R (§2) has only 10 returns, so fixture tests run under ``FIXTURE_GATES`` (the spec states that
fixture R "would be gated" in production).  Gate behaviour itself is tested separately against
``SPEC_GATES``.  Long series used for gate tests are SYNTHETIC (seeded RNG), never presented as market data.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from iip.engine.errors import InsufficientHistory, InvalidInput
from iip.engine.money import D
from iip.engine.stats.metrics import (
    SPEC_GATES,
    AssetCategory,
    CreditBucket,
    Exposure,
    Gates,
    ReturnKind,
    RiskFreeSeries,
    beta,
    correlation,
    correlation_matrix,
    credit_exposure,
    deposit_insurance_excess,
    downside_deviation,
    hhi,
    hhi_from_values,
    historical_cvar,
    historical_var,
    issuer_aggregation,
    lo_eta,
    max_drawdown,
    sharpe,
    smoothing_flag,
    sortino,
    sqrt_time_var,
    tracking_error,
    volatility,
    worst_observed_loss,
)
from iip.engine.stats.series import Frequency, ReturnSeries

FIXTURE_GATES = Gates.relaxed_for_fixtures()
R_PCT = ["1", "-1", "2", "-1", "-3", "1", "3", "-1", "2", "1"]
B_PCT = ["0.8", "-1.2", "1.5", "-0.5", "-2.5", "1.2", "2.0", "-0.8", "1.8", "0.6"]


def bdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def path(returns_pct: list[str], start: Decimal = Decimal(100)) -> list[Decimal]:
    prices = [start]
    for r in returns_pct:
        prices.append(prices[-1] * (1 + D(r) / 100))
    return prices


def series_from(prices: list[Decimal], dates: list[date], freq: Frequency = Frequency.DAILY_BUSINESS) -> ReturnSeries:
    return ReturnSeries.from_observations(list(zip(dates, prices, strict=True)), freq)


R_DATES = bdays(date(2025, 1, 6), 11)
R = series_from(path(R_PCT), R_DATES)
B = series_from(path(B_PCT), R_DATES)


def synthetic_daily(n: int, seed: int, start: date = date(2018, 1, 1), sigma: float = 0.01) -> ReturnSeries:
    """SYNTHETIC test series (seeded) — not market data."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, sigma, n - 1)
    prices = [Decimal(100)]
    for r in rets:
        prices.append(prices[-1] * (1 + Decimal(repr(float(r)))))
    return series_from(prices, bdays(start, n))


def approx(value: Decimal | None, expected: str, tol: str = "1e-6") -> bool:
    assert value is not None
    return abs(value - Decimal(expected)) <= Decimal(tol)


# ---------------------------------------------------------------- series construction


class TestSeries:
    def test_fixture_r_path(self) -> None:
        assert approx(R.prices[-1], "103.915183")
        assert R.n_returns == 10
        assert R.frequency is Frequency.DAILY_BUSINESS

    def test_simple_and_log_returns(self) -> None:
        assert np.allclose(R.simple_returns(), np.array([float(x) / 100 for x in R_PCT]), atol=1e-12)
        expected_log = [0.00995033, -0.01005034, 0.01980263, -0.01005034, -0.03045921]
        assert np.allclose(R.log_returns()[:5], expected_log, atol=1e-8)

    def test_returns_are_read_only(self) -> None:
        arr = R.simple_returns()
        with pytest.raises(ValueError):
            arr[0] = 1.0

    def test_single_observation_rejected(self) -> None:
        with pytest.raises(InsufficientHistory):
            ReturnSeries.from_observations([(date(2025, 1, 6), D(100))], Frequency.DAILY_BUSINESS)

    def test_duplicates_rejected(self) -> None:
        with pytest.raises(InvalidInput, match="duplicate"):
            series_from([D(100), D(101), D(102)], [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 7)])

    def test_out_of_order_rejected(self) -> None:
        with pytest.raises(InvalidInput, match="increasing"):
            series_from([D(100), D(101), D(102)], [date(2025, 1, 6), date(2025, 1, 8), date(2025, 1, 7)])

    @pytest.mark.parametrize("bad", ["0", "-1", "-100.5"])
    def test_non_positive_prices_rejected(self, bad: str) -> None:
        with pytest.raises(InvalidInput, match="positive"):
            series_from([D(100), D(bad), D(102)], bdays(date(2025, 1, 6), 3))

    def test_float_prices_rejected(self) -> None:
        with pytest.raises(InvalidInput):
            ReturnSeries.from_observations(
                [(date(2025, 1, 6), 100.0), (date(2025, 1, 7), 101.0)],  # type: ignore[list-item]
                Frequency.DAILY_BUSINESS,
            )

    def test_datetime_rejected(self) -> None:
        from datetime import datetime

        with pytest.raises(InvalidInput):
            ReturnSeries.from_observations(
                [(datetime(2025, 1, 6), D(100)), (datetime(2025, 1, 7), D(101))], Frequency.DAILY_BUSINESS
            )

    def test_declared_frequency_must_match_spacing(self) -> None:
        monthly_dates = [date(2025, m, 28) for m in range(1, 7)]
        with pytest.raises(InvalidInput, match="frequency"):
            series_from([D(100 + i) for i in range(6)], monthly_dates, Frequency.DAILY_BUSINESS)
        ok = series_from([D(100 + i) for i in range(6)], monthly_dates, Frequency.MONTHLY)
        assert ok.n_returns == 5

    def test_gap_flagged_not_forward_filled(self) -> None:
        dates = [*bdays(date(2025, 1, 6), 5), *bdays(date(2025, 1, 27), 5)]  # 10 Jan → 27 Jan = 17 days
        s = series_from([D(100 + i) for i in range(10)], dates)
        assert s.n_observations == 10  # nothing inserted
        assert len(s.gaps) == 1
        gap = s.gaps[0]
        assert (gap.start, gap.end, gap.calendar_days) == (date(2025, 1, 10), date(2025, 1, 27), 17)
        assert s.suspect_fraction == Decimal(1) / Decimal(10)
        assert not s.risk_eligible  # 10 % > 2 %

    def test_weekend_is_not_a_gap(self) -> None:
        assert R.gaps == ()
        assert R.risk_eligible

    def test_gap_threshold_exactly_seven_days_is_not_suspect(self) -> None:
        tail = bdays(date(2025, 1, 15), 4)
        prices = [D(100 + i) for i in range(6)]
        s = series_from(prices, [date(2025, 1, 6), date(2025, 1, 13), *tail])  # 7-day gap
        assert s.gaps == ()
        s2 = series_from(prices, [date(2025, 1, 6), date(2025, 1, 14), *tail])  # 8-day gap
        assert len(s2.gaps) == 1 and s2.gaps[0].calendar_days == 8

    def test_known_holidays_excluded_from_gap(self) -> None:
        holidays = frozenset({date(2025, 1, 14), date(2025, 1, 15)})
        dates = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 16), date(2025, 1, 17)]  # 9-day gap
        flagged = series_from([D(100), D(101), D(102), D(103)], dates)
        assert len(flagged.gaps) == 1
        excused = ReturnSeries.from_observations(
            list(zip(dates, [D(100), D(101), D(102), D(103)], strict=True)),
            Frequency.DAILY_BUSINESS,
            holidays=holidays,
        )
        assert excused.gaps == ()

    def test_ineligible_series_refused_by_metrics(self) -> None:
        dates = [*bdays(date(2025, 1, 6), 5), *bdays(date(2025, 1, 27), 5)]
        s = series_from([D(100 + i) for i in range(10)], dates)
        with pytest.raises(InsufficientHistory, match="gap"):
            volatility(s, gates=FIXTURE_GATES, annualisation=252)

    def test_window(self) -> None:
        w = R.window(R_DATES[2], R_DATES[5])
        assert w.dates == tuple(R_DATES[2:6])

    def test_annualisation_fallback_under_one_year(self) -> None:
        a = R.annualisation()
        assert (a.factor, a.source) == (248, "fallback")

    def test_annualisation_estimated(self) -> None:
        s = synthetic_daily(800, seed=1)
        a = s.annualisation()
        assert a.source == "estimated"
        assert 255 <= a.factor <= 265  # synthetic Mon–Fri calendar has ~261 days/yr, no holidays


# ---------------------------------------------------------------- §2 volatility


class TestVolatility:
    def test_fixture_r_log_vol(self) -> None:
        res = volatility(R, annualisation=252, gates=FIXTURE_GATES)
        assert approx(res.value, "0.291673", "5e-7")
        assert approx(res.period_value, "0.01837370", "5e-9")
        assert res.method_id == "VOL_LOG_DDOF1@1"
        assert res.observations == 10
        assert res.frequency is Frequency.DAILY_BUSINESS
        assert (res.period_start, res.period_end) == (R_DATES[0], R_DATES[-1])
        assert res.annualisation_factor == 252
        assert "NON_SPEC_GATES" in res.caveats

    def test_constant_series_zero_vol(self) -> None:
        s = series_from([D(100)] * 11, R_DATES)
        res = volatility(s, annualisation=252, gates=FIXTURE_GATES)
        assert res.value == Decimal(0)

    def test_refuse_below_60(self) -> None:
        with pytest.raises(InsufficientHistory):
            volatility(synthetic_daily(60, seed=2))  # 59 returns

    def test_low_confidence_between_60_and_252(self) -> None:
        res = volatility(synthetic_daily(61, seed=2))
        assert "LOW_CONFIDENCE" in res.caveats
        assert "NON_SPEC_GATES" not in res.caveats
        res2 = volatility(synthetic_daily(253, seed=2))
        assert "LOW_CONFIDENCE" not in res2.caveats

    def test_liquid_fund_daily_vol_refused(self) -> None:
        with pytest.raises(InvalidInput, match="weekly"):
            volatility(synthetic_daily(300, seed=3), category=AssetCategory.LIQUID)

    def test_debt_category_carries_understated_caveat(self) -> None:
        res = volatility(synthetic_daily(300, seed=3), category=AssetCategory.DEBT)
        assert "VOLATILITY_UNDERSTATED_SMOOTHED_NAV" in res.caveats


# ---------------------------------------------------------------- §3 drawdown


class TestDrawdown:
    def test_fixture_r(self) -> None:
        res = max_drawdown(R, gates=FIXTURE_GATES)
        assert approx(res.value, "0.0397", "1e-12")  # positive magnitude of −3.97 %
        assert res.peak_date == R_DATES[3]
        assert res.trough_date == R_DATES[5]
        assert res.recovery_date == R_DATES[9]
        assert res.peak_to_trough_obs == 2
        assert res.trough_to_recovery_obs == 4
        assert res.underwater_obs == 6
        assert res.peak_to_trough_days == (R_DATES[5] - R_DATES[3]).days
        assert res.recovered
        assert approx(res.largest_one_period_loss, "0.03", "1e-12")

    def test_short_history_label(self) -> None:
        res = max_drawdown(R)
        assert "MDD_WITHIN_AVAILABLE_HISTORY" in res.caveats

    def test_unrecovered_is_ongoing(self) -> None:
        s = series_from([D(100), D(110), D(90), D(95)], bdays(date(2025, 1, 6), 4))
        res = max_drawdown(s, gates=FIXTURE_GATES)
        assert not res.recovered
        assert res.recovery_date is None and res.trough_to_recovery_obs is None
        assert "DRAWDOWN_ONGOING" in res.caveats
        assert res.ongoing_min_obs == 2  # "≥ n (ongoing)" from the peak

    def test_starts_in_drawdown_caveat(self) -> None:
        s = series_from([D(100), D(90), D(95)], bdays(date(2025, 1, 6), 3))
        res = max_drawdown(s, gates=FIXTURE_GATES)
        assert "PEAK_AT_SERIES_START" in res.caveats

    def test_constant_series(self) -> None:
        res = max_drawdown(series_from([D(100)] * 5, bdays(date(2025, 1, 6), 5)), gates=FIXTURE_GATES)
        assert res.value == Decimal(0)
        assert res.peak_date is None and res.trough_date is None


# ---------------------------------------------------------------- §4 Sharpe / Sortino / Lo


def rf_const(series: ReturnSeries, y_eff: str) -> RiskFreeSeries:
    return RiskFreeSeries.from_constant(series.return_dates, D(y_eff), series.frequency)


class TestSharpe:
    def test_fixture_r(self) -> None:
        res = sharpe(R, rf_const(R, "0.065"), annualisation=252, gates=FIXTURE_GATES)
        assert approx(res.period_value, "0.204044", "5e-7")
        assert approx(res.value, "3.2391", "5e-5")
        assert approx(res.mean_excess, "0.00375007", "5e-9")
        assert approx(res.risk_free_per_period, "0.00024993", "5e-9")
        assert res.defined

    def test_risk_free_per_period_conversion_tbill(self) -> None:
        from iip.engine.stats.metrics import tbill_effective_annual

        # y = 6.40 % money-market yield → effective annual (1 + y·91/365)^(365/91) − 1
        eff = tbill_effective_annual(D("0.064"))
        expected = (1 + 0.064 * 91 / 365) ** (365 / 91) - 1
        assert abs(float(eff) - expected) < 1e-15

    def test_constant_series_sharpe_undefined_not_infinite(self) -> None:
        s = series_from([D(100)] * 11, R_DATES)
        res = sharpe(s, rf_const(s, "0.065"), annualisation=252, gates=FIXTURE_GATES)
        assert not res.defined
        assert res.value is None and res.period_value is None
        assert res.undefined_reason == "ZERO_VOLATILITY"

    def test_risk_free_dates_must_align(self) -> None:
        rf = RiskFreeSeries.from_constant(R.return_dates[:-1], D("0.065"), R.frequency)
        with pytest.raises(InvalidInput, match="align"):
            sharpe(R, rf, annualisation=252, gates=FIXTURE_GATES)

    def test_risk_free_frequency_must_match(self) -> None:
        rf = RiskFreeSeries.from_constant(R.return_dates, D("0.065"), Frequency.MONTHLY)
        with pytest.raises(InvalidInput, match="frequenc"):
            sharpe(R, rf, annualisation=252, gates=FIXTURE_GATES)

    def test_gate_three_years(self) -> None:
        s = synthetic_daily(500, seed=4)
        with pytest.raises(InsufficientHistory):
            sharpe(s, rf_const(s, "0.065"))
        long = synthetic_daily(800, seed=4)
        res = sharpe(long, rf_const(long, "0.065"))
        assert res.defined

    def test_debt_daily_sharpe_refused_monthly_lo_adjusted(self) -> None:
        s = synthetic_daily(800, seed=5)
        with pytest.raises(InvalidInput, match="monthly"):
            sharpe(s, rf_const(s, "0.065"), category=AssetCategory.DEBT)
        months = [date(2019 + (m // 12), m % 12 + 1, 28) for m in range(40)]
        rng = np.random.default_rng(6)  # SYNTHETIC
        prices = [Decimal(100)]
        for r in rng.normal(0.006, 0.004, 39):
            prices.append(prices[-1] * (1 + Decimal(repr(float(r)))))
        ms = series_from(prices, months, Frequency.MONTHLY)
        res = sharpe(ms, rf_const(ms, "0.065"), category=AssetCategory.DEBT)
        assert "AUTOCORRELATION_ADJUSTED" in res.caveats
        assert res.method_id == "SHARPE_LO2002@1"


class TestSortino:
    def test_fixture_r_target_zero(self) -> None:
        res = sortino(R, D(0), annualisation=252, gates=FIXTURE_GATES)
        assert approx(res.downside_deviation, "0.0109545", "5e-8")
        assert approx(res.period_value, "0.365148", "5e-7")
        assert approx(res.value, "5.7966", "5e-5")

    def test_denominator_is_full_sample_not_negative_count(self) -> None:
        dd = downside_deviation(R, D(0), gates=FIXTURE_GATES)
        wrong = (Decimal("1.2e-3") / 4).sqrt()  # the common bug: divide by N_neg = 4
        assert not approx(dd.value, str(wrong), "1e-6")
        assert approx(dd.value, "0.0109545", "5e-8")
        assert dd.below_target_obs == 4

    def test_below_target_obs_gate(self) -> None:
        g = Gates.relaxed_for_fixtures(sortino_min_below_target=20)
        with pytest.raises(InsufficientHistory, match="below-target"):
            sortino(R, D(0), annualisation=252, gates=g)

    def test_no_downside_undefined(self) -> None:
        s = series_from(path(["1", "2", "1", "1"]), bdays(date(2025, 1, 6), 5))
        res = sortino(s, D(0), annualisation=252, gates=FIXTURE_GATES)
        assert not res.defined and res.value is None


class TestLo:
    def test_fixture_lo1(self) -> None:
        res = lo_eta(2, [D("0.3")])
        assert approx(res.value, "1.2403", "5e-5")
        assert approx(res.iid_value, "1.4142", "5e-5")

    def test_needs_q_minus_1_autocorrelations(self) -> None:
        with pytest.raises(InvalidInput):
            lo_eta(3, [D("0.3")])


# ---------------------------------------------------------------- §5 VaR / CVaR


class TestVaR:
    @pytest.mark.parametrize(("alpha", "k", "var", "cvar"), [("0.90", 1, "0.03", "0.03"), ("0.80", 2, "0.01", "0.02")])
    def test_fixture_r(self, alpha: str, k: int, var: str, cvar: str) -> None:
        v = historical_var(R, D(alpha), gates=FIXTURE_GATES)
        c = historical_cvar(R, D(alpha), gates=FIXTURE_GATES)
        assert v.k == k and c.k == k
        assert approx(v.value, var, "1e-12")
        assert approx(c.value, cvar, "1e-12")
        assert v.method_id == "VAR_HIST_HF1@1"

    def test_not_linear_interpolation(self) -> None:
        v = historical_var(R, D("0.90"), gates=FIXTURE_GATES)
        assert not approx(v.value, "0.012", "1e-6")

    def test_inr_value_in_decimal(self) -> None:
        v = historical_var(R, D("0.90"), position=D("100000"), gates=FIXTURE_GATES)
        assert v.value_inr is not None
        assert abs(v.value_inr - Decimal("3000")) < Decimal("1e-6")

    def test_horizon_overlapping_caveat(self) -> None:
        v = historical_var(R, D("0.80"), horizon=2, gates=FIXTURE_GATES)
        assert v.windows == 9
        assert v.effective_observations == 5
        assert "OVERLAPPING_WINDOWS_AUTOCORRELATED" in v.caveats

    def test_gate_span(self) -> None:
        with pytest.raises(InsufficientHistory):
            historical_var(synthetic_daily(500, seed=7), D("0.95"))
        v = historical_var(synthetic_daily(800, seed=7), D("0.95"))
        assert v.value is not None
        with pytest.raises(InsufficientHistory):
            historical_var(synthetic_daily(800, seed=7), D("0.99"))  # needs 10 y

    def test_gate_effective_sample_for_horizon(self) -> None:
        s = synthetic_daily(800, seed=8)  # ~3 y; h = 63 → n_eff = 12 < 20
        with pytest.raises(InsufficientHistory, match="n_eff"):
            historical_var(s, D("0.95"), horizon=63)

    def test_cvar_tail_gate(self) -> None:
        s = synthetic_daily(800, seed=9)
        c = historical_cvar(s, D("0.95"))  # ceil(799 × 0.05) = 40 ≥ 10
        assert c.tail_observations >= 10
        g = Gates.relaxed_for_fixtures(cvar_min_tail=10)
        with pytest.raises(InsufficientHistory, match="tail"):
            historical_cvar(R, D("0.90"), gates=g)

    def test_confidence_bounds(self) -> None:
        for bad in ["0", "1", "1.5", "-0.1"]:
            with pytest.raises(InvalidInput):
                historical_var(R, D(bad), gates=FIXTURE_GATES)

    def test_worst_observed_loss(self) -> None:
        w = worst_observed_loss(R)
        assert approx(w.value, "0.03", "1e-12")
        assert w.observations == 10


class TestSqrtTime:
    def test_fixture_sq1(self) -> None:
        iid = sqrt_time_var(D("0.015"), 21)
        assert approx(iid.value, "0.0687", "5e-5")
        ar = sqrt_time_var(D("0.015"), 21, rho=D("0.2"))
        assert approx(ar.variance_factor, "1.4702", "5e-5")
        assert approx(ar.value, "0.0833", "5e-5")
        assert "SQRT_TIME_FALLBACK" in iid.caveats

    def test_never_for_debt(self) -> None:
        with pytest.raises(InvalidInput):
            sqrt_time_var(D("0.015"), 21, category=AssetCategory.DEBT)


# ---------------------------------------------------------------- §6 beta / TE / correlation


class TestPairwise:
    def test_fixture_beta_simple(self) -> None:
        res = beta(R, B, returns=ReturnKind.SIMPLE, gates=FIXTURE_GATES)
        assert approx(res.value, "1.2222", "5e-5")
        assert approx(res.benchmark_variance, "2.185444e-4", "5e-10")
        assert approx(res.covariance, "2.671111e-4", "5e-10")

    def test_beta_default_is_log(self) -> None:
        res = beta(R, B, gates=FIXTURE_GATES)
        assert res.return_kind is ReturnKind.LOG
        assert not approx(res.value, "1.2222", "5e-5")

    def test_fixture_correlation_simple(self) -> None:
        res = correlation(R, B, returns=ReturnKind.SIMPLE, gates=FIXTURE_GATES)
        assert approx(res.value, "0.9831", "5e-5")
        assert res.spearman is not None

    def test_fixture_tracking_error(self) -> None:
        res = tracking_error(R, B, annualisation=252, gates=FIXTURE_GATES)
        assert approx(res.period_value, "0.0047011", "5e-8")
        assert approx(res.value, "0.074627", "5e-7")
        assert res.information_ratio is not None
        expected_ir = 0.0011 * 252 / 0.07462707283553335
        assert approx(res.information_ratio, repr(expected_ir), "1e-9")

    def test_alignment_by_intersection(self) -> None:
        drop = [d for i, d in enumerate(R_DATES) if i != 4]
        b2 = series_from([p for i, p in enumerate(path(B_PCT)) if i != 4], drop)
        res = beta(R, b2, gates=FIXTURE_GATES)
        assert res.observations == 9  # 10 aligned prices → 9 returns
        assert res.dropped == (1, 0)
        assert "ALIGNED_BY_INTERSECTION" in res.caveats

    def test_mixed_frequencies_rejected(self) -> None:
        months = [date(2025, m, 28) for m in range(1, 12)]
        m = series_from(path(B_PCT), months, Frequency.MONTHLY)
        with pytest.raises(InvalidInput, match="frequenc"):
            beta(R, m, gates=FIXTURE_GATES)

    def test_mixed_periods_rejected(self) -> None:
        shifted = series_from(path(B_PCT), bdays(date(2025, 1, 7), 11))
        with pytest.raises(InvalidInput, match="period"):
            tracking_error(R, shifted, annualisation=252, gates=FIXTURE_GATES)

    def test_gate_250_aligned(self) -> None:
        a = synthetic_daily(200, seed=10)
        b = synthetic_daily(200, seed=11)
        with pytest.raises(InsufficientHistory):
            beta(a, b)

    def test_constant_benchmark_beta_undefined(self) -> None:
        flat = series_from([D(100)] * 11, R_DATES)
        res = beta(R, flat, gates=FIXTURE_GATES)
        assert not res.defined and res.value is None

    def test_matrix(self) -> None:
        res = correlation_matrix({"r": R, "b": B}, gates=FIXTURE_GATES)
        assert res.labels == ("r", "b")
        assert res.matrix[0][0] == Decimal(1)
        assert res.matrix[0][1] == res.matrix[1][0]
        lr, lb = R.log_returns(), B.log_returns()
        assert approx(res.matrix[0][1], repr(float(np.corrcoef(lr, lb)[0, 1])), "1e-12")

    def test_matrix_mixed_frequency_rejected(self) -> None:
        months = [date(2025, m, 28) for m in range(1, 12)]
        m = series_from(path(B_PCT), months, Frequency.MONTHLY)
        with pytest.raises(InvalidInput):
            correlation_matrix({"r": R, "m": m}, gates=FIXTURE_GATES)


# ---------------------------------------------------------------- smoothing flag (§4.3)


class TestSmoothing:
    def test_category_triggers(self) -> None:
        res = smoothing_flag(synthetic_daily(300, seed=12), category=AssetCategory.DEBT)
        assert res.flagged
        assert "VOLATILITY_UNDERSTATED_SMOOTHED_NAV" in res.caveats

    def test_ar1_series_flagged_by_ljung_box(self) -> None:
        rng = np.random.default_rng(13)  # SYNTHETIC AR(1), φ = 0.6
        e = rng.normal(0, 0.001, 400)
        r = np.zeros(400)
        for t in range(1, 400):
            r[t] = 0.6 * r[t - 1] + e[t]
        prices = [Decimal(100)]
        for x in r:
            prices.append(prices[-1] * (1 + Decimal(repr(float(x)))))
        s = series_from(prices, bdays(date(2020, 1, 1), 401))
        res = smoothing_flag(s)
        assert res.flagged
        assert res.lag1_autocorrelation > Decimal("0.4")
        assert res.ljung_box_p_value < Decimal("0.05")

    def test_iid_not_flagged(self) -> None:
        res = smoothing_flag(synthetic_daily(400, seed=14), category=AssetCategory.EQUITY)
        assert not res.flagged

    def test_rho_threshold(self) -> None:
        s = synthetic_daily(400, seed=14)
        res = smoothing_flag(s, lag1_threshold=D("-1"))
        assert res.flagged

    def test_too_short(self) -> None:
        with pytest.raises(InsufficientHistory):
            smoothing_flag(R)


# ---------------------------------------------------------------- §7 concentration / credit


SNAP = date(2025, 9, 30)


class TestConcentration:
    def test_fixture_h1(self) -> None:
        res = hhi({"a": D("0.4"), "b": D("0.3"), "c": D("0.2"), "d": D("0.1")}, snapshot_date=SNAP, as_of=SNAP)
        assert res.value == Decimal("0.30")
        assert approx(res.effective_count, "3.3333333", "1e-7")
        assert res.band == "concentrated"
        assert res.method_id == "HHI@1"

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(InvalidInput):
            hhi({"a": D("0.5"), "b": D("0.4")}, snapshot_date=SNAP, as_of=SNAP)

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(InvalidInput):
            hhi({"a": D("1.1"), "b": D("-0.1")}, snapshot_date=SNAP, as_of=SNAP)

    def test_from_values_and_stale(self) -> None:
        res = hhi_from_values(
            {"a": D(400), "b": D(300), "c": D(200), "d": D(100)}, snapshot_date=SNAP, as_of=SNAP + timedelta(days=46)
        )
        assert res.value == Decimal("0.30")
        assert "STALE_HOLDINGS_SNAPSHOT" in res.caveats
        fresh = hhi_from_values({"a": D(1)}, snapshot_date=SNAP, as_of=SNAP + timedelta(days=45))
        assert "STALE_HOLDINGS_SNAPSHOT" not in fresh.caveats

    @pytest.mark.parametrize(
        ("weights", "band"),
        [(["0.1"] * 10, "diversified"), (["0.15", "0.85"], "concentrated"), (["0.5", "0.5"], "concentrated")],
    )
    def test_bands(self, weights: list[str], band: str) -> None:
        res = hhi({str(i): D(w) for i, w in enumerate(weights)}, snapshot_date=SNAP, as_of=SNAP)
        assert res.band == band

    def test_band_boundaries(self) -> None:
        from iip.engine.stats.metrics import hhi_band

        assert hhi_band(Decimal("0.1499")) == "diversified"
        assert hhi_band(Decimal("0.15")) == "moderate"
        assert hhi_band(Decimal("0.25")) == "moderate"
        assert hhi_band(Decimal("0.2501")) == "concentrated"

    def test_issuer_look_through(self) -> None:
        ex = [
            Exposure("fund1:ncd1", D(300), "NBFC-X", CreditBucket.AA),
            Exposure("fund2:ncd7", D(200), "NBFC-X", CreditBucket.AA),
            Exposure("gsec", D(500), "GOI", CreditBucket.SOVEREIGN),
        ]
        agg = issuer_aggregation(ex, snapshot_date=SNAP, as_of=SNAP)
        assert dict(agg.issuer_values) == {"GOI": D(500), "NBFC-X": D(500)}
        assert agg.concentration.value == Decimal("0.5")

    def test_credit_exposure(self) -> None:
        ex = [
            Exposure("g", D(400), "GOI", CreditBucket.SOVEREIGN),
            Exposure("s", D(100), "State-1", CreditBucket.QUASI_SOVEREIGN),
            Exposure("a1", D(200), "Bank-A", CreditBucket.AAA),
            Exposure("a2", D(150), "NBFC-X", CreditBucket.AA),
            Exposure("a3", D(100), "NBFC-Y", CreditBucket.A_AND_BELOW, side_pocket=True),
            Exposure("u", D(50), "Co-Z", CreditBucket.UNRATED),
        ]
        res = credit_exposure(ex, snapshot_date=SNAP, as_of=SNAP)
        assert res.bucket_weights[CreditBucket.SOVEREIGN] == Decimal("0.4")
        assert res.below_aaa_weight == Decimal("0.3")
        assert res.largest_non_sovereign_issuer == ("Bank-A", Decimal("0.2"))
        assert res.side_pocket_present

    def test_dicgc_excess(self) -> None:
        res = deposit_insurance_excess({"bank-a": D(700000), "bank-b": D(300000)}, cover_per_bank=D(500000))
        assert res.excess_by_bank == (("bank-a", D(200000)), ("bank-b", D(0)))
        assert res.total_excess == D(200000)
        assert "COVER_AMOUNT_NOT_VERIFIED" in res.caveats

    def test_empty_holdings_rejected(self) -> None:
        with pytest.raises(InvalidInput):
            hhi_from_values({}, snapshot_date=SNAP, as_of=SNAP)


def test_spec_gates_are_the_default() -> None:
    assert SPEC_GATES == Gates()
    assert SPEC_GATES.vol_min[Frequency.DAILY_BUSINESS] == 60
    assert SPEC_GATES.pairwise_min[Frequency.MONTHLY] == 36
