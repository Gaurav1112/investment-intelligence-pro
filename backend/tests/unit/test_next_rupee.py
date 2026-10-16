"""``actions.next_rupee@1`` (design-risk-first.md §5.7): L1 → L5 order, allocation arithmetic, no forecast.

All values are FICTIONAL.  The oracle is an independent exact-Fraction re-implementation (ADR-0011).
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from iip.engine.actions.next_rupee import (
    FORMULA_ID,
    EmergencyInput,
    GoalInput,
    GoalSleeve,
    SchemeOption,
    SleeveClass,
    plan_next_rupee,
)
from iip.engine.actions.rebalance import Abstention
from iip.engine.errors import InvalidInput

AS_OF = date(2026, 10, 15)
FAR = date(2040, 1, 1)
LIQ = SchemeOption("LIQ", held=True, ber=None)
EQF = SchemeOption("EQF", held=True, ber=None)
DBF = SchemeOption("DBF", held=True, ber=None)


def _goal(gid: str, prio: int, eq_mv: str, debt_mv: str, eq_w: str, **kw: object) -> GoalInput:
    base = GoalInput(
        goal_id=gid,
        priority=prio,
        goal_date=FAR,
        target_amount=None,
        sleeves=(
            GoalSleeve("EQ", SleeveClass.EQUITY, Decimal(eq_mv), Decimal(eq_w), (EQF,)),
            GoalSleeve("DEBT", SleeveClass.DEBT, Decimal(debt_mv), 1 - Decimal(eq_w), (DBF,)),
        ),
        e_cap=Decimal("1"),
        h_safe_years=Decimal("3"),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _amounts(plan: object) -> list[tuple[str, str | None, str, str | None, Decimal]]:
    return [(s.layer, s.goal_id, s.sleeve_id, s.instrument_id, s.amount) for s in plan.steps]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- L1 first


def test_emergency_shortfall_is_filled_first_then_l3_capped_goal() -> None:
    g1 = _goal("G1", 1, "600000", "300000", "0.6", e_cap=Decimal("0.5"))
    plan = plan_next_rupee(
        Decimal("100000"), as_of=AS_OF, emergency=EmergencyInput(Decimal("30000"), (LIQ,)), goals=(g1,)
    )
    assert plan.status == "ACTION"
    assert plan.formula_id == FORMULA_ID == "actions.next_rupee@1"
    # L3 caps equity to 50 %: a* = max(600000/0.5, 300000/0.5) − 900000 = 300000 > 70000 → all to DEBT
    assert _amounts(plan) == [
        ("L1", None, "RESERVE", "LIQ", Decimal("30000.00")),
        ("L5", "G1", "DEBT", "DBF", Decimal("70000.00")),
    ]
    assert plan.steps[0].cost.stamp == Decimal("1.50")  # 30000 × 0.00005 / 1.00005 = 1.49992…
    assert plan.steps[0].net_effect == Decimal("29998.50")
    assert sum(s.amount for s in plan.steps) == Decimal("100000")


def test_contribution_smaller_than_shortfall_all_goes_to_reserve() -> None:
    plan = plan_next_rupee(
        Decimal("5000"),
        as_of=AS_OF,
        emergency=EmergencyInput(Decimal("30000"), (LIQ,)),
        goals=(_goal("G", 1, "1", "1", "0.5"),),
    )
    assert _amounts(plan) == [("L1", None, "RESERVE", "LIQ", Decimal("5000.00"))]


def test_unknown_emergency_inputs_abstain_the_whole_plan() -> None:
    plan = plan_next_rupee(Decimal("5000"), as_of=AS_OF, emergency=EmergencyInput(None, (LIQ,)), goals=())
    assert plan.status == "ABSTAIN"
    assert plan.steps == ()
    assert plan.abstentions[0].code == "emergency_inputs_missing"


# ---------------------------------------------------------------- L2 goal-date safety


def test_goal_inside_safe_window_gets_no_equity() -> None:
    g = _goal("G", 1, "0", "0", "0.7", goal_date=date(2028, 6, 1), target_amount=Decimal("500000"))
    plan = plan_next_rupee(Decimal("70000"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g,))
    assert _amounts(plan) == [("REMAINDER", "G", "DEBT", "DBF", Decimal("70000.00"))]
    (gt,) = plan.goal_traces
    assert gt.effective_weights == (("EQ", Decimal(0)), ("DEBT", Decimal(1)))
    assert "L2_SAFE_WINDOW" in gt.layer_flags


def test_safe_window_without_a_safe_sleeve_abstains_for_that_goal() -> None:
    g = _goal("G", 1, "0", "0", "1", goal_date=date(2027, 1, 1), target_amount=Decimal("1"))
    plan = plan_next_rupee(Decimal("100"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g,))
    assert [a.code for a in plan.abstentions] == ["no_safe_sleeve_target", "no_goal_for_remainder"]
    assert plan.unallocated == Decimal("100.00")


def test_missing_h_safe_or_e_cap_abstains_only_that_goal() -> None:
    g1 = _goal("G1", 1, "100", "100", "0.5", h_safe_years=None, target_amount=Decimal("1000"))
    g2 = _goal("G2", 2, "100", "100", "0.5", e_cap=None, target_amount=Decimal("1000"))
    g3 = _goal("G3", 3, "0", "0", "0.5", target_amount=Decimal("1000"))
    plan = plan_next_rupee(Decimal("1000"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g1, g2, g3))
    assert {(a.code, a.missing_input.split(":")[0]) for a in plan.abstentions} == {
        ("h_safe_missing", "G1"),
        ("loss_budget_missing", "G2"),
    }
    assert {s.goal_id for s in plan.steps} == {"G3"}
    assert sum(s.amount for s in plan.steps) == Decimal("1000")


def test_caller_abstention_skips_goal() -> None:
    ab = Abstention("stale_nav", "G1: NAV older than 5 days", "Refresh data.")
    g1 = _goal("G1", 1, "100", "900", "0.5", abstentions=(ab,))
    g2 = _goal("G2", 2, "100", "900", "0.5")
    plan = plan_next_rupee(Decimal("200"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g1, g2))
    assert ab in plan.abstentions
    assert _amounts(plan) == [("L5", "G2", "EQ", "EQF", Decimal("200.00"))]


# ---------------------------------------------------------------- L5 priorities and remainder


def test_priority_goal_rebalanced_first_then_remainder_to_largest_funded_gap() -> None:
    g1 = _goal("G1", 1, "500000", "500000", "0.6", target_amount=Decimal("2000000"))
    g2 = _goal("G2", 2, "0", "0", "0.7", target_amount=Decimal("500000"))
    g3 = _goal("G3", 3, "70", "30", "0.7", target_amount=Decimal("100"))  # on target, funded 100 % → gap 0
    plan = plan_next_rupee(Decimal("300000"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g2, g3, g1))
    # G1 a* = max(500000/0.6, 500000/0.4) − 1000000 = 250000, all of it to the underweight EQ sleeve.
    # Remainder 50000 → largest funded-% gap after step 2: G1 1 − 1.25M/2M = 0.375, G2 1.0, G3 0 → G2, split 70/30.
    assert _amounts(plan) == [
        ("L5", "G1", "EQ", "EQF", Decimal("250000.00")),
        ("REMAINDER", "G2", "EQ", "EQF", Decimal("35000.00")),
        ("REMAINDER", "G2", "DEBT", "DBF", Decimal("15000.00")),
    ]
    assert sum(s.amount for s in plan.steps) == Decimal("300000")


def test_zero_weight_sleeve_holding_money_absorbs_whole_remaining_amount() -> None:
    g1 = _goal("G1", 1, "100", "0", "0")  # 100 % debt target but holds equity: cash alone can never fix it
    g2 = _goal("G2", 2, "0", "0", "0.5", target_amount=Decimal("10"))
    plan = plan_next_rupee(Decimal("50"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g1, g2))
    assert _amounts(plan) == [("L5", "G1", "DEBT", "DBF", Decimal("50.00"))]


def test_remainder_tie_breaks_by_earliest_goal_date() -> None:
    g1 = _goal("G1", 1, "0", "0", "0.5", target_amount=Decimal("100"), goal_date=date(2045, 1, 1))
    g2 = _goal("G2", 2, "0", "0", "0.5", target_amount=Decimal("100"), goal_date=date(2041, 1, 1))
    plan = plan_next_rupee(Decimal("10"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g1, g2))
    assert {s.goal_id for s in plan.steps} == {"G2"}


# ---------------------------------------------------------------- scheme choice inside a sleeve (with L4 headroom)


def test_scheme_choice_held_then_lowest_ber_then_abstain() -> None:
    a = SchemeOption("A", held=False, ber=Decimal("0.0020"))
    b = SchemeOption("B", held=False, ber=Decimal("0.0010"))
    h = SchemeOption("H", held=True, ber=None, headroom=Decimal("50"))
    sleeve_opts = {
        "held_fits": (a, b, replace(h, headroom=None)),
        "held_full": (a, b, h),
        "unknown_ber": (replace(a, ber=None),),
    }
    got = {}
    for name, opts in sleeve_opts.items():
        g = GoalInput(
            "G",
            1,
            FAR,
            Decimal("1000"),
            (GoalSleeve("DEBT", SleeveClass.DEBT, Decimal(0), Decimal(1), opts),),
            e_cap=None,
            h_safe_years=None,
        )
        plan = plan_next_rupee(Decimal("100"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g,))
        (step,) = plan.steps
        got[name] = (step.instrument_id, step.abstention.code if step.abstention else None)
    assert got == {
        "held_fits": ("H", None),
        "held_full": ("B", None),  # held scheme would breach its L4 limit → cheapest known BER
        "unknown_ber": (None, "scheme_choice_unknown"),
    }


def test_reserve_without_options_shows_sleeve_amount_only() -> None:
    plan = plan_next_rupee(Decimal("100"), as_of=AS_OF, emergency=EmergencyInput(Decimal("100"), ()), goals=())
    (step,) = plan.steps
    assert step.instrument_id is None and step.amount == Decimal("100.00")
    assert step.abstention is not None and step.abstention.code == "scheme_choice_unknown"


# ---------------------------------------------------------------- validation and determinism


@pytest.mark.parametrize("c", [Decimal("0"), Decimal("-1"), Decimal("10.005")])
def test_contribution_must_be_positive_whole_paise(c: Decimal) -> None:
    with pytest.raises(InvalidInput):
        plan_next_rupee(c, as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=())


def test_weights_must_sum_to_one() -> None:
    g = _goal("G", 1, "0", "0", "0.5")
    bad = replace(g, sleeves=(g.sleeves[0], replace(g.sleeves[1], policy_weight=Decimal("0.4"))))
    with pytest.raises(InvalidInput):
        plan_next_rupee(Decimal(1), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(bad,))


def test_paise_rounding_sums_exactly() -> None:
    weights = (Decimal("0.4"), Decimal("0.3"), Decimal("0.3"))
    g = GoalInput(
        "G",
        1,
        FAR,
        Decimal("1000"),
        tuple(GoalSleeve(f"D{i}", SleeveClass.DEBT, Decimal(0), w, (DBF,)) for i, w in enumerate(weights)),
        e_cap=None,
        h_safe_years=None,
    )
    plan = plan_next_rupee(Decimal("0.05"), as_of=AS_OF, emergency=EmergencyInput(Decimal(0), ()), goals=(g,))
    # raw 0.02 / 0.015 / 0.015 → floors 0.02 / 0.01 / 0.01, the spare paisa goes to the first largest remainder
    assert [s.amount for s in plan.steps] == [Decimal("0.02"), Decimal("0.02"), Decimal("0.01")]


# ---------------------------------------------------------------- oracle


def _oracle(c: int, shortfall: int, goals: list[GoalInput]) -> dict[tuple[str, str], Fraction]:
    """Exact re-implementation of §5.7 for goals with far dates, e_cap = 1, no abstentions."""
    out: dict[tuple[str, str], Fraction] = {}
    left = Fraction(c)
    take = min(left, Fraction(shortfall))
    if take:
        out[("", "RESERVE")] = take
    left -= take

    def fill(g: GoalInput, amount: Fraction) -> None:
        mv = {s.sleeve_id: Fraction(str(s.market_value)) + out.get((g.goal_id, s.sleeve_id), 0) for s in g.sleeves}
        w = {s.sleeve_id: Fraction(str(s.policy_weight)) for s in g.sleeves}
        v_after = sum(mv.values()) + amount
        need = {k: max(Fraction(0), w[k] * v_after - mv[k]) for k in mv}
        tot = sum(need.values())
        for k in mv:
            if need[k]:
                out[(g.goal_id, k)] = out.get((g.goal_id, k), Fraction(0)) + amount * need[k] / tot

    for g in sorted(goals, key=lambda g: (g.priority, g.goal_id)):
        if left == 0:
            break
        # bisection-free closed form, computed differently: smallest a with all w_k(V+a) ≥ MV_k
        mv = {s.sleeve_id: Fraction(str(s.market_value)) for s in g.sleeves}
        w = {s.sleeve_id: Fraction(str(s.policy_weight)) for s in g.sleeves}
        v = sum(mv.values())
        if any(w[k] == 0 and mv[k] > 0 for k in mv):
            a_star = left
        else:
            a_star = Fraction(0)
            for k, value in mv.items():
                if w[k] > 0:
                    a_star = max(a_star, value / w[k] - v)
        a = min(left, a_star)
        if a > 0:
            fill(g, a)
            left -= a
    if left > 0:

        def gap(g: GoalInput) -> tuple[Fraction, int, str]:
            v = sum(Fraction(str(s.market_value)) for s in g.sleeves)
            v += sum(amt for (gid, _), amt in out.items() if gid == g.goal_id)
            return (-(1 - v / Fraction(str(g.target_amount))), g.goal_date.toordinal(), g.goal_id)

        fill(min(goals, key=gap), left)
    return out


@pytest.mark.parametrize("seed", range(40))
def test_matches_independent_oracle(seed: int) -> None:
    rng = random.Random(1000 + seed)
    goals = []
    for i in range(rng.randint(1, 4)):
        eq_w = Decimal(rng.randint(0, 10)) / 10
        goals.append(
            _goal(
                f"G{i}",
                rng.randint(1, 3),
                str(rng.randint(0, 50) * 1000),
                str(rng.randint(0, 50) * 1000),
                str(eq_w),
                target_amount=Decimal(rng.randint(1, 200) * 1000),
                goal_date=date(2035 + rng.randint(0, 10), 1, 1),
            )
        )
    c = rng.randint(1, 200) * 500
    shortfall = rng.choice([0, 0, rng.randint(1, 40) * 1000])
    plan = plan_next_rupee(Decimal(c), as_of=AS_OF, emergency=EmergencyInput(Decimal(shortfall), (LIQ,)), goals=goals)
    expected = _oracle(c, shortfall, goals)
    got: dict[tuple[str, str], Decimal] = {}
    for s in plan.steps:
        key = (s.goal_id or "", s.sleeve_id)
        got[key] = got.get(key, Decimal(0)) + s.amount
    assert set(got) <= set(expected)
    for k, v in expected.items():  # each step is within one paisa of the exact share (two steps per key at most)
        assert abs(Fraction(str(got.get(k, Decimal(0)))) - v) < Fraction(2, 100), (k, v, got)
    assert sum(got.values()) == Decimal(c)
    # L1 → L5 order: the reserve step (if any) comes first and equals min(C, shortfall)
    if shortfall:
        assert plan.steps[0].layer == "L1" and plan.steps[0].amount == min(Decimal(c), Decimal(shortfall))
