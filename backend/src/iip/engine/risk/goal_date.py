"""L2 goal-date safety — ``risk.goal_date@1`` (design-risk-first.md §5.4).

    years_to_goal = year_fraction(as_of, goal_date)   (ACT/365F, engine/dates.py)
    for each holding mapped to the goal:
      years_to_goal < h_safe and class ∈ EQUITY_CLASSES ∪ {GOLD}       → BREACH(equity_inside_safe_window)
      class == DEBT_MTM and macaulay_duration_years > years_to_goal     → ACTION(duration_exceeds_horizon)

``h_safe`` is a user-set PARAMETER (no default is chosen by the engine; missing → ABSTAIN).  A debt holding with no
duration abstains.  A goal date already passed counts as zero years to go.  The layer never asks for a sale: the
remedy is to send new money for this goal to safe instruments; any switch is a downstream, user-enabled policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from iip.engine.dates import DayCount, year_fraction
from iip.engine.errors import InvalidInput
from iip.engine.money import ZERO
from iip.engine.risk import (
    EQUITY_CLASSES,
    REMEDY_REDIRECT_NEW_CONTRIBUTIONS,
    Abstention,
    Outcome,
    RiskClass,
    combine_outcomes,
)

RULE_ID = "risk.goal_date@1"
CAN_FALL: frozenset[RiskClass] = EQUITY_CLASSES | {RiskClass.GOLD}


@dataclass(frozen=True)
class GoalDateHolding:
    holding_id: str
    risk_class: RiskClass
    market_value: Decimal
    macaulay_duration_years: Decimal | None = None  # DEBT_MTM only


@dataclass(frozen=True)
class GoalDateFinding:
    holding_id: str
    risk_class: RiskClass
    market_value: Decimal
    outcome: Outcome  # BREACH, ACTION or ABSTAIN
    code: str


@dataclass(frozen=True)
class GoalDateResult:
    goal_id: str
    outcome: Outcome
    years_to_goal: Decimal
    h_safe_years: Decimal | None
    findings: tuple[GoalDateFinding, ...]
    at_risk_value: Decimal  # Σ MV of BREACH findings
    abstentions: tuple[Abstention, ...]
    flags: tuple[str, ...]
    remedy: str | None  # REDIRECT_NEW_CONTRIBUTIONS on a breach; never a sale
    rule_id: str = RULE_ID


def goal_date_safety(
    goal_id: str,
    *,
    as_of: date,
    goal_date: date,
    h_safe_years: Decimal | None,
    holdings: Sequence[GoalDateHolding],
) -> GoalDateResult:
    if h_safe_years is not None and h_safe_years < 0:
        raise InvalidInput("h_safe must be ≥ 0 years")
    flags: list[str] = []
    if goal_date <= as_of:
        years = ZERO
        if goal_date < as_of:
            flags.append("GOAL_DATE_PASSED")
    else:
        years = year_fraction(as_of, goal_date, DayCount.ACT_365F)

    for h in holdings:
        if h.market_value < 0:
            raise InvalidInput(f"holding {h.holding_id!r}: market value must be ≥ 0")
        if h.macaulay_duration_years is not None and h.macaulay_duration_years < 0:
            raise InvalidInput(f"holding {h.holding_id!r}: duration must be ≥ 0")

    if h_safe_years is None:
        return GoalDateResult(
            goal_id=goal_id,
            outcome=Outcome.ABSTAIN,
            years_to_goal=years,
            h_safe_years=None,
            findings=(),
            at_risk_value=ZERO,
            abstentions=(
                Abstention(
                    code="h_safe_missing",
                    missing_input="safe-window length in years (h_safe)",
                    how_to_fix="choose how many years before the goal date money must be out of instruments "
                    "that can fall",
                ),
            ),
            flags=tuple(flags),
            remedy=None,
        )

    findings: list[GoalDateFinding] = []
    abstentions: list[Abstention] = []
    for h in holdings:
        if h.market_value == 0:
            continue
        if h.risk_class in CAN_FALL and years < h_safe_years:
            findings.append(
                GoalDateFinding(h.holding_id, h.risk_class, h.market_value, Outcome.BREACH, "equity_inside_safe_window")
            )
        elif h.risk_class is RiskClass.DEBT_MTM:
            if h.macaulay_duration_years is None:
                findings.append(
                    GoalDateFinding(h.holding_id, h.risk_class, h.market_value, Outcome.ABSTAIN, "duration_missing")
                )
                abstentions.append(
                    Abstention(
                        code="duration_missing",
                        missing_input=f"Macaulay duration for {h.holding_id}",
                        how_to_fix="enter the duration from the scheme's latest factsheet",
                    )
                )
            elif h.macaulay_duration_years > years:
                findings.append(
                    GoalDateFinding(
                        h.holding_id, h.risk_class, h.market_value, Outcome.ACTION, "duration_exceeds_horizon"
                    )
                )

    outcome = combine_outcomes(
        [f.outcome for f in findings], precedence=(Outcome.BREACH, Outcome.ABSTAIN, Outcome.ACTION)
    )
    at_risk = sum((f.market_value for f in findings if f.outcome is Outcome.BREACH), ZERO)
    return GoalDateResult(
        goal_id=goal_id,
        outcome=outcome,
        years_to_goal=years,
        h_safe_years=h_safe_years,
        findings=tuple(findings),
        at_risk_value=at_risk,
        abstentions=tuple(abstentions),
        flags=tuple(flags),
        remedy=REMEDY_REDIRECT_NEW_CONTRIBUTIONS if outcome is Outcome.BREACH else None,
    )
