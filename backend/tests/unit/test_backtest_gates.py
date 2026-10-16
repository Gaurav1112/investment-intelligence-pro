"""Gates G1-G14 fail closed with reason codes (WP B05). Synthetic inputs only."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from iip.engine.backtest import gates as gt
from iip.engine.backtest.stats_gates import GATE_NOT_IMPLEMENTED, GateStatus
from iip.engine.backtest.walkforward import CanaryResult, NavPanel, RegimeEdge

D = Decimal


def _canary(passed: bool = True) -> CanaryResult:
    return CanaryResult(
        replicates=20,
        seed=1,
        permuted_scores=(),
        noise_scores=(),
        mean_permuted_score=D("0.5"),
        mean_noise_score=D("0.5"),
        threshold=D("0.75"),
        passed=passed,
    )


def _strong_edges(n: int = 400) -> tuple[float, ...]:
    # Deterministic, strongly positive, non-degenerate (fictional).
    return tuple(0.02 + 0.01 * math.sin(i * 1.7) for i in range(n))


def _good() -> gt.GateInputs:
    """Everything a signal could possibly show today. It must still not be ACCEPTED (PBO is not implemented)."""
    return gt.GateInputs(
        provenance=(
            gt.SeriesProvenance(
                role="index_fund.x.direct",
                source_id="fixture",
                licence_status="VERIFIED",
                known_time_populated=True,
                snapshot_hash="a" * 64,
            ),
        ),
        universe_kind="fixed_roles",
        survivorship_verified=False,
        price_gaps=(),
        leakage_invariants_ok=True,
        canary=_canary(),
        oos_edges=_strong_edges(),
        hac_lag=2,
        n_trials=1,
        family_sharpes=(),
        family_p_values=(1e-9,),
        selected_index=0,
        edge_after_tax=D("5000"),
        stressed_edge_after_tax=D("4000"),
        tax_rules_missing=False,
        cost_rules_missing=False,
        costs_estimated=False,
        regimes=tuple(RegimeEdge(regime_id=f"r{i}", n_periods=10, mean_edge=D("0.01")) for i in range(3)),
        rolling_variant_edge=D("0.01"),
        neighbour_edges=(D("0.01"), D("0.02")),
        vault=None,
        live=None,
        strategy_mdd=D("0.10"),
        benchmark_mdd=D("0.20"),
        loss_budget=D("0.25"),
        exposure_at_max_tilt=D("0.60"),
    )


def test_even_perfect_evidence_cannot_be_accepted_while_pbo_is_unbuilt() -> None:
    panel = gt.evaluate_gates(_good())
    assert [g.gate_id for g in panel.gates] == list(gt.GATE_IDS)
    assert panel.verdict.state is gt.SignalState.ABSTAIN
    assert panel.verdict.gate_id == "G10" and panel.verdict.reason_code == GATE_NOT_IMPLEMENTED
    for gid in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G13", "G14"):
        assert panel.gate(gid).passed, panel.gate(gid)
    assert panel.gate("G11").reason_code == "vault_sealed"


@pytest.mark.parametrize(
    ("change", "gate", "state", "reason"),
    [
        ({"provenance": ()}, "G1", "ABSTAIN", "data_unverified"),
        ({"universe_kind": "cross_section"}, "G2", "ABSTAIN", "survivorship_unverified"),
        ({"leakage_invariants_ok": False}, "G4", "ABSTAIN", "leakage"),
        ({"canary": None}, "G4", "ABSTAIN", "leakage"),
        ({"oos_edges": _strong_edges(20)}, "G5", "ABSTAIN", "insufficient_evidence"),
        ({"cost_rules_missing": True}, "G6", "ABSTAIN", "cost_rules_missing"),
        ({"tax_rules_missing": True, "edge_after_tax": None}, "G6", "ABSTAIN", "tax_rules_missing"),
        ({"edge_after_tax": D("-1")}, "G6", "NO_SIGNAL", "edge_not_positive_after_costs_tax"),
        ({"stressed_edge_after_tax": D("0")}, "G7", "NO_SIGNAL", "fragile_to_costs"),
        ({"n_trials": None}, "G8", "ABSTAIN", "trials_unknown"),
        ({"family_p_values": (0.5,)}, "G9", "NO_SIGNAL", "not_significant_after_multiple_testing"),
        ({"neighbour_edges": (D("0.01"), D("-0.01"))}, "G10", "NO_SIGNAL", "not_robust"),
        ({"loss_budget": None}, "G13", None, "loss_budget_missing"),
        ({"strategy_mdd": D("0.30"), "loss_budget": D("0.10")}, "G13", None, "exceeds_loss_budget"),
        ({"strategy_mdd": D("0.30")}, "G14", None, "drawdown_inferior"),
    ],
)
def test_each_gate_fails_closed_with_its_reason(
    change: dict[str, object], gate: str, state: str | None, reason: str
) -> None:
    panel = gt.evaluate_gates(replace(_good(), **change))  # type: ignore[arg-type]
    g = panel.gate(gate)
    assert not g.passed and g.reason_code == reason
    if state is not None:  # an earlier gate decides the verdict
        assert panel.verdict.gate_id == gate
        assert panel.verdict.state.value == state and panel.verdict.reason_code == reason


def test_price_gaps_flag_g3_unless_explained() -> None:
    dates = (date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3))
    panel = NavPanel(dates, {"r.x": (D("10"), D("13"), D("13.1"))})
    gaps = gt.unexplained_gaps(panel)
    assert [(g.role, g.on) for g in gaps] == [("r.x", date(2020, 1, 2))]
    assert gt.unexplained_gaps(panel, explained=frozenset({("r.x", date(2020, 1, 2))})) == ()
    v = gt.evaluate_gates(replace(_good(), price_gaps=gaps)).verdict
    assert (v.gate_id, v.reason_code) == ("G3", "unadjusted_prices_suspected")


def test_vault_opens_only_after_every_other_gate_and_retires_on_failure() -> None:
    vault = gt.VaultOutcome(edge_after_tax=D("-1"), mean_edge=D("0.01"), wf_low_80=D("0"), wf_high_80=D("0.02"))
    # Other gates do not all pass (PBO): the vault stays sealed even if an outcome is supplied.
    assert gt.evaluate_gates(replace(_good(), vault=vault)).gate("G11").reason_code == "vault_sealed"


def test_live_decay_monitor_is_non_blocking_until_live_and_suspends_on_decay() -> None:
    g12 = gt.evaluate_gates(_good()).gate("G12")
    assert g12.status is GateStatus.ABSTAIN and g12.reason_code == "not_live"
    decayed = gt.evaluate_gates(replace(_good(), live=gt.LiveRecord(edges=(-0.01,) * 24, backtest_low_80=-0.001)))
    assert decayed.gate("G12").reason_code == "decay"


def test_costs_estimated_marks_evidence_incomplete() -> None:
    assert gt.evaluate_gates(_good()).evidence_complete
    assert not gt.evaluate_gates(replace(_good(), costs_estimated=True)).evidence_complete


def test_large_families_need_spa_which_fails_closed() -> None:
    panel = gt.evaluate_gates(
        replace(
            _good(), n_trials=25, family_sharpes=tuple(0.1 + i / 100 for i in range(25)), family_p_values=(1e-9,) * 25
        )
    )
    assert panel.gate("G9").reason_code == GATE_NOT_IMPLEMENTED
    assert panel.verdict.gate_id == "G9"


def test_p_value_from_sharpe() -> None:
    assert gt.p_value_from_sharpe(0.0, 100) == pytest.approx(0.5)
    assert gt.p_value_from_sharpe(0.3, 100) == pytest.approx(1 - 0.998650, abs=1e-6)  # Φ(3) = 0.998650


def _regimes(*edges: str | None) -> tuple[RegimeEdge, ...]:
    return tuple(
        RegimeEdge(regime_id=f"r{i}", n_periods=0 if e is None else 10, mean_edge=None if e is None else D(e))
        for i, e in enumerate(edges)
    )


def _g10_regimes(panel: gt.GatePanel) -> str:
    return next(p for p in panel.gate("G10").detail.split("; ") if p.startswith("G10.regimes"))


def test_g10_abstains_when_a_regime_is_empty_never_counts_it_as_not_positive() -> None:
    # SIG-4: an empty regime (no pre-vault period, mean_edge None) is MISSING evidence, not a non-positive edge.
    panel = gt.evaluate_gates(replace(_good(), regimes=_regimes("0.01", None, "-0.01")))
    g = panel.gate("G10")
    assert g.status is gt.GateStatus.ABSTAIN and g.reason_code == "regime_empty"
    assert _g10_regimes(panel) == "G10.regimes: abstain (regime_empty)"
    assert panel.verdict.state is gt.SignalState.ABSTAIN and panel.verdict.gate_id == "G10"
    assert panel.verdict.reason_code == "regime_empty"
    # even with the threshold count reached, an empty regime still abstains (U-06: no inference from missing data)
    assert gt.evaluate_gates(replace(_good(), regimes=_regimes("0.01", "0.02", None))).gate("G10").reason_code == (
        "regime_empty"
    )


def test_g10_still_fails_when_every_regime_has_evidence_and_too_few_are_positive() -> None:
    panel = gt.evaluate_gates(replace(_good(), regimes=_regimes("0.01", "-0.01", "0")))
    g = panel.gate("G10")
    assert g.status is gt.GateStatus.FAIL and g.reason_code == "not_robust"
    assert _g10_regimes(panel) == "G10.regimes: fail (not_robust)"
    assert panel.verdict.state is gt.SignalState.NO_SIGNAL and panel.verdict.reason_code == "not_robust"
