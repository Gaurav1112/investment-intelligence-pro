"""Next-rupee planner — ``actions.next_rupee@1`` (design-risk-first.md §5.7; risk hierarchy §4).

Where should the next contribution ``C`` (the next SIP total or a lump sum) go?  Allocation arithmetic only: no
forecast, no clock, no IO.  The risk layers are applied strictly in order L1 → L5:

* **L1 liquidity.** ``a1 = min(C, emergency_shortfall)`` goes to the reserve first.  An unknown shortfall abstains
  the whole plan (``emergency_inputs_missing``) — it cannot be skipped.
* **L2 goal-date safety.** For a goal due in fewer than ``h_safe`` years (ACT/365F), EQUITY and GOLD target weights
  become 0, redistributed pro rata to the DEBT and CASH_LIKE targets.
* **L3 loss budget.** Total equity weight is capped at ``e_cap_g`` (from ``risk.loss_budget@1``); the excess is
  redistributed pro rata to the non-equity targets.
* **L4 limits.** Inside a sleeve a scheme is chosen only if adding the amount keeps it inside its limit headroom.
* **L5 policy target.** Goals in user priority order (ties: goal_id).  For goal ``g`` the cash needed to reach its
  target using new money alone is ``a* = max_s(MV_s / w_s) − V_g`` (infinite if a zero-weight sleeve holds money);
  it receives ``a_g = min(R, a*)`` split pro rata to ``need_s = max(0, w_s × (V_g + a_g) − MV_s)``.
* **Remainder** → the goal with the largest funded-% gap ``1 − V_g / target_g`` after the step above (ties:
  earliest goal date, then goal_id), split the same way.
* **Scheme choice** (§5.7 step 4): the held scheme; else the scheme with the lowest known BER; else ABSTAIN on the
  choice and show only the sleeve amount.

Amounts are rounded to paise once, at the end, with a largest-remainder rule so they sum exactly to ``C``.
Stamp duty (0.005 %, ``engine/costs.stamp_duty``) is applied to every purchase.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from iip.engine.actions.rebalance import Abstention, PlanStep, StepCost, cash_flow_split, split_to_paise
from iip.engine.costs import stamp_duty
from iip.engine.dates import DayCount, year_fraction
from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, PAISA, ZERO, D, engine_context, money

FORMULA_ID = "actions.next_rupee@1"
RESERVE_SLEEVE = "RESERVE"

Status = Literal["ACTION", "ABSTAIN"]


class SleeveClass(StrEnum):
    EQUITY = "EQUITY"  # includes hybrids, treated as 100 % equity (design §5.2)
    GOLD = "GOLD"
    DEBT = "DEBT"
    CASH_LIKE = "CASH_LIKE"


RISKY_FOR_GOAL_DATE = frozenset({SleeveClass.EQUITY, SleeveClass.GOLD})
SAFE = frozenset({SleeveClass.DEBT, SleeveClass.CASH_LIKE})


@dataclass(frozen=True, slots=True)
class SchemeOption:
    instrument_id: str
    held: bool
    ber: Decimal | None  # None = unknown (TER/BER source is a user decision)
    headroom: Decimal | None = None  # ₹ that can be added before an L4 limit binds; None = no limit configured


@dataclass(frozen=True, slots=True)
class GoalSleeve:
    sleeve_id: str
    sleeve_class: SleeveClass
    market_value: Decimal
    policy_weight: Decimal  # user-set, from allocation_policy; the engine never invents it
    options: tuple[SchemeOption, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalInput:
    goal_id: str
    priority: int
    goal_date: date
    target_amount: Decimal | None  # ₹ goal target; None → not eligible for the remainder
    sleeves: tuple[GoalSleeve, ...]
    e_cap: Decimal | None  # from risk.loss_budget@1; required when the goal targets equity
    h_safe_years: Decimal | None  # user PARAMETER; required when the goal targets equity or gold
    abstentions: tuple[Abstention, ...] = ()  # L0 or upstream abstentions → the goal is skipped


@dataclass(frozen=True, slots=True)
class EmergencyInput:
    shortfall: Decimal | None  # from risk.emergency_gate@1; None → ABSTAIN the whole plan
    options: tuple[SchemeOption, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalTrace:
    goal_id: str
    effective_weights: tuple[tuple[str, Decimal], ...]
    layer_flags: tuple[str, ...]
    cash_to_target: Decimal | None  # a*; None = cannot be reached with new money alone
    allocated: Decimal


@dataclass(frozen=True, slots=True)
class NextRupeePlan:
    status: Status
    as_of: date
    contribution: Decimal
    steps: tuple[PlanStep, ...]
    unallocated: Decimal
    goal_traces: tuple[GoalTrace, ...]
    abstentions: tuple[Abstention, ...]
    formula_id: str = FORMULA_ID


@dataclass(frozen=True, slots=True)
class _Raw:
    layer: str
    goal_id: str | None
    sleeve_id: str
    options: tuple[SchemeOption, ...]
    amount: Decimal


def _validate(contribution: Decimal, goals: Sequence[GoalInput], emergency: EmergencyInput) -> Decimal:
    c = D(contribution)
    if c <= 0 or c != c.quantize(PAISA):
        raise InvalidInput(f"contribution must be > 0 and in whole paise, got {c}")
    if emergency.shortfall is not None and D(emergency.shortfall) < 0:
        raise InvalidInput("emergency shortfall must be ≥ 0")
    ids = [g.goal_id for g in goals]
    if len(set(ids)) != len(ids):
        raise InvalidInput("goal ids must be unique")
    for g in goals:
        sids = [s.sleeve_id for s in g.sleeves]
        if not sids or len(set(sids)) != len(sids):
            raise InvalidInput(f"goal {g.goal_id}: sleeves must be non-empty with unique ids")
        with engine_context():
            if sum((D(s.policy_weight) for s in g.sleeves), ZERO) != ONE:
                raise InvalidInput(f"goal {g.goal_id}: policy weights must sum to exactly 1")
        for s in g.sleeves:
            if D(s.market_value) < 0 or not ZERO <= D(s.policy_weight) <= ONE:
                raise InvalidInput(f"goal {g.goal_id}/{s.sleeve_id}: market value ≥ 0 and weight in [0, 1] required")
        if g.e_cap is not None and not ZERO <= D(g.e_cap) <= ONE:
            raise InvalidInput(f"goal {g.goal_id}: e_cap must be in [0, 1]")
        if g.h_safe_years is not None and D(g.h_safe_years) < 0:
            raise InvalidInput(f"goal {g.goal_id}: h_safe_years must be ≥ 0")
        if g.target_amount is not None and D(g.target_amount) <= 0:
            raise InvalidInput(f"goal {g.goal_id}: target_amount must be > 0")
    return c


def _shift(weights: list[Decimal], take_from: Sequence[bool], give_to: Sequence[bool], keep: Decimal) -> list[Decimal]:
    """Scale the ``take_from`` weights by ``keep`` and give the freed weight to ``give_to`` pro rata."""
    with engine_context():
        freed = sum((w * (ONE - keep) for w, t in zip(weights, take_from, strict=True) if t), ZERO)
        base = sum((w for w, g in zip(weights, give_to, strict=True) if g), ZERO)
        out = []
        for w, t, g in zip(weights, take_from, give_to, strict=True):
            if t:
                out.append(w * keep)
            elif g:
                out.append(w + freed * w / base)
            else:
                out.append(w)
        return out


def _effective_weights(g: GoalInput, as_of: date) -> tuple[list[Decimal] | None, list[str], Abstention | None]:
    """Apply L2 then L3 to the policy weights. Returns (weights, flags, abstention)."""
    weights = [D(s.policy_weight) for s in g.sleeves]
    classes = [s.sleeve_class for s in g.sleeves]
    flags: list[str] = []
    # ---- L2 goal-date safety
    risky = [c in RISKY_FOR_GOAL_DATE for c in classes]
    if any(w > 0 and r for w, r in zip(weights, risky, strict=True)):
        if g.h_safe_years is None:
            return (
                None,
                flags,
                Abstention("h_safe_missing", f"{g.goal_id}: safe-window years (h_safe)", "Set h_safe for this goal."),
            )
        years = year_fraction(as_of, g.goal_date, DayCount.ACT_365F) if g.goal_date > as_of else ZERO
        if years < D(g.h_safe_years):
            safe = [c in SAFE for c in classes]
            if sum((w for w, s in zip(weights, safe, strict=True) if s), ZERO) == 0:
                return (
                    None,
                    flags,
                    Abstention(
                        "no_safe_sleeve_target",
                        f"{g.goal_id}: a debt or cash target inside the safe window",
                        "Give this goal a debt or cash-like target.",
                    ),
                )
            weights = _shift(weights, risky, safe, ZERO)
            flags.append("L2_SAFE_WINDOW")
    # ---- L3 loss budget: cap total equity at e_cap
    equity = [c is SleeveClass.EQUITY for c in classes]
    with engine_context():
        w_eq = sum((w for w, e in zip(weights, equity, strict=True) if e), ZERO)
        if w_eq > 0:
            if g.e_cap is None:
                return (
                    None,
                    flags,
                    Abstention(
                        "loss_budget_missing", f"{g.goal_id}: loss limit in ₹ (e_cap)", "Set this goal's loss limit."
                    ),
                )
            cap = D(g.e_cap)
            if w_eq > cap:
                non_eq = [not e for e in equity]
                if sum((w for w, n in zip(weights, non_eq, strict=True) if n), ZERO) == 0:
                    return (
                        None,
                        flags,
                        Abstention(
                            "no_non_equity_sleeve_target",
                            f"{g.goal_id}: a non-equity target to receive weight above the equity cap",
                            "Give this goal a non-equity target.",
                        ),
                    )
                weights = _shift(weights, equity, non_eq, cap / w_eq)
                flags.append("L3_EQUITY_CAPPED")
    return weights, flags, None


def _cash_to_target(values: Sequence[Decimal], weights: Sequence[Decimal]) -> Decimal | None:
    with engine_context():
        if any(w == 0 and v > 0 for v, w in zip(values, weights, strict=True)):
            return None
        total = sum(values, ZERO)
        level = max((v / w for v, w in zip(values, weights, strict=True) if w > 0), default=ZERO)
        return max(ZERO, level - total)


def _choose(options: tuple[SchemeOption, ...], amount: Decimal) -> tuple[str | None, Abstention | None]:
    if not options:
        return None, Abstention("scheme_choice_unknown", "a scheme for this sleeve", "Add a core-universe scheme.")
    fits = [o for o in options if o.headroom is None or D(o.headroom) >= amount]
    if not fits:
        return None, Abstention(
            "limit_headroom_exhausted", "a scheme with room under your L4 limits", "Review your concentration limits."
        )
    held = sorted((o for o in fits if o.held), key=lambda o: o.instrument_id)
    if len(held) == 1:
        return held[0].instrument_id, None
    pool = held or sorted(fits, key=lambda o: o.instrument_id)
    if all(o.ber is not None for o in pool):
        best = min(pool, key=lambda o: (D(o.ber), o.instrument_id))  # type: ignore[arg-type]
        return best.instrument_id, None
    return None, Abstention(
        "scheme_choice_unknown", "expense ratio (BER) of the candidate schemes", "Add the BER or pick the scheme."
    )


_Eligible = tuple[GoalInput, list[Decimal], list[Decimal], list[str], Decimal | None]


def _eligible_goals(goals: Sequence[GoalInput], as_of: date, abstentions: list[Abstention]) -> list[_Eligible]:
    """Goals in priority order with their L2/L3-adjusted weights; abstaining goals are skipped and recorded."""
    out: list[_Eligible] = []
    for g in sorted(goals, key=lambda g: (g.priority, g.goal_id)):
        if g.abstentions:
            abstentions.extend(g.abstentions)
            continue
        weights, flags, missing = _effective_weights(g, as_of)
        if missing is not None:
            abstentions.append(missing)
            continue
        if weights is None:  # pragma: no cover - _effective_weights returns weights or an abstention
            continue
        values = [D(s.market_value) for s in g.sleeves]
        out.append((g, weights, values, flags, _cash_to_target(values, weights)))
    return out


def _allocate_goals(
    eligible: list[_Eligible], left: Decimal, raws: list[_Raw], abstentions: list[Abstention]
) -> tuple[Decimal, dict[str, Decimal]]:
    """L5 by priority, then the remainder to the largest funded-% gap. Mutates the goals' values and ``raws``."""
    allocated: dict[str, Decimal] = {g.goal_id: ZERO for g, *_ in eligible}
    with engine_context():
        for g, weights, values, _, a_star in eligible:
            if left == 0:
                break
            a = left if a_star is None else min(left, a_star)
            if a <= 0:
                continue
            shares = cash_flow_split(values, weights, a)
            for i, (s, amt) in enumerate(zip(g.sleeves, shares, strict=True)):
                if amt > 0:
                    raws.append(_Raw("L5", g.goal_id, s.sleeve_id, s.options, amt))
                values[i] += amt
            allocated[g.goal_id] += a
            left -= a
        if left <= 0:
            return left, allocated
        cands = [e for e in eligible if e[0].target_amount is not None]
        if not cands:
            abstentions.append(
                Abstention("no_goal_for_remainder", "a goal with a ₹ target", "Add a target amount to a goal.")
            )
            return left, allocated

        def gap_key(e: _Eligible) -> tuple[Decimal, date, str]:
            g, _, values, _, _ = e
            gap = ONE - sum(values, ZERO) / D(g.target_amount)  # type: ignore[arg-type]  # filtered above
            return (-gap, g.goal_date, g.goal_id)

        g, weights, values, _, _ = min(cands, key=gap_key)
        for s, amt in zip(g.sleeves, cash_flow_split(values, weights, left), strict=True):
            if amt > 0:
                raws.append(_Raw("REMAINDER", g.goal_id, s.sleeve_id, s.options, amt))
        allocated[g.goal_id] += left
    return ZERO, allocated


def _invest_steps(raws: Sequence[_Raw], parts: Sequence[Decimal], as_of: date) -> list[PlanStep]:
    steps: list[PlanStep] = []
    for r, amt in zip(raws, parts, strict=True):
        if amt <= 0:
            continue
        iid, choice_abstention = _choose(r.options, amt)
        sd = stamp_duty(amt, trade_date=as_of)
        steps.append(
            PlanStep(
                verb="INVEST",
                sleeve_id=r.sleeve_id,
                amount=amt,
                instrument_id=iid,
                goal_id=r.goal_id,
                layer=r.layer,
                cost=StepCost(stamp=sd.stamp_duty),
                net_effect=sd.invested,
                abstention=choice_abstention,
            )
        )
    return steps


def plan_next_rupee(
    contribution: Decimal,
    *,
    as_of: date,
    emergency: EmergencyInput,
    goals: Sequence[GoalInput],
) -> NextRupeePlan:
    """Plan where the next contribution goes, applying L1 → L5 in order (see the module docstring)."""
    c = _validate(contribution, goals, emergency)
    if emergency.shortfall is None:
        missing = Abstention(
            "emergency_inputs_missing",
            "essential monthly expenses and emergency months",
            "Answer the two emergency-fund questions.",
        )
        return NextRupeePlan("ABSTAIN", as_of, c, (), c, (), (missing,))

    raws: list[_Raw] = []
    abstentions: list[Abstention] = []
    with engine_context():
        a1 = min(c, D(emergency.shortfall))  # ---- L1 first
        if a1 > 0:
            raws.append(_Raw("L1", None, RESERVE_SLEEVE, emergency.options, a1))
        eligible = _eligible_goals(goals, as_of, abstentions)  # ---- L2, L3 per goal
        left, allocated = _allocate_goals(eligible, c - a1, raws, abstentions)  # ---- L5 + remainder
        parts = split_to_paise(c, [r.amount for r in raws] + [left])  # round once, summing exactly to C
    steps = _invest_steps(raws, parts[:-1], as_of)  # ---- scheme choice (L4 headroom) + stamp duty
    traces = tuple(
        GoalTrace(
            g.goal_id,
            tuple((s.sleeve_id, w) for s, w in zip(g.sleeves, weights, strict=True)),
            tuple(flags),
            a_star,
            money(allocated[g.goal_id]),
        )
        for g, weights, _, flags, a_star in eligible
    )
    status: Status = "ACTION" if steps else "ABSTAIN"
    return NextRupeePlan(status, as_of, c, tuple(steps), money(parts[-1]), traces, tuple(abstentions))
