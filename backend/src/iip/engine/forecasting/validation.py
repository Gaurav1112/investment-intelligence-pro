"""Forecast validation harness (validation-methodology.md §4–§7, ADR-0010).

* Rolling-origin walk-forward splitter with purging and an embargo (§4).
* Point, quantile and distribution metrics: MAE, RMSE, directional accuracy, pinball, interval coverage/score,
  CRPS (ensemble, Gaussian, quantile-grid), PIT values (§5).
* Diebold–Mariano with the Harvey–Leybourne–Newbold small-sample correction and the promotion gate (§6).
* Drift monitors: rolling coverage versus nominal, rolling loss ratio and PSI (§7).

Floats are allowed here (implementation-rules §5). Every function raises a typed engine error instead of
returning NaN or a silently degraded value.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Any

import numpy as np
import numpy.typing as npt

from iip.engine.errors import InsufficientHistory, InvalidInput, NumericalError


class _LazyScipyStats:
    """``scipy.stats`` imported on first attribute access (A05 / RC-5): keeps scipy off the app's cold-start path."""

    def __getattr__(self, name: str) -> Any:
        from scipy import stats as scipy_stats  # noqa: PLC0415

        return getattr(scipy_stats, name)


stats: Any = _LazyScipyStats()

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

VALIDATION_VERSION = "VALIDATION@1"
MIN_NON_OVERLAPPING_TEST_POINTS = 10  # §4.1
MIN_CALIBRATION_POINTS = 30  # §5.3
COVERAGE_GATE = (0.70, 0.90)  # §5.4 (for the 80 % band)
KUPIEC_MIN_P = 0.05


class LeakageError(InvalidInput):
    """A training sample's label window is not fully observed at the origin (or violates the embargo)."""

    code = "LEAKAGE_DETECTED"


def _arr(x: Sequence[float] | FloatArray, name: str) -> FloatArray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 1 or a.size == 0:
        raise InvalidInput(f"{name} must be a non-empty 1-D sequence")
    if not np.all(np.isfinite(a)):
        raise InvalidInput(f"{name} contains non-finite values")
    return a


def _pair(a: Sequence[float] | FloatArray, b: Sequence[float] | FloatArray) -> tuple[FloatArray, FloatArray]:
    x, y = _arr(a, "a"), _arr(b, "b")
    if x.shape != y.shape:
        raise InvalidInput(f"length mismatch {x.size} vs {y.size}")
    return x, y


def _finite(x: float, what: str) -> float:
    if not math.isfinite(x):
        raise NumericalError(f"{what} is not finite")
    return x


# =====================================================================================================
# §4 Walk-forward splitter
# =====================================================================================================


def default_embargo(n_obs: int) -> int:
    """Spec §4.1 default: e = max(5 business days, 0.01 × N), rounded up."""
    return max(5, math.ceil(0.01 * n_obs))


def assert_no_leakage(train: Sequence[int] | IntArray, *, origin: int, horizon: int, embargo: int) -> None:
    """Raise LeakageError unless every training label (t, t+H] is observed at the origin, plus embargo.

    Conditions (§3.3, §4.1): ``t + H ≤ T`` (purged) and ``t ≤ T − H − e`` (embargo).
    """
    idx = np.asarray(train, dtype=np.int64)
    if idx.size == 0:
        return
    t_max = int(idx.max())
    if t_max + horizon > origin:
        raise LeakageError(
            f"training sample t={t_max} has label window ({t_max}, {t_max + horizon}] beyond origin {origin}"
        )
    if t_max > origin - horizon - embargo:
        raise LeakageError(f"training sample t={t_max} violates embargo e={embargo} at origin {origin}")


@dataclass(frozen=True)
class Split:
    origin: int
    horizon: int
    embargo: int
    train: IntArray
    test: IntArray

    @property
    def train_max(self) -> int:
        return int(self.train.max())

    @property
    def test_min(self) -> int:
        return int(self.test.min())


@dataclass(frozen=True)
class WalkForwardPlan:
    splits: tuple[Split, ...]
    horizon: int
    embargo: int
    window: str
    verdict: str  # "ok" | "insufficient_evidence" (< 10 non-overlapping test points, §4.1)
    method_id: str = "WALK_FORWARD_PURGED@1"

    def __len__(self) -> int:
        return len(self.splits)

    def __iter__(self) -> Iterator[Split]:
        return iter(self.splits)

    def __getitem__(self, i: int) -> Split:
        return self.splits[i]


def walk_forward_splits(
    *,
    n_obs: int,
    horizon: int,
    origins: Sequence[int],
    embargo: int | None = None,
    window: str = "expanding",
    rolling_size: int | None = None,
) -> WalkForwardPlan:
    """Rolling-origin splits over samples t = 0..n_obs−1 whose label is y_t = Σ r_{t+1..t+H}.

    * A sample t has a label only if ``t + H ≤ n_obs − 1``.
    * At origin T the test samples are ``T..T+H−1``; training is ``t ≤ T − H − e`` (purge + embargo).
    * Origins must be strictly increasing and spaced by ≥ H so that test labels do not overlap.
    """
    if horizon < 1:
        raise InvalidInput("horizon must be ≥ 1")
    e = default_embargo(n_obs) if embargo is None else embargo
    if e < 0:
        raise InvalidInput("embargo must be ≥ 0")
    if window not in ("expanding", "rolling"):
        raise InvalidInput("window must be 'expanding' or 'rolling'")
    if window == "rolling" and (rolling_size is None or rolling_size < 1):
        raise InvalidInput("rolling window needs rolling_size ≥ 1")
    if not origins:
        raise InvalidInput("no origins")
    last_labelled = n_obs - 1 - horizon
    splits: list[Split] = []
    prev: int | None = None
    for origin in origins:
        if prev is not None and origin - prev < horizon:
            raise InvalidInput(f"origins {prev} and {origin} are closer than the horizon {horizon}")
        prev = origin
        test = np.arange(origin, origin + horizon, dtype=np.int64)
        if int(test.max()) > last_labelled:
            raise InsufficientHistory(f"test labels at origin {origin} are not observed within n_obs={n_obs}")
        hi = origin - horizon - e
        if hi < 0:
            raise InsufficientHistory(f"no training samples at origin {origin} after purge and embargo")
        lo = 0 if window == "expanding" else max(0, hi - int(rolling_size or 0) + 1)
        train = np.arange(lo, hi + 1, dtype=np.int64)
        assert_no_leakage(train, origin=origin, horizon=horizon, embargo=e)
        if not int(train.max()) + e < int(test.min()):  # explicit invariant, never stripped by -O
            raise LeakageError(f"train max {int(train.max())} + embargo {e} ≥ test min {int(test.min())}")
        splits.append(Split(origin=origin, horizon=horizon, embargo=e, train=train, test=test))
    verdict = "ok" if len(splits) >= MIN_NON_OVERLAPPING_TEST_POINTS else "insufficient_evidence"
    return WalkForwardPlan(splits=tuple(splits), horizon=horizon, embargo=e, window=window, verdict=verdict)


def purged_kfold(*, n_samples: int, k: int, horizon: int, embargo: int) -> tuple[Split, ...]:
    """k-fold CV variant for hyper-parameter search *inside* a training window (§4.2).

    For each contiguous test fold [a, b]: drop training t ∈ [a − H, a − 1] (purge) and t ∈ [b + 1, b + H + e]
    (purge plus embargo).
    """
    if k < 2 or n_samples < k:
        raise InvalidInput("need k ≥ 2 and n_samples ≥ k")
    if horizon < 1 or embargo < 0:
        raise InvalidInput("horizon ≥ 1 and embargo ≥ 0 required")
    bounds = np.array_split(np.arange(n_samples, dtype=np.int64), k)
    out: list[Split] = []
    for fold in bounds:
        a, b = int(fold[0]), int(fold[-1])
        all_idx = np.arange(n_samples, dtype=np.int64)
        keep = (all_idx < a - horizon) | (all_idx > b + horizon + embargo)
        out.append(Split(origin=a, horizon=horizon, embargo=embargo, train=all_idx[keep], test=fold))
    return tuple(out)


# =====================================================================================================
# §5.1 Point metrics
# =====================================================================================================


def mae(y: Sequence[float] | FloatArray, yhat: Sequence[float] | FloatArray) -> float:
    a, b = _pair(y, yhat)
    return float(np.mean(np.abs(a - b)))


def rmse(y: Sequence[float] | FloatArray, yhat: Sequence[float] | FloatArray) -> float:
    a, b = _pair(y, yhat)
    return float(np.sqrt(np.mean((a - b) ** 2)))


@dataclass(frozen=True)
class DirectionalAccuracy:
    accuracy: float
    base_rate: float  # share of positive excess outcomes — compare against this, not 50 % (§5.1)
    n: int
    beats_base_rate: bool
    metric_id: str = "DIRECTIONAL_ACCURACY@1"


def directional_accuracy(
    y: Sequence[float] | FloatArray,
    yhat: Sequence[float] | FloatArray,
    *,
    risk_free: Sequence[float] | FloatArray | None = None,
) -> DirectionalAccuracy:
    """Share of origins where sign(ŷ − r_f·H) = sign(y − r_f·H). ``risk_free`` is r_f·H per origin."""
    a, b = _pair(y, yhat)
    rf = np.zeros_like(a) if risk_free is None else _arr(risk_free, "risk_free")
    if rf.shape != a.shape:
        raise InvalidInput("risk_free length mismatch")
    acc = float(np.mean(np.sign(b - rf) == np.sign(a - rf)))
    base = float(np.mean((a - rf) > 0))
    base_ref = max(base, 1.0 - base)  # the naive "always predict the majority direction" score
    return DirectionalAccuracy(accuracy=acc, base_rate=base, n=int(a.size), beats_base_rate=acc > base_ref)


# =====================================================================================================
# §5.2 Quantile / distribution metrics
# =====================================================================================================


def _check_tau(tau: float) -> None:
    if not 0.0 < tau < 1.0:
        raise InvalidInput(f"quantile level must be in (0, 1): {tau}")


def pinball_loss(y: float, q: float, tau: float) -> float:
    """L_τ(y, q) = τ (y − q) if y ≥ q, else (1 − τ)(q − y)."""
    _check_tau(tau)
    if not (math.isfinite(y) and math.isfinite(q)):
        raise InvalidInput("non-finite input to pinball loss")
    return tau * (y - q) if y >= q else (1.0 - tau) * (q - y)


def _check_quantile_vector(qs: FloatArray, taus: FloatArray) -> None:
    if qs.shape != taus.shape:
        raise InvalidInput("quantile values and levels differ in length")
    for t in taus:
        _check_tau(float(t))
    if np.any(np.diff(taus) <= 0):
        raise InvalidInput("quantile levels must be strictly increasing")
    if np.any(np.diff(qs) < 0):
        raise InvalidInput("quantile values must be non-decreasing (crossing quantiles)")


def mean_pinball_loss(y: float, quantiles: Sequence[float] | FloatArray, levels: Sequence[float] | FloatArray) -> float:
    qs, taus = _arr(quantiles, "quantiles"), _arr(levels, "levels")
    _check_quantile_vector(qs, taus)
    return float(np.mean([pinball_loss(y, float(q), float(t)) for q, t in zip(qs, taus, strict=True)]))


def crps_ensemble(ensemble: Sequence[float] | FloatArray, y: float) -> float:
    """Ensemble CRPS, energy form: mean|X − y| − ½ mean|X − X'| (all M² pairs; Gneiting & Raftery 2007)."""
    x = _arr(ensemble, "ensemble")
    if not math.isfinite(y):
        raise InvalidInput("non-finite outcome")
    term1 = float(np.mean(np.abs(x - y)))
    # mean|X − X'| over all ordered pairs, O(M log M) via sorted ranks: Σ_i (2i − M − 1) x_(i) · 2 / M²
    xs = np.sort(x)
    m = xs.size
    ranks = np.arange(1, m + 1, dtype=np.float64)
    term2 = float(2.0 * np.sum((2.0 * ranks - m - 1.0) * xs) / (m * m))
    return _finite(term1 - 0.5 * term2, "CRPS")


def crps_gaussian(y: float, mu: float, sigma: float) -> float:
    """σ [z(2Φ(z) − 1) + 2φ(z) − 1/√π], z = (y − μ)/σ."""
    if not sigma > 0:
        raise InvalidInput("sigma must be > 0")
    z = (y - mu) / sigma
    val = sigma * (
        z * (2.0 * float(stats.norm.cdf(z)) - 1.0) + 2.0 * float(stats.norm.pdf(z)) - 1.0 / math.sqrt(math.pi)
    )
    return _finite(val, "Gaussian CRPS")


def crps_from_quantiles(
    y: float, quantiles: Sequence[float] | FloatArray, levels: Sequence[float] | FloatArray
) -> float:
    """CRPS ≈ 2 × mean pinball loss over a dense τ grid (§5.2)."""
    return 2.0 * mean_pinball_loss(y, quantiles, levels)


def pit_values(
    outcomes: Sequence[float] | FloatArray,
    quantile_vectors: Sequence[Sequence[float]] | FloatArray,
    levels: Sequence[float] | FloatArray,
) -> tuple[float, ...]:
    """u_k = F_k(y_k) by linear interpolation of the quantile vector; clipped to the outer levels (§5.3)."""
    ys = _arr(outcomes, "outcomes")
    taus = _arr(levels, "levels")
    qv = np.asarray(quantile_vectors, dtype=np.float64)
    if qv.ndim != 2 or qv.shape != (ys.size, taus.size):
        raise InvalidInput("quantile_vectors must be (n_outcomes × n_levels)")
    out: list[float] = []
    for y, qs in zip(ys, qv, strict=True):
        _check_quantile_vector(qs, taus)
        out.append(float(np.interp(y, qs, taus, left=taus[0], right=taus[-1])))
    return tuple(out)


def pit_histogram(u: Sequence[float], bins: int = 10) -> tuple[int, ...]:
    arr = _arr(u, "pit")
    counts, _ = np.histogram(arr, bins=bins, range=(0.0, 1.0))
    return tuple(int(c) for c in counts)


# =====================================================================================================
# §5.3 Calibration: interval coverage
# =====================================================================================================


def _xlogy(x: float, y: float) -> float:
    return 0.0 if x == 0 else x * math.log(y)


def kupiec_pof(n: int, inside: int, nominal: float) -> tuple[float, float]:
    """Kupiec proportion-of-failures LR on the inside-count; p from χ²₁."""
    if n < 1:
        raise InvalidInput("n must be ≥ 1")
    out = n - inside
    pi_hat = inside / n
    ll0 = _xlogy(inside, nominal) + _xlogy(out, 1.0 - nominal)
    ll1 = _xlogy(inside, pi_hat) + _xlogy(out, 1.0 - pi_hat)
    lr = max(0.0, -2.0 * (ll0 - ll1))
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen_independence(misses: Sequence[bool]) -> tuple[float, float]:
    """Christoffersen (1998) LR_ind on a miss/hit sequence (first-order Markov vs independence)."""
    seq = [bool(m) for m in misses]
    n00 = n01 = n10 = n11 = 0
    for prev, cur in pairwise(seq):
        if not prev and not cur:
            n00 += 1
        elif not prev and cur:
            n01 += 1
        elif prev and not cur:
            n10 += 1
        else:
            n11 += 1
    total = n00 + n01 + n10 + n11
    if total == 0:
        raise InsufficientHistory("need ≥ 2 observations for the independence test")
    pi = (n01 + n11) / total
    pi0 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi1 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    ll0 = _xlogy(n00 + n10, 1 - pi) + _xlogy(n01 + n11, pi)
    ll1 = _xlogy(n00, 1 - pi0) + _xlogy(n01, pi0) + _xlogy(n10, 1 - pi1) + _xlogy(n11, pi1)
    lr = max(0.0, -2.0 * (ll0 - ll1))
    return lr, float(stats.chi2.sf(lr, 1))


@dataclass(frozen=True)
class IntervalCoverage:
    nominal: float
    n: int
    inside: int
    coverage: float
    interval_scores: tuple[float, ...]
    mean_interval_score: float
    binomial_p: float
    kupiec_lr: float
    kupiec_p: float
    christoffersen_lr: float | None
    christoffersen_p: float | None
    status: str  # "calibration_unknown" (n < 30) | "calibrated" | "miscalibrated"
    passes_gate: bool  # §5.4 product gate
    metric_id: str = "INTERVAL_COVERAGE@1"


def interval_coverage(
    lower: Sequence[float] | FloatArray,
    upper: Sequence[float] | FloatArray,
    outcomes: Sequence[float] | FloatArray,
    *,
    nominal: float,
) -> IntervalCoverage:
    """Empirical coverage of central (1 − α) intervals on non-overlapping outcomes (§5.3, §5.4)."""
    lo, hi = _pair(lower, upper)
    y = _arr(outcomes, "outcomes")
    if y.shape != lo.shape:
        raise InvalidInput("outcomes length mismatch")
    if np.any(hi < lo):
        raise InvalidInput("upper < lower")
    if not 0.0 < nominal < 1.0:
        raise InvalidInput("nominal must be in (0, 1)")
    alpha = 1.0 - nominal
    inside_mask = (y >= lo) & (y <= hi)
    n = int(y.size)
    inside = int(inside_mask.sum())
    scores = (hi - lo) + (2.0 / alpha) * (lo - y) * (y < lo) + (2.0 / alpha) * (y - hi) * (y > hi)
    binom_p = float(stats.binomtest(inside, n, nominal).pvalue)
    lr, kp = kupiec_pof(n, inside, nominal)
    c_lr: float | None = None
    c_p: float | None = None
    if n >= 2:
        c_lr, c_p = christoffersen_independence([not bool(v) for v in inside_mask])
    coverage = inside / n
    if n < MIN_CALIBRATION_POINTS:
        status = "calibration_unknown"
        passes = False
    else:
        lo_gate, hi_gate = _coverage_gate(nominal)
        ok = lo_gate <= coverage <= hi_gate and kp >= KUPIEC_MIN_P
        status = "calibrated" if ok else "miscalibrated"
        passes = ok
    return IntervalCoverage(
        nominal=nominal,
        n=n,
        inside=inside,
        coverage=coverage,
        interval_scores=tuple(float(s) for s in scores),
        mean_interval_score=float(np.mean(scores)),
        binomial_p=binom_p,
        kupiec_lr=lr,
        kupiec_p=kp,
        christoffersen_lr=c_lr,
        christoffersen_p=c_p,
        status=status,
        passes_gate=passes,
    )


def _coverage_gate(nominal: float) -> tuple[float, float]:
    """§5.4 states [70 %, 90 %] for the 80 % band, i.e. nominal ± 10 pp, applied symmetrically to other bands."""
    return max(0.0, nominal - 0.10), min(1.0, nominal + 0.10)


# =====================================================================================================
# §6 Diebold–Mariano with HLN correction, promotion gate
# =====================================================================================================


@dataclass(frozen=True)
class DieboldMariano:
    t: int
    h: int
    mean_differential: float  # mean of d = L_model − L_baseline (negative ⇒ model better)
    gamma0: float
    long_run_variance: float
    dm_raw: float
    p_raw: float  # two-sided, Student t_{T−1} (as in the spec fixture)
    hln_factor: float
    dm_hln: float
    p_hln: float  # two-sided, Student t_{T−1} (Harvey–Leybourne–Newbold 1997)
    test_id: str = "DM_HLN@1"


def diebold_mariano(
    loss_model: Sequence[float] | FloatArray, loss_baseline: Sequence[float] | FloatArray, *, h: int
) -> DieboldMariano:
    """DM on d_k = L_M,k − L_B,k with HAC (rectangular, lag h−1, 1/T autocovariances) and the HLN correction."""
    a, b = _pair(loss_model, loss_baseline)
    if h < 1:
        raise InvalidInput("h must be ≥ 1")
    d = a - b
    t = int(d.size)
    if t < 3 or t <= 2 * h - 1:
        raise InsufficientHistory(f"T={t} too small for the DM test at h={h}")
    dbar = float(d.mean())
    dc = d - dbar
    gammas = [float(np.dot(dc[k:], dc[: t - k]) / t) for k in range(h)]
    lrv = gammas[0] + 2.0 * sum(gammas[1:])
    var = lrv / t
    if not var > 0.0:
        raise NumericalError(f"non-positive DM variance ({var}); loss differential is degenerate")
    dm = dbar / math.sqrt(var)
    factor_sq = (t + 1 - 2 * h + h * (h - 1) / t) / t
    if not factor_sq > 0:
        raise NumericalError("HLN correction factor is not positive")
    factor = math.sqrt(factor_sq)
    dm_star = dm * factor
    p_raw = float(2.0 * stats.t.sf(abs(dm), t - 1))
    p_hln = float(2.0 * stats.t.sf(abs(dm_star), t - 1))
    return DieboldMariano(
        t=t,
        h=h,
        mean_differential=dbar,
        gamma0=gammas[0],
        long_run_variance=lrv,
        dm_raw=_finite(dm, "DM"),
        p_raw=p_raw,
        hln_factor=factor,
        dm_hln=_finite(dm_star, "DM*"),
        p_hln=p_hln,
    )


class PromotionVerdict(StrEnum):
    PROMOTED = "promoted"
    BASELINE_RETAINED = "baseline retained"


@dataclass(frozen=True)
class PromotionResult:
    verdict: PromotionVerdict
    reasons: tuple[str, ...]  # empty only when promoted
    relative_improvement: float
    alpha: float
    alpha_adjusted: float
    dm: DieboldMariano
    rule_id: str = "PROMOTION_GATE@1"


def promotion_gate(
    loss_candidate: Sequence[float] | FloatArray,
    loss_baseline: Sequence[float] | FloatArray,
    *,
    h: int,
    alpha: float = 0.05,
    min_relative_improvement: float = 0.05,
    calibration_passed: bool | None,
    subperiods_improved: Sequence[bool] | None,
    n_candidates_tried: int = 1,
) -> PromotionResult:
    """§6: promote only if every condition holds; otherwise "baseline retained" with all failing reasons.

    1. mean loss lower by ≥ ``min_relative_improvement`` (relative);
    2. HLN-corrected two-sided DM p < α (Bonferroni α / n_candidates when several were tried — conservative
       relative to Holm for the smallest p-value);
    3. calibration gate passed (``None`` = not evaluated ⇒ not promoted);
    4. improvement holds in ≥ 2 of 3 sub-periods (``None`` = not evaluated ⇒ not promoted);
    plus ≥ 10 non-overlapping held-out origins (§4.1).
    """
    if not 0.0 < alpha < 1.0:
        raise InvalidInput("alpha must be in (0, 1)")
    if n_candidates_tried < 1:
        raise InvalidInput("n_candidates_tried must be ≥ 1")
    a, b = _pair(loss_candidate, loss_baseline)
    dm = diebold_mariano(a, b, h=h)
    base_mean = float(b.mean())
    if not base_mean > 0:
        raise InvalidInput("baseline mean loss must be > 0 for a relative comparison")
    rel = (base_mean - float(a.mean())) / base_mean
    alpha_adj = alpha / n_candidates_tried
    reasons: list[str] = []
    if dm.t < MIN_NON_OVERLAPPING_TEST_POINTS:
        reasons.append(f"insufficient evidence: {dm.t} held-out origins < {MIN_NON_OVERLAPPING_TEST_POINTS}")
    if rel < min_relative_improvement:
        reasons.append(f"relative improvement {rel:.4f} below the required {min_relative_improvement:.4f}")
    if dm.mean_differential >= 0:
        reasons.append("candidate mean loss is not lower than the baseline")
    if not dm.p_hln < alpha_adj:
        note = f" (raw DM p = {dm.p_raw:.4f} would pass)" if dm.p_raw < alpha_adj else ""
        reasons.append(f"small-sample corrected (HLN) DM p = {dm.p_hln:.4f} not below α = {alpha_adj:.4f}{note}")
    if calibration_passed is None:
        reasons.append("calibration gate not evaluated")
    elif not calibration_passed:
        reasons.append("calibration gate failed")
    if subperiods_improved is None:
        reasons.append("sub-period robustness not evaluated")
    elif sum(bool(s) for s in subperiods_improved) < 2:
        reasons.append("improvement does not hold in ≥ 2 sub-periods")
    verdict = PromotionVerdict.PROMOTED if not reasons else PromotionVerdict.BASELINE_RETAINED
    return PromotionResult(
        verdict=verdict,
        reasons=tuple(reasons),
        relative_improvement=rel,
        alpha=alpha,
        alpha_adjusted=alpha_adj,
        dm=dm,
    )


# =====================================================================================================
# §7 Drift monitoring
# =====================================================================================================


@dataclass(frozen=True)
class CoverageMonitor:
    window: int
    coverage: float
    nominal: float
    kupiec_p: float
    alarm: bool
    reasons: tuple[str, ...]
    monitor_id: str = "DRIFT_ROLLING_COVERAGE@1"


def rolling_coverage_monitor(
    lower: Sequence[float] | FloatArray,
    upper: Sequence[float] | FloatArray,
    outcomes: Sequence[float] | FloatArray,
    *,
    nominal: float = 0.8,
    horizon_months: int,
    alarm_band: tuple[float, float] = (0.65, 0.95),
) -> CoverageMonitor:
    """Coverage over the last 24 (36 for H ≥ 6 m) non-overlapping matured forecasts; alarm outside the band
    or when Kupiec p < 0.05."""
    window = 36 if horizon_months >= 6 else 24
    lo, hi = _pair(lower, upper)
    y = _arr(outcomes, "outcomes")
    if y.shape != lo.shape:
        raise InvalidInput("outcomes length mismatch")
    if y.size < window:
        raise InsufficientHistory(f"{y.size} matured forecasts < monitor window {window}")
    lo, hi, y = lo[-window:], hi[-window:], y[-window:]
    inside = int(((y >= lo) & (y <= hi)).sum())
    cov = inside / window
    _, kp = kupiec_pof(window, inside, nominal)
    reasons: list[str] = []
    if not alarm_band[0] <= cov <= alarm_band[1]:
        reasons.append(f"coverage {cov:.3f} outside [{alarm_band[0]:.2f}, {alarm_band[1]:.2f}]")
    if kp < KUPIEC_MIN_P:
        reasons.append(f"Kupiec p = {kp:.4f} < {KUPIEC_MIN_P}")
    return CoverageMonitor(
        window=window, coverage=cov, nominal=nominal, kupiec_p=kp, alarm=bool(reasons), reasons=tuple(reasons)
    )


@dataclass(frozen=True)
class LossRatioMonitor:
    window: int
    ratio: float
    above_one: bool
    revert_to_baseline: bool  # ratio > 1 for 2 consecutive reviews
    monitor_id: str = "DRIFT_LOSS_RATIO@1"


def rolling_loss_ratio_monitor(
    loss_model: Sequence[float] | FloatArray,
    loss_baseline: Sequence[float] | FloatArray,
    *,
    previous_review_above_one: bool,
    window: int = 24,
) -> LossRatioMonitor:
    a, b = _pair(loss_model, loss_baseline)
    if a.size < window:
        raise InsufficientHistory(f"{a.size} matured forecasts < monitor window {window}")
    denom = float(b[-window:].mean())
    if not denom > 0:
        raise NumericalError("baseline loss is zero over the monitor window")
    ratio = float(a[-window:].mean()) / denom
    above = ratio > 1.0
    return LossRatioMonitor(
        window=window, ratio=ratio, above_one=above, revert_to_baseline=above and previous_review_above_one
    )


PSI_EPSILON = 1e-4


@dataclass(frozen=True)
class PSIResult:
    value: float
    status: str  # "stable" < 0.10 ≤ "watch" ≤ 0.25 < "alarm" (rule of thumb, not a statistical test)
    expected_shares: tuple[float, ...]
    actual_shares: tuple[float, ...]
    epsilon_applied: bool
    metric_id: str = "PSI@1"


def _psi_status(v: float) -> str:
    if v < 0.10:
        return "stable"
    if v <= 0.25:
        return "watch"
    return "alarm"


def psi_from_shares(expected: Sequence[float], actual: Sequence[float]) -> PSIResult:
    """PSI = Σ (a_i − e_i) ln(a_i / e_i). Zero-share bins: ε = 1e−4 added to both shares, recorded."""
    e, a = _pair(expected, actual)
    if np.any(e < 0) or np.any(a < 0):
        raise InvalidInput("shares must be ≥ 0")
    for name, s in (("expected", e), ("actual", a)):
        if not math.isclose(float(s.sum()), 1.0, abs_tol=1e-9):
            raise InvalidInput(f"{name} shares must sum to 1")
    eps_applied = bool(np.any(e == 0) or np.any(a == 0))
    if eps_applied:
        e = e + PSI_EPSILON
        a = a + PSI_EPSILON
    v = _finite(float(np.sum((a - e) * np.log(a / e))), "PSI")
    return PSIResult(
        value=v,
        status=_psi_status(v),
        expected_shares=tuple(float(x) for x in e),
        actual_shares=tuple(float(x) for x in a),
        epsilon_applied=eps_applied,
    )


def psi(
    expected_sample: Sequence[float] | FloatArray, actual_sample: Sequence[float] | FloatArray, *, bins: int = 10
) -> PSIResult:
    """PSI over quantile bins (deciles by default) of the expected (training) sample."""
    e = _arr(expected_sample, "expected_sample")
    a = _arr(actual_sample, "actual_sample")
    if bins < 2:
        raise InvalidInput("bins must be ≥ 2")
    edges = np.quantile(e, np.linspace(0.0, 1.0, bins + 1), method="linear")
    inner = np.unique(edges[1:-1])
    e_idx = np.searchsorted(inner, e, side="right")
    a_idx = np.searchsorted(inner, a, side="right")
    k = inner.size + 1
    e_sh = np.bincount(e_idx, minlength=k) / e.size
    a_sh = np.bincount(a_idx, minlength=k) / a.size
    return psi_from_shares(list(e_sh), list(a_sh))
