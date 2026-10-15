"""Invariants for the ranking policy (Phase 10: ranking/eligibility stable for identical versioned inputs)."""

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from iip.engine.money import D
from iip.engine.ranking import Candidate, Objective, OutcomeBand, RankingRequest, Tier, rank

AMOUNT = D("100000")


@st.composite
def candidates(draw: st.DrawFn, idx: int) -> Candidate:
    q05 = Decimal(draw(st.integers(85_000, 110_000)))
    spread1 = Decimal(draw(st.integers(0, 5_000)))
    spread2 = Decimal(draw(st.integers(0, 5_000)))
    contractual = draw(st.booleans())
    band = OutcomeBand.contractual(q05) if contractual else OutcomeBand(q05, q05 + spread1, q05 + spread1 + spread2)
    return Candidate(
        instrument_id=f"c{idx:03d}",
        name=f"candidate {idx}",
        tier=draw(st.sampled_from(list(Tier))),
        outcome=band,
        loss_frequency=draw(st.one_of(st.none(), st.decimals("0", "0.5", places=3))),
        days_to_cash=draw(st.integers(0, 10)),
        exit_cost=draw(st.decimals("0", "0.02", places=4)),
        horizon_fit=draw(st.booleans()),
        credit_rating=draw(st.sampled_from([None, "SOVEREIGN", "AAA", "AA", "A", "UNRATED"])),
        data_ok=draw(st.booleans()),
    )


@st.composite
def universes(draw: st.DrawFn) -> list[Candidate]:
    n = draw(st.integers(0, 8))
    return [draw(candidates(i)) for i in range(n)]


objectives = st.sampled_from(list(Objective))


def _request(obj: Objective) -> RankingRequest:
    return RankingRequest(
        objective=obj,
        amount=AMOUNT,
        horizon_days=90,
        max_days_to_cash=7,
        loss_budget=D("0.10") if obj in (Objective.GROWTH, Objective.AGGRESSIVE_GROWTH) else None,
    )


@settings(max_examples=150, deadline=None)
@given(universes(), objectives, st.randoms(use_true_random=False))
def test_permutation_invariance_and_determinism(universe: list[Candidate], obj: Objective, rnd) -> None:  # type: ignore[no-untyped-def]
    shuffled = list(universe)
    rnd.shuffle(shuffled)
    a, b = rank(_request(obj), universe), rank(_request(obj), shuffled)
    assert a.output_hash == b.output_hash
    assert [r.instrument_id for r in a.ranked] == [r.instrument_id for r in b.ranked]


@settings(max_examples=150, deadline=None)
@given(universes(), objectives)
def test_partition_every_candidate_is_ranked_or_excluded_once(universe: list[Candidate], obj: Objective) -> None:
    result = rank(_request(obj), universe)
    ids = [r.instrument_id for r in result.ranked] + [e.instrument_id for e in result.excluded]
    assert sorted(ids) == sorted(c.instrument_id for c in universe)
    assert all(e.reason_codes for e in result.excluded)
    assert [r.rank for r in result.ranked] == list(range(1, len(result.ranked) + 1))


@settings(max_examples=150, deadline=None)
@given(universes(), objectives)
def test_adding_an_ineligible_candidate_does_not_change_the_ranking(universe: list[Candidate], obj: Objective) -> None:
    base = rank(_request(obj), universe)
    junk = Candidate(
        "zzz-junk",
        "junk",
        Tier.T4,
        OutcomeBand(D("1"), D("2"), D("3")),
        D("0.9"),
        99,
        D("0.5"),
        horizon_fit=False,
        credit_rating=None,
        data_ok=False,
    )
    with_junk = rank(_request(obj), [*universe, junk])
    assert [r.instrument_id for r in base.ranked] == [r.instrument_id for r in with_junk.ranked]


@settings(max_examples=150, deadline=None)
@given(universes())
def test_preservation_never_ranks_a_lower_tier_above_a_higher_one(universe: list[Candidate]) -> None:
    result = rank(_request(Objective.CAPITAL_PRESERVATION), universe)
    tiers = [int(r.tier) for r in result.ranked]
    assert tiers == sorted(tiers)


@settings(max_examples=150, deadline=None)
@given(universes())
def test_preservation_eligible_set_never_contains_a_projected_loss(universe: list[Candidate]) -> None:
    result = rank(_request(Objective.CAPITAL_PRESERVATION), universe)
    assert all(r.outcome.q05 >= AMOUNT for r in result.ranked)


@settings(max_examples=100, deadline=None)
@given(universes())
def test_improving_q05_never_hurts_rank_under_preservation(universe: list[Candidate]) -> None:
    result = rank(_request(Objective.CAPITAL_PRESERVATION), universe)
    if not result.ranked:
        return
    target = result.ranked[-1].instrument_id
    improved = []
    for c in universe:
        if c.instrument_id == target:
            o = c.outcome
            bump = D("1000")
            band = OutcomeBand(o.q05 + bump, max(o.q50, o.q05 + bump), max(o.q95, o.q05 + bump), o.is_contractual)
            improved.append(replace(c, outcome=band))
        else:
            improved.append(c)
    new = rank(_request(Objective.CAPITAL_PRESERVATION), improved)
    old_pos = [r.instrument_id for r in result.ranked].index(target)
    new_pos = [r.instrument_id for r in new.ranked].index(target)
    assert new_pos <= old_pos
