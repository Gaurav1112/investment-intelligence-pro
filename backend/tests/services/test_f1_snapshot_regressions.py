"""Regression tests from the wave-2 ECC review, group F1 (snapshot, shadow ledger, outcomes). Every id, name, NAV,
duration and rate here is SYNTHETIC and fictional (scheme codes in the 97xxxx range, origin 'fixture').

* silent-failure-hunter-01: an invalid portfolio ledger (or a folio link that cannot be applied) fails CLOSED with a
  visible L0 abstention, instead of a snapshot computed on a partial household.
* silent-failure-hunter-04: an "I did this" on a card is carried to the same card in later snapshots until a CAS
  checks it; a CAS that contradicts it re-raises the card.
* python-reviewer-2: an L2 ACTION finding (debt duration longer than the time to the goal) is never dropped.
* python-reviewer-3: the L4 theme limit never groups unrelated sectoral funds by their shared SEBI category text.
* database-reviewer-06: outcomes that can be recorded are never starved by rows that cannot progress.
* database-reviewer-08: the shadow run reads the existing evaluation keys once.
* graft TA-1: every outcome records the date it became known (resolved_on).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from iip.services import outcomes as oc
from iip.services import risk_snapshot as rs
from iip.services import shadow
from iip.services.today_view import today_response
from iip.store import goals_repo, ledger
from tests.services import _snapshot_fixtures as fx


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = fx.open_db(tmp_path / "iip.db")
    yield c
    c.close()


def _payload(conn: Any, as_of: date = fx.AS_OF) -> dict[str, Any]:
    snap = rs.compute_snapshot(rs.load_inputs(conn, as_of, fx.stress_table()), fx.TEMPLATES)
    out: dict[str, Any] = json.loads(snap.payload_json)
    return out


def _codes(card: dict[str, Any]) -> set[str]:
    return {a["code"] for a in card.get("abstentions") or []}


# ------------------------------------------------------------------------------------- silent-failure-hunter-01


def _add_bad_sell(conn: Any) -> None:
    """A 'sell' with no prior buy in portfolio p1 (an out-of-order or missing CAS row)."""
    fx.add_scheme(conn, "mf:970003", "970003", "Fictional Small Fund", "Equity Scheme - Small Cap Fund")
    fx.add_nav(conn, "970003", fx.AS_OF, "10")
    conn.execute(
        "INSERT INTO transactions(txn_id, portfolio_id, instrument_id, txn_date, txn_type, units, amount, source,"
        " created_at) VALUES ('t-bad', 'p1', 'mf:970003', '2025-02-01', 'sell', '5', '50', 'manual', ?)",
        (fx.NOW,),
    )


def test_invalid_portfolio_ledger_fails_closed_with_a_visible_l0_abstention(conn: Any) -> None:
    fx.seed_two_goals(conn)
    good = _payload(conn)
    assert good["verdict"] == rs.VERDICT_ACTIONS  # the real L3 breach of g-house
    _add_bad_sell(conn)
    bad = _payload(conn)
    l0 = [c for c in bad["cards"] if c["layer"] == 0]
    assert len(l0) == 1 and l0[0]["kind"] == "ABSTAIN" and l0[0]["goal_id"] is None
    assert _codes(l0[0]) == {"portfolio_ledger_invalid"}
    assert "p1" in l0[0]["abstentions"][0]["missing_input"]
    assert "PORTFOLIO_LEDGER_INVALID_EXCLUDED" in bad["flags"]
    # nothing computed on the partial household is shown as an action; it is kept (suppressed), never dropped
    assert not [c for c in bad["cards"] if c["is_action"]]
    assert bad["verdict"] == rs.VERDICT_ABSTAIN
    suppressed = {s["card"]["kind"] for s in bad["suppressed"]}
    assert "EMERGENCY_SHORTFALL" in suppressed  # the partial-household L1 card a user must not act on
    assert all(s["suppressed_by"] == l0[0]["card_id"] for s in bad["suppressed"])
    # the abstention reaches "Needs from you"
    assert any("portfolio_ledger_invalid" in n["codes"] for n in bad["needs"])


def test_folio_link_that_cannot_be_applied_abstains_that_goal(conn: Any) -> None:
    fx.seed_two_goals(conn)
    goals_repo.replace_goal_map(
        conn,
        [goals_repo.GoalLink("mf:970001", "", "g-house", Decimal("0.8")),
         goals_repo.GoalLink("mf:970001", "", "g-car", Decimal("0.2")),
         goals_repo.GoalLink("mf:970002", "FOLIO-1", "g-house", Decimal("1"))],
        fx.NOW,
    )  # fmt: skip
    p = _payload(conn)
    l0 = [c for c in p["cards"] if c["layer"] == 0]
    assert [(c["kind"], c["goal_id"]) for c in l0] == [("ABSTAIN", "g-house")]
    assert _codes(l0[0]) == {"folio_link_not_applied"}
    assert "FOLIO_LINK_NOT_APPLIED" in p["flags"]
    # g-house's own layer cards are suppressed by it; the household and g-car are not
    assert not [c for c in p["cards"] if c["goal_id"] == "g-house" and c["layer"] > 0]
    assert {s["card"]["goal_id"] for s in p["suppressed"]} == {"g-house"}


# ------------------------------------------------------------------------------------- silent-failure-hunter-04


def _action(today: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(c for c in today["cards"] if c["kind"] == kind)


def test_done_decision_is_carried_to_the_same_card_in_later_snapshots(conn: Any) -> None:
    fx.seed_two_goals(conn)
    kw: dict[str, Any] = {"stress_table": fx.stress_table(), "templates": fx.TEMPLATES}
    rs.run_daily(conn, as_of=fx.AS_OF, now=fx.NOW, **kw)
    day1 = rs.read_today(conn)
    card1 = _action(day1, "LOSS_BUDGET_BREACH")
    rec = rs.record_decision(conn, snapshot_id=day1["snapshot_id"], card_id=card1["card_id"], decision="done",
                             note=None, now="2026-10-16T06:00:00+00:00")  # fmt: skip
    rs.run_daily(conn, as_of=date(2026, 10, 16), now="2026-10-17T05:00:00+00:00", **kw)
    raw = rs.read_today(conn)
    assert raw["snapshot_id"] != day1["snapshot_id"]
    card2 = _action(raw, "LOSS_BUDGET_BREACH")
    assert card2["card_id"] != card1["card_id"]  # a new card id: the snapshot changed
    view = _action(today_response(raw), "LOSS_BUDGET_BREACH")
    assert view["decision"] is not None, "the card the user marked done came back unmarked"
    assert view["decision"]["decision_id"] == rec["decision"]["decision_id"]
    carried = [d for d in raw["decisions"] if d["card_id"] == card2["card_id"]]
    assert carried and carried[0]["carried_from_snapshot_id"] == day1["snapshot_id"]
    # a CAS that CONTRADICTS the "I did this" re-raises the card (no marker)
    ledger.confirm_decisions_from_cas(conn, [(int(rec["decision"]["decision_id"]), False)], fx.NOW, "cas-1")
    again = today_response(rs.read_today(conn))
    assert _action(again, "LOSS_BUDGET_BREACH")["decision"] is None


def test_carry_forward_keeps_today_one_statement(conn: Any) -> None:
    fx.seed_two_goals(conn)
    rs.run_daily(conn, as_of=fx.AS_OF, now=fx.NOW, stress_table=fx.stress_table(), templates=fx.TEMPLATES)
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    rs.read_today(conn)
    conn.set_trace_callback(None)
    assert len(seen) == 1


# ------------------------------------------------------------------------------------------- python-reviewer-2


def _long_duration_goal(conn: Any, *, equity: bool = False) -> None:
    fx.add_portfolio(conn)
    fx.add_scheme(conn, "mf:970010", "970010", "Fictional Long Bond Fund", "Debt Scheme - Long Duration Fund")
    fx.add_nav(conn, "970010", fx.AS_OF, "10")
    fx.buy(conn, "t10", "mf:970010", "1000", "10000")
    conn.execute(
        "INSERT INTO fund_facts(instrument_id, as_of_month, as_of_date, modified_duration, macaulay_duration,"
        " lowest_rating, citation_url, verified_on, entered_at)"
        " VALUES ('mf:970010', '2026-09', '2026-09-30', '9', '10', 'SOV', 'https://example.test/f', '2026-10-01', ?)",
        (fx.NOW,),
    )
    links = [goals_repo.GoalLink("mf:970010", "", "g1", Decimal("1"))]
    if equity:
        fx.add_scheme(conn, "mf:970011", "970011", "Fictional Large Fund", "Equity Scheme - Large Cap Fund")
        fx.add_nav(conn, "970011", fx.AS_OF, "10")
        fx.buy(conn, "t11", "mf:970011", "100", "1000")
        links.append(goals_repo.GoalLink("mf:970011", "", "g1", Decimal("1")))
    goals_repo.upsert_goals(
        conn,
        [goals_repo.Goal("g1", "Fictional Goal", 1, target_date="2028-10-15", h_safe_years=Decimal("3"),
                         loss_budget_inr=Decimal("5000"), recovery_months=60)],
        fx.NOW,
    )  # fmt: skip
    goals_repo.replace_goal_map(conn, links, fx.NOW)


def test_l2_action_outcome_is_never_dropped(conn: Any) -> None:
    _long_duration_goal(conn)
    p = _payload(conn)
    g1 = next(s for s in p["scopes"] if s["scope_id"] == "g1")
    assert g1["layers"]["L2"]["outcome"] == "ACTION"
    l2 = [c for c in p["cards"] if c["layer"] == 2 and c["goal_id"] == "g1"]
    assert l2, "the engine found an L2 ACTION and no card carries it"
    assert "duration_exceeds_horizon" in _codes(l2[0])
    assert "mf:970010" in l2[0]["abstentions"][0]["missing_input"]
    assert p["verdict"] != rs.VERDICT_NOTHING


def test_l2_action_finding_survives_next_to_a_breach(conn: Any) -> None:
    _long_duration_goal(conn, equity=True)  # 2 years to go, safety window 3: equity is a BREACH, the bond an ACTION
    p = _payload(conn)
    g1 = next(s for s in p["scopes"] if s["scope_id"] == "g1")
    assert g1["layers"]["L2"]["outcome"] == "BREACH"
    kinds = {c["kind"]: c for c in p["cards"] if c["layer"] == 2 and c["goal_id"] == "g1"}
    assert "GOAL_DATE_BREACH" in kinds and "duration_exceeds_horizon" in _codes(kinds["ABSTAIN"])


# ------------------------------------------------------------------------------------------- python-reviewer-3


def test_theme_limit_never_groups_sectoral_funds_by_category_text(conn: Any) -> None:
    fx.add_portfolio(conn)
    fx.add_scheme(conn, "mf:970021", "970021", "Fictional Bank Fund", "Equity Scheme - Sectoral/ Thematic", "AMC A")
    fx.add_scheme(conn, "mf:970022", "970022", "Fictional Pharma Fund", "Equity Scheme - Sectoral/ Thematic", "AMC B")
    fx.add_scheme(conn, "mf:970002", "970002", "Fictional Overnight Fund", "Debt Scheme - Overnight Fund", "AMC C")
    for code, nav in (("970021", "10"), ("970022", "10"), ("970002", "10")):
        fx.add_nav(conn, code, fx.AS_OF, nav)
    fx.buy(conn, "t1", "mf:970021", "1500", "15000")
    fx.buy(conn, "t2", "mf:970022", "1500", "15000")
    fx.buy(conn, "t3", "mf:970002", "7000", "70000")
    goals_repo.append_policy_version(conn, {"limits": {"c_theme": "0.2"}}, "2026-10-01", fx.NOW)
    p = _payload(conn)
    every = [*p["cards"], *(s["card"] for s in p["suppressed"])]
    assert not [c for c in every if c["rule_ref"] == "risk.limits.theme@1"], "a VERIFIED breach from a shared label"
    l4 = [c for c in every if c["layer"] == 4 and c["kind"] == "ABSTAIN"]
    assert l4 and "theme_unknown" in _codes(l4[0])
    missing = " ".join(a["missing_input"] for a in l4[0]["abstentions"] if a["code"] == "theme_unknown")
    assert "Fictional Bank Fund" in missing and "Fictional Pharma Fund" in missing


# ------------------------------------------------------------------------------------------ database-reviewer-06


def _evaluation(day: str, condition_met: int | None, horizon_end: str | None) -> ledger.RuleEvaluation:
    payload = {"horizon_end": horizon_end, "reason": None if condition_met is not None else "insufficient_history"}
    return ledger.RuleEvaluation(
        rule_id="S-F", version=1, as_of_date=day, scope_id="role:fictional", state="PRE_REGISTERED",
        condition_met=condition_met, payload_json=json.dumps(payload), input_hash=f"h-{day}", snapshot_id="s" * 64,
        evaluated_at=fx.NOW,
    )  # fmt: skip


def test_recordable_outcomes_are_not_starved_by_rows_waiting_for_a_basis(conn: Any) -> None:
    rows = [_evaluation(f"2020-01-0{d}", 1, f"2020-02-0{d}") for d in (1, 2, 3)]
    rows.append(_evaluation("2020-01-05", None, None))  # abstained: recordable at once as 'unscorable'
    ledger.append_rule_evaluations(conn, rows)
    runs = [oc.score_outcomes(conn, as_of=date(2020, 6, 1), now=fx.NOW, basis=None, limit=3) for _ in range(3)]
    assert conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1
    assert runs[0].unscorable == 1 and runs[0].waiting_for_basis == 3
    assert runs[1].unscorable == 0 and runs[1].waiting_for_basis == 3


def test_not_yet_due_rows_are_counted_but_not_read(conn: Any) -> None:
    ledger.append_rule_evaluations(conn, [_evaluation("2020-01-01", 0, "2020-12-31")])
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    run = oc.score_outcomes(conn, as_of=date(2020, 6, 1), now=fx.NOW, basis=None)
    conn.set_trace_callback(None)
    assert run.not_yet_due == 1 and run.considered == 1
    assert sum("rule_evaluations" in s for s in seen) == 1  # one statement reads rows and counts together


# ------------------------------------------------------------------------------------------ database-reviewer-08

TREND = """id: S-X
version: 1
family: trend_timing
roles: {in: index_fund.fictional.direct, out: liquid_fund.fictional.direct}
params: {lookback_months: 3}
horizon_months: 1
"""


def test_run_shadow_reads_the_existing_keys_once(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    first = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    conn.set_trace_callback(None)
    reads = [s for s in seen if s.lstrip().upper().startswith("SELECT") and "FROM rule_evaluations" in s]
    assert len(reads) == 1, reads
    assert first.written == 1 and first.already_recorded == 0


def test_run_shadow_rerun_keeps_the_first_write_even_when_inputs_changed(conn: Any) -> None:
    fx.register_s_rule(conn, "S-X", TREND)
    shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="a" * 64, now=fx.NOW)
    before = conn.execute("SELECT input_hash FROM rule_evaluations").fetchone()[0]
    fx.add_scheme(conn, "mf:971001", "971001", "Fictional Index Fund", "Equity Scheme - Large Cap Fund")
    ledger.bind_roles(conn, [ledger.RoleBinding("index_fund.fictional.direct", "mf:971001", "fixture", fx.NOW)])
    again = shadow.run_shadow(conn, as_of=fx.AS_OF, snapshot_id="b" * 64, now=fx.NOW)  # content differs now
    assert again.written == 0 and again.already_recorded == 1
    assert conn.execute("SELECT input_hash FROM rule_evaluations").fetchone()[0] == before


# --------------------------------------------------------------------------------------------------- graft TA-1


def test_outcomes_record_when_they_became_known(conn: Any) -> None:
    ledger.append_rule_evaluations(conn, [_evaluation("2020-01-05", None, "2020-02-29")])
    oc.score_outcomes(conn, as_of=date(2020, 3, 10), now="2026-10-16T05:00:00+00:00", basis=None)
    row = conn.execute("SELECT horizon_end, resolved_on FROM outcomes").fetchone()
    assert row["horizon_end"] == "2020-02-29"
    assert row["resolved_on"] == "2020-03-10"  # the DATA date of the scoring pass, never the wall clock
    # point in time: invisible before it was known, visible from then on
    assert ledger.outcomes_as_of(conn, "2020-03-09") == []
    assert [r["rule_id"] for r in ledger.outcomes_as_of(conn, "2020-03-10")] == ["S-F"]
