"""Oracle cross-checks for forecast scoring (rule 3): scoringrules for CRPS/pinball, independent hand DM."""

import math
import statistics

import numpy as np
import pytest
import scoringrules as sr
from scipy import stats

from iip.engine.forecasting.validation import (
    crps_ensemble,
    crps_from_quantiles,
    crps_gaussian,
    diebold_mariano,
    interval_coverage,
    pinball_loss,
)

pytestmark = pytest.mark.oracle

RNG_SEED = 20261015


def test_crps_ensemble_vs_scoringrules() -> None:
    rng = np.random.default_rng(RNG_SEED)
    for _ in range(50):
        m = int(rng.integers(2, 60))
        ens = rng.normal(0, 1, m)
        y = float(rng.normal())
        ours = crps_ensemble(ens, y)
        theirs = float(sr.crps_ensemble(y, ens, estimator="nrg"))
        assert ours == pytest.approx(theirs, rel=1e-12, abs=1e-12)


def test_crps_gaussian_vs_scoringrules() -> None:
    for y, mu, sigma in [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (-2.5, 0.3, 0.7), (4.0, 1.0, 3.0)]:
        assert crps_gaussian(y, mu, sigma) == pytest.approx(float(sr.crps_normal(y, mu, sigma)), rel=1e-12)


def test_pinball_vs_scoringrules_quantile_score() -> None:
    rng = np.random.default_rng(RNG_SEED + 1)
    for _ in range(100):
        y, q = (float(v) for v in rng.normal(0, 2, 2))
        tau = float(rng.uniform(0.01, 0.99))
        # scoringrules' quantile_score is the pinball loss (Gneiting 2011, without the factor 2)
        assert pinball_loss(y, q, tau) == pytest.approx(float(sr.quantile_score(y, q, tau)), rel=1e-12, abs=1e-15)


def test_crps_from_quantiles_vs_scoringrules_and_closed_form() -> None:
    taus = np.linspace(0.005, 0.995, 199)
    qs = stats.norm.ppf(taus)
    for y in (-1.3, 0.0, 0.4, 2.2):
        ours = crps_from_quantiles(y, qs, taus)
        theirs = float(sr.crps_quantile(y, qs, taus))
        assert ours == pytest.approx(theirs, rel=1e-9)
        # dense-grid approximation of the Gaussian closed form (spec §5.2): within 1 %
        assert ours == pytest.approx(crps_gaussian(y, 0.0, 1.0), rel=0.01)


def test_interval_score_vs_scoringrules() -> None:
    lo = [-2, -1, -3, 0, -2, -1, -2, -4, -1, -2]
    hi = [3, 4, 2, 5, 3, 4, 3, 1, 4, 3]
    y = [1, 5, 0, 2, -3, 2, 1, 2, 3, 0]
    ours = interval_coverage(lo, hi, y, nominal=0.8).interval_scores
    theirs = [float(sr.interval_score(yy, lower, upper, 0.2)) for yy, lower, upper in zip(y, lo, hi, strict=True)]
    assert ours == pytest.approx(theirs, rel=1e-12)


def _hand_dm(d: list[float], h: int) -> tuple[float, float, float, float]:
    """Independent pure-Python DM + HLN (no numpy)."""
    t = len(d)
    mean = sum(d) / t

    def gamma(k: int) -> float:
        return sum((d[i] - mean) * (d[i - k] - mean) for i in range(k, t)) / t

    var = (gamma(0) + 2 * sum(gamma(k) for k in range(1, h))) / t
    dm = mean / math.sqrt(var)
    factor = math.sqrt((t + 1 - 2 * h + h * (h - 1) / t) / t)
    p_raw = 2 * stats.t.sf(abs(dm), t - 1)
    p_hln = 2 * stats.t.sf(abs(dm * factor), t - 1)
    return dm, dm * factor, p_raw, p_hln


def test_dm_vs_hand_computation_and_ttest() -> None:
    model = [1.0, 0.8, 1.2, 0.9, 1.1, 0.7, 1.0, 0.9, 1.3, 0.8]
    base = [1.1, 1.0, 1.1, 1.2, 1.0, 0.9, 1.2, 1.0, 1.2, 1.1]
    d = [a - b for a, b in zip(model, base, strict=True)]
    ours = diebold_mariano(model, base, h=1)
    dm, dm_star, p_raw, p_hln = _hand_dm(d, 1)
    assert ours.dm_raw == pytest.approx(dm, rel=1e-12)
    assert ours.dm_hln == pytest.approx(dm_star, rel=1e-12)
    assert ours.p_raw == pytest.approx(p_raw, rel=1e-10)
    assert ours.p_hln == pytest.approx(p_hln, rel=1e-10)
    # For h = 1, HLN-corrected DM equals the one-sample t statistic (sample sd with T−1).
    tt = stats.ttest_1samp(d, 0.0)
    assert ours.dm_hln == pytest.approx(float(tt.statistic), rel=1e-12)
    assert ours.p_hln == pytest.approx(float(tt.pvalue), rel=1e-10)
    assert statistics.fmean(d) == pytest.approx(ours.mean_differential)


@pytest.mark.parametrize("h", [2, 3])
def test_dm_multi_step_vs_hand(h: int) -> None:
    rng = np.random.default_rng(RNG_SEED + h)
    a = list(rng.normal(1.0, 0.3, 60))
    b = list(rng.normal(1.1, 0.3, 60))
    d = [x - y for x, y in zip(a, b, strict=True)]
    ours = diebold_mariano(a, b, h=h)
    dm, dm_star, _, p_hln = _hand_dm(d, h)
    assert ours.dm_raw == pytest.approx(dm, rel=1e-10)
    assert ours.dm_hln == pytest.approx(dm_star, rel=1e-10)
    assert ours.p_hln == pytest.approx(p_hln, rel=1e-9)
