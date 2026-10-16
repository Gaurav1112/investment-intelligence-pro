"""Integration glue: the stored ``today_snapshot@1`` payload reshaped into the C01 ``TodayResponse`` contract.

All data is SYNTHETIC (see ``_snapshot_fixtures``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from iip.services import risk_snapshot as rs
from iip.services.today_view import NO_SNAPSHOT, today_response
from tests.services import _snapshot_fixtures as fx


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _today(conn: Any) -> dict[str, Any]:
    rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(), templates=fx.TEMPLATES)
    return today_response(rs.read_today(conn))


def test_no_snapshot_is_a_state_with_null_ids(conn: Any) -> None:
    view = today_response(rs.read_today(conn))
    assert view["state"] == NO_SNAPSHOT and view["snapshot_id"] is None and view["cards"] == []
    assert view["needs"] == [] and view["suppressed"] == [] and view["top_n"] >= 1


def test_every_number_shows_the_template_display_and_explains_itself(conn: Any) -> None:
    fx.seed_two_goals(conn)
    view = _today(conn)
    breach = next(c for c in view["cards"] if c["kind"] == "LOSS_BUDGET_BREACH")
    assert breach["layer"] == "L3" and breach["goal_name"] == "House" and breach["why"]["rule_ref"]
    for n in breach["numbers"]:
        assert n["display"] and n["explain"]["display"] == n["display"]
        assert n["explain"]["inputs"] == [f"fact {f}" for f in n["fact_ids"]]
        assert n["explain"]["formula_id"] == (n["formula_id"] or "")
    # Every display the template rendered appears in the text, so each number in the sentence is clickable.
    for n in breach["numbers"]:
        if n["slot"] in {"loss_limit", "stress_loss", "redirect_amount"}:
            assert n["display"] in breach["text"]
    step_numbers = [x for s in breach["steps"] for x in s["numbers"]]
    assert step_numbers and all(x["formula_id"] == breach["steps"][0]["formula_id"] for x in step_numbers)
    assert "expected_return" not in json.dumps(view)


def test_only_done_decisions_reach_the_card(conn: Any) -> None:
    fx.seed_two_goals(conn)
    rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(), templates=fx.TEMPLATES)
    raw = rs.read_today(conn)
    action = next(c for c in raw["cards"] if c["is_action"])
    rs.record_decision(conn, snapshot_id=raw["snapshot_id"], card_id=action["card_id"], decision="not_now",
                       note=None, now=fx.NOW)  # fmt: skip
    card = next(c for c in today_response(rs.read_today(conn))["cards"] if c["card_id"] == action["card_id"])
    assert card["decision"] is None
    rs.record_decision(conn, snapshot_id=raw["snapshot_id"], card_id=action["card_id"], decision="done",
                       note=None, now=fx.NOW)  # fmt: skip
    card = next(c for c in today_response(rs.read_today(conn))["cards"] if c["card_id"] == action["card_id"])
    assert card["decision"] is not None and card["decision"]["cas_confirmed"] is None


def test_needs_keep_their_order_and_unlocks_are_numbers(conn: Any) -> None:
    fx.seed_two_goals(conn)
    view = _today(conn)
    raw = rs.read_today(conn)
    assert [n["missing_input"] for n in view["needs"]] == [n["missing_input"] for n in raw["needs"]]
    for need in view["needs"]:
        for u in need["unlocks"]:
            assert u["number"]["unit"] == "inr" and u["number"]["formula_id"]
