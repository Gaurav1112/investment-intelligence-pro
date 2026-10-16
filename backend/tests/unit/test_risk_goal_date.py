"""L2 goal-date safety (design-risk-first.md §5.4).  All values are FICTIONAL."""

from __future__ import annotations

from datetime import date

import pytest

from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.risk import REMEDY_REDIRECT_NEW_CONTRIBUTIONS, Outcome, RiskClass
from iip.engine.risk.goal_date import GoalDateHolding, goal_date_safety

AS_OF = date(2026, 1, 1)


def run(goal: date, *holdings: GoalDateHolding, h_safe: str | None = "3"):  # type: ignore[no-untyped-def]
    return goal_date_safety(
        "goal-fictional",
        as_of=AS_OF,
        goal_date=goal,
        h_safe_years=None if h_safe is None else D(h_safe),
        holdings=holdings,
    )


EQ = GoalDateHolding("eq", RiskClass.EQ_BROAD, D("100000"))
GOLD = GoalDateHolding("gold", RiskClass.GOLD, D("50000"))
CASH = GoalDateHolding("cash", RiskClass.CASH_LIKE, D("50000"))


def test_equity_and_gold_inside_window_breach() -> None:
    r = run(date(2028, 1, 1), EQ, GOLD, CASH)
    assert r.years_to_goal == D(730) / D(365)
    assert r.outcome is Outcome.BREACH
    assert {f.holding_id for f in r.findings} == {"eq", "gold"}
    assert all(f.code == "equity_inside_safe_window" for f in r.findings)
    assert r.at_risk_value == D("150000")
    assert r.remedy == REMEDY_REDIRECT_NEW_CONTRIBUTIONS
    assert r.rule_id == "risk.goal_date@1"


def test_hybrid_and_stock_count_as_equity() -> None:
    r = run(
        date(2027, 1, 1),
        GoalDateHolding("h", RiskClass.HYBRID, D("1")),
        GoalDateHolding("s", RiskClass.STOCK, D("1")),
    )
    assert r.outcome is Outcome.BREACH
    assert len(r.findings) == 2


def test_equity_outside_window_passes() -> None:
    r = run(date(2036, 1, 1), EQ, GOLD, CASH)
    assert r.outcome is Outcome.PASS
    assert r.findings == ()
    assert r.remedy is None


def test_debt_duration_longer_than_horizon_is_an_action() -> None:
    long_debt = GoalDateHolding("d", RiskClass.DEBT_MTM, D("100000"), D("4"))
    r = run(date(2028, 1, 1), long_debt)
    assert r.outcome is Outcome.ACTION
    assert r.findings[0].code == "duration_exceeds_horizon"
    short = run(date(2028, 1, 1), GoalDateHolding("d", RiskClass.DEBT_MTM, D("1"), D("1.5")))
    assert short.outcome is Outcome.PASS


def test_debt_without_duration_abstains_but_breach_dominates() -> None:
    unknown = GoalDateHolding("d", RiskClass.DEBT_MTM, D("1"))
    r = run(date(2040, 1, 1), unknown)
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "duration_missing"
    both = run(date(2027, 1, 1), unknown, EQ)
    assert both.outcome is Outcome.BREACH
    assert len(both.abstentions) == 1


def test_missing_h_safe_abstains() -> None:
    r = run(date(2027, 1, 1), EQ, h_safe=None)
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "h_safe_missing"


def test_goal_date_passed_counts_as_zero_years() -> None:
    r = run(date(2025, 6, 1), EQ)
    assert r.years_to_goal == D(0)
    assert "GOAL_DATE_PASSED" in r.flags
    assert r.outcome is Outcome.BREACH


def test_zero_value_holdings_are_ignored() -> None:
    assert run(date(2027, 1, 1), GoalDateHolding("eq", RiskClass.EQ_BROAD, D("0"))).outcome is Outcome.PASS


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(InvalidInput):
        run(date(2027, 1, 1), EQ, h_safe="-1")
    with pytest.raises(InvalidInput):
        run(date(2027, 1, 1), GoalDateHolding("x", RiskClass.EQ_BROAD, D("-1")))
    with pytest.raises(InvalidInput):
        run(date(2027, 1, 1), GoalDateHolding("x", RiskClass.DEBT_MTM, D("1"), D("-1")))
