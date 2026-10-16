"""GOAL-1 / GOAL-2 (wave-2 follow-up): goal updates merge, every goal field round-trips, answers can be cleared.

* ``GET/PUT /api/goals/setup`` return every goal field, ``objective`` and ``h_safe_years`` included.
* Updating a goal (``PUT /api/goals/{id}`` or a setup goal carrying its ``goal_id``) changes only the fields the body
  carries. An omitted field keeps its stored value; an explicit ``null`` on a goal field still clears it.
* ``PUT /api/goals/setup`` keeps ``null`` = "keep the stored answer" for the emergency and extras answers, and adds an
  explicit ``clear`` list for clearing one.

Every number in this file is SYNTHETIC.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.api.test_goals_api import Client, _app, _goal, _login


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Client]:
    c, settings = _app(tmp_path)
    with c:
        yield c, _login(c, settings), settings


def _full_goal() -> dict[str, object]:
    return _goal(h_safe_years="7.5", priority=3)


def _created(api: Client) -> str:
    c, h, _ = api
    r = c.post("/api/goals", json=_full_goal(), headers=h)
    assert r.status_code == 200, r.text
    return str(r.json()["goal_id"])


# ---------------------------------------------------------------------------------------------- GOAL-1


def test_setup_state_returns_every_goal_field(api: Client) -> None:
    c, _h, _ = api
    gid = _created(api)
    (goal,) = c.get("/api/goals/setup").json()["answers"]["goals"]
    assert goal == {
        "goal_id": gid,
        "name": "Long-term growth",
        "priority": 3,
        "target_amount": "1000000",
        "target_date": "2036-04-01",
        "objective": "D_growth",
        "loss_budget_inr": "250000",
        "recovery_months": 36,
        "h_safe_years": "7.5",
    }


def test_put_goal_merges_only_the_fields_it_carries(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    r = c.put(f"/api/goals/{gid}", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["name"] == "Renamed"
    assert g["objective"] == "D_growth" and g["h_safe_years"] == "7.5" and g["priority"] == 3
    assert g["target_amount"] == "1000000" and g["loss_budget_inr"] == "250000" and g["recovery_months"] == 36
    assert g["target_date"] == "2036-04-01"


def test_put_goal_explicit_null_still_clears_a_goal_field(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    g = c.put(f"/api/goals/{gid}", json={"h_safe_years": None, "objective": None}, headers=h).json()
    assert g["h_safe_years"] is None and g["objective"] is None
    assert g["name"] == "Long-term growth" and g["loss_budget_inr"] == "250000"


def test_put_goal_name_cannot_be_cleared(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    assert c.put(f"/api/goals/{gid}", json={"name": None}, headers=h).status_code == 422
    assert c.put(f"/api/goals/{gid}", json={"name": "  "}, headers=h).status_code == 422


def test_merged_goal_is_validated_and_nothing_is_written_on_refusal(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    # The stored target is 1,000,000; a loss limit above it is refused only once merged with the stored goal.
    r = c.put(f"/api/goals/{gid}", json={"loss_budget_inr": "1500000"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_INPUT", r.text
    (goal,) = c.get("/api/goals").json()["goals"]
    assert goal["loss_budget_inr"] == "250000"


def test_put_goal_keeps_csrf_and_unknown_id(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    assert c.put(f"/api/goals/{gid}", json={"name": "X"}, headers={"Origin": h["Origin"]}).status_code == 403
    assert c.put("/api/goals/g-000000000000", json={"name": "X"}, headers=h).status_code == 404


def test_create_still_needs_a_name(api: Client) -> None:
    c, h, _ = api
    assert c.post("/api/goals", json={"target_amount": "1000"}, headers=h).status_code == 422


def test_setup_goal_with_id_merges_and_keeps_objective_and_horizon(api: Client) -> None:
    c, h, _ = api
    gid = _created(api)
    body = {"goals": [{"goal_id": gid, "loss_budget_inr": "200000"}]}
    r = c.put("/api/goals/setup", json=body, headers=h)
    assert r.status_code == 200, r.text
    (goal,) = r.json()["answers"]["goals"]
    assert goal["loss_budget_inr"] == "200000"
    assert goal["objective"] == "D_growth" and goal["h_safe_years"] == "7.5" and goal["name"] == "Long-term growth"


def test_setup_new_goal_needs_a_name(api: Client) -> None:
    c, h, _ = api
    r = c.put("/api/goals/setup", json={"goals": [{"goal_id": None, "target_amount": "1000"}]}, headers=h)
    assert r.status_code == 422
    assert c.get("/api/goals/setup").json()["answers"]["goals"] == []
