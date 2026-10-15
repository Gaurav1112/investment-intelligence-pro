"""Ranking policy tests (ADR-0005, risk-methodology.md §9). Numbers are ILLUSTRATIVE fixtures, not market data."""

from dataclasses import replace
from decimal import Decimal

import pytest

from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.ranking import (
    POLICY_VERSION,
    Candidate,
    Objective,
    OutcomeBand,
    RankingRequest,
    RankStatus,
    Tier,
    rank,
)

AMOUNT = D("100000")


def tbill() -> Candidate:
    # Spec worked example: 30 days to maturity at 6.50 % → ₹1,00,534 contractual (illustrative).
    return Candidate(
        instrument_id="tbill:91d:example",
        name="91-day T-bill (secondary, 30d residual)",
        tier=Tier.T1,
        outcome=OutcomeBand.contractual(D("100534")),
        loss_frequency=D("0"),
        days_to_cash=1,
        exit_cost=D("0"),
        horizon_fit=True,
        credit_rating="SOVEREIGN",
        data_ok=True,
    )


def equity() -> Candidate:
    # Spec worked example: q05 −7 %, q50 +1 %, q95 +8 %, P(loss) ≈ 40 % (illustrative).
    return Candidate(
        instrument_id="mf:equity:example",
        name="Equity index fund (illustrative)",
        tier=Tier.T4,
        outcome=OutcomeBand(q05=D("93000"), q50=D("101000"), q95=D("108000")),
        loss_frequency=D("0.40"),
        days_to_cash=3,
        exit_cost=D("0"),
        horizon_fit=True,
        credit_rating=None,
        data_ok=True,
    )


def liquid() -> Candidate:
    return Candidate(
        instrument_id="mf:liquid:example",
        name="Liquid fund (illustrative)",
        tier=Tier.T3,
        outcome=OutcomeBand(q05=D("100480"), q50=D("100520"), q95=D("100560")),
        loss_frequency=D("0.000"),
        days_to_cash=1,
        exit_cost=D("0"),
        horizon_fit=True,
        credit_rating=None,
        data_ok=True,
    )


def req(objective: Objective = Objective.CAPITAL_PRESERVATION, **kw: object) -> RankingRequest:
    base = {"objective": objective, "amount": AMOUNT, "horizon_days": 30, "max_days_to_cash": 7}
    base.update(kw)
    return RankingRequest(**base)  # type: ignore[arg-type]


def test_spec_worked_example_equity_excluded_for_preservation() -> None:
    result = rank(req(), [equity(), tbill()])
    assert result.status is RankStatus.RANKED
    assert [r.instrument_id for r in result.ranked] == ["tbill:91d:example"]
    excluded = {e.instrument_id: e.reason_codes for e in result.excluded}
    assert "LOSS_FREQUENCY_ABOVE_LIMIT" in excluded["mf:equity:example"]
    assert "LOWER_BAND_BELOW_FLOOR" in excluded["mf:equity:example"]


def test_higher_median_never_beats_better_tier_for_preservation() -> None:
    result = rank(req(), [liquid(), tbill()])
    # Liquid fund median 1,00,520 < T-bill 1,00,534 anyway; make the liquid median higher to prove the rule.
    richer_liquid = replace(liquid(), outcome=OutcomeBand(q05=D("100480"), q50=D("100900"), q95=D("101000")))
    result = rank(req(), [richer_liquid, tbill()])
    assert [r.instrument_id for r in result.ranked] == ["tbill:91d:example", "mf:liquid:example"]


def test_no_suitable_candidate_is_never_forced() -> None:
    result = rank(req(), [equity()])
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE
    assert result.ranked == ()
    assert result.message == "No suitable candidate found under the current constraints."


def test_unknown_loss_frequency_is_not_assumed_safe() -> None:
    unknown = replace(liquid(), loss_frequency=None)
    result = rank(req(), [unknown])
    assert result.status is RankStatus.NO_SUITABLE_CANDIDATE
    assert "MISSING_LOSS_EVIDENCE" in result.excluded[0].reason_codes


def test_contractual_candidate_needs_no_loss_frequency() -> None:
    result = rank(req(), [replace(tbill(), loss_frequency=None)])
    assert result.status is RankStatus.RANKED


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"horizon_fit": False}, "HORIZON_MISMATCH"),
        ({"days_to_cash": 10}, "LIQUIDITY_TOO_SLOW"),
        ({"data_ok": False}, "INSUFFICIENT_OR_STALE_DATA"),
        ({"exit_cost": D("0.02")}, "EXIT_COST_TOO_HIGH"),
    ],
)
def test_each_hard_constraint_has_a_reason_code(change: dict[str, object], code: str) -> None:
    result = rank(req(max_exit_cost=D("0.01")), [replace(tbill(), **change)])  # type: ignore[arg-type]
    assert code in result.excluded[0].reason_codes


def test_credit_floor() -> None:
    aa = replace(tbill(), instrument_id="bond:aa", tier=Tier.T2, credit_rating="AA")
    aaa = replace(tbill(), instrument_id="bond:aaa", tier=Tier.T2, credit_rating="AAA")
    unrated = replace(tbill(), instrument_id="bond:unrated", tier=Tier.T2, credit_rating="UNRATED")
    result = rank(req(credit_floor="AA+"), [aa, aaa, unrated])
    assert [r.instrument_id for r in result.ranked] == ["bond:aaa"]
    codes = {e.instrument_id: e.reason_codes for e in result.excluded}
    assert "BELOW_CREDIT_FLOOR" in codes["bond:aa"] and "BELOW_CREDIT_FLOOR" in codes["bond:unrated"]


def test_user_exclusions() -> None:
    result = rank(req(excluded_ids=frozenset({"tbill:91d:example"})), [tbill()])
    assert "EXCLUDED_BY_USER" in result.excluded[0].reason_codes


def test_growth_requires_loss_budget_and_uses_certainty_equivalent() -> None:
    with pytest.raises(InvalidInput):
        rank(req(Objective.AGGRESSIVE_GROWTH, horizon_days=365), [equity()])
    eq = replace(equity(), outcome=OutcomeBand(q05=D("85000"), q50=D("112000"), q95=D("135000")))
    debt = replace(
        liquid(),
        tier=Tier.T4,
        instrument_id="mf:debt",
        outcome=OutcomeBand(q05=D("104000"), q50=D("107000"), q95=D("109000")),
        loss_frequency=D("0.02"),
    )
    # Loss budget 20 % → both eligible. CE(λ=0.5): equity 112000 − 0.5·27000 = 98500; debt 107000 − 1500 = 105500.
    result = rank(req(Objective.GROWTH, horizon_days=365, loss_budget=D("0.20")), [eq, debt])
    assert [r.instrument_id for r in result.ranked] == ["mf:debt", "mf:equity:example"]
    assert result.ranked[0].sort_key_display["certainty_equivalent"] == "105500.00"
    # λ = 0 (user only cares about the median) → equity first.
    result0 = rank(req(Objective.GROWTH, horizon_days=365, loss_budget=D("0.20"), risk_lambda=D("0")), [eq, debt])
    assert result0.ranked[0].instrument_id == "mf:equity:example"
    # Loss budget 10 % → equity q05 −15 % fails.
    result10 = rank(req(Objective.GROWTH, horizon_days=365, loss_budget=D("0.10")), [eq, debt])
    assert "LOWER_BAND_BELOW_LOSS_BUDGET" in result10.excluded[0].reason_codes


def test_liquidity_objective_orders_by_days_to_cash() -> None:
    slow = replace(tbill(), instrument_id="slow", days_to_cash=3)
    result = rank(req(Objective.LIQUIDITY), [slow, liquid()])
    assert [r.instrument_id for r in result.ranked] == ["mf:liquid:example", "slow"]


def test_income_objective_prefers_narrow_band() -> None:
    wide = replace(
        liquid(), instrument_id="wide", outcome=OutcomeBand(q05=D("100300"), q50=D("100700"), q95=D("101100"))
    )
    narrow = replace(liquid(), instrument_id="narrow")
    result = rank(req(Objective.INCOME), [wide, narrow])
    assert [r.instrument_id for r in result.ranked] == ["narrow", "wide"]


def test_deterministic_total_order_and_input_order_independence() -> None:
    a = replace(tbill(), instrument_id="b-id")
    b = replace(tbill(), instrument_id="a-id")
    r1 = rank(req(), [a, b])
    r2 = rank(req(), [b, a])
    assert [x.instrument_id for x in r1.ranked] == ["a-id", "b-id"]
    assert r1.output_hash == r2.output_hash and r1.input_hash == r2.input_hash
    assert r1.policy_version == POLICY_VERSION


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(InvalidInput):
        rank(req(), [tbill(), tbill()])


def test_band_must_be_ordered() -> None:
    with pytest.raises(InvalidInput):
        OutcomeBand(q05=D("3"), q50=D("2"), q95=D("1"))


def test_every_ranked_item_explains_itself() -> None:
    result = rank(req(), [tbill(), liquid()])
    for item in result.ranked:
        assert item.reasons and all(isinstance(r, str) for r in item.reasons)
    assert result.policy["epsilon_loss_frequency"] == "0.01"
    assert Decimal(result.policy["preservation_floor"]) == 0
