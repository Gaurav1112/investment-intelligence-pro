"""Forecast baselines B1–B4 (validation-methodology.md §2, ADR-0010).

Every output is a **scenario range** — never a probability. Each result carries its horizon, data cutoff, model
id + version, baseline comparator, assumptions, limitations and ``unreliable_when`` conditions.

Floats are allowed here (implementation-rules §5). Randomness only via ``numpy.random.default_rng(seed)`` with an
explicit seed. Dates are passed in; nothing reads the clock.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

import numpy as np
import numpy.typing as npt

from iip.engine.errors import InsufficientHistory, InvalidInput, StaleData
from iip.engine.money import engine_context

FloatArray = npt.NDArray[np.float64]

SCENARIO_LABEL = "scenario range"
DEFAULT_LEVELS: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
INTERPOLATION_METHODS = {
    "linear": "Hyndman–Fan type 7 (linear) — forecast bands",
    "inverted_cdf": "Hyndman–Fan type 1 (inverse empirical CDF) — risk VaR convention",
}
N_EFF_TAILS_5_95 = 20
N_EFF_TAILS_10_90 = 10
N_EFF_MIN = 10  # §8: suppressed when n_eff < 10
BLOCK_LENGTH_RANGE = (5.0, 63.0)
FACTSHEET_MAX_AGE_DAYS = 45
DEFAULT_DY_GRID_BP: tuple[int, ...] = (-100, -50, 0, 50, 100)
STRESS_DY_BP: tuple[int, ...] = (200,)

_COMMON_UNRELIABLE = (
    "history shorter than the gate for this horizon (n_eff < 10) or data gaps beyond the gate",
    "scheme event in or announced for the training window (merger, fundamental attribute change, category or "
    "benchmark change, side-pocketing, wind-up, subscription/redemption suspension)",
    "credit event affecting a holding",
    "instrument launched less than 1 year ago",
    "volatility regime stress (21-day vol / 3-year median vol > 2) or a recent policy-rate turn",
    "fund manager changed within 12 months",
    "calibration status is calibration_unknown (< 30 non-overlapping validated outcomes)",
)


@dataclass(frozen=True)
class ForecastMeta:
    label: str
    model_id: str
    model_version: str
    horizon: int
    horizon_unit: str  # "business_days" | "months"
    data_cutoff: date
    baseline_comparator: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    unreliable_when: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioRange:
    """Quantiles of the simple horizon return R_H (fractions), labelled as a scenario range."""

    meta: ForecastMeta
    quantiles: tuple[tuple[float, float], ...]  # (level, value)
    interpolation: str
    n_obs: int
    n_windows: int
    n_eff: int
    seed: int | None = None
    n_paths: int | None = None
    mean_block_length: float | None = None
    mc_standard_errors: tuple[tuple[float, float], ...] = ()  # (level, MC s.e.)


@dataclass(frozen=True)
class PointScenario:
    """A naive point baseline (B3) — the comparator anchor for MAE/RMSE and directional accuracy."""

    meta: ForecastMeta
    point: float
    inputs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class YieldCarryScenarios:
    """B4: E[R_H] ≈ (YTM − ER)·H_years − D_mod·Δy + ½·C·Δy², over a Δy grid (bp)."""

    meta: ForecastMeta
    carry: Decimal
    scenarios: tuple[tuple[int, Decimal], ...]  # (Δy in bp, R_H)
    stress_scenarios: tuple[tuple[int, Decimal], ...]
    inputs: tuple[tuple[str, str], ...]
    formula_id: str = "YIELD_CARRY@1"


def derive_seed(instrument_id: str, as_of: date, model_version: str) -> int:
    """seed = int.from_bytes(sha256(f"{instrument_id}|{as_of}|{model_version}")[:8], "big") (spec preamble)."""
    digest = hashlib.sha256(f"{instrument_id}|{as_of.isoformat()}|{model_version}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


# -----------------------------------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------------------------------


def _cut(dates: Sequence[date], prices: Sequence[float], as_of: date) -> tuple[list[date], FloatArray]:
    """Point-in-time cut: keep observations dated ≤ as_of; validate ordering and positivity."""
    if len(dates) != len(prices):
        raise InvalidInput("dates and prices differ in length")
    for a, b in pairwise(dates):
        if not a < b:
            raise InvalidInput(f"dates must be strictly increasing ({a} → {b})")
    keep = [i for i, d in enumerate(dates) if d <= as_of]
    if not keep:
        raise InsufficientHistory(f"no observations on or before {as_of}")
    p = np.asarray([prices[i] for i in keep], dtype=np.float64)
    if not np.all(np.isfinite(p)) or np.any(p <= 0):
        raise InvalidInput("prices must be finite and > 0")
    return [dates[i] for i in keep], p


def _gate_levels(n_eff: int, levels: Sequence[float]) -> tuple[tuple[float, ...], tuple[str, ...]]:
    if n_eff < N_EFF_MIN:
        raise InsufficientHistory(f"n_eff = {n_eff} < {N_EFF_MIN}: forecast suppressed (§8)")
    out = list(levels)
    warnings: list[str] = []
    if n_eff < N_EFF_TAILS_5_95:
        out = [lv for lv in out if 0.10 - 1e-12 <= lv <= 0.90 + 1e-12]
        warnings.append("LOW_CONFIDENCE")
        warnings.append("TAILS_5_95_SUPPRESSED")
    return tuple(out), tuple(warnings)


def _check_levels(levels: Sequence[float]) -> None:
    if not levels:
        raise InvalidInput("no quantile levels")
    for lv in levels:
        if not 0.0 < lv < 1.0:
            raise InvalidInput(f"quantile level outside (0, 1): {lv}")
    if any(b <= a for a, b in pairwise(levels)):
        raise InvalidInput("quantile levels must be strictly increasing")


def _quantiles(sample: FloatArray, levels: Sequence[float], method: str) -> tuple[tuple[float, float], ...]:
    vals = np.quantile(sample, np.asarray(levels, dtype=np.float64), method=method)  # type: ignore[call-overload]
    vals = np.maximum.accumulate(np.asarray(vals, dtype=np.float64))  # guard against FP non-monotonicity
    return tuple((float(lv), float(v)) for lv, v in zip(levels, vals, strict=True))


# -----------------------------------------------------------------------------------------------------
# B1 — empirical overlapping-window distribution
# -----------------------------------------------------------------------------------------------------


def empirical_horizon_distribution(
    dates: Sequence[date],
    prices: Sequence[float],
    *,
    horizon: int,
    as_of: date,
    levels: Sequence[float] = DEFAULT_LEVELS,
    interpolation: str = "linear",
    model_version: str = "1",
) -> ScenarioRange:
    """B1: R_t^H = P_{t+H}/P_t − 1 for every t with t + H ≤ cutoff; quantiles with an explicit method.

    ``horizon`` is in observation steps (business days for daily NAV: 21/63/126/252).
    n_eff = ⌊N/H⌋ with N = number of one-step returns. Gates: n_eff ≥ 20 for 5/95, ≥ 10 for 10/90;
    n_eff < 10 → InsufficientHistory (suppressed, §8).
    """
    if interpolation not in INTERPOLATION_METHODS:
        raise InvalidInput(f"interpolation must be one of {sorted(INTERPOLATION_METHODS)}")
    if horizon < 1:
        raise InvalidInput("horizon must be ≥ 1")
    _check_levels(levels)
    ds, p = _cut(dates, prices, as_of)
    n = p.size - 1
    if horizon > n:
        raise InsufficientHistory(f"horizon {horizon} exceeds the history ({n} steps)")
    windows = p[horizon:] / p[:-horizon] - 1.0
    n_eff = n // horizon
    lv, warnings = _gate_levels(n_eff, levels)
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B1_EMPIRICAL_OVERLAPPING",
        model_version=model_version,
        horizon=horizon,
        horizon_unit="business_days",
        data_cutoff=ds[-1],
        baseline_comparator="B3_ZERO_DRIFT",
        assumptions=(
            "the past distribution of H-step returns is representative of the next H steps",
            "returns are net of scheme expenses (NAV is net); user-level costs and tax are applied later",
            f"quantiles: {INTERPOLATION_METHODS[interpolation]}",
            "no recency weighting",
        ),
        limitations=(
            f"{windows.size} overlapping windows contain only about {n_eff} independent observations",
            "cannot represent events absent from the history",
            "regime changes (rate-cycle turns, stress episodes) break the stationarity assumption",
        ),
        unreliable_when=(*_COMMON_UNRELIABLE, "horizon ≥ 12 months (few independent windows)"),
        warnings=warnings,
    )
    return ScenarioRange(
        meta=meta,
        quantiles=_quantiles(windows, lv, interpolation),
        interpolation=interpolation,
        n_obs=int(p.size),
        n_windows=int(windows.size),
        n_eff=n_eff,
    )


# -----------------------------------------------------------------------------------------------------
# B2 — stationary block bootstrap (Politis & Romano 1994)
# -----------------------------------------------------------------------------------------------------


def _stationary_paths(
    logret: FloatArray, horizon: int, mean_block_length: float, n_paths: int, rng: np.random.Generator
) -> FloatArray:
    """Sum of H log returns per path. Start uniform; each next step continues the block with prob 1 − 1/L,
    else jumps to a fresh uniform index; indices wrap circularly."""
    n = logret.size
    idx = rng.integers(0, n, size=n_paths)
    total = logret[idx].copy()
    p_jump = 1.0 / mean_block_length
    for _ in range(1, horizon):
        jump = rng.random(n_paths) < p_jump
        fresh = rng.integers(0, n, size=n_paths)
        idx = np.where(jump, fresh, (idx + 1) % n)
        total += logret[idx]
    return total


def stationary_bootstrap(
    dates: Sequence[date],
    prices: Sequence[float],
    *,
    horizon: int,
    as_of: date,
    mean_block_length: float,
    seed: int,
    n_paths: int = 5000,
    levels: Sequence[float] = DEFAULT_LEVELS,
    interpolation: str = "linear",
    model_version: str = "1",
) -> ScenarioRange:
    """B2: stationary bootstrap of daily log returns; R_H = exp(Σ ℓ) − 1 over ``n_paths`` paths.

    MC standard error per quantile from the binomial (order-statistic) approximation:
    s.e.(q_p) ≈ [Q(p + s) − Q(p − s)] / 2 with s = √(p(1 − p)/B).
    """
    if interpolation not in INTERPOLATION_METHODS:
        raise InvalidInput(f"interpolation must be one of {sorted(INTERPOLATION_METHODS)}")
    if horizon < 1:
        raise InvalidInput("horizon must be ≥ 1")
    if not (math.isfinite(mean_block_length) and mean_block_length >= 1.0):
        raise InvalidInput("mean_block_length must be ≥ 1")
    if n_paths < 100:
        raise InvalidInput("n_paths must be ≥ 100")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise InvalidInput("seed must be an explicit non-negative int")
    _check_levels(levels)
    ds, p = _cut(dates, prices, as_of)
    logret = np.diff(np.log(p))
    n = logret.size
    if horizon > n:
        raise InsufficientHistory(f"horizon {horizon} exceeds the history ({n} returns)")
    n_eff = n // horizon
    lv, gate_warnings = _gate_levels(n_eff, levels)
    warnings = list(gate_warnings)
    if not BLOCK_LENGTH_RANGE[0] <= mean_block_length <= BLOCK_LENGTH_RANGE[1]:
        warnings.append("BLOCK_LENGTH_OUTSIDE_5_63")
    rng = np.random.default_rng(seed)
    sums = _stationary_paths(logret, horizon, mean_block_length, n_paths, rng)
    outcomes = np.expm1(sums)
    q = _quantiles(outcomes, lv, interpolation)
    ses: list[tuple[float, float]] = []
    for level, _ in q:
        s = math.sqrt(level * (1.0 - level) / n_paths)
        lo_hi = np.quantile(outcomes, [max(0.0, level - s), min(1.0, level + s)], method=interpolation)  # type: ignore[call-overload]
        ses.append((level, float((lo_hi[1] - lo_hi[0]) / 2.0)))
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B2_STATIONARY_BOOTSTRAP",
        model_version=model_version,
        horizon=horizon,
        horizon_unit="business_days",
        data_cutoff=ds[-1],
        baseline_comparator="B1_EMPIRICAL_OVERLAPPING",
        assumptions=(
            "daily log returns are stationary with short-range dependence captured by random-length blocks",
            f"mean block length L = {mean_block_length:g}; {n_paths} paths; seed {seed}",
            f"quantiles: {INTERPOLATION_METHODS[interpolation]}",
        ),
        limitations=(
            "cannot generate events absent from history (e.g. a first-ever credit event)",
            "a fixed seed reproduces the same Monte Carlo sampling error every time; see the MC standard errors",
            "block length is supplied, not selected automatically (Politis–White) here",
        ),
        unreliable_when=_COMMON_UNRELIABLE,
        warnings=tuple(warnings),
    )
    return ScenarioRange(
        meta=meta,
        quantiles=q,
        interpolation=interpolation,
        n_obs=int(p.size),
        n_windows=n_paths,
        n_eff=n_eff,
        seed=seed,
        n_paths=n_paths,
        mean_block_length=float(mean_block_length),
        mc_standard_errors=tuple(ses),
    )


# -----------------------------------------------------------------------------------------------------
# B3 — naive point baselines
# -----------------------------------------------------------------------------------------------------


def zero_drift_baseline(*, horizon_months: int, as_of: date, model_version: str = "1") -> PointScenario:
    """B3 zero drift / random walk: E[R_H] = 0."""
    if horizon_months < 1:
        raise InvalidInput("horizon_months must be ≥ 1")
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B3_ZERO_DRIFT",
        model_version=model_version,
        horizon=horizon_months,
        horizon_unit="months",
        data_cutoff=as_of,
        baseline_comparator="none (this is the reference baseline)",
        assumptions=("price follows a random walk with no drift over the horizon",),
        limitations=("ignores carry and long-run drift; a point anchor only, not a range",),
        unreliable_when=("used as a range: it is a point comparator for MAE/RMSE/direction only",),
    )
    return PointScenario(meta=meta, point=0.0)


def historical_mean_baseline(
    dates: Sequence[date],
    prices: Sequence[float],
    *,
    horizon_months: int,
    as_of: date,
    model_version: str = "1",
) -> PointScenario:
    """B3 historical mean: E[R_H] = (1 + CAGR_hist)^(H/12) − 1, CAGR on the training window (ACT/365F)."""
    if horizon_months < 1:
        raise InvalidInput("horizon_months must be ≥ 1")
    ds, p = _cut(dates, prices, as_of)
    days = (ds[-1] - ds[0]).days
    if p.size < 2 or days <= 0:
        raise InsufficientHistory("need ≥ 2 observations spanning > 0 days")
    years = days / 365.0
    if years * 12.0 < horizon_months:
        raise InsufficientHistory(f"training window {years:.2f} y is shorter than the horizon")
    cagr = float((p[-1] / p[0]) ** (1.0 / years) - 1.0)
    point = (1.0 + cagr) ** (horizon_months / 12.0) - 1.0
    warnings: tuple[str, ...] = ("ANNUALISED_FROM_SHORT_PERIOD",) if years < 1.0 else ()
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B3_HISTORICAL_MEAN",
        model_version=model_version,
        horizon=horizon_months,
        horizon_unit="months",
        data_cutoff=ds[-1],
        baseline_comparator="B3_ZERO_DRIFT",
        assumptions=("the training-window CAGR (ACT/365F) persists over the horizon",),
        limitations=(
            "the mean is estimated with large error (≈ σ/√years), often larger than fund-to-fund differences",
            "a point anchor only, not a range",
        ),
        unreliable_when=_COMMON_UNRELIABLE,
        warnings=warnings,
    )
    return PointScenario(
        meta=meta,
        point=point,
        inputs=(("cagr_hist", repr(cagr)), ("train_start", ds[0].isoformat()), ("train_years", repr(years))),
    )


def risk_free_carry_baseline(
    *, tbill_91d_yield: Decimal, days: int, as_of: date, model_version: str = "1"
) -> PointScenario:
    """B3 risk-free carry: E[R_H] = 91-day T-bill yield × days/365."""
    if days < 1:
        raise InvalidInput("days must be ≥ 1")
    with engine_context():
        value = tbill_91d_yield * Decimal(days) / Decimal(365)
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B3_RISK_FREE_CARRY",
        model_version=model_version,
        horizon=days,
        horizon_unit="days",
        data_cutoff=as_of,
        baseline_comparator="B3_ZERO_DRIFT",
        assumptions=("the 91-day T-bill yield is earned simple-interest over the horizon",),
        limitations=("ignores reinvestment and rate changes; a point anchor only",),
        unreliable_when=("the T-bill yield input is stale",),
    )
    return PointScenario(meta=meta, point=float(value), inputs=(("tbill_91d_yield", str(tbill_91d_yield)),))


# -----------------------------------------------------------------------------------------------------
# B4 — yield-carry scenarios (debt)
# -----------------------------------------------------------------------------------------------------


def yield_carry_scenarios(
    *,
    ytm: Decimal,
    expense_ratio: Decimal,
    modified_duration: Decimal,
    horizon_months: int | None = None,
    as_of: date,
    factsheet_published: date,
    horizon_days: int | None = None,
    convexity: Decimal | None = None,
    dy_grid_bp: Sequence[int] = DEFAULT_DY_GRID_BP,
    stress_bp: Sequence[int] = STRESS_DY_BP,
    model_version: str = "1",
) -> YieldCarryScenarios:
    """B4: R_H ≈ (YTM − ER) × H/12 − D_mod × Δy + ½ C Δy² (Δy as a fraction; grid given in bp).

    Factsheet inputs older than 45 days (by *publication* date) → StaleData. Give exactly one of ``horizon_months``
    (H/12 years) or ``horizon_days`` (days/365 years, for horizons that are not whole months).
    """
    for name, v in (("ytm", ytm), ("expense_ratio", expense_ratio), ("modified_duration", modified_duration)):
        if not isinstance(v, Decimal) or not v.is_finite():
            raise InvalidInput(f"{name} must be a finite Decimal")
    if expense_ratio < 0 or modified_duration < 0:
        raise InvalidInput("expense ratio and duration must be ≥ 0")
    if (horizon_months is None) == (horizon_days is None):
        raise InvalidInput("give exactly one of horizon_months and horizon_days")
    if horizon_months is not None and horizon_months < 1:
        raise InvalidInput("horizon_months must be ≥ 1")
    if horizon_days is not None and horizon_days < 1:
        raise InvalidInput("horizon_days must be ≥ 1")
    if factsheet_published > as_of:
        raise InvalidInput("factsheet published after as_of (look-ahead)")
    age = (as_of - factsheet_published).days
    if age > FACTSHEET_MAX_AGE_DAYS:
        raise StaleData(f"factsheet is {age} days old (> {FACTSHEET_MAX_AGE_DAYS})")
    c = Decimal(0) if convexity is None else convexity
    with engine_context():
        h_years = (
            Decimal(horizon_months) / Decimal(12) if horizon_months is not None else Decimal(horizon_days or 0) / 365
        )
        carry = (ytm - expense_ratio) * h_years

        def scen(bp: int) -> Decimal:
            dy = Decimal(bp) / Decimal(10000)
            return carry - modified_duration * dy + c * dy * dy / Decimal(2)

        grid = tuple((int(bp), scen(int(bp))) for bp in dy_grid_bp)
        stress = tuple((int(bp), scen(int(bp))) for bp in stress_bp)
    meta = ForecastMeta(
        label=SCENARIO_LABEL,
        model_id="B4_YIELD_CARRY",
        model_version=model_version,
        horizon=horizon_months if horizon_months is not None else horizon_days or 0,
        horizon_unit="months" if horizon_months is not None else "days",
        data_cutoff=factsheet_published,
        baseline_comparator="B3_RISK_FREE_CARRY",
        assumptions=(
            "portfolio YTM, modified duration (and convexity if disclosed) from the latest published factsheet",
            "the yield change Δy happens immediately and is held for the horizon",
            "expense ratio = TER/BER plus levies",
        ),
        limitations=(
            "roll-down is ignored",
            "duration drift over the horizon is ignored",
            "credit-spread moves are separate scenarios",
            "fund flows and turnover are ignored",
            "these are scenarios, not a calibrated range; empirical coverage is measured separately",
        ),
        unreliable_when=(
            *_COMMON_UNRELIABLE,
            "factsheet inputs older than 45 days",
            "a credit event or rating downgrade in the portfolio",
        ),
        warnings=() if convexity is not None else ("CONVEXITY_NOT_DISCLOSED",),
    )
    return YieldCarryScenarios(
        meta=meta,
        carry=carry,
        scenarios=grid,
        stress_scenarios=stress,
        inputs=(
            ("ytm", str(ytm)),
            ("expense_ratio", str(expense_ratio)),
            ("modified_duration", str(modified_duration)),
            ("convexity", "not disclosed" if convexity is None else str(convexity)),
            ("factsheet_published", factsheet_published.isoformat()),
        ),
    )
