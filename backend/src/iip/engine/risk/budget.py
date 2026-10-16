"""L3 loss budget and the equity cap — ``risk.loss_budget@1`` (design-risk-first.md §5.3).

Per goal ``g`` (user inputs, mandatory for any goal with equity, U-02): ``B_g`` the ₹ fall the user would sit through
without selling, and ``T_g`` the longest number of months they would wait for a recovery.

    stress_loss = Σ_i MV_i × s(class_i)        all equity sleeves added at correlation 1 (no diversification credit)
    breach      = stress_loss > B
    b           = B / V
    s_e         = MV-weighted stress of the equity sleeves (hybrids count as 100 % equity)
    s_d         = MV-weighted stress of the non-equity sleeves (debt from the duration formula)
    b < s_d     → ABSTAIN(budget_below_non_equity_stress)      even 0 % equity breaches the budget
    e_cap       = floor_0.01( min(policy_cap, (b − s_d) / (s_e − s_d)) )

When the goal holds no equity (or no non-equity), the policy's model sleeve supplies ``s_e`` (or ``s_d``); the model
sleeve's market values are used only as weights.

A breach never triggers a sale.  The only remedy named here is redirecting new contributions; a market fall lowers the
stress loss and can only clear a breach, never create one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, D, engine_context
from iip.engine.risk import (
    EQUITY_CLASSES,
    REMEDY_REDIRECT_NEW_CONTRIBUTIONS,
    Abstention,
    Outcome,
    RiskClass,
)
from iip.engine.risk.stress import ClassStress, CreditBucket, DebtShock, debt_mtm_stress

RULE_ID = "risk.loss_budget@1"
CAP_QUANTUM = D("0.01")  # a 1 percentage-point grid; caps never round up
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class BudgetHolding:
    holding_id: str
    risk_class: RiskClass
    market_value: Decimal
    modified_duration: Decimal | None = None  # DEBT_MTM only
    spread_duration: Decimal | None = None  # DEBT_MTM only
    credit: CreditBucket | None = None  # DEBT_MTM only


@dataclass(frozen=True)
class StressLine:
    holding_id: str
    risk_class: RiskClass
    market_value: Decimal
    is_equity: bool
    stress: Decimal | None  # None → abstained
    stress_loss: Decimal | None
    formula_id: str


@dataclass(frozen=True)
class LossBudgetResult:
    goal_id: str
    outcome: Outcome
    goal_value: Decimal
    loss_budget_inr: Decimal | None
    loss_budget_fraction: Decimal | None  # b = B / V; feeds RankingRequest.loss_budget
    stress_loss: Decimal  # lower bound when some lines abstained (see stress_complete)
    stress_complete: bool
    breach: bool
    excess_stress_loss: Decimal  # max(0, stress_loss − B)
    equity_value: Decimal
    equity_stress: Decimal | None  # s_e
    non_equity_stress: Decimal | None  # s_d
    e_cap_raw: Decimal | None  # (b − s_d) / (s_e − s_d) before the policy cap and rounding
    e_cap: Decimal | None  # floor-rounded to 0.01
    equity_over_cap_inr: Decimal | None  # max(0, E − e_cap × V)
    loss_at_cap_equity: Decimal | None  # e_cap × V × s_e
    loss_at_cap_non_equity: Decimal | None  # (1 − e_cap) × V × s_d
    worst_recovery_years: Decimal | None
    lines: tuple[StressLine, ...]
    abstentions: tuple[Abstention, ...]
    flags: tuple[str, ...]
    remedy: str | None  # only ever REDIRECT_NEW_CONTRIBUTIONS; never a sale
    rule_id: str = RULE_ID


def _stress_line(h: BudgetHolding, table: Mapping[RiskClass, ClassStress], shock: DebtShock | None) -> StressLine:
    if h.market_value < 0:
        raise InvalidInput(f"holding {h.holding_id!r}: market value must be ≥ 0")
    is_equity = h.risk_class in EQUITY_CLASSES
    stress: Decimal | None
    if h.risk_class is RiskClass.DEBT_MTM:
        debt = debt_mtm_stress(h.modified_duration, h.spread_duration, h.credit, shock)
        stress, formula_id = debt.value, debt.formula_id
    else:
        row = table.get(h.risk_class)
        stress = None if row is None else row.value
        formula_id = "risk.stress_combinator@1" if row is None else row.formula_id
    with engine_context():
        loss = None if stress is None else h.market_value * stress
    return StressLine(h.holding_id, h.risk_class, h.market_value, is_equity, stress, loss, formula_id)


def _weighted(lines: Sequence[StressLine]) -> Decimal | None:
    """MV-weighted stress; None when any line abstained or the sleeve has no value."""
    if not lines or any(line.stress is None for line in lines):
        return None
    with engine_context():
        total = sum((line.market_value for line in lines), ZERO)
        if total == 0:
            return None
        return sum((line.market_value * line.stress for line in lines if line.stress is not None), ZERO) / total


def _missing_stress(line: StressLine) -> Abstention:
    if line.risk_class is RiskClass.DEBT_MTM:
        return Abstention(
            code="duration_missing",
            missing_input=f"duration or credit rating for {line.holding_id}",
            how_to_fix="enter modified duration, spread duration and lowest rating from the latest factsheet",
        )
    return Abstention(
        code="stress_value_missing",
        missing_input=f"stress value for {line.risk_class} ({line.holding_id})",
        how_to_fix="add the cited stress row to local config or recompute the drawdown from AMFI NAV history",
    )


def _validate(
    loss_budget_inr: Decimal | None,
    policy_cap: Decimal | None,
    recovery_tolerance_months: int | None,
    planned_value: Decimal | None,
    policy_equity_sleeve: Sequence[BudgetHolding],
    policy_non_equity_sleeve: Sequence[BudgetHolding],
) -> None:
    if loss_budget_inr is not None and loss_budget_inr < 0:
        raise InvalidInput("loss budget must be ≥ 0")
    if policy_cap is not None and not (ZERO <= policy_cap <= ONE):
        raise InvalidInput("policy cap must be a fraction in [0, 1]")
    if recovery_tolerance_months is not None and recovery_tolerance_months < 0:
        raise InvalidInput("recovery tolerance must be ≥ 0 months")
    if planned_value is not None and planned_value <= 0:
        raise InvalidInput("planned value must be > 0")
    for model in policy_equity_sleeve:
        if model.risk_class not in EQUITY_CLASSES:
            raise InvalidInput(f"policy equity sleeve contains non-equity class {model.risk_class}")
    for model in policy_non_equity_sleeve:
        if model.risk_class in EQUITY_CLASSES:
            raise InvalidInput(f"policy non-equity sleeve contains equity class {model.risk_class}")


def _recovery_check(
    goal_id: str,
    equity_sleeve: Sequence[StressLine],
    has_equity: bool,
    stress_table: Mapping[RiskClass, ClassStress],
    recovery_tolerance_months: int | None,
    abstentions: list[Abstention],
    flags: list[str],
) -> Decimal | None:
    """The worst peak→recovery duration among the equity classes (a historical fact, not a prediction)."""
    equity_classes = sorted({line.risk_class for line in equity_sleeve})
    recoveries = [stress_table[rc].recovery_years if rc in stress_table else None for rc in equity_classes]
    known = [r for r in recoveries if r is not None]
    worst = max(known) if known else None
    if equity_classes and len(known) < len(recoveries):
        flags.append("RECOVERY_UNKNOWN_FOR_SOME_EQUITY")
    if has_equity and recovery_tolerance_months is None:
        abstentions.append(
            Abstention(
                code="recovery_tolerance_missing",
                missing_input=f"recovery tolerance in months for goal {goal_id}",
                how_to_fix="enter the longest number of months you would wait for this goal to recover",
            )
        )
    if (
        recovery_tolerance_months is not None
        and worst is not None
        and worst * MONTHS_PER_YEAR > recovery_tolerance_months
    ):
        flags.append("RECOVERY_EXCEEDS_TOLERANCE")
    return worst


@dataclass(frozen=True)
class _Cap:
    b: Decimal | None = None
    e_raw: Decimal | None = None
    e_cap: Decimal | None = None
    below_floor: bool = False


def _equity_cap(
    goal_id: str,
    *,
    loss_budget_inr: Decimal | None,
    basis: Decimal | None,
    s_e: Decimal | None,
    s_d: Decimal | None,
    equity_sleeve_known: bool,
    non_equity_sleeve_known: bool,
    policy_cap: Decimal | None,
    abstentions: list[Abstention],
    flags: list[str],
) -> _Cap:
    if loss_budget_inr is None:
        abstentions.insert(
            0,
            Abstention(
                code="loss_budget_missing",
                missing_input=f"loss limit in ₹ for goal {goal_id}",
                how_to_fix="view the worst-fall table, then enter the largest ₹ fall you would sit through "
                "without selling",
            ),
        )
        return _Cap()
    if basis is None:
        abstentions.append(
            Abstention(
                code="goal_value_missing",
                missing_input=f"planned value for empty goal {goal_id}",
                how_to_fix="enter how much this goal will hold",
            )
        )
        return _Cap()
    with engine_context():
        b = loss_budget_inr / basis
    if s_d is None:
        if not non_equity_sleeve_known:  # otherwise the abstaining line is already listed
            abstentions.append(
                Abstention(
                    code="non_equity_mix_unknown",
                    missing_input=f"non-equity sleeve stress for goal {goal_id}",
                    how_to_fix="hold or choose the non-equity sleeve for this goal (with debt durations)",
                )
            )
        return _Cap(b=b)
    if b < s_d:
        abstentions.insert(
            0,
            Abstention(
                code="budget_below_non_equity_stress",
                missing_input=f"a loss limit of at least {s_d} of the goal value",
                how_to_fix="even 0 % equity breaches this loss limit: raise the limit or choose a lower-stress "
                "non-equity sleeve",
            ),
        )
        return _Cap(b=b, below_floor=True)
    if s_e is None:
        if not equity_sleeve_known:
            abstentions.append(
                Abstention(
                    code="equity_mix_unknown",
                    missing_input=f"equity sleeve stress for goal {goal_id}",
                    how_to_fix="choose the policy equity sleeve for this goal",
                )
            )
        return _Cap(b=b)
    with engine_context():
        if s_e <= s_d:
            e_raw = ONE
            flags.append("EQUITY_STRESS_NOT_ABOVE_NON_EQUITY")
        else:
            e_raw = (b - s_d) / (s_e - s_d)
        capped = min(e_raw, ONE)
        if policy_cap is None:
            flags.append("POLICY_CAP_NOT_SUPPLIED")
        else:
            capped = min(capped, policy_cap)
        e_cap = capped.quantize(CAP_QUANTUM, rounding=ROUND_FLOOR)
    return _Cap(b=b, e_raw=e_raw, e_cap=e_cap)


def loss_budget(
    goal_id: str,
    *,
    loss_budget_inr: Decimal | None,
    holdings: Sequence[BudgetHolding],
    stress_table: Mapping[RiskClass, ClassStress],
    recovery_tolerance_months: int | None = None,
    policy_cap: Decimal | None = None,
    policy_equity_sleeve: Sequence[BudgetHolding] = (),
    policy_non_equity_sleeve: Sequence[BudgetHolding] = (),
    planned_value: Decimal | None = None,
    debt_shock: DebtShock | None = None,
) -> LossBudgetResult:
    """Evaluate L3 for one goal.  Pure; Decimal throughout."""
    _validate(
        loss_budget_inr,
        policy_cap,
        recovery_tolerance_months,
        planned_value,
        policy_equity_sleeve,
        policy_non_equity_sleeve,
    )
    lines = tuple(_stress_line(h, stress_table, debt_shock) for h in holdings)
    abstentions: list[Abstention] = [_missing_stress(line) for line in lines if line.stress is None]
    flags: list[str] = []
    stress_complete = not abstentions

    with engine_context():
        goal_value = sum((line.market_value for line in lines), ZERO)
        equity_value = sum((line.market_value for line in lines if line.is_equity), ZERO)
        stress_loss = sum((line.stress_loss for line in lines if line.stress_loss is not None), ZERO)
    if any(line.risk_class is RiskClass.HYBRID for line in lines):
        flags.append("HYBRID_COUNTED_AS_100PCT_EQUITY")
    if sum(1 for line in lines if line.is_equity) > 1:
        flags.append("EQUITY_SLEEVES_CORRELATION_1")

    held_equity = [line for line in lines if line.is_equity and line.market_value > 0]
    held_non_equity = [line for line in lines if not line.is_equity and line.market_value > 0]
    equity_sleeve = held_equity or [_stress_line(h, stress_table, debt_shock) for h in policy_equity_sleeve]
    non_equity_sleeve = held_non_equity or [_stress_line(h, stress_table, debt_shock) for h in policy_non_equity_sleeve]
    if not held_equity and policy_equity_sleeve:
        flags.append("EQUITY_STRESS_FROM_POLICY_SLEEVE")
    if not held_non_equity and policy_non_equity_sleeve:
        flags.append("NON_EQUITY_STRESS_FROM_POLICY_SLEEVE")
    s_e = _weighted(equity_sleeve)
    s_d = _weighted(non_equity_sleeve)

    worst_recovery = _recovery_check(
        goal_id, equity_sleeve, bool(held_equity), stress_table, recovery_tolerance_months, abstentions, flags
    )
    basis = goal_value if goal_value > 0 else planned_value
    cap = _equity_cap(
        goal_id,
        loss_budget_inr=loss_budget_inr,
        basis=basis,
        s_e=s_e,
        s_d=s_d,
        equity_sleeve_known=bool(equity_sleeve),
        non_equity_sleeve_known=bool(non_equity_sleeve),
        policy_cap=policy_cap,
        abstentions=abstentions,
        flags=flags,
    )

    breach = loss_budget_inr is not None and stress_loss > loss_budget_inr
    e_cap = cap.e_cap
    with engine_context():
        excess = max(ZERO, stress_loss - loss_budget_inr) if loss_budget_inr is not None else ZERO
        over_cap = None if e_cap is None else max(ZERO, equity_value - e_cap * goal_value)
        cap_basis = basis if basis is not None else ZERO
        at_cap_eq = None if e_cap is None or s_e is None else e_cap * cap_basis * s_e
        at_cap_ne = None if e_cap is None or s_d is None else (ONE - e_cap) * cap_basis * s_d

    if loss_budget_inr is None or cap.below_floor:
        outcome = Outcome.ABSTAIN
    elif breach:
        outcome = Outcome.BREACH  # a known breach (even a lower bound) is never hidden by a missing input
        if not stress_complete:
            flags.append("BREACH_ON_PARTIAL_STRESS_LOWER_BOUND")
    elif abstentions:  # fail closed: any missing input (stress, recovery tolerance, sleeve mix) abstains
        outcome = Outcome.ABSTAIN
    else:
        outcome = Outcome.PASS

    return LossBudgetResult(
        goal_id=goal_id,
        outcome=outcome,
        goal_value=goal_value,
        loss_budget_inr=loss_budget_inr,
        loss_budget_fraction=cap.b,
        stress_loss=stress_loss,
        stress_complete=stress_complete,
        breach=breach,
        excess_stress_loss=excess,
        equity_value=equity_value,
        equity_stress=s_e,
        non_equity_stress=s_d,
        e_cap_raw=cap.e_raw,
        e_cap=e_cap,
        equity_over_cap_inr=over_cap,
        loss_at_cap_equity=at_cap_eq,
        loss_at_cap_non_equity=at_cap_ne,
        worst_recovery_years=worst_recovery,
        lines=lines,
        abstentions=tuple(abstentions),
        flags=tuple(flags),
        remedy=REMEDY_REDIRECT_NEW_CONTRIBUTIONS if breach else None,
    )
