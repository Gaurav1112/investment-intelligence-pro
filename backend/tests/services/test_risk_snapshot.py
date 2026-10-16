"""B02: the risk snapshot (J4 compute). Acceptance checks:

* byte-identical snapshot on re-run, content-addressed id;
* per-goal abstention (a missing input abstains that layer for that goal only);
* ABSTAIN snapshots are stored;
* Today is read in ONE statement and the engine never runs on page load;
* S rules are never shown as actions.

All data is SYNTHETIC (see ``_snapshot_fixtures``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.engine.determinism import content_hash
from iip.services import risk_snapshot as rs
from iip.store import goals_repo
from tests.services import _snapshot_fixtures as fx


class Counting:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.seen: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.seen.append(sql)
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _compute(conn: Any) -> rs.Snapshot:
    return rs.compute_snapshot(rs.load_inputs(conn, fx.AS_OF, fx.stress_table()), fx.TEMPLATES)


def _cards(snap: rs.Snapshot) -> list[dict[str, Any]]:
    return list(json.loads(snap.payload_json)["cards"])


# --------------------------------------------------------------------------------------------- identity


def test_snapshot_is_byte_identical_on_rerun(conn: Any) -> None:
    fx.seed_two_goals(conn)
    a, b = _compute(conn), _compute(conn)
    assert a.payload_json == b.payload_json
    assert a.snapshot_id == b.snapshot_id
    assert "created_at" not in a.payload_json  # no wall-clock value in the content


def test_snapshot_is_content_addressed(conn: Any) -> None:
    fx.seed_two_goals(conn)
    inputs = rs.load_inputs(conn, fx.AS_OF, fx.stress_table())
    snap = rs.compute_snapshot(inputs, fx.TEMPLATES)
    assert snap.input_manifest_hash == content_hash(inputs)
    assert snap.snapshot_id == content_hash(
        {"engine_version": rs.ENGINE_VERSION, "rules_version": snap.rules_version,
         "input_manifest_hash": snap.input_manifest_hash}
    )  # fmt: skip
    changed = replace(inputs, goals=(replace(inputs.goals[0], loss_budget_inr=Decimal("20001")), *inputs.goals[1:]))
    assert rs.compute_snapshot(changed, fx.TEMPLATES).snapshot_id != snap.snapshot_id
    # every card names the snapshot it belongs to
    assert {c["snapshot_id"] for c in _cards(snap)} == {snap.snapshot_id}


def test_store_is_idempotent(conn: Any) -> None:
    fx.seed_two_goals(conn)
    snap, first = rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(),
                                  templates=fx.TEMPLATES)  # fmt: skip
    _, second = rs.run_snapshot(conn, as_of=fx.AS_OF, now="2026-10-16T06:00:00+00:00",
                                stress_table=fx.stress_table(), templates=fx.TEMPLATES)  # fmt: skip
    assert first.created and not second.created
    rows = conn.execute("SELECT snapshot_id, payload_json FROM signal_snapshots").fetchall()
    assert len(rows) == 1 and rows[0]["payload_json"] == snap.payload_json


# --------------------------------------------------------------------------------------------- abstention


def test_empty_database_stores_an_abstain_snapshot(conn: Any) -> None:
    snap, run = rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(),
                                templates=fx.TEMPLATES)  # fmt: skip
    assert run.created and snap.verdict == rs.VERDICT_ABSTAIN
    payload = json.loads(conn.execute("SELECT payload_json FROM signal_snapshots").fetchone()["payload_json"])
    assert payload["state"] == "ABSTAINED_ONLY"
    assert all(c["kind"] == "ABSTAIN" for c in payload["cards"])
    codes = {code for n in payload["needs"] for code in n["codes"]}
    assert "goals_missing" in codes
    assert any(code.startswith("context_missing:user.emergency_months") for code in codes)


def test_missing_input_abstains_that_goal_and_layer_only(conn: Any) -> None:
    fx.seed_two_goals(conn)
    snap = _compute(conn)
    by = {(c["kind"], c["goal_id"], c["layer"]) for c in _cards(snap)}
    # g-car has no loss limit: its L3 abstains ...
    assert ("ABSTAIN", "g-car", 3) in by
    # ... while g-house's L3 still runs (and breaches), and both goals' L2 run.
    assert ("LOSS_BUDGET_BREACH", "g-house", 3) in by
    scopes = {s["scope_id"]: s for s in json.loads(snap.payload_json)["scopes"]}
    assert scopes["g-car"]["layers"]["L2"]["outcome"] == "PASS"
    assert scopes["g-car"]["layers"]["L3"]["outcome"] == "ABSTAIN"
    assert scopes["g-house"]["layers"]["L3"]["outcome"] == "BREACH"
    car_gaps = scopes["g-car"]["layers"]["L3"]["gate"]["gaps"]
    assert [g["item_id"] for g in car_gaps] == ["goal.loss_budget_inr", "goal.recovery_months"]


def test_unknown_category_abstains_instead_of_guessing(conn: Any) -> None:
    fx.seed_two_goals(conn)
    fx.add_scheme(conn, "mf:970003", "970003", "Fictional Index Fund", "Other Scheme - Index Funds")
    fx.add_nav(conn, "970003", fx.AS_OF, "50")
    fx.buy(conn, "t3", "mf:970003", "100", "5000")
    goals_repo.replace_goal_map(conn, [goals_repo.GoalLink("mf:970003", "", "g-house", Decimal("1"))], fx.NOW)
    snap = _compute(conn)
    house = next(s for s in json.loads(snap.payload_json)["scopes"] if s["scope_id"] == "g-house")
    assert house["layers"]["L3"]["outcome"] == "ABSTAIN"
    assert house["layers"]["L3"]["gate"]["gaps"][0]["item_id"] == "holdings.classified"


def test_stale_nav_abstains(conn: Any) -> None:
    fx.seed_two_goals(conn)
    inputs = rs.load_inputs(conn, fx.AS_OF.replace(day=30), fx.stress_table())
    assert all(h.exclusion == "STALE_NAV" for h in inputs.holdings)
    snap = rs.compute_snapshot(inputs, fx.TEMPLATES)
    assert not any(c["kind"] == "LOSS_BUDGET_BREACH" for c in _cards(snap))


def test_missing_stress_config_abstains(conn: Any) -> None:
    fx.seed_two_goals(conn)
    snap = rs.compute_snapshot(rs.load_inputs(conn, fx.AS_OF, fx.stress_table(local=None)), fx.TEMPLATES)
    house = next(s for s in json.loads(snap.payload_json)["scopes"] if s["scope_id"] == "g-house")
    assert house["layers"]["L3"]["outcome"] == "ABSTAIN"


# --------------------------------------------------------------------------------------------- cards


def test_loss_budget_breach_card_is_traceable_and_neutral(conn: Any) -> None:
    fx.seed_two_goals(conn)
    card = next(c for c in _cards(_compute(conn)) if c["kind"] == "LOSS_BUDGET_BREACH")
    nums = {n["slot"]: n for n in card["numbers"]}
    assert nums["loss_limit"]["value"] == "20000"
    assert nums["stress_loss"]["value"] == "40000.00"  # 0.50 × ₹80,000 (fictional stress) + 0 × ₹50,000
    assert nums["excess"]["value"] == "20000.00"
    # e_cap = floor_0.01(0.1538… / 0.50) = 0.30 → redirect = 80,000 / 0.30 − 1,30,000
    assert nums["redirect_amount"]["value"] == "136666.67"
    for n in card["numbers"]:
        assert n["fact_ids"] or n["formula_id"]
    assert card["impact"] == {"amount_inr": "20000.00", "basis": "AMOUNT_AT_RISK", "slot": "excess"}
    assert "obs:" in json.dumps(nums["stress_loss"]["fact_ids"])
    text = card["text"]
    assert text is not None and "risk.loss_budget@1" in text and "₹20,000" in text
    lowered = text.lower()
    assert "buy" not in lowered and "sell" not in lowered
    assert card["is_action"] and card["status"] == "NOT VERIFIED"  # cited stress without the AMFI recompute


def test_emergency_breach_suppresses_lower_layers(conn: Any) -> None:
    fx.seed_two_goals(conn)
    goals_repo.set_risk_profile(
        conn, goals_repo.RiskProfile(essential_monthly_expenses=Decimal("100000"), emergency_months=6,
                                     savings_balance=Decimal("0"), sweep_fd_balance=Decimal("0")), fx.NOW,
    )  # fmt: skip
    payload = json.loads(_compute(conn).payload_json)
    assert payload["cards"][0]["kind"] == "EMERGENCY_SHORTFALL"
    shortfall = {n["slot"]: n for n in payload["cards"][0]["numbers"]}["shortfall"]["value"]
    assert shortfall == "550000.00"  # 6 × ₹1,00,000 − ₹50,000 overnight
    suppressed = {s["card"]["kind"] for s in payload["suppressed"]}
    assert "LOSS_BUDGET_BREACH" in suppressed


def test_limit_breach_cards(conn: Any) -> None:
    fx.seed_two_goals(conn)
    goals_repo.append_policy_version(conn, {"limits": {"c_scheme": "0.5"}}, "2026-10-01", fx.NOW)
    cards = _cards(_compute(conn))
    limit = [c for c in cards if c["kind"] == "LIMIT_BREACH"]
    assert len(limit) == 1
    nums = {n["slot"]: n["value"] for n in limit[0]["numbers"]}
    # ₹1,00,000 of ₹1,50,000 in one scheme, limit 50 % → ₹25,000 over
    assert nums["limit_share"] == "0.5" and nums["excess"] == "25000.00"
    assert limit[0]["rule_ref"] == "risk.limits.scheme@1"
    # c_amc etc. are not set: the L4 abstention is still listed
    assert any(c["kind"] == "ABSTAIN" and c["layer"] == 4 for c in cards)


def test_nothing_needed_is_first_class(conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fx.seed_two_goals(conn)
    goals_repo.upsert_goals(
        conn,
        [goals_repo.Goal("g-house", "House", 1, target_date="2035-06-30", loss_budget_inr=Decimal("100000"),
                         recovery_months=60, h_safe_years=Decimal("3")),
         goals_repo.Goal("g-car", "Car", 2, target_date="2034-01-31", loss_budget_inr=Decimal("50000"),
                         recovery_months=60, h_safe_years=Decimal("2"))],
        fx.NOW,
    )  # fmt: skip
    goals_repo.replace_goal_map(  # each goal holds some non-equity, so s_d is known for both
        conn,
        [goals_repo.GoalLink("mf:970002", "", "g-house", Decimal("0.5")),
         goals_repo.GoalLink("mf:970002", "", "g-car", Decimal("0.5"))],
        fx.NOW,
    )  # fmt: skip
    goals_repo.append_policy_version(
        conn, {"limits": {k: "1" for k in ("c_scheme", "c_amc", "c_theme", "c_factor", "c_issuer")}}, "2026-10-01",
        fx.NOW,
    )  # fmt: skip
    snap = _compute(conn)
    payload = json.loads(snap.payload_json)
    assert snap.verdict == rs.VERDICT_NOTHING
    assert [c["kind"] for c in payload["cards"]] == ["NO_ACTION_NEEDED"]
    assert payload["cards"][0]["text"].startswith("Nothing needs doing today.")


# --------------------------------------------------------------------------------------------- Today read


def test_today_reads_one_statement_and_never_runs_the_engine(conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fx.seed_two_goals(conn)
    snap, _ = rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(),
                              templates=fx.TEMPLATES)  # fmt: skip

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the engine ran on page load")

    monkeypatch.setattr(rs, "compute_snapshot", boom)
    monkeypatch.setattr(rs, "load_inputs", boom)
    counting = Counting(conn)
    today = rs.read_today(counting)  # type: ignore[arg-type]
    assert len(counting.seen) == 1
    assert today["snapshot_id"] == snap.snapshot_id and today["decisions"] == []
    counting.seen.clear()
    needs = rs.read_needs(counting)  # type: ignore[arg-type]
    assert len(counting.seen) == 1 and needs["needs"]


def test_today_without_snapshot_is_a_state_not_an_error(conn: Any) -> None:
    counting = Counting(conn)
    assert rs.read_today(counting)["state"] == rs.NO_SNAPSHOT  # type: ignore[arg-type]
    assert len(counting.seen) == 1


def test_decisions_are_attached_to_today(conn: Any) -> None:
    fx.seed_two_goals(conn)
    snap, _ = rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(),
                              templates=fx.TEMPLATES)  # fmt: skip
    card = next(c for c in snap.cards if c.is_action)
    rs.record_decision(conn, snapshot_id=snap.snapshot_id, card_id=card.card_id, decision="done", note=None,
                       now=fx.NOW)  # fmt: skip
    today = rs.read_today(conn)
    assert today["decisions"] == [
        {"card_id": card.card_id, "decision": "done", "decided_at": fx.NOW, "cas_confirmed": None}
    ]
    abstain = next(c for c in snap.cards if not c.is_action)
    with pytest.raises(rs.DecisionRejected) as exc:
        rs.record_decision(conn, snapshot_id=snap.snapshot_id, card_id=abstain.card_id, decision="done", note=None,
                           now=fx.NOW)  # fmt: skip
    assert exc.value.code == "NOT_AN_ACTION"


def test_classifier_is_conservative() -> None:
    assert rs.classify_category("Equity Scheme - Large & Mid Cap Fund") == rs.RiskClass.EQ_MID
    assert rs.classify_category("Hybrid Scheme - Arbitrage Fund") == rs.RiskClass.HYBRID
    assert rs.classify_category("Other Scheme - Index Funds") is None
    assert rs.classify_category("Other Scheme - Gold ETF") == rs.RiskClass.GOLD
    assert rs.classify_category("Debt Scheme - Overnight Fund") == rs.RiskClass.CASH_LIKE
    assert rs.classify_category(None) is None


def test_today_query_and_snapshot_work_on_libsql(tmp_path: Path) -> None:
    from iip.store.db import connect_libsql, migrate

    conn = connect_libsql(str(tmp_path / "remote-like.db"))
    migrate(conn, fx.NOW)
    fx.seed_two_goals(conn)
    snap, run = rs.run_snapshot(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(),
                                templates=fx.TEMPLATES)  # fmt: skip
    assert run.created
    card = next(c for c in snap.cards if c.is_action)
    rs.record_decision(conn, snapshot_id=snap.snapshot_id, card_id=card.card_id, decision="not_now", note="later",
                       now=fx.NOW)  # fmt: skip
    today = rs.read_today(conn)
    assert today["snapshot_id"] == snap.snapshot_id
    assert [d["decision"] for d in today["decisions"]] == ["not_now"]
    conn.close()
