"""L1 emergency-fund gate — ``risk.emergency_gate@1`` (design-risk-first.md §5.1).

    target_reserve  = months × essential_monthly_expenses                 (both user inputs, U-03)
    liquid_reserves = savings + sweep FD + Σ overnight/liquid MF (MV − exit load if redeemed today)
    shortfall       = max(0, target_reserve − liquid_reserves)

* ELSS and every other lock-in count as zero liquidity, as does anything not in the liquid list.
* The 3–6 month range is US-regulator guidance (Investor.gov); a SEBI attribution is NOT VERIFIED.  The engine never
  chooses the number of months: it is a user input.
* Missing months or expenses → ``ABSTAIN(emergency_inputs_missing)``; growth views still render under a banner.
* Bank balances above the DICGC cover are flagged by reusing :func:`iip.engine.deposits.dicgc_coverage`.

A shortfall is a ``BREACH``: every new rupee goes to the reserve first.  It never asks for a sale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from iip.engine.deposits import ABOVE_LIMIT, NOT_INSURED, DepositHolding, dicgc_coverage
from iip.engine.errors import InvalidInput
from iip.engine.money import ZERO, engine_context
from iip.engine.risk import REMEDY_REDIRECT_NEW_CONTRIBUTIONS, Abstention, Outcome

RULE_ID = "risk.emergency_gate@1"


class LiquidityKind(StrEnum):
    SAVINGS = "SAVINGS"
    SWEEP_FD = "SWEEP_FD"
    OVERNIGHT_MF = "OVERNIGHT_MF"
    LIQUID_MF = "LIQUID_MF"
    LOCK_IN = "LOCK_IN"  # ELSS and other lock-ins: zero liquidity
    OTHER = "OTHER"  # anything else: not counted


COUNTED: frozenset[LiquidityKind] = frozenset(
    {LiquidityKind.SAVINGS, LiquidityKind.SWEEP_FD, LiquidityKind.OVERNIGHT_MF, LiquidityKind.LIQUID_MF}
)
_MF_KINDS = frozenset({LiquidityKind.OVERNIGHT_MF, LiquidityKind.LIQUID_MF})


@dataclass(frozen=True)
class ReserveHolding:
    holding_id: str
    kind: LiquidityKind
    market_value: Decimal
    exit_load_if_redeemed_today: Decimal = ZERO  # ₹; MF kinds only


@dataclass(frozen=True)
class ReserveLine:
    holding_id: str
    kind: LiquidityKind
    market_value: Decimal
    counted_value: Decimal  # zero when not counted


@dataclass(frozen=True)
class EmergencyResult:
    outcome: Outcome  # PASS, BREACH or ABSTAIN
    months: int | None
    essential_monthly_expenses: Decimal | None
    target_reserve: Decimal | None
    liquid_reserves: Decimal
    shortfall: Decimal | None
    lines: tuple[ReserveLine, ...]
    abstentions: tuple[Abstention, ...]
    flags: tuple[str, ...]
    remedy: str | None  # REDIRECT_NEW_CONTRIBUTIONS on a shortfall; never a sale
    rule_id: str = RULE_ID


def emergency_gate(
    *,
    months: int | None,
    essential_monthly_expenses: Decimal | None,
    holdings: Sequence[ReserveHolding],
    deposits: Sequence[DepositHolding] = (),
    as_of: date | None = None,
) -> EmergencyResult:
    """Evaluate L1.  ``deposits`` and ``as_of`` are needed only for the DICGC flag."""
    if months is not None and months <= 0:
        raise InvalidInput("months must be a positive whole number")
    if essential_monthly_expenses is not None and essential_monthly_expenses < 0:
        raise InvalidInput("essential monthly expenses must be ≥ 0")
    lines: list[ReserveLine] = []
    flags: list[str] = []
    with engine_context():
        for h in holdings:
            if h.market_value < 0 or h.exit_load_if_redeemed_today < 0:
                raise InvalidInput(f"holding {h.holding_id!r}: values must be ≥ 0")
            if h.exit_load_if_redeemed_today > h.market_value:
                raise InvalidInput(f"holding {h.holding_id!r}: exit load exceeds market value")
            if h.kind not in _MF_KINDS and h.exit_load_if_redeemed_today != 0:
                raise InvalidInput(f"holding {h.holding_id!r}: exit load applies to mutual fund kinds only")
            counted = h.market_value - h.exit_load_if_redeemed_today if h.kind in COUNTED else ZERO
            if h.kind is LiquidityKind.LOCK_IN and h.market_value > 0:
                flags.append("LOCK_IN_COUNTED_AS_ZERO")
            lines.append(ReserveLine(h.holding_id, h.kind, h.market_value, counted))
        liquid = sum((line.counted_value for line in lines), ZERO)

    if deposits:
        if as_of is None:
            raise InvalidInput("as_of is required to check deposit insurance cover")
        cover = dicgc_coverage(deposits, as_of=as_of)
        if any(ABOVE_LIMIT in g.flags for g in cover.groups):
            flags.append("DEPOSIT_ABOVE_DICGC_LIMIT")
        if any(NOT_INSURED in g.flags for g in cover.groups):
            flags.append("DEPOSIT_NOT_DICGC_INSURED")
    flags = sorted(set(flags))

    if months is None or essential_monthly_expenses is None:
        missing = [
            n for n, v in (("months", months), ("essential monthly expenses", essential_monthly_expenses)) if v is None
        ]
        return EmergencyResult(
            outcome=Outcome.ABSTAIN,
            months=months,
            essential_monthly_expenses=essential_monthly_expenses,
            target_reserve=None,
            liquid_reserves=liquid,
            shortfall=None,
            lines=tuple(lines),
            abstentions=(
                Abstention(
                    code="emergency_inputs_missing",
                    missing_input=" and ".join(missing),
                    how_to_fix="enter your essential monthly expenses and how many months of reserve you want",
                ),
            ),
            flags=(*flags, "SEBI_ATTRIBUTION_NOT_VERIFIED"),
            remedy=None,
        )
    with engine_context():
        target = essential_monthly_expenses * months
        shortfall = max(ZERO, target - liquid)
    breach = shortfall > 0
    return EmergencyResult(
        outcome=Outcome.BREACH if breach else Outcome.PASS,
        months=months,
        essential_monthly_expenses=essential_monthly_expenses,
        target_reserve=target,
        liquid_reserves=liquid,
        shortfall=shortfall,
        lines=tuple(lines),
        abstentions=(),
        flags=tuple(flags),
        remedy=REMEDY_REDIRECT_NEW_CONTRIBUTIONS if breach else None,
    )
