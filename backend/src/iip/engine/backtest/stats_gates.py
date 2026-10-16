"""Evidence statistics for signal gates: PSR/DSR, MinTRL, 80 %-power length, Holm, HAC t (WP A18).

Sources (all quoted and recomputed in ``docs/research/wave1/research-backtest-method.md`` §9 and
``verify-backtest-method.md`` BT-2 / BT-9):

* Bailey & López de Prado (2014), "The Deflated Sharpe Ratio": PSR, SR₀ (expected maximum Sharpe ratio across N
  trials), DSR and MinTRL. All Sharpe ratios here are **per period** (not annualised); kurtosis is **non-excess**.
* Holm (1979) sequentially rejective procedure on one-sided p-values.
* Newey & West (1987) HAC long-run variance with a Bartlett kernel for the t-statistic of a mean edge; Harvey, Liu &
  Zhu (2016) t > 3 hurdle.
* The 80 %-power length is this package's own derivation (verify BT-9): with the PSR variance term
  ``v(SR) = 1 − γ₃·SR + (γ₄ − 1)/4·SR²`` it reads ``T = 1 + v · ((z₁₋α + z_power)/(SR − SR*))²``, which equals MinTRL at
  50 % power. ``moment_adjusted=False`` uses ``v = 1`` (the ``V[SR] ≈ 1/T`` approximation behind "about 298 months").

Statistics are floats (they are not money); only the stdlib ``statistics.NormalDist`` is used, never scipy. Every
function is pure. PBO/CSCV and Hansen's SPA are **not implemented** and their gates return
``ABSTAIN(gate_not_implemented)``, so deferring them can never let a signal through (PLAN §5.1 rule 7).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import NormalDist

from iip.engine.dates import add_months
from iip.engine.errors import InvalidInput, NumericalError

__all__ = [
    "DSR_THRESHOLD",
    "EULER_MASCHERONI",
    "GATE_NOT_IMPLEMENTED",
    "HAC_T_THRESHOLD",
    "HOLM_MAX_FAMILY",
    "MIN_OOS_PERIODS",
    "DeflatedSharpe",
    "EarliestReview",
    "GateResult",
    "GateStatus",
    "HacT",
    "MultipleTesting",
    "NormalDist",
    "SharpeMoments",
    "bonferroni",
    "deflated_sharpe_ratio",
    "dsr_gate",
    "earliest_review",
    "expected_max_sharpe",
    "hac_t_gate",
    "hac_t_stat",
    "holm",
    "holm_gate",
    "min_track_record_length",
    "mintrl_gate",
    "newey_west_lag",
    "pbo_cscv_gate",
    "power_length",
    "probabilistic_sharpe_ratio",
    "sharpe_moments",
    "spa_gate",
]

_N = NormalDist()

#: Euler–Mascheroni constant ("approx. 0.5772" in Bailey & López de Prado 2014).
EULER_MASCHERONI = 0.57721566490153286061
#: G9 thresholds (design-judgement.md J-6, kept as written by user decision U-06).
DSR_THRESHOLD = 0.95
HAC_T_THRESHOLD = 3.0
#: G5: at least 30 non-overlapping OOS periods, and at least MinTRL.
MIN_OOS_PERIODS = 30
#: G9: Holm for families of at most 20 trials; larger families need SPA (not built → fail closed).
HOLM_MAX_FAMILY = 20
#: MinTRL / PSR confidence level (PSR ≥ 0.95).
PSR_CONFIDENCE = 0.95
GATE_NOT_IMPLEMENTED = "gate_not_implemented"


# ================================================================================================ helpers


def _finite(x: float, name: str) -> float:
    if not math.isfinite(x):
        raise InvalidInput(f"{name} must be finite (got {x!r})")
    return x


def _variance_term(sharpe: float, skewness: float, kurtosis: float) -> float:
    """``1 − γ₃·SR + (γ₄ − 1)/4·SR²``; non-positive means the moments are degenerate and nothing is returned."""
    _finite(sharpe, "sharpe")
    _finite(skewness, "skewness")
    _finite(kurtosis, "kurtosis")
    v = 1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe
    if not v > 0.0:
        raise NumericalError(f"non-positive Sharpe variance term ({v}); skewness/kurtosis are degenerate")
    return v


def _check_alpha(alpha: float) -> float:
    if not (math.isfinite(alpha) and 0.0 < alpha < 1.0):
        raise InvalidInput("alpha must be in (0, 1)")
    return alpha


# ================================================================================================ moments


@dataclass(frozen=True)
class SharpeMoments:
    """Per-period moments of a return (or edge) series. Population (ddof = 0) moments, non-excess kurtosis."""

    n_obs: int
    mean: float
    std: float
    sharpe: float
    skewness: float
    kurtosis: float


def sharpe_moments(returns: Sequence[float]) -> SharpeMoments:
    xs = [_finite(float(x), "return") for x in returns]
    n = len(xs)
    if n < 2:
        raise InvalidInput("need at least 2 observations")
    mean = math.fsum(xs) / n
    dev = [x - mean for x in xs]
    m2 = math.fsum(d * d for d in dev) / n
    if not m2 > 0.0:
        raise NumericalError("zero variance: the Sharpe ratio is undefined")
    m3 = math.fsum(d**3 for d in dev) / n
    m4 = math.fsum(d**4 for d in dev) / n
    std = math.sqrt(m2)
    return SharpeMoments(n_obs=n, mean=mean, std=std, sharpe=mean / std, skewness=m3 / m2**1.5, kurtosis=m4 / (m2 * m2))


# ================================================================================================ PSR / DSR


def probabilistic_sharpe_ratio(
    sharpe: float, benchmark_sharpe: float, *, n_obs: int, skewness: float, kurtosis: float
) -> float:
    """``PSR(SR*) = Φ((ŜR − SR*)·√(T − 1) / √(1 − γ₃·ŜR + (γ₄ − 1)/4·ŜR²))``."""
    if n_obs < 2:
        raise InvalidInput("PSR needs n_obs ≥ 2")
    _finite(benchmark_sharpe, "benchmark_sharpe")
    v = _variance_term(sharpe, skewness, kurtosis)
    z = (sharpe - benchmark_sharpe) * math.sqrt(n_obs - 1) / math.sqrt(v)
    return _N.cdf(z)


def expected_max_sharpe(*, n_trials: int, sharpe_variance: float) -> float:
    """``SR₀ = √V · ((1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))``; one trial has nothing to deflate (SR₀ = 0)."""
    if n_trials < 1:
        raise InvalidInput("n_trials must be ≥ 1")
    if not (math.isfinite(sharpe_variance) and sharpe_variance >= 0.0):
        raise InvalidInput("sharpe_variance must be finite and ≥ 0")
    if n_trials == 1:
        return 0.0
    g = EULER_MASCHERONI
    z = (1.0 - g) * _N.inv_cdf(1.0 - 1.0 / n_trials) + g * _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * z


@dataclass(frozen=True)
class DeflatedSharpe:
    sharpe: float
    n_obs: int
    n_trials: int
    sharpe_variance: float
    skewness: float
    kurtosis: float
    sr0: float
    dsr: float
    threshold: float = DSR_THRESHOLD
    formula_id: str = "stats.dsr@1"

    @property
    def passes(self) -> bool:
        return self.dsr >= self.threshold


def deflated_sharpe_ratio(
    *, sharpe: float, n_obs: int, skewness: float, kurtosis: float, n_trials: int, sharpe_variance: float
) -> DeflatedSharpe:
    """``DSR = PSR(SR₀)``. Use the raw trial count N unless an effective N is computed and logged (§9.1)."""
    sr0 = expected_max_sharpe(n_trials=n_trials, sharpe_variance=sharpe_variance)
    dsr = probabilistic_sharpe_ratio(sharpe, sr0, n_obs=n_obs, skewness=skewness, kurtosis=kurtosis)
    return DeflatedSharpe(
        sharpe=sharpe,
        n_obs=n_obs,
        n_trials=n_trials,
        sharpe_variance=sharpe_variance,
        skewness=skewness,
        kurtosis=kurtosis,
        sr0=sr0,
        dsr=dsr,
    )


# ================================================================================================ MinTRL / power


def min_track_record_length(
    sharpe: float, benchmark_sharpe: float, *, skewness: float, kurtosis: float, confidence: float = PSR_CONFIDENCE
) -> float:
    """``MinTRL = 1 + v(ŜR)·(Φ⁻¹(confidence)/(ŜR − SR*))²`` periods; undefined (InvalidInput) when ŜR ≤ SR*."""
    return power_length(
        sharpe, benchmark_sharpe, alpha=1.0 - confidence, power=0.5, skewness=skewness, kurtosis=kurtosis
    )


def power_length(
    sharpe: float,
    benchmark_sharpe: float,
    *,
    skewness: float,
    kurtosis: float,
    alpha: float = 1.0 - PSR_CONFIDENCE,
    power: float = 0.80,
    moment_adjusted: bool = True,
) -> float:
    """Periods needed for a one-sided level-α PSR test to detect a true per-period Sharpe ``sharpe`` with ``power``.

    ``T = 1 + v·((z₁₋α + z_power)/(SR − SR*))²``, v = the PSR variance term (or 1 when ``moment_adjusted`` is off).
    """
    _check_alpha(alpha)
    if not (math.isfinite(power) and 0.0 < power < 1.0):
        raise InvalidInput("power must be in (0, 1)")
    _finite(benchmark_sharpe, "benchmark_sharpe")
    v = _variance_term(sharpe, skewness, kurtosis) if moment_adjusted else 1.0
    edge = sharpe - benchmark_sharpe
    if not edge > 0.0:
        raise InvalidInput("undefined: the Sharpe ratio does not exceed the benchmark Sharpe ratio")
    z = _N.inv_cdf(1.0 - alpha) + _N.inv_cdf(power)
    return 1.0 + v * (z / edge) ** 2


@dataclass(frozen=True)
class EarliestReview:
    registration: date
    min_trl: float
    months: int  # max(30, ⌈MinTRL⌉)
    review_date: date
    formula_id: str = "stats.earliest_review@1"


def earliest_review(
    registration: date, sharpe: float, benchmark_sharpe: float, *, skewness: float, kurtosis: float
) -> EarliestReview:
    """``registration + max(30, MinTRL) months`` (design-judgement.md §2), MinTRL rounded **up** to whole months.

    The Sharpe inputs are per month (the signals run on a monthly grid). Month arithmetic is EDATE (clamped to
    month-end).
    """
    mtrl = min_track_record_length(sharpe, benchmark_sharpe, skewness=skewness, kurtosis=kurtosis)
    months = max(MIN_OOS_PERIODS, math.ceil(mtrl))
    return EarliestReview(
        registration=registration, min_trl=mtrl, months=months, review_date=add_months(registration, months)
    )


# ================================================================================================ multiple testing


@dataclass(frozen=True)
class MultipleTesting:
    method: str
    alpha: float
    p_values: tuple[float, ...]
    adjusted_p: tuple[float, ...]
    rejected: tuple[bool, ...]

    @property
    def n_rejected(self) -> int:
        return sum(self.rejected)


def _check_p(p_values: Sequence[float]) -> tuple[float, ...]:
    ps = tuple(float(p) for p in p_values)
    if not ps:
        raise InvalidInput("need at least one p-value")
    for p in ps:
        if not (math.isfinite(p) and 0.0 <= p <= 1.0):
            raise InvalidInput(f"p-value out of [0, 1]: {p!r}")
    return ps


def bonferroni(p_values: Sequence[float], *, alpha: float) -> MultipleTesting:
    ps = _check_p(p_values)
    _check_alpha(alpha)
    m = len(ps)
    return MultipleTesting(
        method="bonferroni",
        alpha=alpha,
        p_values=ps,
        adjusted_p=tuple(min(1.0, p * m) for p in ps),
        rejected=tuple(p <= alpha / m for p in ps),
    )


def holm(p_values: Sequence[float], *, alpha: float) -> MultipleTesting:
    """Holm step-down: sort ascending, reject while ``p_(i) ≤ α/(m − i + 1)``; results in the input order.

    Adjusted p-values are ``max_{j ≤ i} min(1, (m − j + 1)·p_(j))``; ``rejected[i]`` ⇔ ``adjusted_p[i] ≤ α``.
    """
    ps = _check_p(p_values)
    _check_alpha(alpha)
    m = len(ps)
    order = sorted(range(m), key=lambda i: (ps[i], i))
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[idx]))
        adjusted[idx] = running
    rejected = [False] * m
    for rank, idx in enumerate(order):
        if ps[idx] <= alpha / (m - rank):
            rejected[idx] = True
        else:
            break
    return MultipleTesting(
        method="holm", alpha=alpha, p_values=ps, adjusted_p=tuple(adjusted), rejected=tuple(rejected)
    )


# ================================================================================================ HAC t


def newey_west_lag(n_obs: int) -> int:
    """Newey–West (1994) plug-in rule ``⌊4·(T/100)^(2/9)⌋``; callers may pass any lag they pre-register."""
    if n_obs < 1:
        raise InvalidInput("n_obs must be ≥ 1")
    return math.floor(4.0 * math.pow(n_obs / 100.0, 2.0 / 9.0))


@dataclass(frozen=True)
class HacT:
    n_obs: int
    lag: int
    mean: float
    long_run_variance: float
    t_stat: float
    p_one_sided: float  # normal approximation, H1: mean > 0
    threshold: float = HAC_T_THRESHOLD
    formula_id: str = "stats.hac_t_bartlett@1"

    @property
    def passes(self) -> bool:
        return self.t_stat >= self.threshold


def hac_t_stat(edge: Sequence[float], *, lag: int) -> HacT:
    """t-statistic of the mean edge with a Newey–West (Bartlett) long-run variance and 1/T autocovariances.

    ``LRV = γ₀ + 2·Σ_{k=1..L} (1 − k/(L + 1))·γ_k``; ``t = mean / √(LRV/T)``. ``lag`` is mandatory (no hidden default).
    """
    xs = [_finite(float(x), "edge") for x in edge]
    n = len(xs)
    if n < 2:
        raise InvalidInput("need at least 2 observations")
    if lag < 0 or lag >= n:
        raise InvalidInput(f"lag must be in [0, {n - 1}] (got {lag})")
    mean = math.fsum(xs) / n
    dev = [x - mean for x in xs]

    def gamma(k: int) -> float:
        return math.fsum(dev[i] * dev[i - k] for i in range(k, n)) / n

    lrv = gamma(0) + 2.0 * math.fsum((1.0 - k / (lag + 1)) * gamma(k) for k in range(1, lag + 1))
    if not lrv > 0.0:
        raise NumericalError(f"non-positive long-run variance ({lrv}); the edge series is degenerate")
    t = mean / math.sqrt(lrv / n)
    return HacT(n_obs=n, lag=lag, mean=mean, long_run_variance=lrv, t_stat=t, p_one_sided=1.0 - _N.cdf(t))


# ================================================================================================ gates


class GateStatus(StrEnum):
    PASS = "pass"  # noqa: S105 (a gate status, not a credential)
    FAIL = "fail"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class GateResult:
    """One statistical gate outcome. Only PASS passes; FAIL and ABSTAIN always carry a reason code."""

    gate_id: str
    status: GateStatus
    passed: bool
    reason_code: str | None
    value: float | None
    threshold: float | None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.passed != (self.status is GateStatus.PASS):
            raise InvalidInput("passed must be True exactly when status is PASS")
        if self.status is not GateStatus.PASS and not self.reason_code:
            raise InvalidInput("a failing or abstaining gate needs a reason code")


def _not_implemented(gate_id: str, what: str) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        status=GateStatus.ABSTAIN,
        passed=False,
        reason_code=GATE_NOT_IMPLEMENTED,
        value=None,
        threshold=None,
        detail=f"{what} is not implemented; the gate fails closed",
    )


def pbo_cscv_gate() -> GateResult:
    """PBO via CSCV (Bailey, Borwein, López de Prado & Zhu 2017) — deferred; fails closed."""
    return _not_implemented("G10.pbo_cscv", "PBO/CSCV")


def spa_gate() -> GateResult:
    """Hansen (2005) SPA — deferred; fails closed."""
    return _not_implemented("G9.spa", "Hansen SPA")


def dsr_gate(
    *, sharpe: float, n_obs: int, skewness: float, kurtosis: float, n_trials: int, sharpe_variance: float
) -> GateResult:
    r = deflated_sharpe_ratio(
        sharpe=sharpe,
        n_obs=n_obs,
        skewness=skewness,
        kurtosis=kurtosis,
        n_trials=n_trials,
        sharpe_variance=sharpe_variance,
    )
    ok = r.passes
    return GateResult(
        gate_id="G9.dsr",
        status=GateStatus.PASS if ok else GateStatus.FAIL,
        passed=ok,
        reason_code=None if ok else "not_significant_after_multiple_testing",
        value=r.dsr,
        threshold=r.threshold,
        detail=f"DSR {r.dsr:.4f} vs {r.threshold} (N = {n_trials}, SR0 = {r.sr0:.6f})",
    )


def hac_t_gate(edge: Sequence[float], *, lag: int) -> GateResult:
    r = hac_t_stat(edge, lag=lag)
    ok = r.passes
    return GateResult(
        gate_id="G9.hac_t",
        status=GateStatus.PASS if ok else GateStatus.FAIL,
        passed=ok,
        reason_code=None if ok else "hac_t_below_threshold",
        value=r.t_stat,
        threshold=r.threshold,
        detail=f"HAC t {r.t_stat:.3f} (lag {lag}, T = {r.n_obs}) vs {r.threshold}",
    )


def holm_gate(p_values: Sequence[float], *, selected: int, alpha: float = 0.05) -> GateResult:
    """Holm on the family's one-sided p-values; the selected trial must be rejected. N > 20 needs SPA → abstain."""
    ps = _check_p(p_values)
    if not 0 <= selected < len(ps):
        raise InvalidInput("selected index out of range")
    if len(ps) > HOLM_MAX_FAMILY:
        r = spa_gate()
        return GateResult(
            gate_id="G9.multiple_testing",
            status=r.status,
            passed=False,
            reason_code=r.reason_code,
            value=None,
            threshold=None,
            detail=f"family of {len(ps)} trials > {HOLM_MAX_FAMILY} needs SPA, which is not implemented",
        )
    h = holm(ps, alpha=alpha)
    ok = h.rejected[selected]
    return GateResult(
        gate_id="G9.multiple_testing",
        status=GateStatus.PASS if ok else GateStatus.FAIL,
        passed=ok,
        reason_code=None if ok else "not_significant_after_multiple_testing",
        value=h.adjusted_p[selected],
        threshold=alpha,
        detail=f"Holm-adjusted p {h.adjusted_p[selected]:.4f} vs α {alpha} (N = {len(ps)})",
    )


def mintrl_gate(*, n_oos: int, sharpe: float, benchmark_sharpe: float, skewness: float, kurtosis: float) -> GateResult:
    """G5: OOS length ≥ max(30, ⌈MinTRL⌉); otherwise ABSTAIN(insufficient_evidence: has X, needs Y)."""
    if n_oos < 0:
        raise InvalidInput("n_oos must be ≥ 0")
    if not sharpe > benchmark_sharpe:
        return GateResult(
            gate_id="G5.sample_size",
            status=GateStatus.ABSTAIN,
            passed=False,
            reason_code="no_edge",
            value=float(n_oos),
            threshold=None,
            detail="MinTRL is undefined: the Sharpe ratio does not exceed the benchmark",
        )
    mtrl = min_track_record_length(sharpe, benchmark_sharpe, skewness=skewness, kurtosis=kurtosis)
    needs = max(MIN_OOS_PERIODS, math.ceil(mtrl))
    ok = n_oos >= needs
    return GateResult(
        gate_id="G5.sample_size",
        status=GateStatus.PASS if ok else GateStatus.ABSTAIN,
        passed=ok,
        reason_code=None if ok else "insufficient_evidence",
        value=float(n_oos),
        threshold=float(needs),
        detail=f"has {n_oos}, needs {needs} (MinTRL {mtrl:.2f})",
    )
