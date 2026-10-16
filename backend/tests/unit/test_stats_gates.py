"""A18 — engine/backtest/stats_gates.py: DSR, multiple testing, HAC t, MinTRL and power.

Fixtures are the published worked examples recomputed in docs/research/wave1 (research-backtest-method.md §9.2–9.4,
verify-backtest-method.md BT-2/BT-9) plus hand-computed synthetic series. No market data.
"""

from __future__ import annotations

import ast
import math
import pathlib
from datetime import date

import pytest

from iip.engine.backtest import stats_gates as sg
from iip.engine.errors import InvalidInput, NumericalError

SRC = pathlib.Path(sg.__file__)

# DSR-1 (Bailey & López de Prado 2014 worked example): annual SR 2.5, 1,250 daily obs, V[SR_annual] = 0.5.
SR_DAILY = 2.5 / math.sqrt(250)
V_DAILY = 0.5 / 250


# ------------------------------------------------------------------------------------------------ purity


def test_module_uses_stdlib_normal_dist_and_no_scipy_or_numpy() -> None:
    tree = ast.parse(SRC.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "scipy" not in imported
    assert "numpy" not in imported
    assert "statistics" in imported


# ------------------------------------------------------------------------------------------------ DSR-1


def test_dsr1_n100_expected_max_and_dsr() -> None:
    sr0 = sg.expected_max_sharpe(n_trials=100, sharpe_variance=V_DAILY)
    assert sr0 == pytest.approx(0.113172, abs=5e-7)
    dsr = sg.deflated_sharpe_ratio(
        sharpe=SR_DAILY, n_obs=1250, skewness=-3.0, kurtosis=10.0, n_trials=100, sharpe_variance=V_DAILY
    )
    assert dsr.sr0 == pytest.approx(0.113172, abs=5e-7)
    assert round(dsr.dsr, 4) == 0.9004
    assert dsr.passes is False  # below 0.95 → rejected


def test_dsr1_n46_matches_paper_0_9505() -> None:
    dsr = sg.deflated_sharpe_ratio(
        sharpe=SR_DAILY, n_obs=1250, skewness=-3.0, kurtosis=10.0, n_trials=46, sharpe_variance=V_DAILY
    )
    assert dsr.sr0 == pytest.approx(0.100362, abs=5e-7)
    assert round(dsr.dsr, 4) == 0.9505
    assert dsr.passes is True


def test_dsr1_normal_returns_n88_matches_paper_0_9505() -> None:
    dsr = sg.deflated_sharpe_ratio(
        sharpe=SR_DAILY, n_obs=1250, skewness=0.0, kurtosis=3.0, n_trials=88, sharpe_variance=V_DAILY
    )
    assert round(dsr.dsr, 4) == 0.9505


def test_dsr_threshold_is_inclusive_at_0_95() -> None:
    assert sg.DSR_THRESHOLD == 0.95


def test_single_trial_has_no_deflation() -> None:
    assert sg.expected_max_sharpe(n_trials=1, sharpe_variance=V_DAILY) == 0.0
    dsr = sg.deflated_sharpe_ratio(sharpe=0.1, n_obs=500, skewness=0.0, kurtosis=3.0, n_trials=1, sharpe_variance=0.0)
    assert dsr.dsr == pytest.approx(sg.probabilistic_sharpe_ratio(0.1, 0.0, n_obs=500, skewness=0.0, kurtosis=3.0))


def test_psr_rejects_bad_inputs() -> None:
    with pytest.raises(InvalidInput):
        sg.probabilistic_sharpe_ratio(0.1, 0.0, n_obs=1, skewness=0.0, kurtosis=3.0)
    with pytest.raises(InvalidInput):
        sg.expected_max_sharpe(n_trials=0, sharpe_variance=0.1)
    with pytest.raises(InvalidInput):
        sg.expected_max_sharpe(n_trials=10, sharpe_variance=-0.1)
    with pytest.raises(InvalidInput):
        sg.probabilistic_sharpe_ratio(float("nan"), 0.0, n_obs=100, skewness=0.0, kurtosis=3.0)


def test_psr_non_positive_variance_term_raises() -> None:
    # 1 − γ3·SR + (γ4 − 1)/4·SR² ≤ 0 is degenerate: refuse instead of returning a number.
    with pytest.raises(NumericalError):
        sg.probabilistic_sharpe_ratio(1.0, 0.0, n_obs=100, skewness=5.0, kurtosis=1.0)


# ------------------------------------------------------------------------------------------------ MT-1


@pytest.mark.parametrize(("n", "expected"), [(10, 0.4979), (100, 0.8002), (1000, 1.0294)])
def test_mt1_expected_best_annualised_sharpe_from_luck(n: int, expected: float) -> None:
    # Under H0 with T = 120 monthly obs, V[SR_monthly] ≈ 1/T; annualise with √12.
    best_monthly = sg.expected_max_sharpe(n_trials=n, sharpe_variance=1.0 / 120)
    assert round(best_monthly * math.sqrt(12), 4) == expected


# ------------------------------------------------------------------------------------------------ MT-2


def test_mt2_holm_rejects_two_bonferroni_one() -> None:
    p = [0.004, 0.011, 0.019, 0.030, 0.200]
    holm = sg.holm(p, alpha=0.05)
    assert holm.rejected == (True, True, False, False, False)
    assert holm.n_rejected == 2
    assert holm.adjusted_p == pytest.approx((0.02, 0.044, 0.057, 0.06, 0.2))
    assert sg.bonferroni(p, alpha=0.05).n_rejected == 1


def test_holm_preserves_input_order_and_is_monotone() -> None:
    p = [0.2, 0.004, 0.03, 0.011, 0.019]
    holm = sg.holm(p, alpha=0.05)
    assert holm.rejected == (False, True, False, True, False)
    assert holm.adjusted_p[1] == pytest.approx(0.02)
    assert holm.adjusted_p[3] == pytest.approx(0.044)


def test_holm_adjusted_p_capped_at_one_and_rejects_bad_p() -> None:
    assert sg.holm([0.5, 0.9], alpha=0.05).adjusted_p == pytest.approx((1.0, 1.0))
    with pytest.raises(InvalidInput):
        sg.holm([], alpha=0.05)
    with pytest.raises(InvalidInput):
        sg.holm([1.2], alpha=0.05)
    with pytest.raises(InvalidInput):
        sg.holm([0.01], alpha=0.0)


# ------------------------------------------------------------------------------------------------ MT-3 / MinTRL


def test_mt3_mintrl_normal_sr_0_5() -> None:
    sr = 0.5 / math.sqrt(12)
    assert sg.min_track_record_length(sr, 0.0, skewness=0.0, kurtosis=3.0) == pytest.approx(132.22, abs=0.005)


def test_mt3_mintrl_fat_tails() -> None:
    sr = 0.5 / math.sqrt(12)
    assert sg.min_track_record_length(sr, 0.0, skewness=-1.0, kurtosis=6.0) == pytest.approx(152.99, abs=0.005)


def test_mt3_mintrl_sr_1() -> None:
    sr = 1.0 / math.sqrt(12)
    assert sg.min_track_record_length(sr, 0.0, skewness=0.0, kurtosis=3.0) == pytest.approx(34.82, abs=0.005)


def test_mintrl_undefined_when_sharpe_not_above_benchmark() -> None:
    with pytest.raises(InvalidInput):
        sg.min_track_record_length(0.0, 0.0, skewness=0.0, kurtosis=3.0)


# ------------------------------------------------------------------------------------------------ 298-month power


def test_power_298_month_case_unit_variance_approximation() -> None:
    # verify-backtest-method.md BT-9: T ≈ 1 + ((1.645 + 0.842)/0.1443)² ≈ 298 months (V[SR] ≈ 1/T).
    sr = 0.5 / math.sqrt(12)
    t = sg.power_length(sr, 0.0, power=0.80, skewness=0.0, kurtosis=3.0, moment_adjusted=False)
    # exact z-values: 1 + ((1.644854 + 0.841621)/0.144338)² = 297.763 → 298 whole months
    assert t == pytest.approx(297.763, abs=0.001)
    assert math.ceil(t) == 298


def test_power_length_moment_adjusted_is_longer_and_default() -> None:
    sr = 0.5 / math.sqrt(12)
    adjusted = sg.power_length(sr, 0.0, power=0.80, skewness=0.0, kurtosis=3.0)
    assert adjusted == pytest.approx(300.854, abs=0.001)  # 1 + 1.0104167 · 296.763
    assert adjusted > sg.power_length(sr, 0.0, power=0.80, skewness=0.0, kurtosis=3.0, moment_adjusted=False)


def test_power_length_at_50_percent_equals_mintrl() -> None:
    sr = 0.5 / math.sqrt(12)
    for skew, kurt in ((0.0, 3.0), (-1.0, 6.0)):
        assert sg.power_length(sr, 0.0, power=0.5, skewness=skew, kurtosis=kurt) == pytest.approx(
            sg.min_track_record_length(sr, 0.0, skewness=skew, kurtosis=kurt)
        )


def test_power_length_rejects_bad_power() -> None:
    with pytest.raises(InvalidInput):
        sg.power_length(0.1, 0.0, power=1.0, skewness=0.0, kurtosis=3.0)


# ------------------------------------------------------------------------------------------------ earliest review


def test_earliest_review_uses_mintrl_when_longer_than_30() -> None:
    sr = 0.5 / math.sqrt(12)
    review = sg.earliest_review(date(2026, 10, 16), sr, 0.0, skewness=0.0, kurtosis=3.0)
    # MinTRL 132.22 → 133 whole months (ceiling) → 2026-10 + 133 months = 2037-11.
    assert review.months == 133
    assert review.review_date == date(2037, 11, 16)
    assert review.min_trl == pytest.approx(132.22, abs=0.005)


def test_earliest_review_floor_of_30_months() -> None:
    sr = 1.5 / math.sqrt(12)  # MinTRL well under 30
    review = sg.earliest_review(date(2026, 1, 31), sr, 0.0, skewness=0.0, kurtosis=3.0)
    assert review.min_trl < 30
    assert review.months == 30
    assert review.review_date == date(2028, 7, 31)


def test_earliest_review_clamps_to_month_end() -> None:
    sr = 1.5 / math.sqrt(12)
    review = sg.earliest_review(date(2026, 8, 31), sr, 0.0, skewness=0.0, kurtosis=3.0)
    assert review.review_date == date(2029, 2, 28)


# ------------------------------------------------------------------------------------------------ HAC t


def test_hac_t_lag0_hand_computed() -> None:
    # mean 2.5, γ0 = 1.25 (1/T), var(mean) = 1.25/4, t = 2.5/√0.3125
    r = sg.hac_t_stat([1.0, 2.0, 3.0, 4.0], lag=0)
    assert r.mean == pytest.approx(2.5)
    assert r.long_run_variance == pytest.approx(1.25)
    assert r.t_stat == pytest.approx(2.5 / math.sqrt(0.3125))


def test_hac_t_lag1_bartlett_hand_computed() -> None:
    # γ1 = 0.3125, Bartlett weight 1 − 1/2 = 0.5 → LRV = 1.25 + 2·0.5·0.3125 = 1.5625 → se = 0.625 → t = 4.0
    r = sg.hac_t_stat([1.0, 2.0, 3.0, 4.0], lag=1)
    assert r.long_run_variance == pytest.approx(1.5625)
    assert r.t_stat == pytest.approx(4.0)
    assert r.lag == 1
    assert r.n_obs == 4


def test_hac_t_gate_threshold_three() -> None:
    assert sg.HAC_T_THRESHOLD == 3.0
    assert sg.hac_t_stat([1.0, 2.0, 3.0, 4.0], lag=1).passes is True
    assert sg.hac_t_stat([1.0, -1.0, 1.2, -0.8, 0.9, -1.1], lag=1).passes is False


def test_hac_t_one_sided_p_value() -> None:
    r = sg.hac_t_stat([1.0, 2.0, 3.0, 4.0], lag=1)
    assert r.p_one_sided == pytest.approx(1.0 - sg.NormalDist().cdf(4.0))


def test_hac_t_rejects_bad_lag_and_degenerate_series() -> None:
    with pytest.raises(InvalidInput):
        sg.hac_t_stat([1.0, 2.0, 3.0], lag=3)
    with pytest.raises(InvalidInput):
        sg.hac_t_stat([1.0, 2.0, 3.0], lag=-1)
    with pytest.raises(InvalidInput):
        sg.hac_t_stat([1.0], lag=0)
    with pytest.raises(NumericalError):
        sg.hac_t_stat([2.0, 2.0, 2.0, 2.0], lag=1)


def test_newey_west_default_lag_rule() -> None:
    # floor(4 · (T/100)^(2/9))
    assert sg.newey_west_lag(100) == 4
    assert sg.newey_west_lag(120) == 4
    assert sg.newey_west_lag(298) == 5


# ------------------------------------------------------------------------------------------------ sample moments


def test_sharpe_moments_symmetric_series() -> None:
    m = sg.sharpe_moments([1.0, 2.0, 3.0, 4.0])
    assert m.mean == pytest.approx(2.5)
    assert m.sharpe == pytest.approx(2.5 / math.sqrt(1.25))
    assert m.skewness == pytest.approx(0.0)
    assert m.kurtosis == pytest.approx(1.64)  # population, non-excess
    assert m.n_obs == 4


# ------------------------------------------------------------------------------------------------ gates


def test_unbuilt_gates_fail_closed() -> None:
    for result in (sg.pbo_cscv_gate(), sg.spa_gate()):
        assert result.status is sg.GateStatus.ABSTAIN
        assert result.reason_code == "gate_not_implemented"
        assert result.passed is False
        assert result.value is None


def test_dsr_gate_wraps_result() -> None:
    fail = sg.dsr_gate(sharpe=SR_DAILY, n_obs=1250, skewness=-3.0, kurtosis=10.0, n_trials=100, sharpe_variance=V_DAILY)
    assert fail.status is sg.GateStatus.FAIL
    assert fail.passed is False
    assert fail.reason_code == "not_significant_after_multiple_testing"
    ok = sg.dsr_gate(sharpe=SR_DAILY, n_obs=1250, skewness=-3.0, kurtosis=10.0, n_trials=46, sharpe_variance=V_DAILY)
    assert ok.status is sg.GateStatus.PASS
    assert ok.passed is True
    assert ok.reason_code is None
    assert ok.threshold == 0.95


def test_hac_gate_and_holm_gate() -> None:
    assert sg.hac_t_gate([1.0, 2.0, 3.0, 4.0], lag=1).passed is True
    weak = sg.hac_t_gate([1.0, -1.0, 1.2, -0.8, 0.9, -1.1], lag=1)
    assert weak.status is sg.GateStatus.FAIL
    assert weak.reason_code == "hac_t_below_threshold"
    holm_ok = sg.holm_gate([0.004, 0.011, 0.019, 0.030, 0.200], selected=1, alpha=0.05)
    assert holm_ok.passed is True
    holm_bad = sg.holm_gate([0.004, 0.011, 0.019, 0.030, 0.200], selected=2, alpha=0.05)
    assert holm_bad.status is sg.GateStatus.FAIL


def test_holm_gate_abstains_for_large_families() -> None:
    # N > 20 → SPA is required, and SPA is not built: fail closed.
    r = sg.holm_gate([0.001] * 21, selected=0, alpha=0.05)
    assert r.status is sg.GateStatus.ABSTAIN
    assert r.reason_code == "gate_not_implemented"
    assert r.passed is False


def test_gate_status_abstain_never_passes() -> None:
    with pytest.raises(InvalidInput):
        sg.GateResult(
            gate_id="x", status=sg.GateStatus.ABSTAIN, passed=True, reason_code="r", value=None, threshold=None
        )
    with pytest.raises(InvalidInput):
        sg.GateResult(
            gate_id="x", status=sg.GateStatus.FAIL, passed=False, reason_code=None, value=None, threshold=None
        )


def test_mintrl_gate_requires_both_30_and_mintrl() -> None:
    sr = 0.5 / math.sqrt(12)
    short = sg.mintrl_gate(n_oos=126, sharpe=sr, benchmark_sharpe=0.0, skewness=0.0, kurtosis=3.0)
    assert short.status is sg.GateStatus.ABSTAIN
    assert short.reason_code == "insufficient_evidence"
    assert "has 126" in short.detail and "needs 133" in short.detail
    ok = sg.mintrl_gate(n_oos=133, sharpe=sr, benchmark_sharpe=0.0, skewness=0.0, kurtosis=3.0)
    assert ok.passed is True
    big = 2.0 / math.sqrt(12)
    floor = sg.mintrl_gate(n_oos=29, sharpe=big, benchmark_sharpe=0.0, skewness=0.0, kurtosis=3.0)
    assert floor.status is sg.GateStatus.ABSTAIN
    no_edge = sg.mintrl_gate(n_oos=500, sharpe=0.0, benchmark_sharpe=0.0, skewness=0.0, kurtosis=3.0)
    assert no_edge.status is sg.GateStatus.ABSTAIN
    assert no_edge.reason_code == "no_edge"
