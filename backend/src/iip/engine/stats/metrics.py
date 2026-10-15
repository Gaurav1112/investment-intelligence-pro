"""Risk metrics (risk-methodology.md §2–§8).  Floats live here; every output crosses back via ``from_float``.

Conventions
* Volatility, correlation, beta: log returns (§1 table).  VaR/CVaR, downside deviation, Sharpe/Sortino
  excess returns, tracking error: simple returns.  Drawdown: from Decimal levels.
* Sample statistics use ddof = 1.  Quantiles use Hyndman–Fan type 1 (lower empirical quantile).
* VaR, CVaR and max drawdown are reported as **positive losses / magnitudes**.
* Every metric enforces its §8 minimum-data gate and raises ``InsufficientHistory`` below it.  Mixing
  frequencies or periods raises ``InvalidInput``.  An undefined ratio (zero denominator) is returned as a
  typed result with ``defined=False`` and ``value=None`` — never ±inf, NaN or 0.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from typing import Literal

import numpy as np
from scipy import stats as sps

from iip.engine.errors import InsufficientHistory, InvalidInput, NumericalError
from iip.engine.money import ONE, ZERO, engine_context, from_float
from iip.engine.stats.series import (
    AlignedPrices,
    Annualisation,
    FloatArray,
    Frequency,
    ReturnSeries,
    align,
)

# ---------------------------------------------------------------------------------------------- enums


class AssetCategory(StrEnum):
    EQUITY = "equity"
    DEBT = "debt"
    LIQUID = "liquid"
    OVERNIGHT = "overnight"
    MONEY_MARKET = "money-market"
    HYBRID = "hybrid"
    OTHER = "other"


# §4.3: smoothed NAVs (matrix pricing / stale valuation) → positive autocorrelation.
SMOOTHED_CATEGORIES = frozenset(
    {
        AssetCategory.DEBT,
        AssetCategory.LIQUID,
        AssetCategory.OVERNIGHT,
        AssetCategory.MONEY_MARKET,
        AssetCategory.HYBRID,
    }
)
# §1 "Weekend accrual effect": compute vol from weekly returns for these.
WEEKLY_VOL_CATEGORIES = frozenset({AssetCategory.LIQUID, AssetCategory.OVERNIGHT, AssetCategory.MONEY_MARKET})


class ReturnKind(StrEnum):
    SIMPLE = "simple"
    LOG = "log"


# ---------------------------------------------------------------------------------------------- caveats

NON_SPEC_GATES = "NON_SPEC_GATES"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
ANNUALISED_WITH_FALLBACK_FACTOR = "ANNUALISED_WITH_FALLBACK_FACTOR"
VOLATILITY_UNDERSTATED = "VOLATILITY_UNDERSTATED_SMOOTHED_NAV"
CREDIT_JUMP_RISK_NOT_IN_VOL = "CREDIT_JUMP_RISK_NOT_IN_VOL"
SHARPE_OVERSTATED = "SHARPE_OVERSTATED_USE_MONTHLY_LO_ADJUSTED"
AUTOCORRELATION_ADJUSTED = "AUTOCORRELATION_ADJUSTED"
AUTOCORRELATION_UNTESTED = "AUTOCORRELATION_UNTESTED"
IID_ANNUALISATION = "IID_ANNUALISATION"
MDD_WITHIN_AVAILABLE_HISTORY = "MDD_WITHIN_AVAILABLE_HISTORY"
PEAK_AT_SERIES_START = "PEAK_AT_SERIES_START"
DRAWDOWN_ONGOING = "DRAWDOWN_ONGOING"
OVERLAPPING_WINDOWS = "OVERLAPPING_WINDOWS_AUTOCORRELATED"
CI_REQUIRES_BLOCK_BOOTSTRAP = "CI_REQUIRES_BLOCK_BOOTSTRAP"
SQRT_TIME_FALLBACK = "SQRT_TIME_FALLBACK"
IID_ZERO_MEAN_ASSUMED = "IID_ZERO_MEAN_ASSUMED"
ALIGNED_BY_INTERSECTION = "ALIGNED_BY_INTERSECTION"
NON_LINEAR_OR_OUTLIER_DRIVEN = "NON_LINEAR_OR_OUTLIER_DRIVEN"
ROLLING_CORRELATION_UNAVAILABLE = "ROLLING_CORRELATION_UNAVAILABLE"
FULL_PERIOD_HIDES_REGIMES = "FULL_PERIOD_CORRELATION_HIDES_REGIME_CHANGES"
AUTOCORRELATION_UNDEFINED = "AUTOCORRELATION_UNDEFINED_CONSTANT_SERIES"
STALE_HOLDINGS_SNAPSHOT = "STALE_HOLDINGS_SNAPSHOT"
COVER_AMOUNT_NOT_VERIFIED = "COVER_AMOUNT_NOT_VERIFIED"
WORST_OBSERVED_NOT_VAR = "WORST_OBSERVED_LOSS_IS_NOT_A_VAR"


# ---------------------------------------------------------------------------------------------- gates


def _per_freq(daily: int, weekly: int, monthly: int) -> dict[Frequency, int]:
    return {Frequency.DAILY_BUSINESS: daily, Frequency.WEEKLY: weekly, Frequency.MONTHLY: monthly}


@dataclass(frozen=True)
class Gates:
    """§8 minimum-data table.  Defaults are the spec values; see the report for derived weekly/monthly values.

    Any instance that differs from ``SPEC_GATES`` stamps ``NON_SPEC_GATES`` onto every result it produces.
    """

    # Volatility: refuse below 60 daily, "low confidence" below 252 daily (spec).  Weekly/monthly: the
    # spec gives none; we require one year weekly (52) and the spec's monthly ratio gate (36), no tier.
    vol_min: dict[Frequency, int] = field(default_factory=lambda: _per_freq(60, 52, 36))
    vol_full_confidence: dict[Frequency, int] = field(default_factory=lambda: _per_freq(252, 52, 36))
    # Sharpe/Sortino: 3 years daily (span) or 36 monthly (spec); weekly 156 = 3 years (derived).
    ratio_min_years: int = 3
    ratio_min_returns: dict[Frequency, int] = field(default_factory=lambda: _per_freq(0, 156, 36))
    sortino_min_below_target: int = 20
    # VaR: 95 % → 3 y, 99 % → 10 y; n_eff = floor(N/h) ≥ 20; CVaR tail ≥ 10 (spec).
    var_min_years_95: int = 3
    var_min_years_99: int = 10
    var_min_effective: int = 20
    cvar_min_tail: int = 10
    # Beta/TE/correlation: 250 daily or 36 monthly (spec); weekly 156 = 3 years (derived).
    pairwise_min: dict[Frequency, int] = field(default_factory=lambda: _per_freq(250, 156, 36))
    # Drawdown: label (not refuse) below 3 years.
    mdd_full_years: int = 3
    # Ljung-Box (§4.3): lags 1–10 at 5 %.  Needs ≥ 2 × lags returns (implementation choice).
    ljung_box_lags: int = 10
    ljung_box_alpha: Decimal = Decimal("0.05")
    smoothing_min_returns: int = 20

    @classmethod
    def relaxed_for_fixtures(cls, **overrides: int) -> Gates:
        """Gates with every minimum at zero, for formula fixtures (spec §2: "fixture R … would be gated")."""
        base: dict[str, object] = {
            "vol_min": _per_freq(0, 0, 0),
            "vol_full_confidence": _per_freq(0, 0, 0),
            "ratio_min_years": 0,
            "ratio_min_returns": _per_freq(0, 0, 0),
            "sortino_min_below_target": 0,
            "var_min_years_95": 0,
            "var_min_years_99": 0,
            "var_min_effective": 0,
            "cvar_min_tail": 0,
            "pairwise_min": _per_freq(0, 0, 0),
        }
        base.update(overrides)
        return cls(**base)  # type: ignore[arg-type]


SPEC_GATES = Gates()
STALE_SNAPSHOT_DAYS = 45  # §8: holdings snapshot / factsheet ≤ 45 days old


def _gate_caveats(gates: Gates) -> list[str]:
    return [] if gates == SPEC_GATES else [NON_SPEC_GATES]


def _require_eligible(series: ReturnSeries) -> None:
    if not series.risk_eligible:
        raise InsufficientHistory(
            f"series rejected for risk stats: {len(series.gaps)} suspect gap(s) = "
            f"{series.suspect_fraction:.4%} of observations (> 2 %)"
        )


# ---------------------------------------------------------------------------------------------- results


@dataclass(frozen=True, kw_only=True)
class SeriesMetric:
    value: Decimal | None
    period_start: date
    period_end: date
    frequency: Frequency
    observations: int
    method_id: str
    caveats: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class VolatilityResult(SeriesMetric):
    value: Decimal
    period_value: Decimal
    annualisation_factor: int
    annualisation_source: str
    return_kind: ReturnKind = ReturnKind.LOG


@dataclass(frozen=True, kw_only=True)
class DrawdownResult(SeriesMetric):
    value: Decimal  # positive magnitude: 0.0397 means a −3.97 % drawdown
    peak_date: date | None
    trough_date: date | None
    recovery_date: date | None
    recovered: bool
    peak_to_trough_obs: int | None
    trough_to_recovery_obs: int | None
    underwater_obs: int | None
    peak_to_trough_days: int | None
    trough_to_recovery_days: int | None
    underwater_days: int | None
    ongoing_min_obs: int | None  # "≥ n (ongoing)" when not recovered
    largest_one_period_loss: Decimal
    sign_convention: str = "positive_magnitude"


@dataclass(frozen=True, kw_only=True)
class RatioResult(SeriesMetric):
    """Sharpe/Sortino.  ``value`` is annualised; ``None`` with ``defined=False`` when the denominator is 0."""

    period_value: Decimal | None
    defined: bool
    undefined_reason: str | None
    annualisation_factor: int
    annualisation_source: str
    return_kind: ReturnKind = ReturnKind.SIMPLE


@dataclass(frozen=True, kw_only=True)
class SharpeResult(RatioResult):
    mean_excess: Decimal
    stdev_excess: Decimal
    risk_free_per_period: Decimal  # mean of the per-period risk-free series actually subtracted
    lo_eta: Decimal | None


@dataclass(frozen=True, kw_only=True)
class DownsideDeviationResult(SeriesMetric):
    value: Decimal
    target_per_period: Decimal  # mean target when a series is supplied
    below_target_obs: int


@dataclass(frozen=True, kw_only=True)
class SortinoResult(RatioResult):
    downside_deviation: Decimal
    target_per_period: Decimal
    below_target_obs: int


@dataclass(frozen=True, kw_only=True)
class VaRResult(SeriesMetric):
    value: Decimal  # positive loss fraction
    confidence: Decimal
    horizon: int
    k: int
    windows: int
    effective_observations: int
    position: Decimal | None
    value_inr: Decimal | None
    sign_convention: str = "positive_loss"


@dataclass(frozen=True, kw_only=True)
class CVaRResult(VaRResult):
    tail_observations: int


@dataclass(frozen=True, kw_only=True)
class WorstObservedLossResult(SeriesMetric):
    value: Decimal
    horizon: int
    years_covered: Decimal
    label: str


@dataclass(frozen=True)
class SqrtTimeVaRResult:
    value: Decimal
    one_period_var: Decimal
    horizon: int
    rho: Decimal | None
    variance_factor: Decimal
    method_id: str
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class LoEtaResult:
    value: Decimal
    iid_value: Decimal
    q: int
    autocorrelations: tuple[Decimal, ...]
    method_id: str = "LO_ETA@1"


@dataclass(frozen=True, kw_only=True)
class PairwiseMetric(SeriesMetric):
    dropped: tuple[int, int]  # observations dropped by the date inner-join (portfolio, benchmark)
    return_kind: ReturnKind


@dataclass(frozen=True, kw_only=True)
class BetaResult(PairwiseMetric):
    covariance: Decimal
    benchmark_variance: Decimal
    defined: bool
    undefined_reason: str | None


@dataclass(frozen=True, kw_only=True)
class TrackingErrorResult(PairwiseMetric):
    value: Decimal
    period_value: Decimal
    information_ratio: Decimal | None
    annualisation_factor: int
    annualisation_source: str


@dataclass(frozen=True, kw_only=True)
class CorrelationResult(PairwiseMetric):
    spearman: Decimal | None
    defined: bool
    rolling_window: int
    rolling_min: Decimal | None
    rolling_max: Decimal | None


@dataclass(frozen=True, kw_only=True)
class CorrelationMatrixResult(SeriesMetric):
    labels: tuple[str, ...]
    matrix: tuple[tuple[Decimal | None, ...], ...]
    dropped: tuple[int, ...]
    return_kind: ReturnKind


@dataclass(frozen=True, kw_only=True)
class SmoothingResult(SeriesMetric):
    flagged: bool
    reasons: tuple[str, ...]
    lag1_autocorrelation: Decimal | None
    ljung_box_q: Decimal | None
    ljung_box_p_value: Decimal | None
    ljung_box_lags: int
    category: AssetCategory | None


# ---------------------------------------------------------------------------------------------- helpers


def _base(series: ReturnSeries, observations: int, method_id: str, caveats: list[str]) -> dict[str, object]:
    return {
        "period_start": series.start,
        "period_end": series.end,
        "frequency": series.frequency,
        "observations": observations,
        "method_id": method_id,
        "caveats": tuple(dict.fromkeys(caveats)),
    }


def _ann_caveats(a: Annualisation) -> list[str]:
    return [ANNUALISED_WITH_FALLBACK_FACTOR] if a.source == "fallback" else []


def _autocorrelations(x: FloatArray, max_lag: int) -> list[float] | None:
    """Sample autocorrelations ρ_1..ρ_max_lag (Box–Jenkins estimator).  None if the series is constant."""
    d = x - x.mean()
    denom = float(np.dot(d, d))
    if denom == 0.0:
        return None
    return [float(np.dot(d[:-k], d[k:])) / denom for k in range(1, max_lag + 1)]


def _ljung_box(x: FloatArray, lags: int) -> tuple[float, float] | None:
    rho = _autocorrelations(x, lags)
    if rho is None:
        return None
    n = len(x)
    q = n * (n + 2) * sum(r * r / (n - k) for k, r in enumerate(rho, start=1))
    p = float(sps.chi2.sf(q, lags))
    return q, p


def _smoothing_triggered(returns: FloatArray, category: AssetCategory | None, gates: Gates) -> tuple[bool, bool]:
    """(triggered, tested).  Triggered when the category is smoothed or Ljung-Box rejects (§4.3)."""
    if category in SMOOTHED_CATEGORIES:
        return True, True
    if len(returns) < gates.smoothing_min_returns:
        return False, False
    lb = _ljung_box(returns, gates.ljung_box_lags)
    if lb is None:
        return False, True
    return lb[1] < float(gates.ljung_box_alpha), True


# ---------------------------------------------------------------------------------------------- §2 volatility


def volatility(
    series: ReturnSeries,
    *,
    annualisation: int | None = None,
    category: AssetCategory | None = None,
    gates: Gates = SPEC_GATES,
) -> VolatilityResult:
    """``σ_ann = stdev(ln returns, ddof=1) × √A`` (VOL_LOG_DDOF1@1)."""
    _require_eligible(series)
    freq = series.frequency
    if category in WEEKLY_VOL_CATEGORIES and freq is Frequency.DAILY_BUSINESS:
        raise InvalidInput(
            f"{category} fund NAVs carry the weekend-accrual effect: compute vol from weekly "
            "(Wednesday-to-Wednesday) returns (risk-methodology §1)"
        )
    n = series.n_returns
    minimum = max(2, gates.vol_min[freq])
    if n < minimum:
        raise InsufficientHistory(f"volatility needs ≥ {minimum} {freq.value} returns, got {n}")
    caveats = _gate_caveats(gates)
    if n < gates.vol_full_confidence[freq]:
        caveats.append(LOW_CONFIDENCE)
    lr = series.log_returns()
    a = series.annualisation(annualisation)
    caveats += _ann_caveats(a)
    triggered, _ = _smoothing_triggered(lr, category, gates)
    if triggered:
        caveats.append(VOLATILITY_UNDERSTATED)
    if category in SMOOTHED_CATEGORIES:
        caveats.append(CREDIT_JUMP_RISK_NOT_IN_VOL)
    sd = float(np.std(lr, ddof=1))
    return VolatilityResult(
        value=from_float(sd * math.sqrt(a.factor)),
        period_value=from_float(sd),
        annualisation_factor=a.factor,
        annualisation_source=a.source,
        **_base(series, n, "VOL_LOG_DDOF1@1", caveats),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------------------------- §3 drawdown


def max_drawdown(series: ReturnSeries, *, gates: Gates = SPEC_GATES) -> DrawdownResult:
    """MDD from Decimal levels with peak, trough, recovery and durations (MDD@1)."""
    _require_eligible(series)
    prices = series.prices
    dates = series.dates
    caveats = _gate_caveats(gates)
    if not series.covers_years(gates.mdd_full_years):
        caveats.append(MDD_WITHIN_AVAILABLE_HISTORY)
    with engine_context():
        peak, peak_idx = prices[0], 0
        worst = ZERO
        trough_idx: int | None = None
        trough_peak_idx = 0
        largest_loss = ZERO
        for t in range(1, len(prices)):
            p = prices[t]
            loss = ONE - p / prices[t - 1]
            largest_loss = max(largest_loss, loss)
            if p >= peak:
                peak, peak_idx = p, t
                continue
            dd = ONE - p / peak  # positive magnitude
            if dd > worst:
                worst, trough_idx, trough_peak_idx = dd, t, peak_idx
    last = len(prices) - 1
    if trough_idx is None:
        return DrawdownResult(
            value=ZERO,
            peak_date=None,
            trough_date=None,
            recovery_date=None,
            recovered=True,
            peak_to_trough_obs=None,
            trough_to_recovery_obs=None,
            underwater_obs=None,
            peak_to_trough_days=None,
            trough_to_recovery_days=None,
            underwater_days=None,
            ongoing_min_obs=None,
            largest_one_period_loss=largest_loss,
            **_base(series, series.n_returns, "MDD@1", caveats),  # type: ignore[arg-type]
        )
    peak_level = prices[trough_peak_idx]
    recovery_idx = next((t for t in range(trough_idx + 1, last + 1) if prices[t] >= peak_level), None)
    if trough_peak_idx == 0:
        caveats.append(PEAK_AT_SERIES_START)
    p_date, t_date = dates[trough_peak_idx], dates[trough_idx]
    if recovery_idx is None:
        caveats.append(DRAWDOWN_ONGOING)
        r_date = None
        t2r_obs = uw_obs = t2r_days = uw_days = None
        ongoing: int | None = last - trough_peak_idx
    else:
        r_date = dates[recovery_idx]
        t2r_obs, uw_obs = recovery_idx - trough_idx, recovery_idx - trough_peak_idx
        t2r_days, uw_days = (r_date - t_date).days, (r_date - p_date).days
        ongoing = None
    return DrawdownResult(
        value=worst,
        peak_date=p_date,
        trough_date=t_date,
        recovery_date=r_date,
        recovered=recovery_idx is not None,
        peak_to_trough_obs=trough_idx - trough_peak_idx,
        trough_to_recovery_obs=t2r_obs,
        underwater_obs=uw_obs,
        peak_to_trough_days=(t_date - p_date).days,
        trough_to_recovery_days=t2r_days,
        underwater_days=uw_days,
        ongoing_min_obs=ongoing,
        largest_one_period_loss=largest_loss,
        **_base(series, series.n_returns, "MDD@1", caveats),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------------------------- §4 risk-free


def tbill_effective_annual(money_market_yield: Decimal) -> Decimal:
    """§4.1: ``y_eff = (1 + y × 91/365)^(365/91) − 1`` for the 91-day T-bill yield."""
    with engine_context():
        return (ONE + money_market_yield * Decimal(91) / Decimal(365)) ** (Decimal(365) / Decimal(91)) - ONE


@dataclass(frozen=True)
class RiskFreeSeries:
    """Point-in-time effective-annual risk-free yields, one per return end date, at a declared frequency.

    Converted to the series frequency with the metric's own ``A`` before subtraction (§1.1 rule 2):
    ``r_f,period = (1 + y_eff)^(1/A) − 1``.
    """

    dates: tuple[date, ...]
    effective_annual: tuple[Decimal, ...]
    frequency: Frequency

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.effective_annual) or not self.dates:
            raise InvalidInput("risk-free dates and yields must be non-empty and equal in length")
        for a, b in zip(self.dates, self.dates[1:], strict=False):
            if b <= a:
                raise InvalidInput("risk-free dates must be strictly increasing")
        for y in self.effective_annual:
            if not isinstance(y, Decimal) or not y.is_finite() or y <= -1:
                raise InvalidInput(f"invalid risk-free yield {y!r}")

    @classmethod
    def from_constant(cls, dates: Sequence[date], effective_annual: Decimal, frequency: Frequency) -> RiskFreeSeries:
        return cls(tuple(dates), tuple(effective_annual for _ in dates), frequency)

    def per_period(self, series: ReturnSeries, factor: int) -> FloatArray:
        if self.frequency is not series.frequency:
            raise InvalidInput(
                f"mixed frequencies: risk-free {self.frequency.value} vs series {series.frequency.value}"
            )
        if self.dates != series.return_dates:
            raise InvalidInput("risk-free dates do not align with the series' return dates (exact match required)")
        y = np.array([float(v) for v in self.effective_annual], dtype=np.float64)
        return np.power(1.0 + y, 1.0 / factor) - 1.0


def _ratio_gate(series: ReturnSeries, gates: Gates, name: str) -> None:
    minimum = max(2, gates.ratio_min_returns[series.frequency])
    if not series.covers_years(gates.ratio_min_years):
        raise InsufficientHistory(f"{name} needs ≥ {gates.ratio_min_years} years of history")
    if series.n_returns < minimum:
        raise InsufficientHistory(f"{name} needs ≥ {minimum} {series.frequency.value} returns")


def lo_eta(q: int, autocorrelations: Sequence[Decimal | float]) -> LoEtaResult:
    """Lo (2002): ``η(q) = q / sqrt(q + 2 Σ_{k=1}^{q−1} (q−k) ρ_k)``."""
    if q < 1:
        raise InvalidInput("q must be ≥ 1")
    if len(autocorrelations) < q - 1:
        raise InvalidInput(f"η({q}) needs {q - 1} autocorrelations, got {len(autocorrelations)}")
    rho = [float(r) for r in autocorrelations[: q - 1]]
    if any(not -1.0 <= r <= 1.0 for r in rho):
        raise InvalidInput("autocorrelations must lie in [−1, 1]")
    denom = q + 2 * sum((q - k) * r for k, r in enumerate(rho, start=1))
    if denom <= 0:
        raise NumericalError(f"Lo η denominator is non-positive ({denom}); autocorrelations inconsistent")
    return LoEtaResult(
        value=from_float(q / math.sqrt(denom)),
        iid_value=from_float(math.sqrt(q)),
        q=q,
        autocorrelations=tuple(from_float(r) for r in rho),
    )


def sharpe(
    series: ReturnSeries,
    risk_free: RiskFreeSeries,
    *,
    annualisation: int | None = None,
    category: AssetCategory | None = None,
    gates: Gates = SPEC_GATES,
) -> SharpeResult:
    """§4.1 Sharpe on simple excess returns; §4.3 Lo-adjusted monthly Sharpe when autocorrelation applies."""
    _require_eligible(series)
    _ratio_gate(series, gates, "Sharpe")
    a = series.annualisation(annualisation)
    rf = risk_free.per_period(series, a.factor)
    excess = series.simple_returns() - rf
    caveats = _gate_caveats(gates) + _ann_caveats(a)
    triggered, tested = _smoothing_triggered(series.simple_returns(), category, gates)
    if not tested:
        caveats.append(AUTOCORRELATION_UNTESTED)
    mean = float(excess.mean())
    sd = float(np.std(excess, ddof=1))
    eta: LoEtaResult | None = None
    method = "SHARPE@1"
    if triggered:
        if series.frequency is not Frequency.MONTHLY:
            raise InvalidInput(
                "autocorrelated / smoothed NAVs: Sharpe must be computed from monthly returns (A = 12) "
                "with Lo's adjustment (risk-methodology §4.3)"
            )
        method = "SHARPE_LO2002@1"
        caveats.append(AUTOCORRELATION_ADJUSTED)
    else:
        caveats.append(IID_ANNUALISATION)
    n = series.n_returns
    common = _base(series, n, method, caveats)
    if sd == 0.0 or float(np.ptp(excess)) == 0.0:
        return SharpeResult(
            value=None,
            period_value=None,
            defined=False,
            undefined_reason="ZERO_VOLATILITY",
            annualisation_factor=a.factor,
            annualisation_source=a.source,
            mean_excess=from_float(mean),
            stdev_excess=from_float(0.0),
            risk_free_per_period=from_float(float(rf.mean())),
            lo_eta=None,
            **common,  # type: ignore[arg-type]
        )
    sr = mean / sd
    if triggered:
        q = a.factor
        if n <= q:
            raise InsufficientHistory(f"Lo adjustment with q = {q} needs > {q} returns")
        rho = _autocorrelations(excess, q - 1)
        if rho is None:  # pragma: no cover - sd > 0 implies non-constant
            raise NumericalError("autocorrelation undefined")
        eta = lo_eta(q, rho)
        ann = sr * float(eta.value)
    else:
        ann = sr * math.sqrt(a.factor)
    return SharpeResult(
        value=from_float(ann),
        period_value=from_float(sr),
        defined=True,
        undefined_reason=None,
        annualisation_factor=a.factor,
        annualisation_source=a.source,
        mean_excess=from_float(mean),
        stdev_excess=from_float(sd),
        risk_free_per_period=from_float(float(rf.mean())),
        lo_eta=None if eta is None else eta.value,
        **common,  # type: ignore[arg-type]
    )


def _target_array(series: ReturnSeries, target: Decimal | RiskFreeSeries, factor: int) -> FloatArray:
    if isinstance(target, RiskFreeSeries):
        return target.per_period(series, factor)
    if not isinstance(target, Decimal) or not target.is_finite():
        raise InvalidInput("target must be a finite Decimal per-period return or a RiskFreeSeries")
    return np.full(series.n_returns, float(target), dtype=np.float64)


def _lpm2(series: ReturnSeries, tau: FloatArray) -> tuple[float, int]:
    diff = series.simple_returns() - tau
    shortfall = np.minimum(diff, 0.0)
    return math.sqrt(float(np.mean(shortfall * shortfall))), int(np.count_nonzero(diff < 0))


def downside_deviation(
    series: ReturnSeries,
    target: Decimal | RiskFreeSeries,
    *,
    annualisation: int | None = None,
    gates: Gates = SPEC_GATES,
) -> DownsideDeviationResult:
    """§4.2: ``DD_τ = sqrt((1/N) Σ min(r_t − τ, 0)²)`` — full-sample denominator N (LPM2@1)."""
    _require_eligible(series)
    _ratio_gate(series, gates, "downside deviation")
    a = series.annualisation(annualisation)
    tau = _target_array(series, target, a.factor)
    dd, below = _lpm2(series, tau)
    return DownsideDeviationResult(
        value=from_float(dd),
        target_per_period=from_float(float(tau.mean())),
        below_target_obs=below,
        **_base(series, series.n_returns, "LPM2_FULL_N@1", _gate_caveats(gates)),  # type: ignore[arg-type]
    )


def sortino(
    series: ReturnSeries,
    target: Decimal | RiskFreeSeries,
    *,
    annualisation: int | None = None,
    category: AssetCategory | None = None,
    gates: Gates = SPEC_GATES,
) -> SortinoResult:
    """§4.2: ``Sortino = (mean(r) − τ) / DD_τ``, annualised × √A (SORTINO_LPM2@1)."""
    _require_eligible(series)
    _ratio_gate(series, gates, "Sortino")
    a = series.annualisation(annualisation)
    tau = _target_array(series, target, a.factor)
    dd, below = _lpm2(series, tau)
    if below < gates.sortino_min_below_target:
        raise InsufficientHistory(
            f"Sortino needs ≥ {gates.sortino_min_below_target} below-target observations, got {below}"
        )
    caveats = _gate_caveats(gates) + _ann_caveats(a) + [IID_ANNUALISATION]
    if category in SMOOTHED_CATEGORIES:
        caveats.append(SHARPE_OVERSTATED)
    excess_mean = float(series.simple_returns().mean() - tau.mean())
    common = _base(series, series.n_returns, "SORTINO_LPM2@1", caveats)
    if dd == 0.0:
        return SortinoResult(
            value=None,
            period_value=None,
            defined=False,
            undefined_reason="ZERO_DOWNSIDE_DEVIATION",
            annualisation_factor=a.factor,
            annualisation_source=a.source,
            downside_deviation=from_float(0.0),
            target_per_period=from_float(float(tau.mean())),
            below_target_obs=below,
            **common,  # type: ignore[arg-type]
        )
    ratio = excess_mean / dd
    return SortinoResult(
        value=from_float(ratio * math.sqrt(a.factor)),
        period_value=from_float(ratio),
        defined=True,
        undefined_reason=None,
        annualisation_factor=a.factor,
        annualisation_source=a.source,
        downside_deviation=from_float(dd),
        target_per_period=from_float(float(tau.mean())),
        below_target_obs=below,
        **common,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------------------------- §5 VaR / CVaR


def _check_confidence(confidence: Decimal) -> None:
    if not isinstance(confidence, Decimal) or not confidence.is_finite() or not ZERO < confidence < ONE:
        raise InvalidInput(f"confidence must be a Decimal in (0, 1), got {confidence!r}")


def _ceil(x: Decimal) -> int:
    with engine_context():
        return int(x.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class _VarCore:
    sorted_returns: FloatArray
    k: int
    windows: int
    n_eff: int
    caveats: list[str]


def _var_core(series: ReturnSeries, confidence: Decimal, horizon: int, gates: Gates) -> _VarCore:
    _check_confidence(confidence)
    _require_eligible(series)
    if confidence <= Decimal("0.95"):
        years = gates.var_min_years_95
    elif confidence <= Decimal("0.99"):
        years = gates.var_min_years_99
    else:
        raise InvalidInput("the spec defines VaR gates only up to 99 % confidence")
    if not series.covers_years(years):
        raise InsufficientHistory(
            f"VaR at {confidence} needs ≥ {years} years of history; show worst observed loss instead"
        )
    rh = series.horizon_returns(horizon)
    n_eff = series.n_returns // horizon
    if n_eff < gates.var_min_effective:
        raise InsufficientHistory(
            f"horizon VaR needs n_eff = floor(N/h) ≥ {gates.var_min_effective}, got n_eff = {n_eff}; "
            "present scenario bands instead"
        )
    windows = len(rh)
    with engine_context():
        k = _ceil(Decimal(windows) * (ONE - confidence))
    k = min(max(k, 1), windows)
    caveats = _gate_caveats(gates)
    if horizon > 1:
        caveats += [OVERLAPPING_WINDOWS, CI_REQUIRES_BLOCK_BOOTSTRAP]
    return _VarCore(np.sort(rh), k, windows, n_eff, caveats)


def _inr(fraction: Decimal, position: Decimal | None) -> Decimal | None:
    if position is None:
        return None
    if not isinstance(position, Decimal) or not position.is_finite() or position < 0:
        raise InvalidInput("position must be a non-negative Decimal")
    with engine_context():
        return position * fraction


def historical_var(
    series: ReturnSeries,
    confidence: Decimal,
    *,
    horizon: int = 1,
    position: Decimal | None = None,
    gates: Gates = SPEC_GATES,
) -> VaRResult:
    """§5.1/5.2: ``VaR_α = −r_(k)``, ``k = ceil(N(1−α))`` on (overlapping) simple h-period returns."""
    core = _var_core(series, confidence, horizon, gates)
    var = from_float(-float(core.sorted_returns[core.k - 1]))
    return VaRResult(
        value=var,
        confidence=confidence,
        horizon=horizon,
        k=core.k,
        windows=core.windows,
        effective_observations=core.n_eff,
        position=position,
        value_inr=_inr(var, position),
        **_base(series, core.windows, "VAR_HIST_HF1@1", core.caveats),  # type: ignore[arg-type]
    )


def historical_cvar(
    series: ReturnSeries,
    confidence: Decimal,
    *,
    horizon: int = 1,
    position: Decimal | None = None,
    gates: Gates = SPEC_GATES,
) -> CVaRResult:
    """§5.1: ``CVaR_α = −mean(r_(1..k))``; requires ``ceil(N_eff(1−α)) ≥ 10`` tail observations."""
    core = _var_core(series, confidence, horizon, gates)
    tail = _ceil(Decimal(core.n_eff) * (ONE - confidence))
    if tail < gates.cvar_min_tail:
        raise InsufficientHistory(f"CVaR needs ≥ {gates.cvar_min_tail} effective tail observations, got {tail}")
    cvar = from_float(-float(np.mean(core.sorted_returns[: core.k])))
    return CVaRResult(
        value=cvar,
        confidence=confidence,
        horizon=horizon,
        k=core.k,
        windows=core.windows,
        effective_observations=core.n_eff,
        position=position,
        value_inr=_inr(cvar, position),
        tail_observations=tail,
        **_base(series, core.windows, "CVAR_HIST_HF1@1", core.caveats),  # type: ignore[arg-type]
    )


def worst_observed_loss(series: ReturnSeries, *, horizon: int = 1) -> WorstObservedLossResult:
    """§5.3 / §8 fallback below the VaR gate: "worst observed loss in N years" (not a VaR)."""
    _require_eligible(series)
    rh = series.horizon_returns(horizon)
    with engine_context():
        years = (Decimal(series.span_days) / Decimal("365.25")).quantize(Decimal("0.1"))
    caveats = [WORST_OBSERVED_NOT_VAR] + ([OVERLAPPING_WINDOWS] if horizon > 1 else [])
    return WorstObservedLossResult(
        value=from_float(-float(rh.min())),
        horizon=horizon,
        years_covered=years,
        label=f"worst observed loss in {years} years",
        **_base(series, len(rh), "WORST_OBSERVED_LOSS@1", caveats),  # type: ignore[arg-type]
    )


def sqrt_time_var(
    one_period_var: Decimal,
    horizon: int,
    *,
    rho: Decimal | None = None,
    category: AssetCategory | None = None,
) -> SqrtTimeVaRResult:
    """§5.2 labelled fallback: ``VaR_h = VaR_1 × sqrt(h × [1 + 2 Σ_{k=1}^{h−1} (1 − k/h) ρ^k])``."""
    if category in SMOOTHED_CATEGORIES:
        raise InvalidInput("√t-scaled VaR is never used for debt / smoothed-NAV funds (risk-methodology §5.2)")
    if horizon < 1:
        raise InvalidInput("horizon must be ≥ 1")
    if not isinstance(one_period_var, Decimal) or not one_period_var.is_finite():
        raise InvalidInput("one_period_var must be a finite Decimal")
    caveats = [SQRT_TIME_FALLBACK]
    r = 0.0
    if rho is None:
        caveats.append(IID_ZERO_MEAN_ASSUMED)
    else:
        r = float(rho)
        if not -1.0 < r < 1.0:
            raise InvalidInput("rho must lie in (−1, 1)")
    factor = 1.0 + 2.0 * sum((1.0 - k / horizon) * r**k for k in range(1, horizon))
    if factor <= 0:
        raise NumericalError(f"variance factor {factor} is non-positive")
    return SqrtTimeVaRResult(
        value=from_float(float(one_period_var) * math.sqrt(horizon * factor)),
        one_period_var=one_period_var,
        horizon=horizon,
        rho=rho,
        variance_factor=from_float(factor),
        method_id="VAR_SQRT_T@1",
        caveats=tuple(caveats),
    )


# ---------------------------------------------------------------------------------------------- §6 pairwise


def _pairwise(a: ReturnSeries, b: ReturnSeries, gates: Gates, name: str) -> tuple[AlignedPrices, list[str]]:
    aligned = align([a, b])
    _require_eligible(a)
    _require_eligible(b)
    minimum = max(3, gates.pairwise_min[aligned.frequency])
    if aligned.n_returns < minimum:
        raise InsufficientHistory(
            f"{name} needs ≥ {minimum} aligned {aligned.frequency.value} returns, got {aligned.n_returns}"
        )
    caveats = _gate_caveats(gates)
    if any(aligned.dropped):
        caveats.append(ALIGNED_BY_INTERSECTION)
    return aligned, caveats


def _returns(aligned: AlignedPrices, i: int, kind: ReturnKind) -> FloatArray:
    return aligned.log_returns(i) if kind is ReturnKind.LOG else aligned.simple_returns(i)


def _pair_base(aligned: AlignedPrices, method_id: str, caveats: list[str], kind: ReturnKind) -> dict[str, object]:
    return {
        "period_start": aligned.dates[0],
        "period_end": aligned.dates[-1],
        "frequency": aligned.frequency,
        "observations": aligned.n_returns,
        "method_id": method_id,
        "caveats": tuple(dict.fromkeys(caveats)),
        "dropped": (aligned.dropped[0], aligned.dropped[1]),
        "return_kind": kind,
    }


def beta(
    portfolio: ReturnSeries,
    benchmark: ReturnSeries,
    *,
    returns: ReturnKind = ReturnKind.LOG,
    gates: Gates = SPEC_GATES,
) -> BetaResult:
    """§6: ``β = cov(r_p, r_b) / var(r_b)``, ddof = 1, on date-intersected returns (BETA@1)."""
    aligned, caveats = _pairwise(portfolio, benchmark, gates, "beta")
    rp, rb = _returns(aligned, 0, returns), _returns(aligned, 1, returns)
    cov = float(np.cov(rp, rb, ddof=1)[0, 1])
    var_b = float(np.var(rb, ddof=1))
    common = _pair_base(aligned, "BETA@1", caveats, returns)
    if var_b == 0.0:
        return BetaResult(
            value=None,
            covariance=from_float(cov),
            benchmark_variance=from_float(0.0),
            defined=False,
            undefined_reason="ZERO_BENCHMARK_VARIANCE",
            **common,  # type: ignore[arg-type]
        )
    return BetaResult(
        value=from_float(cov / var_b),
        covariance=from_float(cov),
        benchmark_variance=from_float(var_b),
        defined=True,
        undefined_reason=None,
        **common,  # type: ignore[arg-type]
    )


def tracking_error(
    portfolio: ReturnSeries,
    benchmark: ReturnSeries,
    *,
    annualisation: int | None = None,
    gates: Gates = SPEC_GATES,
) -> TrackingErrorResult:
    """§6: ``TE = stdev(r_p − r_b, ddof=1) × √A`` on simple returns; ``IR = mean(active) × A / TE``."""
    aligned, caveats = _pairwise(portfolio, benchmark, gates, "tracking error")
    active = aligned.simple_returns(0) - aligned.simple_returns(1)
    a = aligned.annualisation(annualisation)
    caveats += _ann_caveats(a)
    te_p = float(np.std(active, ddof=1))
    te = te_p * math.sqrt(a.factor)
    ir = None if te == 0.0 else from_float(float(active.mean()) * a.factor / te)
    return TrackingErrorResult(
        value=from_float(te),
        period_value=from_float(te_p),
        information_ratio=ir,
        annualisation_factor=a.factor,
        annualisation_source=a.source,
        **_pair_base(aligned, "TE@1", caveats, ReturnKind.SIMPLE),  # type: ignore[arg-type]
    )


def _pearson(x: FloatArray, y: FloatArray) -> float | None:
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return None
    dx, dy = x - x.mean(), y - y.mean()
    return float(np.dot(dx, dy) / math.sqrt(float(np.dot(dx, dx)) * float(np.dot(dy, dy))))


def _ranks(x: FloatArray) -> FloatArray:
    """Average ranks for ties (the Spearman convention)."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=np.float64)
    sx = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def correlation(
    a: ReturnSeries,
    b: ReturnSeries,
    *,
    returns: ReturnKind = ReturnKind.LOG,
    annualisation: int | None = None,
    gates: Gates = SPEC_GATES,
) -> CorrelationResult:
    """§6: Pearson (headline) and Spearman; flag |Pearson − Spearman| > 0.2; rolling 1-year range."""
    aligned, caveats = _pairwise(a, b, gates, "correlation")
    x, y = _returns(aligned, 0, returns), _returns(aligned, 1, returns)
    pearson = _pearson(x, y)
    spear = _pearson(_ranks(x), _ranks(y))
    if pearson is not None and spear is not None and abs(pearson - spear) > 0.2:
        caveats.append(NON_LINEAR_OR_OUTLIER_DRIVEN)
    window = aligned.annualisation(annualisation).factor
    rolling: list[float] = []
    if len(x) - window + 1 >= 2:
        for s in range(len(x) - window + 1):
            c = _pearson(x[s : s + window], y[s : s + window])
            if c is not None:
                rolling.append(c)
    if rolling:
        caveats.append(FULL_PERIOD_HIDES_REGIMES)
    else:
        caveats.append(ROLLING_CORRELATION_UNAVAILABLE)
    return CorrelationResult(
        value=None if pearson is None else from_float(pearson),
        spearman=None if spear is None else from_float(spear),
        defined=pearson is not None,
        rolling_window=window,
        rolling_min=from_float(min(rolling)) if rolling else None,
        rolling_max=from_float(max(rolling)) if rolling else None,
        **_pair_base(aligned, "CORR_PEARSON@1", caveats, returns),  # type: ignore[arg-type]
    )


def correlation_matrix(
    series: Mapping[str, ReturnSeries],
    *,
    returns: ReturnKind = ReturnKind.LOG,
    gates: Gates = SPEC_GATES,
) -> CorrelationMatrixResult:
    """Pearson correlation matrix on date-intersected returns.  Entries for a constant series are ``None``."""
    if len(series) < 2:
        raise InvalidInput("a correlation matrix needs ≥ 2 series")
    labels = tuple(series)
    items = [series[k] for k in labels]
    aligned = align(items)
    for s in items:
        _require_eligible(s)
    minimum = max(3, gates.pairwise_min[aligned.frequency])
    if aligned.n_returns < minimum:
        raise InsufficientHistory(f"correlation matrix needs ≥ {minimum} aligned returns")
    caveats = _gate_caveats(gates)
    if any(aligned.dropped):
        caveats.append(ALIGNED_BY_INTERSECTION)
    rets = [_returns(aligned, i, returns) for i in range(len(items))]
    n = len(items)
    m: list[list[Decimal | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            c = _pearson(rets[i], rets[j])
            val = None if c is None else (ONE if i == j else from_float(c))
            m[i][j] = m[j][i] = val
    return CorrelationMatrixResult(
        value=None,
        labels=labels,
        matrix=tuple(tuple(row) for row in m),
        dropped=aligned.dropped,
        return_kind=returns,
        period_start=aligned.dates[0],
        period_end=aligned.dates[-1],
        frequency=aligned.frequency,
        observations=aligned.n_returns,
        method_id="CORR_MATRIX_PEARSON@1",
        caveats=tuple(dict.fromkeys(caveats)),
    )


# ---------------------------------------------------------------------------------------------- §4.3 smoothing


def smoothing_flag(
    series: ReturnSeries,
    *,
    category: AssetCategory | None = None,
    lag1_threshold: Decimal | None = None,
    gates: Gates = SPEC_GATES,
) -> SmoothingResult:
    """Debt-fund NAV smoothing flag (§4.3): smoothed category, Ljung-Box rejection (lags 1–10, 5 %), or
    an optional caller-supplied lag-1 autocorrelation threshold → "volatility understated" caveat."""
    _require_eligible(series)
    lags = gates.ljung_box_lags
    minimum = max(gates.smoothing_min_returns, lags + 2)
    if series.n_returns < minimum:
        raise InsufficientHistory(f"smoothing test needs ≥ {minimum} returns, got {series.n_returns}")
    lr = series.log_returns()
    rho = _autocorrelations(lr, 1)
    lb = _ljung_box(lr, lags)
    reasons: list[str] = []
    caveats = _gate_caveats(gates)
    if category in SMOOTHED_CATEGORIES:
        reasons.append("CATEGORY")
    if lb is None:
        caveats.append(AUTOCORRELATION_UNDEFINED)
    elif lb[1] < float(gates.ljung_box_alpha):
        reasons.append("LJUNG_BOX_REJECTS")
    if lag1_threshold is not None and rho is not None and rho[0] > float(lag1_threshold):
        reasons.append("LAG1_ABOVE_THRESHOLD")
    flagged = bool(reasons)
    if flagged:
        caveats += [VOLATILITY_UNDERSTATED, SHARPE_OVERSTATED]
    return SmoothingResult(
        value=None if rho is None else from_float(rho[0]),
        flagged=flagged,
        reasons=tuple(reasons),
        lag1_autocorrelation=None if rho is None else from_float(rho[0]),
        ljung_box_q=None if lb is None else from_float(lb[0]),
        ljung_box_p_value=None if lb is None else from_float(lb[1]),
        ljung_box_lags=lags,
        category=category,
        **_base(series, series.n_returns, "SMOOTHING_LJUNGBOX@1", caveats),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------------------------- §7 concentration

HHIBand = Literal["diversified", "moderate", "concentrated"]


class CreditBucket(StrEnum):
    SOVEREIGN = "sovereign"
    QUASI_SOVEREIGN = "quasi-sovereign"
    AAA = "AAA"
    AA = "AA"
    A_AND_BELOW = "A-and-below"
    UNRATED = "unrated"


BELOW_AAA = frozenset({CreditBucket.AA, CreditBucket.A_AND_BELOW, CreditBucket.UNRATED})


@dataclass(frozen=True)
class HHIResult:
    value: Decimal
    effective_count: Decimal
    band: HHIBand
    level: str
    weights: tuple[tuple[str, Decimal], ...]
    snapshot_date: date
    as_of: date
    observations: int
    method_id: str
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class Exposure:
    """One look-through holding row (instrument inside a fund, an FD, a bond …) at market value."""

    holding_id: str
    market_value: Decimal
    issuer: str
    credit_bucket: CreditBucket
    side_pocket: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.market_value, Decimal) or not self.market_value.is_finite() or self.market_value < 0:
            raise InvalidInput(f"market value must be a non-negative Decimal: {self.holding_id}")
        if not isinstance(self.credit_bucket, CreditBucket):
            raise InvalidInput(f"unknown credit bucket {self.credit_bucket!r}")


@dataclass(frozen=True)
class IssuerAggregation:
    issuer_values: tuple[tuple[str, Decimal], ...]
    issuer_weights: tuple[tuple[str, Decimal], ...]
    concentration: HHIResult
    method_id: str = "ISSUER_AGG@1"


@dataclass(frozen=True)
class CreditExposureResult:
    bucket_values: dict[CreditBucket, Decimal]
    bucket_weights: dict[CreditBucket, Decimal]
    below_aaa_weight: Decimal
    largest_non_sovereign_issuer: tuple[str, Decimal] | None
    side_pocket_present: bool
    snapshot_date: date
    as_of: date
    method_id: str
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class DepositInsuranceResult:
    excess_by_bank: tuple[tuple[str, Decimal], ...]
    total_excess: Decimal
    cover_per_bank: Decimal
    method_id: str
    caveats: tuple[str, ...]


def hhi_band(value: Decimal) -> HHIBand:
    """§7.1 display bands (guidance): < 0.15 diversified; 0.15–0.25 moderate; > 0.25 concentrated."""
    if value < Decimal("0.15"):
        return "diversified"
    if value <= Decimal("0.25"):
        return "moderate"
    return "concentrated"


def _snapshot_caveats(snapshot_date: date, as_of: date) -> list[str]:
    if snapshot_date > as_of:
        raise InvalidInput(f"snapshot {snapshot_date} is after as-of {as_of}")
    return [STALE_HOLDINGS_SNAPSHOT] if (as_of - snapshot_date).days > STALE_SNAPSHOT_DAYS else []


def _hhi_from_weights(weights: Mapping[str, Decimal], level: str, snapshot_date: date, as_of: date) -> HHIResult:
    caveats = _snapshot_caveats(snapshot_date, as_of)
    with engine_context():
        value = sum((w * w for w in weights.values()), ZERO)
        n_eff = ONE / value
    return HHIResult(
        value=value,
        effective_count=n_eff,
        band=hhi_band(value),
        level=level,
        weights=tuple(sorted(weights.items())),
        snapshot_date=snapshot_date,
        as_of=as_of,
        observations=len(weights),
        method_id="HHI@1",
        caveats=tuple(caveats),
    )


def _check_amounts(values: Mapping[str, Decimal], what: str) -> None:
    if not values:
        raise InvalidInput(f"no {what} supplied")
    for k, v in values.items():
        if not isinstance(v, Decimal) or not v.is_finite() or v < 0:
            raise InvalidInput(f"{what} for {k!r} must be a non-negative Decimal")


def hhi(weights: Mapping[str, Decimal], *, snapshot_date: date, as_of: date, level: str = "instrument") -> HHIResult:
    """§7.1: ``HHI = Σ w_i²`` on market-value weights that sum to 1; ``N_eff = 1/HHI``."""
    _check_amounts(weights, "weights")
    with engine_context():
        total = sum(weights.values(), ZERO)
    if abs(total - ONE) > Decimal("1e-12"):
        raise InvalidInput(f"weights must sum to 1, got {total}")
    return _hhi_from_weights(weights, level, snapshot_date, as_of)


def hhi_from_values(
    values: Mapping[str, Decimal], *, snapshot_date: date, as_of: date, level: str = "instrument"
) -> HHIResult:
    """HHI from market values (weights = value / total)."""
    _check_amounts(values, "market values")
    with engine_context():
        total = sum(values.values(), ZERO)
        if total == 0:
            raise InvalidInput("total market value is zero")
        weights = {k: v / total for k, v in values.items()}
    return _hhi_from_weights(weights, level, snapshot_date, as_of)


def _sum_by(exposures: Sequence[Exposure], key: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    with engine_context():
        for e in exposures:
            k = getattr(e, key)
            out[k] = out.get(k, ZERO) + e.market_value
    return out


def issuer_aggregation(exposures: Sequence[Exposure], *, snapshot_date: date, as_of: date) -> IssuerAggregation:
    """Look-through issuer totals (§7.1: scheme-level HHI hides issuer overlap) and issuer-level HHI."""
    if not exposures:
        raise InvalidInput("no exposures supplied")
    by_issuer = _sum_by(exposures, "issuer")
    conc = hhi_from_values(by_issuer, snapshot_date=snapshot_date, as_of=as_of, level="issuer")
    return IssuerAggregation(
        issuer_values=tuple(sorted(by_issuer.items())),
        issuer_weights=conc.weights,
        concentration=conc,
    )


def credit_exposure(exposures: Sequence[Exposure], *, snapshot_date: date, as_of: date) -> CreditExposureResult:
    """§7.2: bucket weights, share below AAA (unrated counts as below AAA), largest single non-sovereign
    issuer (quasi-sovereign SDLs count as non-sovereign here), side-pocket flag."""
    if not exposures:
        raise InvalidInput("no exposures supplied")
    caveats = _snapshot_caveats(snapshot_date, as_of)
    with engine_context():
        total = sum((e.market_value for e in exposures), ZERO)
        if total == 0:
            raise InvalidInput("total market value is zero")
        values = {b: ZERO for b in CreditBucket}
        for e in exposures:
            values[e.credit_bucket] += e.market_value
        weights = {b: v / total for b, v in values.items()}
        below = sum((weights[b] for b in BELOW_AAA), ZERO)
        non_sov = _sum_by([e for e in exposures if e.credit_bucket is not CreditBucket.SOVEREIGN], "issuer")
        largest: tuple[str, Decimal] | None = None
        if non_sov:
            name, val = min(non_sov.items(), key=lambda kv: (-kv[1], kv[0]))
            largest = (name, val / total)
    return CreditExposureResult(
        bucket_values=values,
        bucket_weights=weights,
        below_aaa_weight=below,
        largest_non_sovereign_issuer=largest,
        side_pocket_present=any(e.side_pocket for e in exposures),
        snapshot_date=snapshot_date,
        as_of=as_of,
        method_id="CREDIT_EXPOSURE@1",
        caveats=tuple(caveats),
    )


def deposit_insurance_excess(
    deposits_by_bank: Mapping[str, Decimal], *, cover_per_bank: Decimal
) -> DepositInsuranceResult:
    """§7.2: FD exposure per bank above the deposit-insurance cover (per depositor per bank, not per FD).

    The cover amount is a required parameter: the spec's ₹5 lakh figure is marked not re-fetched.
    """
    _check_amounts(deposits_by_bank, "deposits")
    if not isinstance(cover_per_bank, Decimal) or not cover_per_bank.is_finite() or cover_per_bank < 0:
        raise InvalidInput("cover_per_bank must be a non-negative Decimal")
    with engine_context():
        excess = tuple(sorted((bank, max(v - cover_per_bank, ZERO)) for bank, v in deposits_by_bank.items()))
        total = sum((v for _, v in excess), ZERO)
    return DepositInsuranceResult(
        excess_by_bank=excess,
        total_excess=total,
        cover_per_bank=cover_per_bank,
        method_id="DICGC_EXCESS@1",
        caveats=(COVER_AMOUNT_NOT_VERIFIED,),
    )
