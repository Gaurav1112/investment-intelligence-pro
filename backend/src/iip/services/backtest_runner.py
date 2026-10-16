"""Backtest runner for pre-registered signals: spec loading, trial logging, gates and evidence bundles (WP B05).

Where it runs: **the local CLI only** (``python -m iip.backtest_cli``). Hosted mode never runs a backtest; it may only
import an evidence bundle, which holds statistics, gate results and hashes and **no raw NAVs**
(design-judgement.md §2.2 item 16). Results are never written into the repository (the CLI refuses such paths).

Flow of :func:`run_backtest`:

1. the spec (``rules/signals/S-*@*.yaml``, role names only) is registered in ``signal_rules`` (idempotent; a changed
   spec under the same version is refused by the store);
2. every configuration about to be evaluated (the spec's parameters and each pre-registered neighbour) is appended to
   ``backtest_trials`` **before** it runs, so abandoned or crashed runs still count towards the family N (G8);
3. the walk-forward runs on pre-vault data, plus a cost-stressed rerun (G7), the neighbours (G10) and the shuffle
   canary (G4);
4. G1–G14 are evaluated (``engine/backtest/gates.py``); the vault is opened only if every other blocking gate passed;
5. one append-only ``backtest_runs`` row stores the manifest, gate panel, statistics and ``output_hash``.

Re-running a manifest (:func:`rerun_manifest`) with the same data and spec reproduces ``output_hash`` exactly
(ADR-0011 oracle): the manifest freezes the family snapshot it used, the seed and every version.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from iip.engine.backtest import gates as gt
from iip.engine.backtest import walkforward as wf
from iip.engine.backtest.ledger import CostBasisPolicy
from iip.engine.backtest.stats_gates import GateResult, earliest_review, power_length, sharpe_moments
from iip.engine.backtest.tax_lots import TaxRateTable
from iip.engine.determinism import CANONICAL_VERSION, canonical_json, content_hash
from iip.engine.errors import EngineError, InvalidInput
from iip.engine.money import ZERO, D, engine_context
from iip.store import ledger as lg

__all__ = [
    "DECAY_HAIRCUT",
    "FORBIDDEN_BUNDLE_KEYS",
    "SIGNALS_DIR",
    "BundleRejected",
    "EvidenceBundle",
    "FamilyTrial",
    "RunContext",
    "SignalSpec",
    "SpecError",
    "compute_evidence",
    "import_evidence_bundle",
    "load_registered_specs",
    "load_signal_spec",
    "rerun_manifest",
    "run_backtest",
    "verify_bundle",
]

SIGNALS_DIR = Path(__file__).resolve().parents[1] / "rules" / "signals"
SCHEMA_PATH = SIGNALS_DIR / "schema.yaml"
RUNNER_VERSION = "BT-RUNNER@1"
#: Any user-facing expected excess is the OOS edge × 0.5 (momentum report gate 7; design-judgement.md §2.2 item 12).
DECAY_HAIRCUT = Decimal("0.5")
_Q = Decimal("0.000001")
_SPEC_NAME = re.compile(r"^S-[A-Z]@[1-9][0-9]*\.yaml$")
#: Keys that would carry raw market data. A bundle containing any of them anywhere is refused (hosted-safe import).
FORBIDDEN_BUNDLE_KEYS = frozenset(
    {"nav", "navs", "price", "prices", "panel", "series", "values", "returns", "periods", "observations"}
)


class SpecError(ValueError):
    """A signal spec is malformed or not a valid pre-registration."""


class BundleRejected(ValueError):
    """An evidence bundle failed verification (hash mismatch, raw data, or malformed)."""


# ================================================================================================ spec model


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_Num = int | str


def _dec(v: Any, name: str) -> Decimal:
    if isinstance(v, bool) or isinstance(v, float):
        raise ValueError(f"{name} must be an int or a decimal string, not {type(v).__name__}")
    try:
        return D(v)
    except EngineError as exc:
        raise ValueError(f"{name}: {exc}") from exc


class _Role(_Strict):
    role: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    tax_class: Literal["EQUITY", "DEBT", "OTHER"]


class _RuleM(_Strict):
    kind: Literal["trend_sma", "abs_momentum", "dual_momentum", "drawdown_topup"]
    params: dict[str, _Num]
    slots: list[str]
    formula: str


class _BenchM(_Strict):
    kind: Literal["buy_and_hold", "equal_weight", "sip_schedule"]
    params: dict[str, _Num]
    slots: list[str]
    description: str


class _CapitalM(_Strict):
    initial_inr: str
    contribution_inr: str


class _FillM(_Strict):
    name: str
    nav_offset: int
    switch_cash_gap: int


class _WalkForwardM(_Strict):
    # No defaults (design-evidence-first.md §6.2): a missing lag/purge/embargo/fill_rule is a validation error.
    lag: int
    purge: int
    embargo: int
    fill_rule: _FillM
    hac_lag: int


class _VaultM(_Strict):
    fraction: str
    min_months: int


class _RegimeM(_Strict):
    id: str
    start: date | None
    end: date | None


class _StressM(_Strict):
    cost_multiplier: str
    slippage_multiplier: str


class _TiltM(_Strict):
    min: str
    max: str


class _EvidenceM(_Strict):
    doc: str
    section: str


class SignalSpec(_Strict):
    """A pre-registered signal spec (``rules/signals/schema.yaml``). Role names only; never a scheme or a result."""

    id: str = Field(pattern=r"^S-[A-Z]$")
    version: int = Field(ge=1)
    class_: Literal["S"] = Field(alias="class")
    family: str = Field(pattern=r"^[a-z_]+$")
    status: Literal["PRE_REGISTERED"]
    title: str
    universe_kind: Literal["fixed_roles", "cross_section"]
    roles: dict[str, _Role]
    rule: _RuleM
    benchmark: _BenchM
    observation: Literal["month_end_nav"]
    decision_every_months: int = Field(ge=1)
    horizon_months: int = Field(ge=1)
    capital: _CapitalM
    walk_forward: _WalkForwardM
    vault: _VaultM
    regimes: list[_RegimeM] = Field(min_length=3, max_length=3)
    neighbours: list[dict[str, _Num]]
    cost_stress: _StressM
    tilt_bounds: _TiltM
    variants_counted: int = Field(ge=1)
    post_publication_from: date | None
    expected_outcome: str
    evidence: list[_EvidenceM] = Field(min_length=1)
    gates: list[str]

    @field_validator("gates")
    @classmethod
    def _all_gates(cls, v: list[str]) -> list[str]:
        if tuple(v) != gt.GATE_IDS:
            raise ValueError(f"gates must be exactly {list(gt.GATE_IDS)} in order")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> SignalSpec:
        for slot in (*self.rule.slots, *self.benchmark.slots):
            if slot not in self.roles:
                raise ValueError(f"slot {slot!r} is not declared in roles")
        classes: dict[str, str] = {}
        for r in self.roles.values():
            if classes.setdefault(r.role, r.tax_class) != r.tax_class:
                raise ValueError(f"role {r.role} declared with two tax classes")
        _dec(self.capital.initial_inr, "capital.initial_inr")
        _dec(self.capital.contribution_inr, "capital.contribution_inr")
        _dec(self.vault.fraction, "vault.fraction")
        tmin, tmax = _dec(self.tilt_bounds.min, "tilt_bounds.min"), _dec(self.tilt_bounds.max, "tilt_bounds.max")
        if tmin > tmax or tmax > ZERO:
            raise ValueError("tilt_bounds: a research rule may only reduce equity (min ≤ max ≤ 0)")
        for n in self.neighbours:
            unknown = set(n) - set(self.rule.params)
            if unknown:
                raise ValueError(f"neighbour overrides unknown parameters {sorted(unknown)}")
        return self

    # ---------------------------------------------------------------------------------------------- engine views

    def role_keys(self) -> tuple[str, ...]:
        return tuple(sorted({r.role for r in self.roles.values()}))

    def tax_classes(self) -> dict[str, str]:
        return {r.role: r.tax_class for r in self.roles.values()}

    def _params(self, raw: Mapping[str, Any]) -> dict[str, Decimal | int]:
        return {k: (v if isinstance(v, int) else _dec(v, k)) for k, v in raw.items()}

    def strategy_rule(self, overrides: Mapping[str, Any] | None = None) -> wf.RuleSpec:
        params = {**self.rule.params, **(overrides or {})}
        return wf.RuleSpec(
            kind=self.rule.kind,
            params=self._params(params),
            slots={s: self.roles[s].role for s in self.rule.slots},
        )

    def benchmark_rule(self) -> wf.RuleSpec:
        return wf.RuleSpec(
            kind=self.benchmark.kind,
            params=self._params(self.benchmark.params),
            slots={s: self.roles[s].role for s in self.benchmark.slots},
        )

    def config(self) -> wf.WalkForwardConfig:
        w = self.walk_forward
        return wf.WalkForwardConfig(
            lag=w.lag,
            purge=w.purge,
            embargo=w.embargo,
            fill_rule=wf.FillRule(
                name=w.fill_rule.name, nav_offset=w.fill_rule.nav_offset, switch_cash_gap=w.fill_rule.switch_cash_gap
            ),
        )


def _spec_from_text(text: str, name: str) -> SignalSpec:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SpecError(f"{name}: not a mapping")
    try:
        spec = SignalSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecError(f"{name}: {exc}") from exc
    expected = f"{spec.id}@{spec.version}.yaml"
    if name.endswith(".yaml") and Path(name).name != expected:
        raise SpecError(f"{name}: file name must be {expected}")
    return spec


def load_signal_spec(path: Path) -> tuple[SignalSpec, str]:
    """(spec, spec text). The text is what is hashed and registered."""
    text = path.read_text(encoding="utf-8")
    return _spec_from_text(text, path.name), text


def load_registered_specs(directory: Path = SIGNALS_DIR) -> dict[str, tuple[SignalSpec, str]]:
    out: dict[str, tuple[SignalSpec, str]] = {}
    for p in sorted(directory.glob("S-*@*.yaml")):
        if not _SPEC_NAME.match(p.name):
            raise SpecError(f"unexpected signal file name {p.name}")
        spec, text = load_signal_spec(p)
        out[f"{spec.id}@{spec.version}"] = (spec, text)
    return out


def spec_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ================================================================================================ run context


@dataclass(frozen=True, kw_only=True)
class RunContext:
    """Inputs gathered by the caller (CLI or a test). ``panel`` is keyed by role name; it is hashed, never stored."""

    panel: wf.NavPanel
    provenance: tuple[gt.SeriesProvenance, ...]
    costs: wf.MfCostSchedule
    cost_policy: CostBasisPolicy
    tax_table: TaxRateTable
    code_version: str
    created_at: str  # ISO-8601, passed in (no clock here)
    canary_replicates: int
    explained_gaps: frozenset[tuple[str, date]] = frozenset()
    survivorship_verified: bool = False
    loss_budget: Decimal | None = None
    exposure_at_max_tilt: Decimal | None = None


@dataclass(frozen=True, kw_only=True)
class FamilyTrial:
    trial_id: str
    sr_hat: Decimal | None
    n_periods: int | None


@dataclass(frozen=True, kw_only=True)
class EvidenceBundle:
    trial: Mapping[str, Any]
    run: Mapping[str, Any]
    neighbour_trials: tuple[Mapping[str, Any], ...]
    verdict: str
    reason_code: str | None
    output_hash: str
    bundle_hash: str

    def to_json(self) -> str:
        return canonical_json(
            {
                "format": "iip.evidence_bundle@1",
                "trial": dict(self.trial),
                "run": dict(self.run),
                "neighbour_trials": [dict(t) for t in self.neighbour_trials],
                "verdict": self.verdict,
                "reason_code": self.reason_code,
                "output_hash": self.output_hash,
                "bundle_hash": self.bundle_hash,
            }
        )


def panel_snapshot_hash(panel: wf.NavPanel) -> str:
    """Content hash of the exact data used (dates and NAV strings per role). Only the hash leaves the machine."""
    return content_hash({"dates": list(panel.dates), "navs": {r: list(v) for r, v in sorted(panel.navs.items())}})


def _rules_version(ctx: RunContext) -> str:
    return content_hash(
        {
            "tax": ctx.tax_table,
            "costs": ctx.costs,
            "cost_policy": {
                "deductible": sorted(ctx.cost_policy.deductible_components),
                "status": ctx.cost_policy.status,
            },
        }
    )


def _trial_id(spec: SignalSpec, sh: str, params: Mapping[str, Any], snapshot: str, code: str, rules: str) -> str:
    key = canonical_json(
        {
            "rule": spec.id,
            "version": spec.version,
            "spec": sh,
            "params": dict(params),
            "snapshot": snapshot,
            "code": code,
            "rules": rules,
        }
    )
    return "trial:" + hashlib.sha256(key.encode()).hexdigest()[:32]


def _seed(spec: SignalSpec, snapshot: str, trial_id: str) -> int:
    """``seed = sha256(rule_id|version|data_snapshot_hash|trial_id)`` (design-evidence-first.md §6.3), 63 bits."""
    h = hashlib.sha256(f"{spec.id}|{spec.version}|{snapshot}|{trial_id}".encode()).hexdigest()
    return int(h[:16], 16) & ((1 << 63) - 1)


# ================================================================================================ evidence


def _q(x: float | Decimal | None) -> Decimal | None:
    if x is None:
        return None
    if isinstance(x, Decimal):
        with engine_context():
            return x.quantize(_Q) if abs(x) < Decimal("1e15") else x
    if not math.isfinite(x):
        return None
    return Decimal(repr(round(x, 6)))


def _gate_json(g: GateResult) -> dict[str, Any]:
    return {
        "gate_id": g.gate_id,
        "status": g.status.value,
        "passed": g.passed,
        "reason_code": g.reason_code,
        "value": _q(g.value),
        "threshold": _q(g.threshold),
        "detail": g.detail,
    }


def _mean(xs: Sequence[Decimal]) -> Decimal | None:
    if not xs:
        return None
    with engine_context():
        return sum(xs, ZERO) / Decimal(len(xs))


def _setup(
    spec: SignalSpec,
    ctx: RunContext,
    *,
    overrides: Mapping[str, Any] | None = None,
    stress: wf.CostStress | None = None,
) -> wf.BacktestSetup:
    return wf.BacktestSetup(
        strategy=spec.strategy_rule(overrides),
        benchmark=spec.benchmark_rule(),
        config=spec.config(),
        decision_every_months=spec.decision_every_months,
        initial_capital=_dec(spec.capital.initial_inr, "initial"),
        contribution=_dec(spec.capital.contribution_inr, "contribution"),
        tax_classes=spec.tax_classes(),
        costs=ctx.costs,
        cost_policy=ctx.cost_policy,
        tax_table=ctx.tax_table,
        vault=wf.VaultSpec(fraction=_dec(spec.vault.fraction, "vault"), min_months=spec.vault.min_months),
        regimes=tuple(wf.RegimeSpec(regime_id=r.id, start=r.start, end=r.end) for r in spec.regimes),
        stress=stress or wf.NO_STRESS,
    )


@dataclass(frozen=True, kw_only=True)
class _Computed:
    main: wf.WalkForwardResult
    neighbours: tuple[tuple[Mapping[str, Any], wf.WalkForwardResult | None], ...]


def _walk(spec: SignalSpec, ctx: RunContext) -> _Computed:
    """Run the main configuration and every neighbour (pre-vault only)."""
    main = wf.run_walk_forward(ctx.panel, _setup(spec, ctx))
    neigh: list[tuple[Mapping[str, Any], wf.WalkForwardResult | None]] = []
    for n in spec.neighbours:
        try:
            neigh.append((n, wf.run_walk_forward(ctx.panel, _setup(spec, ctx, overrides=n))))
        except EngineError:
            neigh.append((n, None))
    return _Computed(main=main, neighbours=tuple(neigh))


def _sharpe(edges: Sequence[float]) -> tuple[float, float, float] | None:
    try:
        m = sharpe_moments(edges)
    except EngineError:
        return None
    return m.sharpe, m.skewness, m.kurtosis


def _percentile(xs: Sequence[Decimal], q: Decimal) -> Decimal:
    s = sorted(xs)
    idx = int((q * Decimal(len(s) - 1)).to_integral_value())
    return s[max(0, min(len(s) - 1, idx))]


def compute_evidence(
    spec: SignalSpec,
    ctx: RunContext,
    *,
    trial_id: str,
    neighbour_trial_ids: Sequence[str],
    family_others: Sequence[FamilyTrial],
    registered_on: date,
    seed: int,
    computed: _Computed | None = None,
) -> dict[str, Any]:
    """Everything that goes into ``output_hash``: gate panel, verdict and statistics. Pure given its inputs."""
    comp = computed or _walk(spec, ctx)
    main = comp.main
    edges = main.oos_edges
    setup = _setup(spec, ctx)

    # G7: the same walk-forward under slippage ×2 and costs ×1.5.
    stress = wf.CostStress(
        cost_multiplier=_dec(spec.cost_stress.cost_multiplier, "cost_multiplier"),
        slippage_multiplier=_dec(spec.cost_stress.slippage_multiplier, "slippage_multiplier"),
    )
    stressed = wf.run_walk_forward(ctx.panel, _setup(spec, ctx, stress=stress))

    # G4: shuffle canary over the same pipeline (pre-vault, main configuration).
    def pipeline(p: wf.NavPanel) -> Sequence[float]:
        return wf.run_walk_forward(p, setup).oos_edges

    canary = wf.shuffle_canary(ctx.panel, pipeline, seed=seed, replicates=ctx.canary_replicates)

    # G8/G9: the family as frozen in the manifest plus the trials computed in this run.
    mom = _sharpe(edges)
    family: list[tuple[str, float, int]] = [
        (t.trial_id, float(t.sr_hat), int(t.n_periods))
        for t in family_others
        if t.sr_hat is not None and t.n_periods is not None and t.n_periods >= 2
    ]
    if mom is not None:
        family.append((trial_id, mom[0], len(edges)))
    for tid, (_n, res) in zip(neighbour_trial_ids, comp.neighbours, strict=True):
        nm = _sharpe(res.oos_edges) if res is not None else None
        if res is not None and nm is not None:
            family.append((tid, nm[0], len(res.oos_edges)))
    family.sort()
    ids = [f[0] for f in family]
    n_trials = len({t.trial_id for t in family_others} | {trial_id, *neighbour_trial_ids}) + spec.variants_counted - 1
    p_values = tuple(gt.p_value_from_sharpe(sr, n) for _, sr, n in family)
    selected = ids.index(trial_id) if trial_id in ids else 0

    neighbour_edges: tuple[Decimal, ...] | None = None
    if comp.neighbours and all(r is not None for _, r in comp.neighbours):
        neighbour_edges = tuple(_mean([p.edge for p in r.periods]) or ZERO for _, r in comp.neighbours if r)

    inputs = gt.GateInputs(
        provenance=ctx.provenance,
        universe_kind=spec.universe_kind,
        survivorship_verified=ctx.survivorship_verified,
        price_gaps=gt.unexplained_gaps(
            ctx.panel.truncate(_pre_vault_obs(ctx.panel, main)), explained=ctx.explained_gaps
        ),
        leakage_invariants_ok=main.leakage_checks > 0,
        canary=canary,
        oos_edges=edges,
        hac_lag=spec.walk_forward.hac_lag,
        n_trials=n_trials,
        family_sharpes=tuple(f[1] for f in family),
        family_p_values=p_values,
        selected_index=selected,
        edge_after_tax=main.edge_after_tax,
        stressed_edge_after_tax=stressed.edge_after_tax,
        tax_rules_missing=main.tax_rules_missing,
        cost_rules_missing=main.cost_rules_missing,
        costs_estimated=main.costs_estimated,
        regimes=main.regimes,
        rolling_variant_edge=None,  # fixed-parameter rule: no fitted window to roll; fails closed in G10
        neighbour_edges=neighbour_edges,
        vault=None,
        live=None,
        strategy_mdd=main.strategy.max_drawdown,
        benchmark_mdd=main.benchmark.max_drawdown,
        loss_budget=ctx.loss_budget,
        exposure_at_max_tilt=ctx.exposure_at_max_tilt,
    )
    panel = gt.evaluate_gates(inputs)
    vault_opened = False
    if panel.verdict.gate_id == "G11":  # every other blocking gate passed: open the vault, once
        vault_opened = True
        v = wf.run_vault(ctx.panel, setup)
        wf_edges = [p.edge for p in main.periods]
        panel = gt.evaluate_gates(
            replace(
                inputs,
                vault=gt.VaultOutcome(
                    edge_after_tax=v.edge_after_tax,
                    mean_edge=_mean([p.edge for p in v.periods]) or ZERO,
                    wf_low_80=_percentile(wf_edges, Decimal("0.10")),
                    wf_high_80=_percentile(wf_edges, Decimal("0.90")),
                ),
            )
        )

    return {
        "verdict": {
            "state": panel.verdict.state.value,
            "reason_code": panel.verdict.reason_code,
            "gate_id": panel.verdict.gate_id,
            "detail": panel.verdict.detail,
            "evidence_complete": panel.evidence_complete,
        },
        "gates": [_gate_json(g) for g in panel.gates],
        "stats": _stats(spec, main, stressed, canary, mom, n_trials, registered_on),
        "vault_opened": vault_opened,
    }


def _pre_vault_obs(panel: wf.NavPanel, res: wf.WalkForwardResult) -> int:
    if res.vault_start is None:
        return len(panel.dates)
    return panel.dates.index(res.vault_start) + 1


def _stats(
    spec: SignalSpec,
    main: wf.WalkForwardResult,
    stressed: wf.WalkForwardResult,
    canary: wf.CanaryResult,
    mom: tuple[float, float, float] | None,
    n_trials: int,
    registered_on: date,
) -> dict[str, Any]:
    edges = [p.edge for p in main.periods]
    mean_edge = _mean(edges)
    post = [p.edge for p in main.periods if spec.post_publication_from and p.start >= spec.post_publication_from]
    out: dict[str, Any] = {
        "formula_ids": [wf.FORMULA_ID, gt.FORMULA_ID, RUNNER_VERSION],
        "n_oos_periods": len(edges),
        "first_oos_date": main.periods[0].start if main.periods else None,
        "last_oos_date": main.periods[-1].end if main.periods else None,
        "vault_start": main.vault_start,
        "n_vault_periods": main.n_vault_periods,
        "n_trials": n_trials,
        "mean_edge_per_period": _q(mean_edge),
        "expected_excess_after_decay_haircut": _q(mean_edge * DECAY_HAIRCUT) if mean_edge is not None else None,
        "post_publication": {
            "from": spec.post_publication_from,
            "n_periods": len(post),
            "mean_edge": _q(_mean(post)),
        },
        "edge_after_tax_inr": _q(main.edge_after_tax),
        "stressed_edge_after_tax_inr": _q(stressed.edge_after_tax),
        "tax_rules_missing": main.tax_rules_missing,
        "cost_rules_missing": main.cost_rules_missing,
        "costs_estimated": main.costs_estimated,
        "strategy_max_drawdown": _q(main.strategy.max_drawdown),
        "benchmark_max_drawdown": _q(main.benchmark.max_drawdown),
        "strategy_trades": main.strategy.n_trades,
        "benchmark_trades": main.benchmark.n_trades,
        "regimes": [{"id": r.regime_id, "n_periods": r.n_periods, "mean_edge": _q(r.mean_edge)} for r in main.regimes],
        "canary": {
            "replicates": canary.replicates,
            "mean_permuted_score": canary.mean_permuted_score,
            "mean_noise_score": canary.mean_noise_score,
            "threshold": canary.threshold,
            "passed": canary.passed,
        },
        "reason_codes": list(main.reason_codes),
        "warnings": list(main.warnings),
        "sharpe_per_period": None,
        "skewness": None,
        "kurtosis": None,
        "min_trl_periods": None,
        "power_80_periods": None,
        "earliest_review": None,
    }
    if mom is not None:
        sr, sk, ku = mom
        out.update(sharpe_per_period=_q(sr), skewness=_q(sk), kurtosis=_q(ku))
        if sr > 0.0:
            try:
                rev = earliest_review(registered_on, sr, 0.0, skewness=sk, kurtosis=ku)
                out["min_trl_periods"] = _q(rev.min_trl)
                out["power_80_periods"] = _q(power_length(sr, 0.0, skewness=sk, kurtosis=ku))
                if spec.decision_every_months == 1:
                    out["earliest_review"] = rev.review_date.strftime("%Y-%m")
            except EngineError:
                pass
    return out


# ================================================================================================ DB orchestration


def _registered_on(conn: sqlite3.Connection, spec: SignalSpec, fallback: str) -> date:
    row = conn.execute(
        "SELECT registered_at FROM signal_rules WHERE rule_id=? AND version=?", (spec.id, spec.version)
    ).fetchone()
    return date.fromisoformat(str(row["registered_at"] if row else fallback)[:10])


def _family_others(conn: sqlite3.Connection, family: str, exclude: set[str]) -> list[FamilyTrial]:
    rows = conn.execute(
        "SELECT trial_id, sr_hat, n_periods FROM backtest_trials WHERE family=? ORDER BY trial_id", (family,)
    ).fetchall()
    return [
        FamilyTrial(
            trial_id=r["trial_id"],
            sr_hat=Decimal(r["sr_hat"]) if r["sr_hat"] is not None else None,
            n_periods=int(r["n_periods"]) if r["n_periods"] is not None else None,
        )
        for r in rows
        if r["trial_id"] not in exclude
    ]


def _trial_row(
    spec: SignalSpec,
    sh: str,
    trial_id: str,
    params: Mapping[str, Any],
    snapshot: str,
    ctx: RunContext,
    rules: str,
    seed: int,
) -> lg.BacktestTrial:
    return lg.BacktestTrial(
        trial_id=trial_id,
        rule_id=spec.id,
        version=spec.version,
        family=spec.family,
        params_json=canonical_json(dict(params)),
        universe_id=canonical_json(sorted(spec.role_keys())),
        horizon=f"{spec.horizon_months}m",
        benchmark_id=f"{spec.benchmark.kind}:{canonical_json(sorted(spec.benchmark.slots))}",
        data_snapshot_hash=snapshot,
        code_version=ctx.code_version,
        rules_version=rules,
        seed=str(seed),
        status="active",
        created_at=ctx.created_at,
    )


def _check_panel(spec: SignalSpec, ctx: RunContext) -> None:
    want = set(spec.role_keys())
    have = set(ctx.panel.navs)
    if want != have:
        raise InvalidInput(f"panel roles {sorted(have)} do not match the spec's roles {sorted(want)}")


def _manifest(
    spec: SignalSpec,
    sh: str,
    ctx: RunContext,
    *,
    trial_id: str,
    neighbour_ids: Sequence[str],
    snapshot: str,
    rules: str,
    seed: int,
    family: Sequence[FamilyTrial],
    registered_on: date,
) -> dict[str, Any]:
    return {
        "format": "iip.backtest_manifest@1",
        "runner": RUNNER_VERSION,
        "canonical": CANONICAL_VERSION,
        "rule_id": spec.id,
        "version": spec.version,
        "spec_hash": sh,
        "trial_id": trial_id,
        "neighbour_trial_ids": list(neighbour_ids),
        "data_snapshot_hash": snapshot,
        "code_version": ctx.code_version,
        "rules_version": rules,
        "seed": seed,
        "canary_replicates": ctx.canary_replicates,
        "registered_on": registered_on,
        "data_window": {
            "first": ctx.panel.dates[0],
            "last": ctx.panel.dates[-1],
            "n_obs": len(ctx.panel.dates),
            "roles": sorted(ctx.panel.navs),
        },
        "family_snapshot": [{"trial_id": t.trial_id, "sr_hat": t.sr_hat, "n_periods": t.n_periods} for t in family],
        "context": {
            "survivorship_verified": ctx.survivorship_verified,
            "loss_budget": ctx.loss_budget,
            "exposure_at_max_tilt": ctx.exposure_at_max_tilt,
            "explained_gaps": sorted(f"{r}|{d.isoformat()}" for r, d in ctx.explained_gaps),
            "provenance": [
                {
                    "role": p.role,
                    "source_id": p.source_id,
                    "licence_status": p.licence_status,
                    "known_time_populated": p.known_time_populated,
                    "snapshot_hash": p.snapshot_hash,
                }
                for p in ctx.provenance
            ],
        },
    }


def run_backtest(conn: sqlite3.Connection, spec: SignalSpec, spec_text: str, ctx: RunContext) -> EvidenceBundle:
    """Register, log trials (before running), run, gate and record one backtest. Returns the evidence bundle."""
    _check_panel(spec, ctx)
    sh = spec_hash(spec_text)
    snapshot = panel_snapshot_hash(ctx.panel)
    rules = _rules_version(ctx)
    lg.register_rules(
        conn,
        [
            lg.SignalRule(
                rule_id=spec.id,
                version=spec.version,
                class_="S",
                family=spec.family,
                spec_yaml=spec_text,
                spec_hash=sh,
                registered_at=ctx.created_at,
                state="PRE_REGISTERED",
                state_reason=None,
                state_changed_at=ctx.created_at,
            )
        ],
    )
    main_params = dict(spec.rule.params)
    trial_id = _trial_id(spec, sh, main_params, snapshot, ctx.code_version, rules)
    seed = _seed(spec, snapshot, trial_id)
    neighbour_params = [{**spec.rule.params, **n} for n in spec.neighbours]
    neighbour_ids = [_trial_id(spec, sh, p, snapshot, ctx.code_version, rules) for p in neighbour_params]

    # Trials are logged automatically, before anything runs (G8 counts abandoned and crashed runs too).
    existing = {
        r["trial_id"]
        for r in lg.select_by_keys(
            conn, "backtest_trials", ("trial_id",), [(t,) for t in [trial_id, *neighbour_ids]], "trial_id"
        )
    }
    new_trials = [
        _trial_row(spec, sh, tid, p, snapshot, ctx, rules, _seed(spec, snapshot, tid))
        for tid, p in [(trial_id, main_params), *zip(neighbour_ids, neighbour_params, strict=True)]
        if tid not in existing
    ]
    lg.append_trials(conn, list({t.trial_id: t for t in new_trials}.values()))

    registered_on = _registered_on(conn, spec, ctx.created_at)
    family = _family_others(conn, spec.family, {trial_id, *neighbour_ids})
    computed = _walk(spec, ctx)
    out = compute_evidence(
        spec,
        ctx,
        trial_id=trial_id,
        neighbour_trial_ids=neighbour_ids,
        family_others=family,
        registered_on=registered_on,
        seed=seed,
        computed=computed,
    )
    output_hash = content_hash(out)
    manifest = _manifest(
        spec,
        sh,
        ctx,
        trial_id=trial_id,
        neighbour_ids=neighbour_ids,
        snapshot=snapshot,
        rules=rules,
        seed=seed,
        family=family,
        registered_on=registered_on,
    )

    # Record trial results (identity columns stay frozen by trigger) and the append-only run row.
    for tid, res in [(trial_id, computed.main), *zip(neighbour_ids, [r for _, r in computed.neighbours], strict=True)]:
        mom = _sharpe(res.oos_edges) if res is not None else None
        if res is not None and mom is not None:
            lg.record_trial_result(
                conn,
                tid,
                oos_edge_hash=content_hash([p.edge for p in res.periods]),
                n_periods=len(res.periods),
                sr_hat=_q(mom[0]) or ZERO,
                skew=_q(mom[1]) or ZERO,
                kurt=_q(mom[2]) or ZERO,
                status=_trial_status(out),
            )
    run = lg.BacktestRun(
        run_id="run:" + hashlib.sha256(f"{trial_id}|{output_hash}|{ctx.created_at}".encode()).hexdigest()[:32],
        trial_id=trial_id,
        manifest_json=canonical_json(manifest),
        output_hash=output_hash,
        gates_json=canonical_json(out["gates"]),
        stats_json=canonical_json({"stats": out["stats"], "verdict": out["verdict"]}),
        verdict=out["verdict"]["state"],
        vault_opened=1 if out["vault_opened"] else 0,
        created_at=ctx.created_at,
    )
    lg.append_backtest_runs(conn, [run])
    lg.set_rule_state(
        conn, spec.id, spec.version, out["verdict"]["state"], out["verdict"]["reason_code"], ctx.created_at
    )
    trial = conn.execute("SELECT * FROM backtest_trials WHERE trial_id=?", (trial_id,)).fetchone()
    neigh = [
        dict(r) for r in lg.select_by_keys(conn, "backtest_trials", ("trial_id",), [(t,) for t in neighbour_ids], "*")
    ]
    return _bundle(dict(trial), _run_dict(run), tuple(sorted(neigh, key=lambda r: r["trial_id"])), out, output_hash)


def _trial_status(out: Mapping[str, Any]) -> str:
    if out["vault_opened"]:
        return "vaulted_pass" if out["verdict"]["state"] == "ACCEPTED" else "vaulted_fail"
    return "active"


def _run_dict(run: lg.BacktestRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "trial_id": run.trial_id,
        "manifest_json": run.manifest_json,
        "output_hash": run.output_hash,
        "gates_json": run.gates_json,
        "stats_json": run.stats_json,
        "verdict": run.verdict,
        "vault_opened": run.vault_opened,
        "created_at": run.created_at,
    }


def _bundle(
    trial: dict[str, Any], run: dict[str, Any], neigh: tuple[dict[str, Any], ...], out: Mapping[str, Any], oh: str
) -> EvidenceBundle:
    body = {"trial": trial, "run": run, "neighbour_trials": list(neigh)}
    return EvidenceBundle(
        trial=trial,
        run=run,
        neighbour_trials=neigh,
        verdict=out["verdict"]["state"],
        reason_code=out["verdict"]["reason_code"],
        output_hash=oh,
        bundle_hash=content_hash(body),
    )


# ================================================================================================ reproduce


def rerun_manifest(manifest_json: str, spec: SignalSpec, spec_text: str, ctx: RunContext) -> str:
    """Recompute a run from its manifest and return the output hash (raise if the data or spec differ)."""
    m = json.loads(manifest_json)
    if m.get("spec_hash") != spec_hash(spec_text):
        raise InvalidInput("spec differs from the manifest's spec hash")
    if m.get("data_snapshot_hash") != panel_snapshot_hash(ctx.panel):
        raise InvalidInput("data differs from the manifest's snapshot hash")
    if m.get("rules_version") != _rules_version(ctx) or m.get("code_version") != ctx.code_version:
        raise InvalidInput("rule tables or code version differ from the manifest")
    family = [
        FamilyTrial(
            trial_id=f["trial_id"],
            sr_hat=Decimal(f["sr_hat"]) if f["sr_hat"] is not None else None,
            n_periods=f["n_periods"],
        )
        for f in m["family_snapshot"]
    ]
    ctx = replace(ctx, canary_replicates=int(m["canary_replicates"]))
    out = compute_evidence(
        spec,
        ctx,
        trial_id=m["trial_id"],
        neighbour_trial_ids=m["neighbour_trial_ids"],
        family_others=family,
        registered_on=date.fromisoformat(m["registered_on"]),
        seed=int(m["seed"]),
    )
    return content_hash(out)


# ================================================================================================ hosted import


def _scan_forbidden(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_BUNDLE_KEYS:
                raise BundleRejected(f"bundle carries raw market data under {path}/{k}")
            _scan_forbidden(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan_forbidden(v, f"{path}[{i}]")
    elif isinstance(obj, str) and obj[:1] in "{[":
        try:
            inner = json.loads(obj)
        except ValueError:
            return
        _scan_forbidden(inner, path)


def verify_bundle(text: str) -> dict[str, Any]:
    """Parse and verify an evidence bundle: format, hash chain and the no-raw-data rule. Returns the parsed bundle."""
    try:
        b = json.loads(text)
    except ValueError as exc:
        raise BundleRejected("not JSON") from exc
    if not isinstance(b, dict) or b.get("format") != "iip.evidence_bundle@1":
        raise BundleRejected("not an iip evidence bundle")
    body = {"trial": b["trial"], "run": b["run"], "neighbour_trials": b["neighbour_trials"]}
    if content_hash(body) != b.get("bundle_hash"):
        raise BundleRejected("bundle hash mismatch")
    if b["run"]["output_hash"] != b.get("output_hash") or b["run"]["trial_id"] != b["trial"]["trial_id"]:
        raise BundleRejected("bundle rows are inconsistent")
    _scan_forbidden(body)
    return dict(b)


def _opt_dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _opt_int(v: Any) -> int | None:
    return None if v is None else int(v)


def _trial_from_json(t: Mapping[str, Any]) -> lg.BacktestTrial:
    return lg.BacktestTrial(
        trial_id=str(t["trial_id"]),
        rule_id=str(t["rule_id"]),
        version=int(t["version"]),
        family=str(t["family"]),
        params_json=str(t["params_json"]),
        universe_id=str(t["universe_id"]),
        horizon=str(t["horizon"]),
        benchmark_id=str(t["benchmark_id"]),
        data_snapshot_hash=str(t["data_snapshot_hash"]),
        code_version=str(t["code_version"]),
        rules_version=str(t["rules_version"]),
        seed=str(t["seed"]),
        status=str(t["status"]),
        created_at=str(t["created_at"]),
        oos_edge_hash=None if t["oos_edge_hash"] is None else str(t["oos_edge_hash"]),
        n_periods=_opt_int(t["n_periods"]),
        sr_hat=_opt_dec(t["sr_hat"]),
        skew=_opt_dec(t["skew"]),
        kurt=_opt_dec(t["kurt"]),
    )


def import_evidence_bundle(conn: sqlite3.Connection, text: str) -> bool:
    """Hosted-safe import: verify, then append the trial(s) and the run if not present. Never reruns a backtest.

    Returns True when a new run row was written."""
    b = verify_bundle(text)
    trials = [b["trial"], *b["neighbour_trials"]]
    have = {
        r["trial_id"]
        for r in lg.select_by_keys(
            conn, "backtest_trials", ("trial_id",), [(t["trial_id"],) for t in trials], "trial_id"
        )
    }
    rows = [_trial_from_json(t) for t in trials if t["trial_id"] not in have]
    lg.append_trials(conn, rows)
    run = b["run"]
    if conn.execute("SELECT 1 FROM backtest_runs WHERE run_id=?", (run["run_id"],)).fetchone():
        return False
    lg.append_backtest_runs(conn, [lg.BacktestRun(**run)])
    return True
