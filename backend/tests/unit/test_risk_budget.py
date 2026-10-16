"""L3 loss budget and equity cap (design-risk-first.md §5.3; PLAN A12).

Every value is a FICTIONAL fixture.  The 34 % case reproduces the design's fictional worked example
(V = ₹10,00,000, B = ₹2,50,000, a broad-equity stress of 0.670 and a D_mod 1.0 AAA debt sleeve); it is not the user's
data and is not loaded from any rule table.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from iip.engine.errors import InvalidInput
from iip.engine.money import D, engine_context
from iip.engine.risk import REMEDY_REDIRECT_NEW_CONTRIBUTIONS, Outcome, RiskClass, Status
from iip.engine.risk.budget import BudgetHolding, LossBudgetResult, loss_budget
from iip.engine.risk.stress import CitedStress, ClassStress, CreditBucket, build_stress_table


def table(**values: tuple[str, str | None]) -> dict[RiskClass, ClassStress]:
    return build_stress_table(
        cited={
            RiskClass(k): CitedStress(
                value=D(v), citation="fictional", status=Status.VERIFIED, recovery_years=None if r is None else D(r)
            )
            for k, (v, r) in values.items()
        },
        recomputed={},
    )


FICTIONAL = table(EQ_BROAD=("0.670", "6.2"), EQ_LARGE=("0.40", "3"), EQ_SMALL=("0.80", "7"), GOLD=("0.30", None))


def eq(hid: str, mv: str, rc: RiskClass = RiskClass.EQ_BROAD) -> BudgetHolding:
    return BudgetHolding(hid, rc, D(mv))


def debt(hid: str, mv: str, dur: str | None = "1.0", credit: CreditBucket | None = CreditBucket.AAA) -> BudgetHolding:
    d = None if dur is None else D(dur)
    return BudgetHolding(hid, RiskClass.DEBT_MTM, D(mv), modified_duration=d, spread_duration=d, credit=credit)


def run(holdings: list[BudgetHolding], budget: str | None = "250000", **kw: object) -> LossBudgetResult:
    kw.setdefault("recovery_tolerance_months", 120)
    return loss_budget(
        "goal-fictional",
        loss_budget_inr=None if budget is None else D(budget),
        holdings=holdings,
        stress_table=FICTIONAL,
        **kw,  # type: ignore[arg-type]
    )


def test_design_worked_example_gives_34_percent() -> None:
    r = run([eq("e", "500000"), debt("d", "500000")])
    assert r.loss_budget_fraction == D("0.25")
    assert r.equity_stress == D("0.670")
    assert r.non_equity_stress == D("0.03")
    assert r.e_cap_raw == D("0.34375")
    assert r.e_cap == D("0.34")
    # card text: 34 % in equity would have lost about ₹2,27,800 plus about ₹19,800 on the debt sleeve
    assert r.loss_at_cap_equity == D("227800")
    assert r.loss_at_cap_non_equity == D("19800")
    # 50 % equity today: 3,35,000 + 15,000 = 3,50,000 > 2,50,000
    assert r.stress_loss == D("350000")
    assert r.breach and r.outcome is Outcome.BREACH
    assert r.excess_stress_loss == D("100000")
    assert r.equity_over_cap_inr == D("160000")
    assert r.remedy == REMEDY_REDIRECT_NEW_CONTRIBUTIONS
    assert r.rule_id == "risk.loss_budget@1"


def test_within_budget_passes() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")])
    assert r.stress_loss == D("201000") + D("21000")
    assert r.outcome is Outcome.PASS
    assert not r.breach
    assert r.remedy is None
    assert r.e_cap == D("0.34")


def test_cap_is_floor_rounded_never_up() -> None:
    # b = 0.2522 → (0.2222)/(0.64) = 0.3471875: HALF_UP would give 0.35, the floor gives 0.34
    r = run([eq("e", "300000"), debt("d", "700000")], budget="252200")
    assert r.e_cap_raw == D("0.3471875")
    assert r.e_cap == D("0.34")


def test_abstain_when_even_zero_equity_breaches() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")], budget="20000")  # b = 0.02 < s_d = 0.03
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "budget_below_non_equity_stress"
    assert r.e_cap is None


def test_budget_equal_to_debt_stress_gives_zero_cap() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")], budget="30000")
    assert r.e_cap == D("0.00")


def test_missing_loss_budget_abstains() -> None:
    r = run([eq("e", "500000"), debt("d", "500000")], budget=None)
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "loss_budget_missing"
    assert r.e_cap is None
    assert not r.breach
    assert r.stress_loss == D("350000")  # the stress history is still shown


def test_equity_sleeves_are_correlated_at_one() -> None:
    r = run([eq("l", "200000", RiskClass.EQ_LARGE), eq("s", "200000", RiskClass.EQ_SMALL), debt("d", "600000")])
    # no diversification credit: 80,000 + 1,60,000 + 18,000
    assert r.stress_loss == D("258000")
    assert r.equity_stress == D("0.60")  # MV-weighted (0.40 + 0.80) / 2
    assert "EQUITY_SLEEVES_CORRELATION_1" in r.flags


def test_hybrid_counts_as_full_equity_at_broad_stress() -> None:
    r = run([BudgetHolding("h", RiskClass.HYBRID, D("400000")), debt("d", "600000")])
    assert r.equity_value == D("400000")
    assert r.lines[0].is_equity
    assert r.lines[0].stress == D("0.670")
    assert r.equity_stress == D("0.670")
    assert "HYBRID_COUNTED_AS_100PCT_EQUITY" in r.flags


def test_gold_and_cash_are_non_equity() -> None:
    gold = BudgetHolding("g", RiskClass.GOLD, D("100000"))
    cash = BudgetHolding("c", RiskClass.CASH_LIKE, D("600000"))
    r = run([eq("e", "300000"), gold, cash])
    assert r.equity_value == D("300000")
    # s_d = (1,00,000 × 0.30 + 6,00,000 × 0) / 7,00,000
    with engine_context():
        expected = D("30000") / D("700000")
    assert r.non_equity_stress == expected


def test_policy_cap_is_applied_when_smaller() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")], policy_cap=D("0.30"))
    assert r.e_cap == D("0.30")
    assert "POLICY_CAP_NOT_SUPPLIED" not in r.flags
    assert "POLICY_CAP_NOT_SUPPLIED" in run([eq("e", "300000"), debt("d", "700000")]).flags


def test_recovery_longer_than_tolerance_is_flagged() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")], recovery_tolerance_months=36)
    assert "RECOVERY_EXCEEDS_TOLERANCE" in r.flags
    assert r.worst_recovery_years == D("6.2")
    ok = run([eq("e", "300000"), debt("d", "700000")], recovery_tolerance_months=75)
    assert "RECOVERY_EXCEEDS_TOLERANCE" not in ok.flags


def test_missing_recovery_tolerance_abstains_for_goal_with_equity() -> None:
    r = run([eq("e", "300000"), debt("d", "700000")], recovery_tolerance_months=None)
    assert r.outcome is Outcome.ABSTAIN
    assert any(a.code == "recovery_tolerance_missing" for a in r.abstentions)
    debt_only = run([debt("d", "700000")], recovery_tolerance_months=None, policy_equity_sleeve=[eq("m", "1")])
    assert not any(a.code == "recovery_tolerance_missing" for a in debt_only.abstentions)


def test_missing_debt_duration_abstains_unless_breach_is_already_certain() -> None:
    r = run([eq("e", "100000"), debt("d", "900000", dur=None)])
    assert r.outcome is Outcome.ABSTAIN
    assert not r.stress_complete
    assert r.abstentions[0].code == "duration_missing"
    certain = run([eq("e", "900000"), debt("d", "100000", dur=None)])  # 6,03,000 > 2,50,000 already
    assert certain.outcome is Outcome.BREACH
    assert "BREACH_ON_PARTIAL_STRESS_LOWER_BOUND" in certain.flags


def test_missing_stress_row_abstains() -> None:
    r = run([eq("m", "300000", RiskClass.EQ_MID), debt("d", "700000")])
    assert r.outcome is Outcome.ABSTAIN
    assert r.abstentions[0].code == "stress_value_missing"
    assert r.e_cap is None


def test_empty_goal_uses_planned_value_and_policy_sleeves() -> None:
    r = run(
        [],
        planned_value=D("1000000"),
        policy_equity_sleeve=[eq("m", "1")],
        policy_non_equity_sleeve=[debt("md", "1")],
    )
    assert r.e_cap == D("0.34")
    assert r.outcome is Outcome.PASS
    assert "EQUITY_STRESS_FROM_POLICY_SLEEVE" in r.flags
    assert run([], planned_value=None).abstentions[0].code == "goal_value_missing"


def test_all_equity_goal_without_non_equity_mix_abstains_on_cap() -> None:
    r = run([eq("e", "100000")], budget="90000")
    assert r.e_cap is None
    assert any(a.code == "non_equity_mix_unknown" for a in r.abstentions)
    assert r.outcome is Outcome.ABSTAIN


def test_policy_sleeves_reject_wrong_classes() -> None:
    with pytest.raises(InvalidInput):
        run([], planned_value=D("1"), policy_equity_sleeve=[debt("x", "1")])
    with pytest.raises(InvalidInput):
        run([], planned_value=D("1"), policy_non_equity_sleeve=[eq("x", "1")])


@pytest.mark.parametrize(
    "kw",
    [
        {"budget": "-1"},
        {"policy_cap": D("1.5")},
        {"recovery_tolerance_months": -1},
        {"planned_value": D("0")},
    ],
)
def test_invalid_inputs_rejected(kw: dict[str, object]) -> None:
    budget = kw.pop("budget", "250000")
    with pytest.raises(InvalidInput):
        run([eq("e", "1")], budget=budget, **kw)  # type: ignore[arg-type]


def test_negative_market_value_rejected() -> None:
    with pytest.raises(InvalidInput):
        run([eq("e", "-1")])


# ---------------------------------------------------------------- "No sale is ever triggered by a drawdown"


@pytest.mark.parametrize("fall", ["0", "0.1", "0.3", "0.5", "0.9"])
def test_a_market_fall_never_creates_a_breach(fall: str) -> None:
    """A drawdown lowers equity MV, so the stress loss falls: it can clear a breach but never create one."""
    before = run([eq("e", "300000"), debt("d", "700000")])
    assert not before.breach
    after = run([eq("e", str(D("300000") * (1 - D(fall)))), debt("d", "700000")])
    assert after.stress_loss <= before.stress_loss
    assert not after.breach
    assert after.remedy is None


def test_breach_remedy_is_never_a_sale() -> None:
    r = run([eq("e", "900000"), debt("d", "100000")])
    assert r.breach
    assert r.remedy == REMEDY_REDIRECT_NEW_CONTRIBUTIONS
    names = {f.name for f in dataclasses.fields(LossBudgetResult)}
    assert not any(word in n for n in names for word in ("sell", "sale", "redeem"))
    assert "SELL" not in (r.remedy or "") and "REDEEM" not in (r.remedy or "")


def test_inputs_have_no_drawdown_or_price_trend_parameter() -> None:
    import inspect

    params = set(inspect.signature(loss_budget).parameters)
    assert not any("drawdown" in p or "trend" in p or "momentum" in p for p in params)


def test_decimal_only() -> None:
    r = run([eq("e", "500000"), debt("d", "500000")])
    for value in (r.stress_loss, r.e_cap, r.equity_stress, r.non_equity_stress, r.loss_at_cap_equity):
        assert isinstance(value, Decimal)


def test_no_risk_module_names_a_sale_verb() -> None:
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parents[2] / "src" / "iip" / "engine" / "risk"
    for path in sorted(pkg.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isupper():
                assert "SELL" not in node.value and "REDEEM" not in node.value, f"{path.name}: {node.value}"
