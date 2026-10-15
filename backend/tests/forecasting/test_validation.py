"""Validation harness — fixtures from docs/forecasting/validation-methodology.md §4.2, §5, §6, §7."""

import numpy as np
import pytest

from iip.engine.errors import InvalidInput, NumericalError
from iip.engine.forecasting.validation import (
    LeakageError,
    PromotionVerdict,
    assert_no_leakage,
    crps_ensemble,
    crps_gaussian,
    diebold_mariano,
    directional_accuracy,
    interval_coverage,
    mae,
    mean_pinball_loss,
    pinball_loss,
    pit_values,
    promotion_gate,
    psi,
    psi_from_shares,
    purged_kfold,
    rmse,
    rolling_coverage_monitor,
    walk_forward_splits,
)

# ---------------------------------------------------------------- PB-1
Q_LEVELS = (0.1, 0.5, 0.9)
Q_VALUES = (2.0, 4.0, 7.0)


@pytest.mark.parametrize(
    ("y", "losses", "mean"),
    [
        (5.0, (0.30, 0.50, 0.20), 0.3333),
        (1.0, (0.90, 1.50, 0.60), 1.0000),
        (8.0, (0.60, 2.00, 0.90), 1.1667),
    ],
)
def test_pinball_pb1(y: float, losses: tuple[float, float, float], mean: float) -> None:
    for tau, q, expected in zip(Q_LEVELS, Q_VALUES, losses, strict=True):
        assert pinball_loss(y, q, tau) == pytest.approx(expected, abs=1e-12)
    assert mean_pinball_loss(y, Q_VALUES, Q_LEVELS) == pytest.approx(mean, abs=5e-5)


def test_pinball_rejects_bad_tau() -> None:
    with pytest.raises(InvalidInput):
        pinball_loss(1.0, 1.0, 1.0)


# ---------------------------------------------------------------- COV-1
COV_L = [-2, -1, -3, 0, -2, -1, -2, -4, -1, -2]
COV_U = [3, 4, 2, 5, 3, 4, 3, 1, 4, 3]
COV_Y = [1, 5, 0, 2, -3, 2, 1, 2, 3, 0]


def test_interval_coverage_cov1() -> None:
    r = interval_coverage(COV_L, COV_U, COV_Y, nominal=0.8)
    assert r.n == 10 and r.inside == 7
    assert r.coverage == pytest.approx(0.7)
    assert r.mean_interval_score == pytest.approx(8.0)
    assert r.interval_scores == pytest.approx((5, 15, 5, 5, 15, 5, 5, 15, 5, 5))
    assert r.binomial_p == pytest.approx(0.4296, abs=5e-5)
    assert r.kupiec_lr == pytest.approx(0.5634, abs=5e-5)
    assert r.kupiec_p == pytest.approx(0.4529, abs=5e-5)
    assert r.status == "calibration_unknown"  # n < 30
    assert r.passes_gate is False


def test_coverage_gate_passes_with_30_well_calibrated_points() -> None:
    y = [0.0] * 24 + [10.0] * 6  # 24/30 = 80 % inside
    r = interval_coverage([-1.0] * 30, [1.0] * 30, y, nominal=0.8)
    assert r.coverage == pytest.approx(0.8)
    assert r.status == "calibrated"
    assert r.passes_gate is True


# ---------------------------------------------------------------- CRPS fixtures
def test_crps_fixtures() -> None:
    assert crps_ensemble([1.0, 3.0], 2.0) == pytest.approx(0.5)
    assert crps_ensemble([0.0, 2.0, 4.0, 6.0], 5.0) == pytest.approx(1.25)
    assert crps_gaussian(0.0, 0.0, 1.0) == pytest.approx(0.233695, abs=5e-7)
    assert crps_gaussian(1.0, 0.0, 1.0) == pytest.approx(0.602441, abs=5e-7)


def test_point_metrics() -> None:
    y = [1.0, -2.0, 3.0]
    yhat = [0.0, -1.0, 5.0]
    assert mae(y, yhat) == pytest.approx(4 / 3)
    assert rmse(y, yhat) == pytest.approx(np.sqrt(6 / 3))
    d = directional_accuracy(y, yhat, risk_free=[0.0, 0.0, 0.0])
    assert d.accuracy == pytest.approx(2 / 3)  # yhat=0 has sign 0 ≠ +1
    assert d.base_rate == pytest.approx(2 / 3)


def test_pit_values_interpolated_and_clipped() -> None:
    u = pit_values([5.0, 3.0, -10.0, 100.0], [Q_VALUES] * 4, Q_LEVELS)
    assert u[0] == pytest.approx(0.5 + 0.4 * (1 / 3))
    assert u[1] == pytest.approx(0.3)
    assert u[2] == pytest.approx(0.1)  # clipped to outer quantile
    assert u[3] == pytest.approx(0.9)


# ---------------------------------------------------------------- §4.2 toy walk-forward
def test_toy_split_purged_with_embargo() -> None:
    splits = walk_forward_splits(n_obs=30, horizon=5, origins=[20], embargo=2)
    (s,) = splits
    assert list(s.train) == list(range(14))  # 0..13
    assert list(s.test) == [20, 21, 22, 23, 24]
    assert s.train_max + 5 <= 20
    assert s.train_max + s.embargo < s.test_min


def test_toy_split_purged_without_embargo() -> None:
    (s,) = walk_forward_splits(n_obs=30, horizon=5, origins=[20], embargo=0)
    assert list(s.train) == list(range(16))  # 0..15 — 16..19 purged


def test_naive_split_detected_as_leakage() -> None:
    naive_train = np.arange(20)  # t < T
    with pytest.raises(LeakageError):
        assert_no_leakage(naive_train, origin=20, horizon=5, embargo=0)


def test_next_origin_reuses_test_samples_progressively() -> None:
    def one(origin: int):  # type: ignore[no-untyped-def]
        (s,) = walk_forward_splits(n_obs=50, horizon=5, origins=[origin], embargo=2)
        return s

    assert one(25).train_max == 18
    assert 20 not in one(25).train
    assert one(27).train_max == 20
    assert one(31).train_max == 24


def test_origins_must_be_spaced_by_horizon() -> None:
    with pytest.raises(InvalidInput):
        walk_forward_splits(n_obs=40, horizon=5, origins=[20, 22], embargo=2)


def test_default_embargo_from_spec() -> None:
    (s,) = walk_forward_splits(n_obs=1000, horizon=5, origins=[900])
    assert s.embargo == 10  # max(5, 0.01 × 1000)


def test_insufficient_evidence_flag() -> None:
    plan = walk_forward_splits(n_obs=200, horizon=5, origins=list(range(100, 150, 5)), embargo=2)
    assert len(plan) == 10
    plan9 = walk_forward_splits(n_obs=200, horizon=5, origins=list(range(100, 145, 5)), embargo=2)
    assert plan9.verdict == "insufficient_evidence"
    assert plan.verdict == "ok"


def test_planted_future_information_never_reaches_training() -> None:
    """Plant a huge shock after the origin; training labels must be byte-identical with and without it."""
    rng = np.random.default_rng(7)
    n, h, e = 60, 5, 2
    r = rng.normal(0, 0.01, n)
    for origin in (30, 35, 40, 45):
        planted = r.copy()
        planted[origin + 1 :] += 1000.0  # future information (strictly after the origin)
        (s,) = walk_forward_splits(n_obs=n, horizon=h, origins=[origin], embargo=e)

        def labels(series: np.ndarray, idx: np.ndarray) -> np.ndarray:
            return np.array([series[t + 1 : t + h + 1].sum() for t in idx])

        clean = labels(r, s.train)
        poisoned = labels(planted, s.train)
        assert np.array_equal(clean, poisoned), origin
        assert np.all(np.abs(poisoned) < 1.0)
        # and the naive splitter WOULD have leaked the plant into training
        naive = np.arange(origin)
        assert not np.array_equal(labels(r, naive), labels(planted, naive))


def test_purged_kfold() -> None:
    folds = purged_kfold(n_samples=60, k=3, horizon=5, embargo=2)
    assert len(folds) == 3
    f = folds[1]  # test [20, 39]
    a, b = int(f.test[0]), int(f.test[-1])
    assert (a, b) == (20, 39)
    for t in range(a - 5, a):
        assert t not in f.train
    for t in range(b + 1, b + 5 + 2 + 1):
        assert t not in f.train
    assert 14 in f.train and 47 in f.train


# ---------------------------------------------------------------- DM-1 and promotion
DM_MODEL = [1.0, 0.8, 1.2, 0.9, 1.1, 0.7, 1.0, 0.9, 1.3, 0.8]
DM_BASE = [1.1, 1.0, 1.1, 1.2, 1.0, 0.9, 1.2, 1.0, 1.2, 1.1]


def test_dm1_raw_and_hln() -> None:
    r = diebold_mariano(DM_MODEL, DM_BASE, h=1)
    assert r.mean_differential == pytest.approx(-0.11)
    assert r.gamma0 == pytest.approx(0.0229)
    assert r.dm_raw == pytest.approx(-2.2987, abs=5e-5)
    assert r.p_raw == pytest.approx(0.0471, abs=5e-5)
    assert r.hln_factor == pytest.approx(np.sqrt(0.9))
    assert r.dm_hln == pytest.approx(-2.1807, abs=5e-5)
    assert r.p_hln == pytest.approx(0.0571, abs=5e-5)


def test_dm1_promotion_gate_retains_baseline() -> None:
    g = promotion_gate(DM_MODEL, DM_BASE, h=1, alpha=0.05, calibration_passed=True, subperiods_improved=(True,) * 3)
    assert g.verdict is PromotionVerdict.BASELINE_RETAINED
    assert g.relative_improvement == pytest.approx(0.11 / 1.08)
    assert g.dm.p_raw < 0.05 < g.dm.p_hln
    assert any("corrected" in reason for reason in g.reasons)


def test_promotion_requires_every_condition() -> None:
    base = [1.0 + 0.01 * (i % 3) for i in range(40)]
    cand = [b - 0.2 + 0.001 * (i % 5) for i, b in enumerate(base)]
    ok = promotion_gate(cand, base, h=1, calibration_passed=True, subperiods_improved=(True, True, False))
    assert ok.verdict is PromotionVerdict.PROMOTED
    assert ok.reasons == ()
    for kwargs in (
        {"calibration_passed": False, "subperiods_improved": (True,) * 3},
        {"calibration_passed": None, "subperiods_improved": (True,) * 3},
        {"calibration_passed": True, "subperiods_improved": (True, False, False)},
        {"calibration_passed": True, "subperiods_improved": None},
    ):
        g = promotion_gate(cand, base, h=1, **kwargs)  # type: ignore[arg-type]
        assert g.verdict is PromotionVerdict.BASELINE_RETAINED
        assert g.reasons


def test_dm_degenerate_raises() -> None:
    with pytest.raises(NumericalError):
        diebold_mariano([1.0, 1.0, 1.0], [2.0, 2.0, 2.0], h=1)


# ---------------------------------------------------------------- drift
def test_psi_fixture() -> None:
    r = psi_from_shares([0.25] * 4, [0.10, 0.20, 0.30, 0.40])
    assert r.value == pytest.approx(0.2282, abs=5e-5)
    assert r.status == "watch"
    assert r.epsilon_applied is False


def test_psi_zero_bin_epsilon_recorded() -> None:
    r = psi_from_shares([0.5, 0.5, 0.0], [0.4, 0.4, 0.2])
    assert r.epsilon_applied is True
    assert np.isfinite(r.value)


def test_psi_from_samples_identical_is_zero() -> None:
    x = np.linspace(0, 1, 500)
    assert psi(x, x).value == pytest.approx(0.0, abs=1e-12)


def test_rolling_coverage_monitor() -> None:
    lower = [-1.0] * 30
    upper = [1.0] * 30
    y = [0.0] * 20 + [5.0] * 10  # last 24: 14 in, 10 out → 58 %
    m = rolling_coverage_monitor(lower, upper, y, nominal=0.8, horizon_months=1)
    assert m.window == 24
    assert m.coverage == pytest.approx(14 / 24)
    assert m.alarm is True
    m6 = rolling_coverage_monitor([-1.0] * 40, [1.0] * 40, [0.0] * 40, nominal=0.8, horizon_months=6)
    assert m6.window == 36
