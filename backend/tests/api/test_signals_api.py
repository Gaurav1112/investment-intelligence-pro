"""C03 over B02/B05: the Signals registry and Rule detail API (ECC typescript-reviewer-1).

Before this router existed, ``GET /api/signals`` and ``GET /api/signals/{rule_id}/{version}`` answered 404, so the
Signals page could only ever show its error state. These tests pin:

* both routes exist, need a session like every other route, and return the ``SignalsResponse`` /
  ``RuleDetailResponse`` keys declared in ``frontend/src/lib/types-signals.ts`` (one contract, checked on both sides);
* every row of the real registry (``signal_rules``) carries its first failing gate from the stored gate panel
  (``backtest_runs.gates_json``), or ``no_backtest_run`` when no run exists, so the page renders ABSTAIN with a gate;
* the shadow ledger (``rule_evaluations`` + ``outcomes``) is summarised and listed, never turned into ``latest``;
* the vocabulary defaults to ``neutral`` (U-11) and uses the Settings wire value ``badges`` after an opt-in.

Every value here is SYNTHETIC: a fictional rule spec, fictional roles, made-up gate values and dates.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.engine.determinism import canonical_json, sha256_hex
from iip.store import ledger

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
TS = NOW.isoformat()
TYPES_SIGNALS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "types-signals.ts"

# A fictional pre-registered spec (role names only; not one of the committed rules).
SPEC_X = """\
id: S-X
version: 1
class: S
family: synthetic_trend
status: PRE_REGISTERED
title: Synthetic trend rule for tests
roles:
  in: {role: test_fund.alpha.direct, tax_class: EQUITY}
  out: {role: test_fund.cash.direct, tax_class: DEBT}
rule:
  kind: trend_sma
  params: {lookback_months: 4}
  slots: [in, out]
  formula: "S_m = 1 if C_m > mean(C_{m-3..m}) else 0"
decision_every_months: 1
horizon_months: 1
post_publication_from: 2001-01-01
evidence:
  - {doc: docs/synthetic.md, section: "§1"}
"""
SPEC_Y = SPEC_X.replace("S-X", "S-Y").replace("Synthetic trend rule", "Second synthetic rule")


def _gates(fail_at: str | None, *, missing: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(1, 15):
        gid = f"G{i}"
        if gid == missing:
            continue
        if gid == fail_at:
            out.append({"gate_id": gid, "status": "abstain", "passed": False, "reason_code": "insufficient_evidence",
                        "value": "12", "threshold": "30", "detail": "synthetic"})  # fmt: skip
        else:
            out.append({"gate_id": gid, "status": "pass", "passed": True, "reason_code": None, "value": None,
                        "threshold": None, "detail": ""})  # fmt: skip
    return out


def _stats() -> dict[str, Any]:
    return {
        "stats": {
            "formula_ids": ["BT-WF@1", "BT-GATES@1", "BT-RUNNER@1"],
            "n_oos_periods": 12,
            "first_oos_date": "2020-01-31",
            "last_oos_date": "2020-12-31",
            "mean_edge_per_period": "0.001000",
            "expected_excess_after_decay_haircut": "0.000500",
            "min_trl_periods": "250.000000",
            "power_80_periods": "400.000000",
            "earliest_review": "2047-08",
        },
        "verdict": {"state": "ABSTAIN", "reason_code": "insufficient_evidence", "gate_id": "G5"},
    }


def _inner(app: Any) -> Any:
    while not hasattr(app, "state"):
        app = app.app
    return app


def _register(conn: Any, rule_id: str, spec: str, *, state: str = "ABSTAIN") -> None:
    ledger.register_rules(
        conn, [ledger.SignalRule(rule_id, 1, "S", "synthetic_trend", spec, sha256_hex(spec), TS, state, None, TS)]
    )


def _trial(conn: Any, trial_id: str, rule_id: str) -> None:
    ledger.append_trials(conn, [ledger.BacktestTrial(
        trial_id, rule_id, 1, "synthetic_trend", "{}", "[]", "1m", "buy_and_hold", "h" * 64, "test", "r", "1",
        "active", TS,
    )])  # fmt: skip


def _run(conn: Any, run_id: str, trial_id: str, gates: list[dict[str, Any]], at: str = TS) -> None:
    ledger.append_backtest_runs(conn, [ledger.BacktestRun(
        run_id, trial_id, "{}", "o" * 64, canonical_json(gates), canonical_json(_stats()), "ABSTAIN", 0, at,
    )])  # fmt: skip


SCOPE = "role:test_fund.alpha.direct"


def _evaluation(conn: Any, rule_id: str, as_of: str, met: int | None, scope: str = SCOPE) -> None:
    payload = canonical_json({"position_if_met": "in", "shown_as_action": False})
    ledger.append_rule_evaluations(conn, [ledger.RuleEvaluation(
        rule_id, 1, as_of, scope, "ABSTAIN", met, payload, sha256_hex(f"{rule_id}{as_of}{scope}"), "s" * 64, TS,
    )])  # fmt: skip


def _seed(conn: Any) -> None:
    _register(conn, "S-X", SPEC_X)
    _register(conn, "S-Y", SPEC_Y, state="PRE_REGISTERED")
    _trial(conn, "trial:x-main", "S-X")
    _trial(conn, "trial:x-neighbour", "S-X")
    _run(conn, "run:x-old", "trial:x-main", _gates("G2"), at="2026-10-01T00:00:00+00:00")
    _run(conn, "run:x-new", "trial:x-main", _gates("G5"))
    _evaluation(conn, "S-X", "2026-09-30", 1)
    _evaluation(conn, "S-X", "2026-10-15", 0)
    ledger.append_outcomes(conn, [ledger.Outcome(
        "S-X", 1, "2026-09-30", "role:test_fund.alpha.direct", "2026-10-31", "unscorable", None,
        "synthetic_reason", "i" * 64, TS,
    )])  # fmt: skip
    conn.commit()


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str], Any]]:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    app = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    c = TestClient(app, base_url=ORIGIN)
    with c:
        token = settings.token_path.read_text().strip()
        csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
        yield c, {"Origin": ORIGIN, "X-IIP-CSRF": csrf}, _inner(app).state.iip.conn


def _ts_fields(interface: str) -> set[str]:
    """Field names of ``export interface <name> { ... }`` in types-signals.ts (one level, comments stripped)."""
    text = TYPES_SIGNALS.read_text(encoding="utf-8")
    m = re.search(r"export interface " + interface + r" \{(.*?)\n\}", text, re.S)
    assert m is not None, interface
    body = re.sub(r"/\*\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"\{[^{}]*\}", "{}", body)  # inline object types
    return {f.group(1) for f in re.finditer(r"^\s*([a-z_0-9]+)\??:", body, re.M)}


# ---------------------------------------------------------------------------------------------- existence + session


def test_signal_routes_exist_for_a_logged_in_user(api: Any) -> None:
    c, _h, conn = api
    _seed(conn)
    assert c.get("/api/signals").status_code == 200  # was 404 before this router existed
    assert c.get("/api/signals/S-X/1").status_code == 200


def test_signal_routes_require_a_session(tmp_path: Path) -> None:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    with TestClient(create_app(settings, routers=all_routers(), clock=lambda: NOW), base_url=ORIGIN) as c:
        for path in ("/api/signals", "/api/signals/S-X/1"):
            r = c.get(path)
            assert r.status_code == 401, (path, r.status_code)


def test_signal_routes_are_read_only(api: Any) -> None:
    c, h, _conn = api
    assert c.post("/api/signals", json={}, headers=h).status_code == 405
    assert c.request("DELETE", "/api/signals/S-X/1", json={}, headers=h).status_code == 405


def test_unknown_rule_is_404_and_bad_keys_are_422(api: Any) -> None:
    c, _h, _conn = api
    r = c.get("/api/signals/S-Z/1")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "UNKNOWN_RULE"
    assert c.get("/api/signals/S-X/0").status_code == 422
    assert c.get("/api/signals/S-X/one").status_code == 422


# ---------------------------------------------------------------------------------------------- registry contract


def test_empty_registry(api: Any) -> None:
    c, _h, _conn = api
    assert c.get("/api/signals").json() == {"as_of": None, "vocabulary": "neutral", "rules": []}


def test_every_row_carries_its_failing_gate_from_the_registry(api: Any) -> None:
    c, _h, conn = api
    _seed(conn)
    body = c.get("/api/signals").json()
    assert set(body) == _ts_fields("SignalsResponse")
    assert body["as_of"] == "2026-10-15"
    assert body["vocabulary"] == "neutral"
    x, y = body["rules"]
    for row in (x, y):
        assert set(row) == _ts_fields("SignalRuleSummary")
        assert set(row["shadow"]) == _ts_fields("ShadowSummary")
        assert set(row["failing_gate"]) == _ts_fields("GateResultJson")
        assert row["failing_gate"]["passed"] is False
    # S-X: the NEWEST run's panel (G5), not the older one (G2).
    assert (x["rule_id"], x["state"], x["title"]) == ("S-X", "ABSTAIN", "Synthetic trend rule for tests")
    assert x["failing_gate"]["gate_id"] == "G5"
    assert x["failing_gate"]["reason_code"] == "insufficient_evidence"
    assert (x["failing_gate"]["value"], x["failing_gate"]["threshold"]) == ("12", "30")
    assert x["trial_count"] == 2
    assert x["earliest_review"] == "2047-08"
    assert x["shadow"] == {
        "evaluations": 2, "first_as_of": "2026-09-30", "last_as_of": "2026-10-15", "condition_met": 1,
        "outcomes_scored": 0, "outcomes_unscorable": 1,
    }  # fmt: skip
    # S-Y: registered, never backtested → G1 abstains with no_backtest_run (fails closed).
    assert y["failing_gate"]["gate_id"] == "G1"
    assert y["failing_gate"]["status"] == "abstain"
    assert y["failing_gate"]["reason_code"] == "no_backtest_run"
    assert y["earliest_review"] is None
    assert y["trial_count"] == 2  # G8 counts the whole family


def test_rule_detail_contract_and_shadow_rows(api: Any) -> None:
    c, _h, conn = api
    _seed(conn)
    d = c.get("/api/signals/S-X/1").json()
    assert set(d) == _ts_fields("RuleDetailResponse")
    assert set(d["power"]) == _ts_fields("PowerInfo")
    assert set(d["publication"]) == _ts_fields("PublicationInfo")
    assert set(d["expected_excess"]) == _ts_fields("ExpectedExcess")
    assert all(set(r) == _ts_fields("ShadowRow") for r in d["shadow"])
    assert d["rule"]["failing_gate"]["gate_id"] == "G5"
    assert [g["gate_id"] for g in d["gates"]] == [f"G{i}" for i in range(1, 15)]
    assert d["rule_text"] == "S_m = 1 if C_m > mean(C_{m-3..m}) else 0"
    assert d["roles"] == ["test_fund.alpha.direct", "test_fund.cash.direct"]
    assert d["spec_hash"] == sha256_hex(SPEC_X)
    assert d["power"] == {
        "n_oos_periods": 12, "min_oos_periods": 30, "min_trl_months": "250.000000", "power80_months": "400.000000",
        "earliest_review": "2047-08", "formula_ids": ["BT-WF@1", "BT-GATES@1", "BT-RUNNER@1"],
    }  # fmt: skip
    assert d["publication"]["tag"] == "POST_PUBLICATION"
    assert d["publication"]["published_on"] == "2001-01-01"
    assert d["expected_excess"]["after_haircut"] == "0.000500"
    assert d["expected_excess"]["period_months"] == 1
    assert [(r["as_of_date"], r["condition_met"], r["direction"]) for r in d["shadow"]] == [
        ("2026-10-15", False, None),
        ("2026-09-30", True, "entry"),
    ]
    assert d["shadow"][1]["outcome_status"] == "unscorable"
    assert d["shadow"][1]["unscorable_reason"] == "synthetic_reason"
    assert d["latest"] is None  # ABSTAIN: the shadow record is never shown as a live condition


def test_accepted_state_with_a_failing_gate_still_has_no_latest(api: Any) -> None:
    """Fail closed: the registry state alone never makes a rule live."""
    c, _h, conn = api
    _register(conn, "S-X", SPEC_X, state="ACCEPTED")
    _trial(conn, "trial:x-main", "S-X")
    _run(conn, "run:x", "trial:x-main", _gates(None, missing="G12"))
    _evaluation(conn, "S-X", "2026-10-15", 1)
    conn.commit()
    d = c.get("/api/signals/S-X/1").json()
    assert d["rule"]["failing_gate"]["gate_id"] == "G12"
    assert d["rule"]["failing_gate"]["reason_code"] == "gate_not_reported"
    assert d["latest"] is None


def test_accepted_rule_with_every_gate_passed_reports_its_latest_condition(api: Any) -> None:
    c, _h, conn = api
    _register(conn, "S-X", SPEC_X, state="ACCEPTED")
    _trial(conn, "trial:x-main", "S-X")
    _run(conn, "run:x", "trial:x-main", _gates(None))
    _evaluation(conn, "S-X", "2026-10-15", 1)
    conn.commit()
    d = c.get("/api/signals/S-X/1").json()
    assert d["rule"]["failing_gate"] is None
    assert d["latest"] == {"as_of_date": "2026-10-15", "condition_met": True, "direction": "entry"}


def test_vocabulary_follows_the_settings_wire_value(api: Any) -> None:
    """typescript-reviewer-4 / react-reviewer-5: one vocabulary value end to end (Settings PUT → Signals GET)."""
    c, h, conn = api
    _seed(conn)
    assert c.get("/api/signals/S-X/1").json()["vocabulary"] == "neutral"
    r = c.put("/api/settings/vocabulary", json={"mode": "badges", "acknowledge_private_only": True}, headers=h)
    assert r.status_code == 200, r.text
    assert c.get("/api/signals").json()["vocabulary"] == "badges"
    assert c.get("/api/signals/S-X/1").json()["vocabulary"] == "badges"


def test_gate_values_are_strings_not_floats(api: Any) -> None:
    c, _h, conn = api
    _seed(conn)
    text = c.get("/api/signals/S-X/1").text
    for g in json.loads(text)["gates"]:
        assert g["value"] is None or isinstance(g["value"], str)
        assert g["threshold"] is None or isinstance(g["threshold"], str)
