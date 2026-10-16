"""The daily shadow forward ledger (design-judgement.md §2.1 graft 1; PLAN.md wave 2, package B02).

Job J4 evaluates EVERY registered signal (class ``S``) rule once per data date, whatever its registry state
(``PRE_REGISTERED``, ``ABSTAIN``, ``NO_SIGNAL``, …; ``RETIRED`` rules are no longer evaluated), and appends one
``rule_evaluations`` row per (rule, version, as-of date, scope). The row is evidence only: it is **never** turned into
an action card, and the Today payload carries none of it (``iip.services.risk_snapshot`` never reads this ledger).
Outcomes are scored later, at each rule's horizon (:mod:`iip.services.outcomes`).

Evaluators are deterministic functions of month-end NAVs from ``series_grid`` for the instruments the user bound to
the spec's roles (``rule_role_bindings``; the public spec names roles only, never schemes). Only COMPLETED months
(before the as-of month) are used, so a part-month NAV never leaks in.

Spec fields an evaluator reads (anything missing → the row is written with ``condition_met = NULL`` and the reason,
which is failing closed, not skipping):

* ``family: trend_timing`` — ``roles.in``, ``roles.out``, ``params.lookback_months`` (L ≥ 2), ``horizon_months`` (≥ 1).
  ``condition_met = 1`` when ``C_m > mean(C_{m−L+1..m})`` (design-risk-first.md §6.1, rule S-E).
* ``family: absolute_momentum`` — ``roles.in``, ``roles.hurdle``, ``params.lookback_months`` (L), ``params.skip_months``
  (S, 0 ≤ S < L), ``horizon_months``. ``R_x = C_{m−S} / C_{m−L} − 1``; ``condition_met = 1`` when ``R_in > R_hurdle``
  (the liquid-fund NAV hurdle, design-judgement.md §2.1 graft 2).

Any other family is recorded as ``evaluator_not_implemented``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import yaml

from iip.engine.determinism import canonical_json, content_hash
from iip.engine.money import engine_context
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


def _int(spec: Mapping[str, Any], path: str) -> int | None:
    node: Any = spec
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    if isinstance(node, bool) or not isinstance(node, int):
        return None
    return node


def _str(spec: Mapping[str, Any], path: str) -> str | None:
    node: Any = spec
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) and node else None


def _series(grid: Mapping[str, Sequence[tuple[str, Decimal]]], instrument_id: str) -> dict[str, Decimal]:
    return dict(grid.get(instrument_id, ()))


def evaluate_rule(
    spec: Mapping[str, Any],
    bindings: Mapping[str, str],
    grid: Mapping[str, Sequence[tuple[str, Decimal]]],
    as_of: date,
) -> Evaluation:
    """Pure evaluation of one spec on the completed months before ``as_of``."""
    family = spec.get("family")
    if family == "trend_timing":
        role_keys = ("in", "out")
    elif family == "absolute_momentum":
        role_keys = ("in", "hurdle")
    else:
        return _abstain("evaluator_not_implemented")
    roles: dict[str, str] = {}
    for key in role_keys:
        role = _str(spec, f"roles.{key}")
        if role is None:
            return _abstain(f"spec_field_missing:roles.{key}")
        roles[key] = role
    horizon = _int(spec, "horizon_months")
    lookback = _int(spec, "params.lookback_months")
    if horizon is None or horizon < 1:
        return _abstain("spec_field_missing:horizon_months")
    if lookback is None or lookback < 2:
        return _abstain("spec_field_missing:params.lookback_months")
    skip = 0
    if family == "absolute_momentum":
        s = _int(spec, "params.skip_months")
        if s is None or not 0 <= s < lookback:
            return _abstain("spec_field_missing:params.skip_months")
        skip = s
    unbound = sorted(r for r in roles.values() if r not in bindings)
    if unbound:
        return _abstain("role_unbound:" + ",".join(unbound), horizon_months=horizon)
    instruments = {k: bindings[r] for k, r in roles.items()}
    m = add_months(f"{as_of.year:04d}-{as_of.month:02d}", -1)  # the last COMPLETED month
    common: dict[str, Any] = {"observation_month": m, "instruments": instruments, "horizon_months": horizon}
    out_key = "out" if family == "trend_timing" else "hurdle"
    common |= {"position_if_met": "in", "position_if_not_met": out_key}

    if family == "trend_timing":
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
    spec: Mapping[str, Any] | None  # None when the YAML does not parse to a mapping


def load_s_rules(conn: sqlite3.Connection) -> list[RegisteredRule]:
    """Every registered S rule except RETIRED ones (one statement)."""
    out: list[RegisteredRule] = []
    for r in conn.execute(
        "SELECT rule_id, version, family, state, spec_yaml, spec_hash FROM signal_rules WHERE class = 'S'"
        " ORDER BY rule_id, version"
    ):
        if r["state"] in NOT_EVALUATED_STATES:
            continue
        try:
            spec = yaml.safe_load(r["spec_yaml"])
        except yaml.YAMLError:
            spec = None
        out.append(
            RegisteredRule(r["rule_id"], int(r["version"]), r["family"], r["state"], r["spec_hash"],
                           spec if isinstance(spec, Mapping) else None)
        )  # fmt: skip
    return out


def build_row(rule: RegisteredRule, ev: Evaluation, as_of: date, snapshot_id: str, now: str) -> ledger.RuleEvaluation:
    scope_role = None
    if rule.spec is not None:
        scope_role = _str(rule.spec, "roles.in")
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


def run_shadow(conn: sqlite3.Connection, *, as_of: date, snapshot_id: str, now: str) -> ShadowRun:
    """Evaluate every registered S rule for ``as_of`` and append the rows. Idempotent: a key already recorded is
    left as it is (the ledger is append-only; the first write for a data date stands). Statements: rules, role
    bindings, the month-end grid (chunked), then the append (ONE chunked existing-key read and the batched insert;
    run_shadow does not read the keys a second time itself)."""
    rules = load_s_rules(conn)
    if not rules:
        return ShadowRun(0, 0, 0, 0, 0)
    bindings = ledger.role_bindings(conn)
    grid = ledger.series_grid(conn, sorted(set(bindings.values())))
    rows = []
    for rule in rules:
        ev = _abstain("spec_unparseable") if rule.spec is None else evaluate_rule(rule.spec, bindings, grid, as_of)
        rows.append(build_row(rule, ev, as_of, snapshot_id, now))
    written = ledger.append_rule_evaluations(conn, rows, keep_existing=True)
    evaluated = sum(1 for r in rows if r.condition_met is not None)
    return ShadowRun(len(rules), written, len(rows) - written, evaluated, len(rows) - evaluated)


def payload(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(row["payload_json"])
    return out
