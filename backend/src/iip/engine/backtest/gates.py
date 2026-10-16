"""Evidence gates G1–G14 for a pre-registered signal (research-backtest-method.md §10; design-risk-first.md §6.2).

Every gate **fails closed**: a missing input, an unbuilt check or a degenerate statistic yields ABSTAIN with a reason
code, never PASS. The verdict is the first gate, in order G1 → G14, that does not pass, mapped to the signal state:

* ABSTAIN from any gate → ``ABSTAIN(<reason>)``;
* FAIL of G6, G7, G9, G10, G13 or G14 → ``NO_SIGNAL(<reason>)``;
* FAIL of G11 (vault) → ``RETIRED(vault_fail)``; FAIL of G12 (live decay) → ``SUSPENDED(decay)``.

G11 is evaluated only once G1–G10, G13 and G14 pass (the runner opens the vault then and never otherwise); until then
it abstains with ``vault_sealed``. G12 monitors a signal *after* acceptance: without a live record it reports
``not_live`` and does not block (it can only ever demote). PBO/CSCV (G10) and Hansen SPA (G9, families > 20) are not
implemented and return ``gate_not_implemented`` (PLAN §5.1 rule 7), so today no rule can reach ACCEPTED: intended.

Thresholds are the user-kept values (U-06): DSR ≥ 0.95, HAC t ≥ 3, Holm α 0.05, ≥ 30 OOS periods and ≥ MinTRL,
G3 gap bounds +25 % / −20 % per observation. ``costs_estimated`` never blocks but marks the evidence incomplete
(design-evidence-first.md §6.2: the state is capped at "evidence incomplete").
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from statistics import NormalDist

from iip.engine.backtest.stats_gates import (
    GateResult,
    GateStatus,
    dsr_gate,
    hac_t_gate,
    holm_gate,
    mintrl_gate,
    pbo_cscv_gate,
    sharpe_moments,
)
from iip.engine.backtest.walkforward import CanaryResult, NavPanel, RegimeEdge
from iip.engine.errors import InvalidInput, NumericalError
from iip.engine.money import ONE, ZERO, D, engine_context

__all__ = [
    "BLOCKED",
    "G3_MAX_DOWN",
    "G3_MAX_UP",
    "GATE_IDS",
    "GateInputs",
    "GatePanel",
    "LiveRecord",
    "PriceGap",
    "SeriesProvenance",
    "SignalState",
    "VaultOutcome",
    "Verdict",
    "evaluate_gates",
    "p_value_from_sharpe",
    "unexplained_gaps",
]

FORMULA_ID = "BT-GATES@1"
GATE_IDS = tuple(f"G{i}" for i in range(1, 15))
BLOCKED = "BLOCKED"
G3_MAX_UP = Decimal("0.25")
G3_MAX_DOWN = Decimal("-0.20")
MIN_REGIMES_POSITIVE = 2
LIVE_WINDOW = 24

_N = NormalDist()


class SignalState(StrEnum):
    PRE_REGISTERED = "PRE_REGISTERED"
    ABSTAIN = "ABSTAIN"
    NO_SIGNAL = "NO_SIGNAL"
    ACCEPTED = "ACCEPTED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


_FAIL_STATE: Mapping[str, SignalState] = {
    "G6": SignalState.NO_SIGNAL,
    "G7": SignalState.NO_SIGNAL,
    "G9": SignalState.NO_SIGNAL,
    "G10": SignalState.NO_SIGNAL,
    "G11": SignalState.RETIRED,
    "G12": SignalState.SUSPENDED,
    "G13": SignalState.NO_SIGNAL,
    "G14": SignalState.NO_SIGNAL,
}


# ================================================================================================ inputs


@dataclass(frozen=True, kw_only=True)
class SeriesProvenance:
    role: str
    source_id: str
    licence_status: str  # registry status: VERIFIED / NOT VERIFIED / REQUIRES CONFIGURATION / BLOCKED / UNKNOWN
    known_time_populated: bool
    snapshot_hash: str


@dataclass(frozen=True, kw_only=True)
class PriceGap:
    role: str
    on: date
    change: Decimal


@dataclass(frozen=True, kw_only=True)
class VaultOutcome:
    edge_after_tax: Decimal | None
    mean_edge: Decimal
    wf_low_80: Decimal
    wf_high_80: Decimal


@dataclass(frozen=True, kw_only=True)
class LiveRecord:
    edges: tuple[float, ...]
    backtest_low_80: float


@dataclass(frozen=True, kw_only=True)
class GateInputs:
    # G1-G4: data and pipeline
    provenance: tuple[SeriesProvenance, ...]
    universe_kind: str  # 'fixed_roles' | 'cross_section'
    survivorship_verified: bool
    price_gaps: tuple[PriceGap, ...]
    leakage_invariants_ok: bool
    canary: CanaryResult | None
    # G5, G9: statistics on the OOS edge series
    oos_edges: tuple[float, ...]
    hac_lag: int
    # G8, G9: trial registry
    n_trials: int | None
    family_sharpes: tuple[float, ...]
    family_p_values: tuple[float, ...]
    selected_index: int
    # G6, G7: after costs and tax (conservative bound)
    edge_after_tax: Decimal | None
    stressed_edge_after_tax: Decimal | None
    tax_rules_missing: bool
    cost_rules_missing: bool
    costs_estimated: bool
    # G10
    regimes: tuple[RegimeEdge, ...]
    rolling_variant_edge: Decimal | None
    neighbour_edges: tuple[Decimal, ...] | None
    # G11, G12
    vault: VaultOutcome | None
    live: LiveRecord | None
    # G13, G14
    strategy_mdd: Decimal
    benchmark_mdd: Decimal
    loss_budget: Decimal | None  # L3 budget as a fraction of the bucket (user decision U-02)
    exposure_at_max_tilt: Decimal | None  # equity share of the bucket at the signal's maximum tilt


@dataclass(frozen=True, kw_only=True)
class Verdict:
    state: SignalState
    reason_code: str | None
    gate_id: str | None
    detail: str


@dataclass(frozen=True, kw_only=True)
class GatePanel:
    formula_id: str
    gates: tuple[GateResult, ...]
    verdict: Verdict
    evidence_complete: bool  # False when any cost or tax row is estimated / not verified

    def gate(self, gate_id: str) -> GateResult:
        for g in self.gates:
            if g.gate_id == gate_id:
                return g
        raise KeyError(gate_id)


# ================================================================================================ helpers


def _pass(gid: str, value: float | None = None, threshold: float | None = None, detail: str = "") -> GateResult:
    return GateResult(gid, GateStatus.PASS, True, None, value, threshold, detail)


def _abstain(gid: str, reason: str, detail: str = "", value: float | None = None) -> GateResult:
    return GateResult(gid, GateStatus.ABSTAIN, False, reason, value, None, detail)


def _fail(gid: str, reason: str, detail: str = "", value: float | None = None, thr: float | None = None) -> GateResult:
    return GateResult(gid, GateStatus.FAIL, False, reason, value, thr, detail)


def _as(gid: str, r: GateResult, detail: str | None = None) -> GateResult:
    return GateResult(gid, r.status, r.passed, r.reason_code, r.value, r.threshold, detail or r.detail)


def _combine(gid: str, parts: Sequence[GateResult], fail_reason: str) -> GateResult:
    """FAIL if any part fails, else ABSTAIN if any abstains (first reason), else PASS. Detail lists every part."""
    detail = "; ".join(
        f"{p.gate_id}: {p.status.value}" + (f" ({p.reason_code})" if p.reason_code else "") for p in parts
    )
    if any(p.status is GateStatus.FAIL for p in parts):
        return _fail(gid, fail_reason, detail)
    for p in parts:
        if p.status is GateStatus.ABSTAIN:
            return _abstain(gid, p.reason_code or "abstain", detail)
    return _pass(gid, detail=detail)


def p_value_from_sharpe(sharpe: float, n_obs: int) -> float:
    """One-sided p of a per-period Sharpe ratio under i.i.d. returns: ``1 − Φ(SR·√T)`` (formula stats.p_sr@1)."""
    if n_obs < 2 or not math.isfinite(sharpe):
        raise InvalidInput("need a finite Sharpe ratio and n_obs ≥ 2")
    return 1.0 - _N.cdf(sharpe * math.sqrt(n_obs))


def unexplained_gaps(
    panel: NavPanel,
    *,
    explained: frozenset[tuple[str, date]] = frozenset(),
    max_up: Decimal = G3_MAX_UP,
    max_down: Decimal = G3_MAX_DOWN,
) -> tuple[PriceGap, ...]:
    """G3 input: observation-to-observation moves above ``max_up`` or below ``max_down`` without a logged event."""
    out: list[PriceGap] = []
    with engine_context():
        for role in sorted(panel.navs):
            xs = panel.navs[role]
            for i in range(1, len(xs)):
                ch = xs[i] / xs[i - 1] - ONE
                if (ch > max_up or ch < max_down) and (role, panel.dates[i]) not in explained:
                    out.append(PriceGap(role=role, on=panel.dates[i], change=ch))
    return tuple(out)


# ================================================================================================ gates


def _g1(inp: GateInputs) -> GateResult:
    if not inp.provenance:
        return _abstain("G1", "data_unverified", "no provenance records")
    bad = [
        p.role
        for p in inp.provenance
        if not p.source_id
        or not p.snapshot_hash
        or not p.known_time_populated
        or p.licence_status in (BLOCKED, "UNKNOWN", "")
    ]
    if bad:
        return _abstain("G1", "data_unverified", f"provenance incomplete or blocked for {sorted(set(bad))}")
    return _pass("G1", detail=f"{len(inp.provenance)} series with source, licence status, known_time and hash")


def _g2(inp: GateInputs) -> GateResult:
    if inp.universe_kind == "fixed_roles":
        return _pass("G2", detail="fixed single-instrument roles (no cross-sectional selection)")
    if inp.universe_kind == "cross_section" and inp.survivorship_verified:
        return _pass("G2", detail="cross-sectional universe verified survivorship-free")
    return _abstain("G2", "survivorship_unverified", f"universe kind {inp.universe_kind!r}")


def _g3(inp: GateInputs) -> GateResult:
    if inp.price_gaps:
        first = inp.price_gaps[0]
        return _abstain(
            "G3",
            "unadjusted_prices_suspected",
            f"{len(inp.price_gaps)} unexplained gap(s); first {first.role} {first.on} change {first.change:.4f}",
        )
    return _pass("G3", detail=f"no move above {G3_MAX_UP} or below {G3_MAX_DOWN} without a logged event")


def _g4(inp: GateInputs) -> GateResult:
    if not inp.leakage_invariants_ok:
        return _abstain("G4", "leakage", "a §4.2 timeline invariant failed")
    if inp.canary is None:
        return _abstain("G4", "leakage", "shuffle canary not run")
    c = inp.canary
    detail = (
        f"canary mean Φ(HAC t) permuted {c.mean_permuted_score}, noise {c.mean_noise_score} vs ≤ {c.threshold} "
        f"({c.replicates} replicates, seed {c.seed})"
    )
    if not c.passed:
        return _abstain("G4", "leakage", detail)
    return _pass("G4", detail=detail)


def _moments(edges: Sequence[float]) -> tuple[float, float, float] | None:
    try:
        m = sharpe_moments(edges)
    except (InvalidInput, NumericalError):
        return None
    return m.sharpe, m.skewness, m.kurtosis


def _g5(inp: GateInputs) -> GateResult:
    mom = _moments(inp.oos_edges)
    if mom is None:
        return _abstain("G5", "insufficient_evidence", f"has {len(inp.oos_edges)} periods; statistics degenerate")
    sr, sk, ku = mom
    try:
        return _as(
            "G5", mintrl_gate(n_oos=len(inp.oos_edges), sharpe=sr, benchmark_sharpe=0.0, skewness=sk, kurtosis=ku)
        )
    except (InvalidInput, NumericalError) as exc:
        return _abstain("G5", "insufficient_evidence", str(exc))


def _g6(inp: GateInputs) -> GateResult:
    if inp.cost_rules_missing:
        return _abstain("G6", "cost_rules_missing", "a cost row does not cover every trade date")
    if inp.tax_rules_missing or inp.edge_after_tax is None:
        return _abstain("G6", "tax_rules_missing", "a tax row does not cover every realisation")
    v = float(inp.edge_after_tax)
    if not inp.edge_after_tax > ZERO:
        return _fail("G6", "edge_not_positive_after_costs_tax", f"terminal edge ₹{inp.edge_after_tax}", v, 0.0)
    return _pass("G6", v, 0.0, f"terminal edge ₹{inp.edge_after_tax} (liquidated, exemption used, highest slab)")


def _g7(inp: GateInputs) -> GateResult:
    if inp.cost_rules_missing:
        return _abstain("G7", "cost_rules_missing")
    if inp.tax_rules_missing or inp.stressed_edge_after_tax is None:
        return _abstain("G7", "tax_rules_missing")
    v = float(inp.stressed_edge_after_tax)
    if not inp.stressed_edge_after_tax > ZERO:
        return _fail("G7", "fragile_to_costs", f"stressed edge ₹{inp.stressed_edge_after_tax}", v, 0.0)
    return _pass("G7", v, 0.0, f"edge ₹{inp.stressed_edge_after_tax} at slippage ×2 and costs ×1.5")


def _g8(inp: GateInputs) -> GateResult:
    if inp.n_trials is None or inp.n_trials < 1:
        return _abstain("G8", "trials_unknown", "family trial count N is not known")
    return _pass("G8", float(inp.n_trials), None, f"N = {inp.n_trials} (raw; N_eff not computed)")


def _variance(xs: Sequence[float]) -> float:
    mean = math.fsum(xs) / len(xs)
    return math.fsum((x - mean) ** 2 for x in xs) / len(xs)


def _g9(inp: GateInputs) -> GateResult:
    mom = _moments(inp.oos_edges)
    if mom is None or inp.n_trials is None or inp.n_trials < 1:
        return _abstain("G9", "insufficient_evidence", "edge statistics or trial count unavailable")
    sr, sk, ku = mom
    n = inp.n_trials
    if n > 1 and len(inp.family_sharpes) < 2:
        return _abstain("G9", "trials_unknown", "family Sharpe dispersion unknown")
    var = _variance(inp.family_sharpes) if n > 1 else 0.0
    parts: list[GateResult] = []
    try:
        parts.append(
            dsr_gate(sharpe=sr, n_obs=len(inp.oos_edges), skewness=sk, kurtosis=ku, n_trials=n, sharpe_variance=var)
        )
    except (InvalidInput, NumericalError) as exc:
        parts.append(_abstain("G9.dsr", "degenerate_statistics", str(exc)))
    try:
        if not inp.family_p_values:
            parts.append(_abstain("G9.multiple_testing", "trials_unknown", "no family p-values"))
        else:
            parts.append(holm_gate(inp.family_p_values, selected=inp.selected_index))
    except InvalidInput as exc:
        parts.append(_abstain("G9.multiple_testing", "trials_unknown", str(exc)))
    try:
        parts.append(hac_t_gate(inp.oos_edges, lag=inp.hac_lag))
    except (InvalidInput, NumericalError) as exc:
        parts.append(_abstain("G9.hac_t", "degenerate_statistics", str(exc)))
    return _combine("G9", parts, "not_significant_after_multiple_testing")


def _g10(inp: GateInputs) -> GateResult:
    parts: list[GateResult] = []
    # An empty regime (no pre-vault period: mean_edge None) is missing evidence, never a non-positive edge, so it
    # abstains (U-06: the threshold is unchanged; only missing data is no longer read as a failure).
    empty = [r.regime_id for r in inp.regimes if r.mean_edge is None or r.n_periods == 0]
    positive = sum(1 for r in inp.regimes if r.mean_edge is not None and r.mean_edge > ZERO)
    if len(inp.regimes) < 3:
        parts.append(_abstain("G10.regimes", "regimes_undefined", f"{len(inp.regimes)} regimes declared"))
    elif empty:
        parts.append(_abstain("G10.regimes", "regime_empty", f"no pre-vault period in regime(s) {', '.join(empty)}"))
    elif positive >= MIN_REGIMES_POSITIVE:
        parts.append(_pass("G10.regimes", float(positive), 2.0))
    else:
        parts.append(_fail("G10.regimes", "not_robust", f"{positive} of {len(inp.regimes)} regimes positive"))
    if inp.rolling_variant_edge is None:
        parts.append(_abstain("G10.rolling", "rolling_variant_not_run"))
    elif inp.rolling_variant_edge > ZERO:
        parts.append(_pass("G10.rolling"))
    else:
        parts.append(_fail("G10.rolling", "not_robust"))
    if not inp.neighbour_edges:
        parts.append(_abstain("G10.neighbours", "neighbours_not_run"))
    elif all(e > ZERO for e in inp.neighbour_edges):
        parts.append(_pass("G10.neighbours"))
    else:
        parts.append(_fail("G10.neighbours", "not_robust", "a neighbouring parameter value is not positive"))
    parts.append(pbo_cscv_gate())
    return _combine("G10", parts, "not_robust")


def _g11(inp: GateInputs, others_pass: bool) -> GateResult:
    if inp.vault is None or not others_pass:
        return _abstain("G11", "vault_sealed", "the vault opens once, only after every other blocking gate passes")
    v = inp.vault
    if v.edge_after_tax is None:
        return _abstain("G11", "tax_rules_missing")
    inside = v.wf_low_80 <= v.mean_edge <= v.wf_high_80
    if v.edge_after_tax > ZERO and inside:
        return _pass("G11", detail=f"vault edge ₹{v.edge_after_tax}, mean {v.mean_edge} inside the 80 % range")
    return _fail("G11", "vault_fail", f"vault edge ₹{v.edge_after_tax}; mean {v.mean_edge} inside range: {inside}")


def _g12(inp: GateInputs) -> GateResult:
    if inp.live is None:
        return _abstain("G12", "not_live", "monitor starts after acceptance")
    xs = inp.live.edges[-LIVE_WINDOW:]
    if len(xs) < LIVE_WINDOW:
        return _abstain("G12", "live_record_short", f"{len(inp.live.edges)} of {LIVE_WINDOW} live periods")
    mean = math.fsum(xs) / len(xs)
    if mean < 0.0 and mean < inp.live.backtest_low_80:
        return _fail("G12", "decay", f"rolling {LIVE_WINDOW}-period edge {mean:.6f}", mean, inp.live.backtest_low_80)
    return _pass("G12", mean, inp.live.backtest_low_80)


def _g13(inp: GateInputs) -> GateResult:
    if inp.loss_budget is None or inp.exposure_at_max_tilt is None:
        return _abstain("G13", "loss_budget_missing", "no per-goal loss budget recorded (U-02)")
    with engine_context():
        implied = D(inp.strategy_mdd) * D(inp.exposure_at_max_tilt)
    detail = f"strategy MDD {inp.strategy_mdd:.4f} × exposure {inp.exposure_at_max_tilt} = {implied:.4f}"
    if implied > inp.loss_budget:
        return _fail("G13", "exceeds_loss_budget", f"{detail} > budget {inp.loss_budget}")
    return _pass("G13", detail=f"{detail} ≤ budget {inp.loss_budget}")


def _g14(inp: GateInputs) -> GateResult:
    detail = f"strategy MDD {inp.strategy_mdd:.4f} vs benchmark {inp.benchmark_mdd:.4f} (+0 pp allowed)"
    if inp.strategy_mdd > inp.benchmark_mdd:
        return _fail("G14", "drawdown_inferior", detail)
    return _pass("G14", detail=detail)


def _non_blocking(g: GateResult) -> bool:
    return g.gate_id == "G12" and g.status is GateStatus.ABSTAIN


def evaluate_gates(inp: GateInputs) -> GatePanel:
    """Evaluate G1–G14 (all of them, for the gate panel) and derive the verdict from the first non-passing gate."""
    first = [_g1(inp), _g2(inp), _g3(inp), _g4(inp), _g5(inp), _g6(inp), _g7(inp), _g8(inp), _g9(inp), _g10(inp)]
    g12, g13, g14 = _g12(inp), _g13(inp), _g14(inp)
    others_pass = all(g.passed for g in (*first, g13, g14))
    gates = (*first, _g11(inp, others_pass), g12, g13, g14)
    verdict = Verdict(state=SignalState.ACCEPTED, reason_code=None, gate_id=None, detail="every gate passed")
    for g in gates:
        if g.passed or _non_blocking(g):
            continue
        state = (
            SignalState.ABSTAIN if g.status is GateStatus.ABSTAIN else _FAIL_STATE.get(g.gate_id, SignalState.ABSTAIN)
        )
        verdict = Verdict(state=state, reason_code=g.reason_code, gate_id=g.gate_id, detail=g.detail)
        break
    return GatePanel(formula_id=FORMULA_ID, gates=gates, verdict=verdict, evidence_complete=not inp.costs_estimated)
