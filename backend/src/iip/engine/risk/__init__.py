"""Risk layers L1–L4 of the risk-first engine (design-risk-first.md §4, §5.1–5.5; PLAN.md package A12).

Shared vocabulary for the risk modules.  Every function in this package is pure: Decimal money under
``engine_context()``, no clock, IO or randomness.  ``as_of`` is always an argument.

* A layer returns ``PASS``, ``ACTION`` (a card that does not suppress lower layers), ``BREACH`` (a card that suppresses
  lower layers for that goal) or ``ABSTAIN`` (a named missing input; fails closed).
* Percentages are fractions; stress values are positive magnitudes of a fall (0.30 means a 30 % fall).
* No function in this package ever proposes a sale.  The only remedy a risk layer names is redirecting new
  contributions; whether any sale is allowed is a user policy (U-04, default cash-flow-only) decided downstream.

This module deliberately does not import its submodules, so they can import these shared types without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Outcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - an outcome label, not a credential
    ACTION = "ACTION"
    BREACH = "BREACH"
    ABSTAIN = "ABSTAIN"


class Status(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT VERIFIED"
    REQUIRES_CONFIGURATION = "REQUIRES CONFIGURATION"
    BLOCKED = "BLOCKED"


class RiskClass(StrEnum):
    EQ_LARGE = "EQ_LARGE"
    EQ_BROAD = "EQ_BROAD"
    EQ_MID = "EQ_MID"
    EQ_SMALL = "EQ_SMALL"
    EQ_FACTOR = "EQ_FACTOR"
    EQ_SECTOR_THEMATIC = "EQ_SECTOR_THEMATIC"
    HYBRID = "HYBRID"  # treated as 100 % EQ_BROAD (design §5.2, conservative PARAMETER)
    STOCK = "STOCK"  # single company; deliberately maximal stress 1.00
    GOLD = "GOLD"
    DEBT_MTM = "DEBT_MTM"  # stress from the duration formula, never from the table
    CASH_LIKE = "CASH_LIKE"  # no mark-to-market stress; default risk is handled in L4


# Classes that count as equity for the loss budget and the goal-date window.  Hybrids count as 100 % equity.
EQUITY_CLASSES: frozenset[RiskClass] = frozenset(
    {
        RiskClass.EQ_LARGE,
        RiskClass.EQ_BROAD,
        RiskClass.EQ_MID,
        RiskClass.EQ_SMALL,
        RiskClass.EQ_FACTOR,
        RiskClass.EQ_SECTOR_THEMATIC,
        RiskClass.HYBRID,
        RiskClass.STOCK,
    }
)

# The only remedy a risk layer may name.  Sales are never triggered here (PLAN A12: "No sale is ever triggered by a
# drawdown"); a downstream package may offer FIFO sales only after the user enables them for an L3 breach (U-04).
REMEDY_REDIRECT_NEW_CONTRIBUTIONS = "REDIRECT_NEW_CONTRIBUTIONS"


@dataclass(frozen=True)
class Abstention:
    code: str
    missing_input: str
    how_to_fix: str


def combine_outcomes(outcomes: list[Outcome], *, precedence: tuple[Outcome, ...]) -> Outcome:
    """Return the first outcome in ``precedence`` that occurs; PASS when none do."""
    for candidate in precedence:
        if candidate in outcomes:
            return candidate
    return Outcome.PASS


__all__ = [
    "EQUITY_CLASSES",
    "REMEDY_REDIRECT_NEW_CONTRIBUTIONS",
    "Abstention",
    "Outcome",
    "RiskClass",
    "Status",
    "combine_outcomes",
]
