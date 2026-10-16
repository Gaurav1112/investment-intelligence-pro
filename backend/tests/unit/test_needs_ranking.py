"""A16: card ranking and "Needs from you" (design-judgement.md grafts 7 and 8; design-user-first.md §5.3, §7.2).

SYNTHETIC values only.
"""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from iip.engine.actions import contracts as c
from iip.engine.actions.needs import collect_needs
from iip.engine.actions.ranking import TodayState, rank_cards, rank_key
from iip.engine.errors import InvalidInput

AS_OF = date(2031, 3, 14)

_TEMPLATE = {
    c.CardKind.EMERGENCY_SHORTFALL: "emergency_shortfall",
    c.CardKind.LOSS_BUDGET_BREACH: "loss_budget_breach",
    c.CardKind.LIMIT_BREACH: "limit_breach",
    c.CardKind.REBALANCE_DUE: "rebalance_due",
    c.CardKind.NEXT_RUPEE: "next_rupee",
    c.CardKind.LTCG_HARVEST: "ltcg_harvest",
    c.CardKind.LT_DATE: "lt_date",
    c.CardKind.REVIEW_FLAG: "review_flag",
    c.CardKind.ABSTAIN: "abstain_missing_input",
    c.CardKind.DATA_ATTENTION: "data_attention",
    c.CardKind.NO_ACTION_NEEDED: "no_action_needed",
    c.CardKind.SIGNAL_TILT: "signal_entry",
}


def card(
    kind: c.CardKind,
    *,
    goal: str | None = "goal-a",
    inr: str | None = None,
    basis: c.ImpactBasis = c.ImpactBasis.AMOUNT_TO_MOVE,
    deadline: date | None = None,
    inst: str = "inst-synthetic-1",
    layer: c.Layer | None = None,
    abstentions: tuple[c.Abstention, ...] = (),
    snapshot: str = "snap-1",
) -> c.ActionCard:
    numbers: tuple[c.CardNumber, ...] = ()
    impact = None
    steps: tuple[c.Step, ...] = ()
    if inr is not None:
        numbers = (
            c.CardNumber(
                slot="impact", value=Decimal(inr), unit=c.NumberUnit.INR, as_of=AS_OF, formula_id="test.formula@1"
            ),
        )
        impact = c.Impact(amount_inr=Decimal(inr), basis=basis, slot="impact")
    if kind not in (c.CardKind.ABSTAIN, c.CardKind.NO_ACTION_NEEDED, c.CardKind.DATA_ATTENTION):
        steps = (c.Step(verb=c.Verb.REVIEW, instrument_id=inst, formula_id="test.formula@1"),)
    kw: dict[str, Any] = {}
    return c.ActionCard(
        kind=kind,
        layer=layer if layer is not None else c.KIND_LAYER[kind],
        goal_id=None if kind is c.CardKind.NO_ACTION_NEEDED else goal,
        as_of=AS_OF,
        deadline=deadline,
        impact=impact,
        steps=steps,
        why=c.Why(rule_id="test.rule", rule_version=1, parameters=()),
        numbers=numbers,
        template_id=_TEMPLATE[kind],
        status=c.CardStatus.VERIFIED,
        abstentions=abstentions,
        engine_version="engine@test",
        rules_version="rules@test",
        input_manifest_hash="c" * 64,
        snapshot_id=snapshot,
        **kw,
    )


def abstention(
    missing: str, bound: str | None = None, basis: c.ImpactBasis = c.ImpactBasis.TAX_DEFERRED
) -> c.Abstention:
    if bound is None:
        return c.Abstention(code="MISSING_" + missing.upper(), missing_input=missing, how_to_fix=f"Enter {missing}")
    return c.Abstention(
        code="MISSING_" + missing.upper(),
        missing_input=missing,
        how_to_fix=f"Enter {missing}",
        unlock_upper_bound_inr=Decimal(bound),
        unlock_basis=basis,
        unlock_formula_id="needs.synthetic_unlock@1",
    )


# --- ranking key -------------------------------------------------------------------------------------------------


def test_layer_dominates_then_deadline_then_inr_then_card_id() -> None:
    l4 = card(c.CardKind.LIMIT_BREACH, inr="900000", inst="i-l4")
    l5_late = card(c.CardKind.REBALANCE_DUE, inr="1", deadline=date(2031, 6, 1), inst="i-late")
    l5_early = card(c.CardKind.REBALANCE_DUE, inr="1", deadline=date(2031, 4, 1), inst="i-early")
    l5_nodeadline_big = card(c.CardKind.REBALANCE_DUE, inr="500000", inst="i-big")
    l5_nodeadline_small = card(c.CardKind.REBALANCE_DUE, inr="5", inst="i-small")
    l5_no_impact = card(c.CardKind.REBALANCE_DUE, inst="i-none")
    l6 = card(c.CardKind.LTCG_HARVEST, inr="999999", basis=c.ImpactBasis.TAX_DEFERRED, inst="i-l6")
    expected = [l4, l5_early, l5_late, l5_nodeadline_big, l5_nodeadline_small, l5_no_impact, l6]
    shuffled = expected[:]
    random.Random(7).shuffle(shuffled)
    result = rank_cards(shuffled)
    assert [x.card_id for x in result.ordered] == [x.card_id for x in expected]
    assert result.state is TodayState.ACTIONS


def test_ties_break_on_card_id_so_the_order_is_total() -> None:
    a = card(c.CardKind.REBALANCE_DUE, inr="10", inst="i-x")
    b = card(c.CardKind.REBALANCE_DUE, inr="10", inst="i-y")
    out = rank_cards([b, a]).ordered
    assert [x.card_id for x in out] == sorted([a.card_id, b.card_id])
    assert rank_key(a) != rank_key(b)


def test_ranking_is_deterministic_under_any_input_order() -> None:
    cards = [card(c.CardKind.REBALANCE_DUE, inr=str(i % 3), inst=f"i-{i}") for i in range(12)]
    first = [x.card_id for x in rank_cards(cards).ordered]
    for seed in range(5):
        shuffled = cards[:]
        random.Random(seed).shuffle(shuffled)
        assert [x.card_id for x in rank_cards(shuffled).ordered] == first


def test_duplicate_card_ids_are_rejected() -> None:
    a = card(c.CardKind.REBALANCE_DUE, inr="10")
    with pytest.raises(InvalidInput, match="duplicate"):
        rank_cards([a, a])


def test_top_n_and_more_count() -> None:
    cards = [card(c.CardKind.REBALANCE_DUE, inr=str(i), inst=f"i-{i}") for i in range(8)]
    out = rank_cards(cards, top_n=5)
    assert len(out.shown) == 5
    assert out.more_count == 3
    assert out.shown == out.ordered[:5]


def test_rank_key_never_adds_inr_across_bases() -> None:
    # The key carries one card's own ₹, so mixing bases in a list compares amounts but never sums them.
    a = card(c.CardKind.LTCG_HARVEST, inr="100", basis=c.ImpactBasis.TAX_DEFERRED, inst="i-a")
    b = card(c.CardKind.LT_DATE, inr="200", basis=c.ImpactBasis.TAX_AVOIDED, inst="i-b")
    out = rank_cards([a, b])
    assert [x.card_id for x in out.ordered] == [b.card_id, a.card_id]
    assert not hasattr(out, "total_inr")


# --- suppression by breaches (design-risk-first.md §4) ----------------------------------------------------------


def test_goal_breach_suppresses_lower_layers_for_that_goal_only() -> None:
    breach = card(c.CardKind.LOSS_BUDGET_BREACH, goal="goal-a", inr="346000", basis=c.ImpactBasis.AMOUNT_AT_RISK)
    same_goal = card(c.CardKind.REBALANCE_DUE, goal="goal-a", inr="10", inst="i-2")
    other_goal = card(c.CardKind.REBALANCE_DUE, goal="goal-b", inr="10", inst="i-3")
    household_l4 = card(c.CardKind.LIMIT_BREACH, goal=None, inr="5", inst="i-4")
    out = rank_cards([same_goal, other_goal, breach, household_l4])
    ids = [x.card_id for x in out.ordered]
    assert same_goal.card_id not in ids
    assert other_goal.card_id in ids
    assert household_l4.card_id in ids  # a goal breach never suppresses household-level cards
    assert [(s.card.card_id, s.suppressed_by) for s in out.suppressed] == [(same_goal.card_id, breach.card_id)]


def test_household_breach_suppresses_every_lower_layer_card() -> None:
    l1 = card(c.CardKind.EMERGENCY_SHORTFALL, goal=None, inr="120000", basis=c.ImpactBasis.SHORTFALL)
    rest = [
        card(c.CardKind.REBALANCE_DUE, goal="goal-a", inr="10", inst="i-2"),
        card(c.CardKind.NEXT_RUPEE, goal="goal-b", inr="10", inst="i-3"),
        card(c.CardKind.LTCG_HARVEST, goal=None, inr="10", basis=c.ImpactBasis.TAX_DEFERRED, inst="i-4"),
    ]
    out = rank_cards([*rest, l1])
    assert [x.card_id for x in out.ordered] == [l1.card_id]
    assert len(out.suppressed) == 3


def test_l0_data_attention_suppresses_that_goal() -> None:
    l0 = card(c.CardKind.DATA_ATTENTION, goal="goal-a", abstentions=(abstention("nav_feed"),))
    l5 = card(c.CardKind.REBALANCE_DUE, goal="goal-a", inr="10", inst="i-2")
    out = rank_cards([l5, l0])
    assert [x.card_id for x in out.ordered] == [l0.card_id]
    assert out.state is TodayState.ABSTAINED_ONLY


def test_non_breach_cards_never_suppress() -> None:
    l4 = card(c.CardKind.LIMIT_BREACH, goal="goal-a", inr="10", inst="i-1")
    l5 = card(c.CardKind.REBALANCE_DUE, goal="goal-a", inr="10", inst="i-2")
    assert len(rank_cards([l4, l5]).ordered) == 2


# --- "Nothing needs doing today" is a valid result ---------------------------------------------------------------


def test_empty_input_is_nothing_needed() -> None:
    out = rank_cards([])
    assert out.state is TodayState.NOTHING_NEEDED
    assert out.ordered == ()
    assert out.more_count == 0


def test_only_a_no_action_card_is_nothing_needed() -> None:
    out = rank_cards([card(c.CardKind.NO_ACTION_NEEDED)])
    assert out.state is TodayState.NOTHING_NEEDED


def test_no_action_card_alongside_actions_is_a_contradiction() -> None:
    with pytest.raises(InvalidInput, match="NO_ACTION_NEEDED"):
        rank_cards([card(c.CardKind.NO_ACTION_NEEDED), card(c.CardKind.REBALANCE_DUE, inr="1")])


def test_abstentions_alone_never_claim_nothing_needed() -> None:
    a = card(c.CardKind.ABSTAIN, layer=c.Layer.L3, abstentions=(abstention("loss_limit_inr"),))
    assert rank_cards([a]).state is TodayState.ABSTAINED_ONLY
    # An action card that abstains on part of its work still counts as an action.
    partial = card(c.CardKind.NEXT_RUPEE, inr="10", abstentions=(abstention("scheme_choice"),))
    assert rank_cards([partial]).state is TodayState.ACTIONS


# --- Needs from you ----------------------------------------------------------------------------------------------


def test_needs_are_ranked_by_the_inr_upper_bound_each_input_unlocks() -> None:
    cards = [
        card(c.CardKind.ABSTAIN, layer=c.Layer.L6, inst="i-1", abstentions=(abstention("realised_ltcg_fy", "15625"),)),
        card(
            c.CardKind.ABSTAIN,
            layer=c.Layer.L6,
            goal="goal-b",
            abstentions=(abstention("sid_upload", "250000", c.ImpactBasis.AMOUNT_AT_RISK),),
        ),
        card(c.CardKind.ABSTAIN, layer=c.Layer.L3, goal="goal-c", abstentions=(abstention("loss_limit_inr"),)),
    ]
    needs = collect_needs(cards)
    assert [n.missing_input for n in needs] == ["sid_upload", "realised_ltcg_fy", "loss_limit_inr"]
    assert needs[0].rank_amount_inr == Decimal(250000)
    assert needs[2].rank_amount_inr is None


def test_need_bounds_are_never_summed_across_cards_or_bases() -> None:
    cards = [
        card(
            c.CardKind.ABSTAIN,
            layer=c.Layer.L6,
            goal="goal-a",
            abstentions=(abstention("tax_slab", "15625", c.ImpactBasis.TAX_DEFERRED),),
        ),
        card(
            c.CardKind.ABSTAIN,
            layer=c.Layer.L6,
            goal="goal-b",
            abstentions=(abstention("tax_slab", "9000", c.ImpactBasis.TAX_AVOIDED),),
        ),
        card(
            c.CardKind.ABSTAIN,
            layer=c.Layer.L6,
            goal="goal-c",
            abstentions=(abstention("tax_slab", "15000", c.ImpactBasis.TAX_DEFERRED),),
        ),
    ]
    (need,) = collect_needs(cards)
    assert need.rank_amount_inr == Decimal(15625)  # the largest single bound, never 15,625 + 9,000 + 15,000
    assert need.rank_basis is c.ImpactBasis.TAX_DEFERRED
    assert len(need.unlocks) == 3
    assert all(u.formula_id == "needs.synthetic_unlock@1" for u in need.unlocks)


def test_needs_tie_break_on_input_name_and_dedupe_codes() -> None:
    cards = [
        card(c.CardKind.ABSTAIN, layer=c.Layer.L3, goal="g1", abstentions=(abstention("zeta"),)),
        card(c.CardKind.ABSTAIN, layer=c.Layer.L3, goal="g2", abstentions=(abstention("alpha"),)),
        card(c.CardKind.ABSTAIN, layer=c.Layer.L3, goal="g3", abstentions=(abstention("alpha"),)),
    ]
    needs = collect_needs(cards)
    assert [n.missing_input for n in needs] == ["alpha", "zeta"]
    assert needs[0].codes == ("MISSING_ALPHA",)
    assert len(needs[0].card_ids) == 2


def test_no_abstentions_means_no_needs() -> None:
    assert collect_needs([card(c.CardKind.REBALANCE_DUE, inr="1")]) == ()
    assert collect_needs([]) == ()
