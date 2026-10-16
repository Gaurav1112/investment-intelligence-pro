"""Integration glue: the Setup and Goals pages' wire shapes (C02 ``frontend/src/lib/types-goals.ts``) over the B01 API.

* GET/PUT ``/api/goals/setup`` return ``SetupState`` (stress history first) and accept ``SetupAnswers``.
* GET ``/api/goals`` carries ``as_of``, ``setup_complete``, ``missing`` and per-goal ``holdings``/``outcome``.

Every number in this file is SYNTHETIC.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.api.test_goals_api import Client, _app, _assert_stress_first, _goal, _instrument, _login


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Client]:
    c, settings = _app(tmp_path)
    with c:
        yield c, _login(c, settings), settings


ANSWERS: dict[str, object] = {
    "tax": {"use_conservative": False, "regime": "new", "slab_rate": "0.2"},
    "emergency": {"essential_monthly_expenses": "40000", "months": 6},
    "goals": [
        {
            "goal_id": None,
            "name": "House",
            "priority": 1,
            "target_amount": "2000000",
            "target_date": "2031-04-01",
            "loss_budget_inr": "300000",
            "recovery_months": 36,
        },
    ],
    "extras": {"ltcg_used_inr": "10000", "savings_balance": "50000", "sweep_fd_balance": None},
}


def test_get_setup_before_any_answer(api: Client) -> None:
    c, _h, _ = api
    r = c.get("/api/goals/setup")
    assert r.status_code == 200
    _assert_stress_first(r.text)
    body = r.json()
    assert body["complete"] is False and body["cas_imported"] is False and body["missing"]
    assert body["answers"]["goals"] == [] and body["answers"]["tax"]["use_conservative"] is False
    row = body["stress_history"]["rows"][0]
    assert row["label"] == row["description"] and row["citation"] == row["source_url"] and row["fact_id"]
    assert body["stress_history"]["caveat"].startswith(body["stress_history"]["caveats"][0])


def test_put_setup_round_trips_every_answer(api: Client) -> None:
    c, h, _ = api
    r = c.put("/api/goals/setup", json=ANSWERS, headers=h)
    assert r.status_code == 200, r.text
    _assert_stress_first(r.text)
    a = r.json()["answers"]
    assert a["tax"] == {"use_conservative": False, "regime": "new", "slab_rate": "0.2"}
    assert a["emergency"] == {"essential_monthly_expenses": "40000", "months": 6}
    assert a["extras"] == {"ltcg_used_inr": "10000", "savings_balance": "50000", "sweep_fd_balance": None}
    (goal,) = a["goals"]
    assert goal["goal_id"].startswith("g-") and goal["loss_budget_inr"] == "300000" and goal["priority"] == 1
    assert r.json()["complete"] is True and r.json()["missing"] == []
    assert c.get("/api/goals/setup").json()["answers"] == a


def test_put_setup_rejects_conservative_with_an_ltcg_figure(api: Client) -> None:
    c, h, _ = api
    bad = {**ANSWERS, "tax": {"use_conservative": True, "regime": None, "slab_rate": None}}
    r = c.put("/api/goals/setup", json=bad, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_INPUT"
    assert c.get("/api/goals/setup").json()["answers"]["goals"] == []  # nothing was written


def test_put_setup_rejects_zero_emergency_months_and_needs_csrf(api: Client) -> None:
    c, h, _ = api
    zero = {**ANSWERS, "emergency": {"essential_monthly_expenses": "40000", "months": 0}}
    assert c.put("/api/goals/setup", json=zero, headers=h).status_code == 422
    assert c.put("/api/goals/setup", json=ANSWERS, headers={"Origin": h["Origin"]}).status_code == 403


def test_goals_view_wire_fields(api: Client) -> None:
    c, h, _ = api
    c.post("/api/goals", json=_goal(loss_budget_inr=None), headers=h)
    body = c.get("/api/goals").json()
    assert next(iter(body)) == "stress_history"
    assert body["as_of"] == "2026-10-15" and body["setup_complete"] is False and body["missing"]
    (goal,) = body["goals"]
    assert goal["outcome"] == "ABSTAIN" and goal["abstentions"] == goal["missing"] and goal["holdings"] == []


def test_goal_holdings_carry_the_instrument_name(api: Client) -> None:
    c, h, settings = api
    _instrument(settings, "mf:900001")
    gid = c.post("/api/goals", json=_goal(), headers=h).json()["goal_id"]
    link = {"instrument_id": "mf:900001", "folio": "F1", "goal_id": gid, "fraction": "0.5"}
    assert c.put("/api/goals/mapping", json={"links": [link]}, headers=h).status_code == 200
    (goal,) = c.get("/api/goals").json()["goals"]
    (held,) = goal["holdings"]
    assert held["instrument_id"] == "mf:900001" and held["folio"] == "F1" and held["fraction"] == "0.5"
    assert held["name"] and held["name"] != "mf:900001"
    edited = c.put(f"/api/goals/{gid}", json=_goal(name="Renamed"), headers=h).json()
    assert [x["instrument_id"] for x in edited["holdings"]] == ["mf:900001"]
