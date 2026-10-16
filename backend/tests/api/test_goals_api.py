"""Goals, risk profile, tax context, policy and the six-answer setup API (PLAN.md wave 2, package B01).

Acceptance checks covered here:
* CRUD, mapping, CSRF and session behaviour identical to the other routes.
* The loss limit is stored in ₹ per goal.
* Every response that carries goal figures shows the stress history *before* any return figure (and carries no
  return figure at all).
* The policy refuses to load without user-set values.

Every number in this file is SYNTHETIC. The stress values below are made up for the test and are deliberately not the
cited index drawdowns (those stay in the user's local config, U-08).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from iip.api.app import create_app
from iip.api.routes import all_routers
from iip.api.settings import Settings
from iip.rules.loader import local_stress_values_path
from iip.services import goals as svc

ORIGIN = "http://127.0.0.1:8741"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)

# SYNTHETIC values (not the cited figures).
LOCAL_STRESS = """\
schema_version: 1
values:
  - risk_class: EQ_LARGE
    stress: "0.400"
    recovery_years: "2.0"
  - risk_class: EQ_BROAD
    stress: "0.500"
    recovery_years: "4.0"
"""

Client = tuple[TestClient, dict[str, str], Settings]


def _app(tmp_path: Path, *, local_stress: str | None = LOCAL_STRESS) -> tuple[TestClient, Settings]:
    settings = Settings(env="prod", data_dir=tmp_path / "iip")
    if local_stress is not None:
        p = local_stress_values_path(settings.data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(local_stress)
    app = create_app(settings, routers=all_routers(), clock=lambda: NOW)
    return TestClient(app, base_url=ORIGIN), settings


def _login(c: TestClient, settings: Settings) -> dict[str, str]:
    token = settings.token_path.read_text().strip()
    csrf = c.post("/api/session", json={"token": token}, headers={"Origin": ORIGIN}).json()["csrf"]
    return {"Origin": ORIGIN, "X-IIP-CSRF": csrf}


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Client]:
    c, settings = _app(tmp_path)
    with c:
        yield c, _login(c, settings), settings


def _goal(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Long-term growth",
        "target_amount": "1000000",
        "target_date": "2036-04-01",
        "objective": "D_growth",
        "loss_budget_inr": "250000",
        "recovery_months": 36,
    }
    body.update(over)
    return body


RETURN_WORDS = re.compile(r'"[a-z_]*(return|cagr|xirr|aspiration|expected|yield)[a-z_]*"\s*:', re.IGNORECASE)


def _assert_stress_first(text: str) -> None:
    """The stress history is the first thing in the body, and no return figure appears anywhere."""
    assert RETURN_WORDS.search(text) is None, RETURN_WORDS.search(text)
    first_key = re.match(r'\s*\{\s*"([^"]+)"', text)
    assert first_key is not None and first_key.group(1) in ("stress_history", "worst_fall_on_target"), text[:120]


# ---------------------------------------------------------------------------------------------- session and CSRF


def test_routes_require_a_session(tmp_path: Path) -> None:
    c, _ = _app(tmp_path)
    with c:
        for method, path in [
            ("GET", "/api/goals"),
            ("POST", "/api/goals"),
            ("PUT", "/api/goals/g-0123456789ab"),
            ("DELETE", "/api/goals/g-0123456789ab"),
            ("PUT", "/api/goals/mapping"),
            ("GET", "/api/goals/stress-history"),
            ("GET", "/api/goals/risk-profile"),
            ("PUT", "/api/goals/risk-profile"),
            ("GET", "/api/goals/tax-context"),
            ("PUT", "/api/goals/tax-context"),
            ("GET", "/api/goals/policy"),
            ("PUT", "/api/goals/policy"),
            ("POST", "/api/goals/setup"),
        ]:
            assert c.request(method, path, headers={"Origin": ORIGIN}).status_code == 401, (method, path)


def test_writes_enforce_csrf_and_origin(api: Client) -> None:
    c, h, _ = api
    no_csrf = {"Origin": ORIGIN}
    hostile = {**h, "Origin": "https://evil.example"}
    for headers in (no_csrf, hostile, {**h, "X-IIP-CSRF": "wrong"}):
        assert c.post("/api/goals", json=_goal(), headers=headers).status_code == 403
        assert c.put("/api/goals/risk-profile", json={"emergency_months": 6}, headers=headers).status_code == 403
        assert c.post("/api/goals/setup", json={"goals": []}, headers=headers).status_code == 403
    assert c.get("/api/goals").json()["goals"] == []  # nothing was written


# ---------------------------------------------------------------------------------------------- goals CRUD


def test_goal_crud_and_loss_limit_in_rupees(api: Client) -> None:
    c, h, settings = api
    r = c.post("/api/goals", json=_goal(), headers=h)
    assert r.status_code == 200, r.text
    created = r.json()
    gid = created["goal_id"]
    assert re.fullmatch(r"g-[0-9a-f]{12}", gid)
    assert created["loss_budget_inr"] == "250000"  # ₹, a Decimal string, never a float
    assert created["objective"] == "D_growth"
    assert created["priority"] == 1

    # stored in ₹ per goal (the A10 column), not as a fraction
    from iip.store.db import connect

    conn = connect(settings.db_path)
    try:
        row = conn.execute("SELECT loss_budget_inr, objective FROM goals WHERE goal_id=?", (gid,)).fetchone()
    finally:
        conn.close()
    assert row["loss_budget_inr"] == "250000" and row["objective"] == "D"

    upd = c.put(f"/api/goals/{gid}", json=_goal(name="Retirement", loss_budget_inr="200000"), headers=h)
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Retirement" and upd.json()["loss_budget_inr"] == "200000"

    listed = c.get("/api/goals").json()["goals"]
    assert [g["goal_id"] for g in listed] == [gid]

    assert c.put("/api/goals/g-000000000000", json=_goal(), headers=h).status_code == 404
    assert c.delete(f"/api/goals/{gid}", headers=h).status_code == 403  # DELETE needs a JSON type, as elsewhere
    jh = {**h, "Content-Type": "application/json"}
    assert c.delete(f"/api/goals/{gid}", headers=jh).status_code == 200
    assert c.delete(f"/api/goals/{gid}", headers=jh).status_code == 404
    assert c.get("/api/goals").json()["goals"] == []


def test_second_goal_gets_next_priority(api: Client) -> None:
    c, h, _ = api
    c.post("/api/goals", json=_goal(), headers=h)
    second = c.post("/api/goals", json=_goal(name="House"), headers=h).json()
    assert second["priority"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"target_amount": 1000000.5},  # floats refused over the wire
        {"loss_budget_inr": 250000.0},
        {"loss_budget_inr": "-1"},
        {"loss_budget_inr": "2000000"},  # a loss larger than the goal itself
        {"objective": "Z_gamble"},
        {"name": ""},
        {"recovery_months": -1},
        {"unknown_field": "x"},
    ],
)
def test_goal_validation(api: Client, bad: dict[str, object]) -> None:
    c, h, _ = api
    assert c.post("/api/goals", json=_goal(**bad), headers=h).status_code == 422


def test_goal_id_path_is_constrained(api: Client) -> None:
    c, h, _ = api
    assert c.put("/api/goals/not-an-id", json=_goal(), headers=h).status_code in (404, 405, 422)


def test_goal_without_loss_limit_abstains_on_equity(api: Client) -> None:
    c, h, _ = api
    g = c.post("/api/goals", json=_goal(loss_budget_inr=None), headers=h).json()
    assert g["equity_status"] == "ABSTAIN"
    assert any("loss limit" in m.lower() for m in g["missing"])
    ok = c.post("/api/goals", json=_goal(name="Other"), headers=h).json()
    assert ok["equity_status"] == "INPUTS_COMPLETE" and ok["missing"] == []


# ---------------------------------------------------------------------------------------------- stress history first


def test_overview_shows_stress_history_before_anything_else(api: Client) -> None:
    c, h, _ = api
    c.post("/api/goals", json=_goal(), headers=h)
    r = c.get("/api/goals")
    assert r.status_code == 200
    _assert_stress_first(r.text)
    body = r.json()
    assert next(iter(body)) == "stress_history"
    goal = body["goals"][0]
    assert next(iter(goal)) == "worst_fall_on_target"


def test_stress_history_rows_and_rupee_illustration(api: Client) -> None:
    c, _, _ = api
    r = c.get("/api/goals/stress-history", params={"amount": "1000000"})
    assert r.status_code == 200, r.text
    _assert_stress_first(json.dumps({"stress_history": r.json()}))
    sh = r.json()
    assert sh["kind"] == "HISTORICAL_WORST_OBSERVED_FALL"
    assert any("not the worst possible" in cv for cv in sh["caveats"])
    rows = {row["risk_class"]: row for row in sh["rows"]}
    assert "STOCK" not in rows  # U-10: stocks abstain; no stock row is offered
    broad = rows["EQ_BROAD"]
    assert broad["stress"] == "0.500" and broad["chosen"] == "CITED"
    assert broad["status"] == "NOT VERIFIED"  # the AMFI recompute is not available, so max() could not be applied
    assert "RECOMPUTED_DRAWDOWN_MISSING" in broad["flags"]
    assert broad["loss_on_amount"] == "500000.00"  # 1,000,000 × 0.500
    assert broad["loss_formula_id"] == svc.STRESS_ON_AMOUNT_ID
    assert broad["recovery_years"] == "4.0"
    assert broad["source_url"].startswith("doc:")
    hybrid = rows["HYBRID"]
    assert hybrid["stress"] == "0.500" and "HYBRID_AS_EQ_BROAD" in hybrid["flags"]
    mid = rows["EQ_MID"]  # not in the synthetic local file
    assert mid["outcome"] == "ABSTAIN" and mid["stress"] is None and mid["loss_on_amount"] is None
    assert "EQ_MID" in sh["requires_configuration"]
    debt = rows["DEBT_MTM"]
    assert debt["stress"] is None and debt["formula"] == "D_mod * dy + D_spread * ds"
    assert rows["CASH_LIKE"]["stress"] == "0"


def test_stress_history_without_local_config_abstains(tmp_path: Path) -> None:
    c, settings = _app(tmp_path, local_stress=None)
    with c:
        _login(c, settings)
        sh = c.get("/api/goals/stress-history").json()
    assert sh["local_values_loaded"] is False
    equity = [r for r in sh["rows"] if r["risk_class"].startswith("EQ_")]
    assert equity and all(r["outcome"] == "ABSTAIN" and r["stress"] is None for r in equity)
    assert sh["amount"] is None


def test_stress_history_rejects_bad_amount(api: Client) -> None:
    c, _, _ = api
    assert c.get("/api/goals/stress-history", params={"amount": "-5"}).status_code == 422
    assert c.get("/api/goals/stress-history", params={"amount": "abc"}).status_code == 422


def test_goal_shows_worst_fall_on_its_target_and_recovery_note(api: Client) -> None:
    c, h, _ = api
    g = c.post("/api/goals", json=_goal(recovery_months=24), headers=h)
    _assert_stress_first(g.text)
    body = g.json()
    lines = {x["risk_class"]: x for x in body["worst_fall_on_target"]}
    assert lines["EQ_BROAD"]["loss_on_amount"] == "500000.00"
    assert lines["EQ_LARGE"]["loss_on_amount"] == "400000.00"
    assert "EQ_MID" not in lines  # abstaining classes are not illustrated
    # recovery tolerance 24 months < 4.0 years in the synthetic worst episode → a historical note, not a prediction
    assert any("4.0 years" in n and "2.0 years" in n for n in body["recovery_notes"])
    assert body["loss_budget_fraction"] == "0.25"  # B / V = 250000 / 1000000 (risk.loss_budget@1 input b)


# ---------------------------------------------------------------------------------------------- mapping


def _instrument(settings: Settings, iid: str) -> None:
    from iip.store.db import connect

    conn = connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO instruments(instrument_id, kind, name, origin, created_at) VALUES (?, 'mf_scheme', ?,"
            " 'fixture', ?)",
            (iid, "Synthetic Fund", NOW.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def test_mapping_replace_and_validation(api: Client) -> None:
    c, h, settings = api
    _instrument(settings, "mf:900001")
    a = c.post("/api/goals", json=_goal(), headers=h).json()["goal_id"]
    b = c.post("/api/goals", json=_goal(name="House"), headers=h).json()["goal_id"]
    links = [
        {"instrument_id": "mf:900001", "folio": "F1", "goal_id": a, "fraction": "0.6"},
        {"instrument_id": "mf:900001", "folio": "F1", "goal_id": b, "fraction": "0.4"},
    ]
    r = c.put("/api/goals/mapping", json={"links": links}, headers=h)
    assert r.status_code == 200, r.text
    assert {(x["goal_id"], x["fraction"]) for x in r.json()["mapping"]} == {(a, "0.6"), (b, "0.4")}

    over = [{**links[0], "fraction": "0.7"}, links[1]]
    assert c.put("/api/goals/mapping", json={"links": over}, headers=h).status_code == 422
    unknown_goal = [{**links[0], "goal_id": "g-ffffffffffff"}]
    assert c.put("/api/goals/mapping", json={"links": unknown_goal}, headers=h).status_code == 422
    unknown_holding = [{**links[0], "instrument_id": "mf:999999"}]
    assert c.put("/api/goals/mapping", json={"links": unknown_holding}, headers=h).status_code == 422
    assert c.put("/api/goals/mapping", json={"links": [{**links[0], "fraction": 0.5}]}, headers=h).status_code == 422
    # failed writes left the earlier mapping untouched
    assert len(c.get("/api/goals").json()["mapping"]) == 2

    # deleting a goal cascades its links (those holdings become Unassigned)
    assert c.delete(f"/api/goals/{b}", headers={**h, "Content-Type": "application/json"}).status_code == 200
    assert [x["goal_id"] for x in c.get("/api/goals").json()["mapping"]] == [a]


# ---------------------------------------------------------------------------------------------- risk profile, tax


def test_risk_profile_roundtrip(api: Client) -> None:
    c, h, _ = api
    assert c.get("/api/goals/risk-profile").json()["missing"] != []
    body = {"essential_monthly_expenses": "50000", "emergency_months": 6, "savings_balance": "100000"}
    r = c.put("/api/goals/risk-profile", json=body, headers=h)
    assert r.status_code == 200, r.text
    got = c.get("/api/goals/risk-profile").json()
    assert got["essential_monthly_expenses"] == "50000" and got["emergency_months"] == 6
    assert got["missing"] == []
    assert c.put("/api/goals/risk-profile", json={"emergency_months": 99}, headers=h).status_code == 422
    assert c.put("/api/goals/risk-profile", json={"savings_balance": 10.5}, headers=h).status_code == 422


def test_tax_context_entered_and_conservative(api: Client) -> None:
    c, h, _ = api
    empty = c.get("/api/goals/tax-context").json()
    assert empty["fy"] == "2026-27"  # 15-Oct-2026 falls in FY 2026-27
    assert empty["assumption"] == svc.CONSERVATIVE_TAX_LABEL
    r = c.put("/api/goals/tax-context", json={"regime": "new", "slab_rate": "0.30"}, headers=h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["regime"] == "new" and got["slab_rate"] == "0.30" and got["ltcg_used_assumed"] is True
    assert got["assumption"] == svc.CONSERVATIVE_LTCG_LABEL  # slab given; LTCG used elsewhere still assumed
    got = c.put("/api/goals/tax-context", json={"regime": "new", "slab_rate": "0.30", "ltcg_used_inr": "0"},
                headers=h).json()  # fmt: skip
    assert got["ltcg_used_assumed"] is False and got["assumption"] is None
    cons = c.put("/api/goals/tax-context", json={"use_conservative_assumption": True}, headers=h).json()
    assert cons["regime"] is None and cons["slab_rate"] is None and cons["assumption"] == svc.CONSERVATIVE_TAX_LABEL
    bad = {"use_conservative_assumption": True, "slab_rate": "0.30"}
    assert c.put("/api/goals/tax-context", json=bad, headers=h).status_code == 422
    assert c.put("/api/goals/tax-context", json={"slab_rate": "0.9"}, headers=h).status_code == 422


@pytest.mark.parametrize(
    ("iso", "fy"), [("2026-04-01", "2026-27"), ("2026-03-31", "2025-26"), ("2027-01-15", "2026-27")]
)
def test_financial_year(iso: str, fy: str) -> None:
    from datetime import date

    assert svc.financial_year(date.fromisoformat(iso)) == fy


# ---------------------------------------------------------------------------------------------- policy


def _targets() -> list[dict[str, object]]:
    return [
        {
            "band_id": "H3_5Y_PLUS",
            "objective": "D_growth",
            "weights": {"EQUITY": "0.6", "DEBT": "0.4"},
            "decided_on": "2026-10-10",
            "set_by": "user",
        }
    ]


def test_policy_refuses_to_load_without_user_values(api: Client) -> None:
    c, h, settings = api
    r = c.get("/api/goals/policy")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "POLICY_REQUIRES_USER_VALUES"
    # the service refuses as well (the snapshot job calls it directly)
    from iip.store.db import connect

    conn = connect(settings.db_path)
    try:
        with pytest.raises(svc.PolicyNotConfigured):
            svc.load_policy(conn)
    finally:
        conn.close()
    # a policy with no user-set targets is not accepted
    assert c.put("/api/goals/policy", json={"decided_on": "2026-10-10", "targets": []}, headers=h).status_code == 422
    not_user = [{**_targets()[0], "set_by": "default"}]
    assert c.put("/api/goals/policy", json={"decided_on": "2026-10-10", "targets": not_user},
                 headers=h).status_code == 422  # fmt: skip
    bad_sum = [{**_targets()[0], "weights": {"EQUITY": "0.6", "DEBT": "0.3"}}]
    assert c.put("/api/goals/policy", json={"decided_on": "2026-10-10", "targets": bad_sum},
                 headers=h).status_code == 422  # fmt: skip
    future = {"decided_on": "2026-12-01", "targets": _targets()}
    assert c.put("/api/goals/policy", json=future, headers=h).status_code == 422
    assert c.get("/api/goals/policy").status_code == 409


def test_policy_roundtrip_with_labelled_defaults(api: Client) -> None:
    c, h, settings = api
    r = c.put("/api/goals/policy", json={"decided_on": "2026-10-10", "targets": _targets()}, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["targets"][0]["weights"] == {"EQUITY": "0.6", "DEBT": "0.4"}
    params = {x["parameter"]: x for x in p["parameters"]}
    assert params["rebalance_mode"] == {"parameter": "rebalance_mode", "value": "CASH_FLOW_ONLY",
                                        "set_by": "PARAMETER_DEFAULT"}  # fmt: skip
    assert params["band_abs"]["value"] == "0.05" and params["band_abs"]["set_by"] == "PARAMETER_DEFAULT"
    again = c.put("/api/goals/policy", json={"decided_on": "2026-10-10", "targets": _targets()}, headers=h).json()
    assert again["policy_version_id"] == p["policy_version_id"]  # content-addressed
    custom = {"decided_on": "2026-10-11", "targets": _targets(), "band_abs": "0.10", "rebalance_mode": "SALES_ALLOWED"}
    p2 = c.put("/api/goals/policy", json=custom, headers=h).json()
    assert p2["policy_version_id"] != p["policy_version_id"]
    params2 = {x["parameter"]: x for x in p2["parameters"]}
    assert params2["band_abs"] == {"parameter": "band_abs", "value": "0.10", "set_by": "user"}
    assert c.get("/api/goals/policy").json()["policy_version_id"] == p2["policy_version_id"]
    assert c.put("/api/goals/policy", json={**custom, "band_abs": 0.1}, headers=h).status_code == 422
    assert c.put("/api/goals/policy", json={**custom, "rebalance_mode": "YOLO"}, headers=h).status_code == 422

    from iip.store.db import connect

    conn = connect(settings.db_path)
    try:
        loaded = svc.load_policy(conn)
    finally:
        conn.close()
    assert loaded.targets[0].weight("EQUITY") == Decimal("0.6")


# ---------------------------------------------------------------------------------------------- six-answer setup


def _setup_body() -> dict[str, object]:
    return {
        "essential_monthly_expenses": "50000",  # answer 1
        "emergency_months": 6,  # answer 2
        "goals": [
            {
                "name": "Long-term growth",  # answer 3: what, how much, when
                "target_amount": "1000000",
                "target_date": "2036-04-01",
                "objective": "D_growth",
                "loss_budget_inr": "250000",  # answer 4: the loss limit in ₹, after seeing the stress history
                "recovery_months": 36,  # answer 5
            }
        ],
        "tax": {"regime": "new", "slab_rate": "0.30"},  # answer 6
    }


def test_six_answer_setup(api: Client) -> None:
    c, h, _ = api
    r = c.post("/api/goals/setup", json=_setup_body(), headers=h)
    assert r.status_code == 200, r.text
    _assert_stress_first(r.text)
    body = r.json()
    assert body["answers"] == {"given": 6, "of": 6, "missing": []}
    assert len(body["goals"]) == 1 and body["goals"][0]["loss_budget_inr"] == "250000"
    assert body["risk_profile"]["emergency_months"] == 6
    assert body["tax_context"]["regime"] == "new"
    assert body["policy"]["status"] == "REQUIRES CONFIGURATION"  # targets are a separate, dated decision

    # re-running setup with the goal id updates instead of duplicating
    gid = body["goals"][0]["goal_id"]
    again = _setup_body()
    again["goals"] = [{**again["goals"][0], "goal_id": gid, "loss_budget_inr": "200000"}]  # type: ignore[index]
    body2 = c.post("/api/goals/setup", json=again, headers=h).json()
    assert [g["goal_id"] for g in body2["goals"]] == [gid]
    assert body2["goals"][0]["loss_budget_inr"] == "200000"


def test_setup_counts_missing_answers_and_uses_conservative_tax(api: Client) -> None:
    c, h, _ = api
    body = {"goals": [{"name": "Emergency"}], "tax": {"use_conservative_assumption": True}}
    r = c.post("/api/goals/setup", json=body, headers=h)
    assert r.status_code == 200, r.text
    ans = r.json()["answers"]
    assert ans["given"] == 1 and ans["of"] == 6  # only the tax answer: a goal needs its amount and date too
    assert len(ans["missing"]) == 5
    assert r.json()["tax_context"]["assumption"] == svc.CONSERVATIVE_TAX_LABEL


def test_setup_is_atomic(api: Client) -> None:
    c, h, _ = api
    bad = _setup_body()
    bad["goals"] = [{**bad["goals"][0], "goal_id": "g-ffffffffffff"}]  # type: ignore[index]  # unknown id
    assert c.post("/api/goals/setup", json=bad, headers=h).status_code == 404
    overview = c.get("/api/goals").json()
    assert overview["risk_profile"]["essential_monthly_expenses"] is None  # nothing from the failed setup stored
