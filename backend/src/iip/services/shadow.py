"""The daily shadow forward ledger (design-judgement.md §2.1 graft 1; PLAN.md wave 2, package B02).

Job J4 first registers the committed specs (:mod:`iip.services.signal_registry`; append-only, idempotent, so a
fresh install has a registry), then evaluates EVERY registered signal (class ``S``) rule once per data date, whatever
its registry state (``PRE_REGISTERED``, ``ABSTAIN``, ``NO_SIGNAL``, …; ``RETIRED`` rules are no longer evaluated), and
appends one ``rule_evaluations`` row per (rule, version, as-of date, scope). The row is evidence only: it is **never**
turned into an action card, and the Today payload carries none of it (``iip.services.risk_snapshot`` never reads this
ledger). Outcomes are scored later, at each rule's horizon (:mod:`iip.services.outcomes`).

Evaluators are deterministic functions of month-end NAVs from ``series_grid`` for the instruments the user bound to
the spec's roles (``rule_role_bindings``; the public spec names roles only, never schemes). Only COMPLETED months
(before the as-of month) are used, so a part-month NAV never leaks in.

The spec contract is the COMMITTED schema (``rules/signals/schema.yaml``), parsed by the same model the backtest
runner uses (:class:`iip.services.backtest_runner.SignalSpec`); there is no second, shadow-only spec shape. A stored
spec that does not validate is written with ``condition_met = NULL`` and ``spec_invalid`` (failing closed, not
skipping). The evaluator dispatches on ``rule.kind`` and reads the slots of ``roles`` named by ``rule.slots``:

* ``trend_sma`` — slots ``risk`` and ``out``, ``rule.params.lookback_months`` (L ≥ 2), ``horizon_months`` (≥ 1).
  ``condition_met = 1`` when ``C_m > mean(C_{m−L+1..m})`` (design-risk-first.md §6.1, rule S-E).
* ``abs_momentum`` — slots ``risk``, ``hurdle`` and ``out``, ``rule.params.lookback_months`` (L),
  ``rule.params.skip_months`` (S, 0 ≤ S < L), ``horizon_months``. ``R_x = C_{m−S} / C_{m−L} − 1``;
  ``condition_met = 1`` when ``R_risk > R_hurdle`` (the liquid-fund NAV hurdle, design-judgement.md §2.1 graft 2).

Both formulas are the ones ``engine/backtest/walkforward.py`` uses for the same kinds. The payload names the legs
``in`` (the ``risk`` slot, also the outcome benchmark), ``out`` and ``hurdle``; the rule holds ``in`` when the
condition is met and ``out`` otherwise. Any other kind (``dual_momentum``, ``drawdown_topup``) is recorded as
``family_not_implemented``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from iip.engine.determinism import canonical_json, content_hash
from iip.engine.money import engine_context
from iip.services import signal_registry
from iip.services.backtest_runner import SIGNALS_DIR, SignalSpec, SpecError, spec_from_text
from iip.store import ledger

SHADOW_VERSION = "shadow.evaluate@1"
EVALUATED = "EVALUATED"
ABSTAINED = "ABSTAIN"
NOT_EVALUATED_STATES = frozenset({"RETIRED"})


def _month_index(month: str) -> int:
    y, m = month.split("-")
    return int(y) * 12 + int(m) - 1


def _month_str(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_end(month: str) -> date:
    i = _month_index(month) + 1
    nxt = date(i // 12, i % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def add_months(month: str, n: int) -> str:
    return _month_str(_month_index(month) + n)


@dataclass(frozen=True)
class Evaluation:
    """What an evaluator found. ``condition_met`` is None when it abstained (``reason`` says why)."""

    condition_met: int | None
    reason: str | None
    observation_month: str | None
    months_used: tuple[str, ...]
    navs_used: tuple[tuple[str, str, Decimal], ...]  # (role, month, nav) — hashed, not stored in the payload
    instruments: Mapping[str, str]  # role key → instrument_id
    horizon_months: int | None
    position_if_met: str | None  # role key held when the condition is met
    position_if_not_met: str | None


def _abstain(reason: str, **kw: Any) -> Evaluation:
    base: dict[str, Any] = {
        "observation_month": None, "months_used": (), "navs_used": (), "instruments": {}, "horizon_months": None,
        "position_if_met": None, "position_if_not_met": None,
    }  # fmt: skip
    base.update(kw)
    return Evaluation(condition_met=None, reason=reason, **base)


#: Shadow leg key → the committed spec's slot name, per implemented ``rule.kind``.
_LEGS: Mapping[str, Mapping[str, str]] = {
    "trend_sma": {"in": "risk", "out": "out"},
    "abs_momentum": {"in": "risk", "hurdle": "hurdle", "out": "out"},
}
FAMILY_NOT_IMPLEMENTED = "family_not_implemented"
SPEC_INVALID = "spec_invalid"


def _param_int(spec: SignalSpec, name: str) -> int | None:
    v = spec.rule.params.get(name)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _series(grid: Mapping[str, Sequence[tuple[str, Decimal]]], instrument_id: str) -> dict[str, Decimal]:
    return dict(grid.get(instrument_id, ()))


def evaluate_rule(
    spec: SignalSpec,
    bindings: Mapping[str, str],
    grid: Mapping[str, Sequence[tuple[str, Decimal]]],
    as_of: date,
) -> Evaluation:
    """Pure evaluation of one validated spec on the completed months before ``as_of``."""
    kind = spec.rule.kind
    legs = _LEGS.get(kind)
    if legs is None:
        return _abstain(FAMILY_NOT_IMPLEMENTED)
    roles: dict[str, str] = {}
    for key, slot in legs.items():
        if slot not in spec.rule.slots or slot not in spec.roles:
            return _abstain(f"spec_field_missing:roles.{slot}")
        roles[key] = spec.roles[slot].role
    horizon = spec.horizon_months
    lookback = _param_int(spec, "lookback_months")
    if lookback is None or lookback < 2:
        return _abstain("spec_field_missing:rule.params.lookback_months")
    skip = 0
    if kind == "abs_momentum":
        s = _param_int(spec, "skip_months")
        if s is None or not 0 <= s < lookback:
            return _abstain("spec_field_missing:rule.params.skip_months")
        skip = s
    unbound = sorted({r for r in roles.values() if r not in bindings})
    if unbound:
        return _abstain("role_unbound:" + ",".join(unbound), horizon_months=horizon)
    instruments = {k: bindings[r] for k, r in roles.items()}
    m = add_months(f"{as_of.year:04d}-{as_of.month:02d}", -1)  # the last COMPLETED month
    common: dict[str, Any] = {"observation_month": m, "instruments": instruments, "horizon_months": horizon}
    common |= {"position_if_met": "in", "position_if_not_met": "out"}

    if kind == "trend_sma":
        months = tuple(add_months(m, -k) for k in range(lookback - 1, -1, -1))
        series = _series(grid, instruments["in"])
        if any(mo not in series for mo in months):
            return _abstain("insufficient_history", months_used=months, **common)
        navs = tuple(("in", mo, series[mo]) for mo in months)
        with engine_context():
            mean = sum((series[mo] for mo in months), Decimal(0)) / len(months)
            met = 1 if series[m] > mean else 0
        return Evaluation(met, None, months_used=months, navs_used=navs, **common)

    start, end = add_months(m, -lookback), add_months(m, -skip)
    months = (start, end)
    navs_list: list[tuple[str, str, Decimal]] = []
    returns: dict[str, Decimal] = {}
    for key in ("in", "hurdle"):
        series = _series(grid, instruments[key])
        if start not in series or end not in series or series[start] <= 0:
            return _abstain("insufficient_history", months_used=months, **common)
        navs_list += [(key, start, series[start]), (key, end, series[end])]
        with engine_context():
            returns[key] = series[end] / series[start] - 1
    met = 1 if returns["in"] > returns["hurdle"] else 0
    return Evaluation(met, None, months_used=months, navs_used=tuple(navs_list), **common)


@dataclass(frozen=True)
class RegisteredRule:
    rule_id: str
    version: int
    family: str
    state: str
    spec_hash: str
    spec: SignalSpec | None  # None when the stored YAML does not validate against the committed schema


def parse_spec(spec_yaml: str) -> SignalSpec | None:
    """The stored spec under the committed schema, or None (→ ``spec_invalid``)."""
    try:
        return spec_from_text(spec_yaml, "signal_rules.spec_yaml")
    except (SpecError, yaml.YAMLError):
        return None


def load_s_rules(conn: sqlite3.Connection) -> list[RegisteredRule]:
    """Every registered S rule except RETIRED ones (one statement)."""
    out: list[RegisteredRule] = []
    for r in conn.execute(
        "SELECT rule_id, version, family, state, spec_yaml, spec_hash FROM signal_rules WHERE class = 'S'"
        " ORDER BY rule_id, version"
    ):
        if r["state"] in NOT_EVALUATED_STATES:
            continue
        out.append(
            RegisteredRule(r["rule_id"], int(r["version"]), r["family"], r["state"], r["spec_hash"],
                           parse_spec(r["spec_yaml"]))
        )  # fmt: skip
    return out


def build_row(rule: RegisteredRule, ev: Evaluation, as_of: date, snapshot_id: str, now: str) -> ledger.RuleEvaluation:
    scope_role = None
    if rule.spec is not None and "risk" in rule.spec.roles:
        scope_role = rule.spec.roles["risk"].role
    scope_id = f"role:{scope_role}" if scope_role else "household"
    horizon_end = None
    if ev.observation_month is not None and ev.horizon_months is not None:
        horizon_end = month_end(add_months(ev.observation_month, ev.horizon_months)).isoformat()
    payload = {
        "rule_ref": f"{rule.rule_id}@{rule.version}",
        "registry_state": rule.state,
        "family": rule.family,
        "evaluation": EVALUATED if ev.condition_met is not None else ABSTAINED,
        "reason": ev.reason,
        "observation_month": ev.observation_month,
        "months_used": list(ev.months_used),
        "instruments": dict(sorted(ev.instruments.items())),
        "position_if_met": ev.position_if_met,
        "position_if_not_met": ev.position_if_not_met,
        "horizon_months": ev.horizon_months,
        "horizon_end": horizon_end,
        "spec_hash": rule.spec_hash,
        "evaluator": SHADOW_VERSION,
        "shown_as_action": False,
    }
    input_hash = content_hash(
        {
            "spec_hash": rule.spec_hash,
            "evaluator": SHADOW_VERSION,
            "instruments": dict(ev.instruments),
            "navs": [list(n) for n in ev.navs_used],
            "observation_month": ev.observation_month,
            "condition_met": ev.condition_met,
            "reason": ev.reason,
        }
    )
    return ledger.RuleEvaluation(
        rule_id=rule.rule_id, version=rule.version, as_of_date=as_of.isoformat(), scope_id=scope_id,
        state=rule.state, condition_met=ev.condition_met, payload_json=canonical_json(payload),
        input_hash=input_hash, snapshot_id=snapshot_id, evaluated_at=now,
    )  # fmt: skip


@dataclass(frozen=True)
class ShadowRun:
    rules: int
    written: int
    already_recorded: int
    evaluated: int
    abstained: int
    registered: int = 0  # committed specs newly registered by this run (SIG-2)
    registry_conflicts: tuple[str, ...] = ()  # committed id@version whose text differs from the registered row
    registry_rejected: tuple[str, ...] = ()  # committed files that fail the spec schema


def run_shadow(
    conn: sqlite3.Connection, *, as_of: date, snapshot_id: str, now: str, specs_dir: Path | None = SIGNALS_DIR
) -> ShadowRun:
    """Register the committed specs in ``specs_dir`` (idempotent, append-only; None skips it), then evaluate every
    registered S rule for ``as_of`` and append the rows. Idempotent: a key already recorded is left as it is (the
    ledger is append-only; the first write for a data date stands). Statements: the registry key read and insert,
    rules, role bindings, the month-end grid (chunked), then the append (ONE chunked existing-key read and the
    batched insert; run_shadow does not read the keys a second time itself)."""
    reg = signal_registry.register_committed_specs(conn, now=now, directory=specs_dir) if specs_dir else None
    extra = (reg.registered, reg.conflicts, reg.rejected) if reg else (0, (), ())
    rules = load_s_rules(conn)
    if not rules:
        return ShadowRun(0, 0, 0, 0, 0, *extra)
    bindings = ledger.role_bindings(conn)
    grid = ledger.series_grid(conn, sorted(set(bindings.values())))
    rows = []
    for rule in rules:
        ev = _abstain(SPEC_INVALID) if rule.spec is None else evaluate_rule(rule.spec, bindings, grid, as_of)
        rows.append(build_row(rule, ev, as_of, snapshot_id, now))
    written = ledger.append_rule_evaluations(conn, rows, keep_existing=True)
    evaluated = sum(1 for r in rows if r.condition_met is not None)
    return ShadowRun(len(rules), written, len(rows) - written, evaluated, len(rows) - evaluated, *extra)


def payload(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(row["payload_json"])
    return out
