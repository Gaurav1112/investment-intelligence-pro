"""Signals registry and rule detail read model (PLAN.md wave 2, C03 over B02/B05; design-risk-first.md §6;
design-judgement.md §2.1 #1, §2.2 #12).

Reads the frozen tables of migration 0004 — ``signal_rules`` (registry), ``backtest_trials`` (G8 family count),
``backtest_runs`` (gate panel and statistics of the newest run), ``rule_evaluations`` + ``outcomes`` (the shadow
forward ledger) — and the owner's vocabulary (:mod:`iip.services.settings_prefs`). It writes nothing and computes no
statistic: every number is a stored engine value passed through as a decimal string, or ``None`` when it was never
computed.

Fail closed, everywhere:

* A rule with no backtest run reports its first gate (G1) as ``abstain`` with ``no_backtest_run``: nothing was
  evaluated, so nothing passed.
* A gate G1–G14 missing from a stored panel is reported as ``abstain`` / ``gate_not_reported``.
* ``failing_gate`` is ``None`` only when every gate G1–G14 is present and both ``status == "pass"`` and
  ``passed``. ``latest`` (the live condition) is returned only for an ``ACCEPTED`` rule with no failing gate; the
  shadow record is never an action.
* Statistics stored per *period* are shown as months only when the spec decides monthly
  (``decision_every_months == 1``); otherwise they are ``None`` (not converted).

The wire shapes are ``SignalsResponse`` and ``RuleDetailResponse`` in ``frontend/src/lib/types-signals.ts``;
``tests/api/test_signals_api.py`` checks the keys against that file.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import yaml

from iip.engine.backtest.gates import GATE_IDS
from iip.engine.backtest.stats_gates import MIN_OOS_PERIODS
from iip.services.settings_prefs import read_vocabulary
from iip.store import ledger

SHADOW_ROWS_LIMIT = 120  # rule detail shows the newest rows of the shadow ledger
HAIRCUT_FACTOR = "0.5"  # backtest_runner.DECAY_HAIRCUT; the stored figure is already the after-haircut value
EXCESS_FORMULA_ID = "BT-RUNNER@1:expected_excess_after_decay_haircut"


class RuleNotFound(LookupError):
    pass


# ------------------------------------------------------------------------------------------------- small helpers


def _spec(spec_yaml: str) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(spec_yaml)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, Mapping) else {}


def _s(v: Any) -> str | None:
    """A stored number as a decimal string (canonical JSON already holds Decimals as strings)."""
    if v is None or isinstance(v, bool):
        return None
    return str(v)


def _json(text: Any) -> Any:
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _gate(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("gate_id"), str):
        return None
    status = raw.get("status")
    return {
        "gate_id": raw["gate_id"],
        "status": status if status in ("pass", "fail", "abstain") else "abstain",
        "passed": raw.get("passed") is True,
        "reason_code": raw.get("reason_code") if isinstance(raw.get("reason_code"), str) else None,
        "value": _s(raw.get("value")),
        "threshold": _s(raw.get("threshold")),
        "detail": raw.get("detail") if isinstance(raw.get("detail"), str) else "",
    }


def _abstain_gate(gate_id: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "gate_id": gate_id, "status": "abstain", "passed": False, "reason_code": reason, "value": None,
        "threshold": None, "detail": detail,
    }  # fmt: skip


def _passed(g: Mapping[str, Any]) -> bool:
    return g["status"] == "pass" and g["passed"] is True


def gates_of(run: Any) -> list[dict[str, Any]]:
    """The stored gate panel of a run, normalised (malformed entries dropped, so they count as missing)."""
    if run is None:
        return []
    raw = _json(run["gates_json"])
    if not isinstance(raw, list):
        return []
    return [g for g in (_gate(x) for x in raw) if g is not None]


def failing_gate(gates: Sequence[Mapping[str, Any]], has_run: bool) -> dict[str, Any] | None:
    """The first gate in G1 → G14 order that did not pass; then any extra failing gate; None only if all passed."""
    if not has_run:
        return _abstain_gate(
            GATE_IDS[0], "no_backtest_run", "no backtest run is recorded for this rule version; every gate fails closed"
        )
    by_id = {g["gate_id"]: g for g in gates}
    for gid in GATE_IDS:
        g = by_id.get(gid)
        if g is None:
            return _abstain_gate(gid, "gate_not_reported", "the stored gate panel does not report this gate")
        if not _passed(g):
            return dict(g)
    for g in gates:
        if not _passed(g):
            return dict(g)
    return None


def _stats(run: Any) -> dict[str, Any]:
    if run is None:
        return {}
    raw = _json(run["stats_json"])
    stats = raw.get("stats") if isinstance(raw, Mapping) else None
    return dict(stats) if isinstance(stats, Mapping) else {}


def _monthly(spec: Mapping[str, Any]) -> bool:
    v = spec.get("decision_every_months")
    return isinstance(v, int) and not isinstance(v, bool) and v == 1


def _earliest_review(stats: Mapping[str, Any]) -> str | None:
    v = stats.get("earliest_review")
    return v if isinstance(v, str) and v else None


# ------------------------------------------------------------------------------------------------- reads


_RULES_SQL = (
    "SELECT r.rule_id, r.version, r.class, r.family, r.spec_yaml, r.spec_hash, r.registered_at, r.state,"
    " r.state_reason, r.state_changed_at,"
    " (SELECT COUNT(*) FROM backtest_trials t WHERE t.family = r.family) AS trial_count,"
    " (SELECT COUNT(*) FROM rule_evaluations e WHERE e.rule_id = r.rule_id AND e.version = r.version) AS evaluations,"
    " (SELECT MIN(e.as_of_date) FROM rule_evaluations e WHERE e.rule_id = r.rule_id AND e.version = r.version)"
    " AS first_as_of,"
    " (SELECT MAX(e.as_of_date) FROM rule_evaluations e WHERE e.rule_id = r.rule_id AND e.version = r.version)"
    " AS last_as_of,"
    " (SELECT COUNT(*) FROM rule_evaluations e WHERE e.rule_id = r.rule_id AND e.version = r.version"
    " AND e.condition_met = 1) AS condition_met,"
    " (SELECT COUNT(*) FROM outcomes o WHERE o.rule_id = r.rule_id AND o.version = r.version"
    " AND o.status = 'scored') AS outcomes_scored,"
    " (SELECT COUNT(*) FROM outcomes o WHERE o.rule_id = r.rule_id AND o.version = r.version"
    " AND o.status = 'unscorable') AS outcomes_unscorable,"
    " (SELECT b.run_id FROM backtest_runs b JOIN backtest_trials t ON t.trial_id = b.trial_id"
    " WHERE t.rule_id = r.rule_id AND t.version = r.version ORDER BY b.created_at DESC, b.run_id DESC LIMIT 1)"
    " AS run_id"
    " FROM signal_rules r"
)


def _rules(conn: sqlite3.Connection, key: tuple[str, int] | None) -> list[sqlite3.Row]:
    if key is None:
        return list(conn.execute(_RULES_SQL + " ORDER BY r.rule_id, r.version"))
    return list(conn.execute(_RULES_SQL + " WHERE r.rule_id = ? AND r.version = ?", key))


def _runs(conn: sqlite3.Connection, run_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
    if not run_ids:
        return {}
    rows = ledger.select_by_keys(
        conn, "backtest_runs", ("run_id",), [(i,) for i in run_ids], "run_id, gates_json, stats_json"
    )
    return {r["run_id"]: r for r in rows}


def _summary(row: Any, spec: Mapping[str, Any], run: Any) -> dict[str, Any]:
    gates = gates_of(run)
    title = spec.get("title")
    return {
        "rule_id": row["rule_id"],
        "version": int(row["version"]),
        "class": row["class"],
        "family": row["family"],
        "title": title if isinstance(title, str) and title else f"{row['rule_id']} (no title in the registered spec)",
        "state": row["state"],
        "state_reason": row["state_reason"],
        "state_changed_at": row["state_changed_at"],
        "registered_at": row["registered_at"],
        "failing_gate": failing_gate(gates, run is not None),
        "trial_count": int(row["trial_count"]),
        "shadow": {
            "evaluations": int(row["evaluations"]),
            "first_as_of": row["first_as_of"],
            "last_as_of": row["last_as_of"],
            "condition_met": int(row["condition_met"]),
            "outcomes_scored": int(row["outcomes_scored"]),
            "outcomes_unscorable": int(row["outcomes_unscorable"]),
        },
        "earliest_review": _earliest_review(_stats(run)),
    }


def signals_response(conn: sqlite3.Connection) -> dict[str, Any]:
    """``GET /api/signals``: the registry, newest shadow date and the owner's vocabulary (three statements)."""
    rows = _rules(conn, None)
    runs = _runs(conn, sorted({r["run_id"] for r in rows if r["run_id"]}))
    rules = [_summary(r, _spec(r["spec_yaml"]), runs.get(r["run_id"]) if r["run_id"] else None) for r in rows]
    last = [r["shadow"]["last_as_of"] for r in rules if r["shadow"]["last_as_of"]]
    return {"as_of": max(last) if last else None, "vocabulary": read_vocabulary(conn).value, "rules": rules}


# ------------------------------------------------------------------------------------------------- detail


def _roles(spec: Mapping[str, Any]) -> list[str]:
    roles = spec.get("roles")
    out: set[str] = set()
    if isinstance(roles, Mapping):
        for v in roles.values():
            if isinstance(v, Mapping) and isinstance(v.get("role"), str):
                out.add(v["role"])
            elif isinstance(v, str):
                out.add(v)
    return sorted(out)


def _rule_text(spec: Mapping[str, Any]) -> str:
    rule = spec.get("rule")
    if isinstance(rule, Mapping) and isinstance(rule.get("formula"), str):
        return " ".join(rule["formula"].split())
    if isinstance(rule, str):
        return rule
    return "(no formula in the registered spec)"


def _power(spec: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    monthly = _monthly(spec)
    n = stats.get("n_oos_periods")
    ids = stats.get("formula_ids")
    return {
        "n_oos_periods": n if isinstance(n, int) and not isinstance(n, bool) else None,
        "min_oos_periods": MIN_OOS_PERIODS,
        "min_trl_months": _s(stats.get("min_trl_periods")) if monthly else None,
        "power80_months": _s(stats.get("power_80_periods")) if monthly else None,
        "earliest_review": _earliest_review(stats),
        "formula_ids": [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else [],
    }


def _publication(spec: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    pub = spec.get("post_publication_from")
    published: str | None = None
    if isinstance(pub, date):  # YAML parses an unquoted ISO date to a date
        published = pub.isoformat()
    elif isinstance(pub, str) and pub:
        published = pub
    evidence = spec.get("evidence")
    source = None
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping):
        source = " ".join(str(evidence[0].get(k, "")) for k in ("doc", "section")).strip() or None
    first, last = stats.get("first_oos_date"), stats.get("last_oos_date")
    tag = "UNKNOWN"
    if published and isinstance(first, str) and isinstance(last, str):
        if first >= published:
            tag = "POST_PUBLICATION"
        elif last < published:
            tag = "PRE_PUBLICATION"
        else:
            tag = "MIXED"
    return {"tag": tag, "published_on": published, "source": source}


def _excess(spec: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = _s(stats.get("mean_edge_per_period"))
    if raw is None:
        return None
    period = spec.get("decision_every_months")
    return {
        "raw": raw,
        "haircut_factor": HAIRCUT_FACTOR,
        "after_haircut": _s(stats.get("expected_excess_after_decay_haircut")),
        "formula_id": EXCESS_FORMULA_ID,
        "period_months": period if isinstance(period, int) and not isinstance(period, bool) else None,
    }


def _direction(condition_met: Any, payload: Mapping[str, Any]) -> str | None:
    """Only a met condition whose payload says it holds the ``in`` role is an entry; anything else is not guessed."""
    if condition_met == 1 and payload.get("position_if_met") == "in":
        return "entry"
    return None


def _shadow_rows(conn: sqlite3.Connection, rule_id: str, version: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT e.as_of_date, e.scope_id, e.state, e.condition_met, e.payload_json, e.snapshot_id, o.status,"
        " o.edge_after_cost_tax, o.unscorable_reason FROM rule_evaluations e LEFT JOIN outcomes o"
        " ON o.rule_id = e.rule_id AND o.version = e.version AND o.as_of_date = e.as_of_date"
        " AND o.scope_id = e.scope_id WHERE e.rule_id = ? AND e.version = ?"
        " ORDER BY e.as_of_date DESC, e.scope_id LIMIT ?",
        (rule_id, version, SHADOW_ROWS_LIMIT),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = _json(r["payload_json"])
        payload = payload if isinstance(payload, Mapping) else {}
        met = r["condition_met"]
        out.append(
            {
                "as_of_date": r["as_of_date"],
                "scope_id": r["scope_id"],
                "state": r["state"],
                "condition_met": None if met is None else met == 1,
                "direction": _direction(met, payload),
                "outcome_status": r["status"],
                "edge_after_cost_tax": _s(r["edge_after_cost_tax"]),
                "unscorable_reason": r["unscorable_reason"],
                "snapshot_id": r["snapshot_id"],
            }
        )
    return out


def rule_detail_response(conn: sqlite3.Connection, rule_id: str, version: int) -> dict[str, Any]:
    """``GET /api/signals/{rule_id}/{version}``. Raises :class:`RuleNotFound` for an unregistered key."""
    rows = _rules(conn, (rule_id, version))
    if not rows:
        raise RuleNotFound(f"{rule_id}@{version} is not registered")
    row = rows[0]
    spec = _spec(row["spec_yaml"])
    run = _runs(conn, [row["run_id"]]).get(row["run_id"]) if row["run_id"] else None
    summary = _summary(row, spec, run)
    stats = _stats(run)
    shadow = _shadow_rows(conn, rule_id, version)
    actionable = summary["state"] == "ACCEPTED" and summary["failing_gate"] is None
    latest = None
    if actionable and shadow:
        newest = shadow[0]
        latest = {
            "as_of_date": newest["as_of_date"],
            "condition_met": newest["condition_met"],
            "direction": newest["direction"],
        }
    return {
        "rule": summary,
        "vocabulary": read_vocabulary(conn).value,
        "rule_text": _rule_text(spec),
        "roles": _roles(spec),
        "spec_hash": row["spec_hash"],
        "gates": gates_of(run),
        "power": _power(spec, stats),
        "publication": _publication(spec, stats),
        "expected_excess": _excess(spec, stats),
        "latest": latest,
        "shadow": shadow,
    }
