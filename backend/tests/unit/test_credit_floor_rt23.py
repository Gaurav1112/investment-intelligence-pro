"""ranking_policy@1.2.0 — red-team RT-23: a debt fund's credit quality must be KNOWN to pass a credit floor.

* With a current factsheet, the debt fund is checked by the lowest rating it holds.
* With no (or a stale, or a non-comparable) factsheet, it is excluded with CREDIT_QUALITY_UNKNOWN — but only when the
  user has set a credit floor.
* Equity schemes are unaffected.
"""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from iip.engine import candidates as cb
from iip.engine.deposits import CardRateBucket, card_rate_for_tenure, validate_card_rate_table
from iip.engine.errors import InvalidInput, MissingData
from iip.engine.money import D
from iip.engine.ranking import POLICY_VERSION, Candidate, Objective, OutcomeBand, RankingRequest, Tier, rank

AS_OF = date(2026, 10, 15)
DEBT = "Debt Scheme - Short Duration Fund"
LIQUID = "Debt Scheme - Liquid Fund"
EQUITY = "Equity Scheme - Large Cap Fund"
FRESH = date(2026, 9, 30)


def test_policy_version_bumped() -> None:
    assert POLICY_VERSION == "ranking_policy@1.2.0"


@pytest.mark.parametrize(
    ("category", "expected"),
    [(DEBT, True), (LIQUID, True), ("Debt Scheme - Gilt Fund", True), ("Hybrid Scheme - Arbitrage Fund", True),
     ("Hybrid Scheme - Conservative Hybrid Fund", True), (EQUITY, False), ("Equity Scheme - ELSS", False)],
)  # fmt: skip
def test_which_funds_carry_portfolio_credit_risk(category: str, expected: bool) -> None:
    assert cb.fund_has_credit_exposure(category) is expected


def test_credit_status_from_facts() -> None:
    assert cb.fund_credit_status(EQUITY, None, AS_OF) == (None, False, None)
    rating, unknown, why = cb.fund_credit_status(DEBT, None, AS_OF)
    assert (rating, unknown) == (None, True) and why is not None and "no factsheet" in why
    assert cb.fund_credit_status(DEBT, cb.FundCreditFacts("AA+", FRESH), AS_OF) == ("AA+", False, None)
    assert cb.fund_credit_status(DEBT, cb.FundCreditFacts(None, FRESH), AS_OF)[1] is True


def test_stale_facts_do_not_establish_credit_quality() -> None:
    old = AS_OF - timedelta(days=cb.FACTSHEET_MAX_AGE_DAYS + 1)
    rating, unknown, why = cb.fund_credit_status(DEBT, cb.FundCreditFacts("AAA", old), AS_OF)
    assert (rating, unknown) == (None, True) and why is not None and "45 days" in why
    edge = AS_OF - timedelta(days=cb.FACTSHEET_MAX_AGE_DAYS)
    assert cb.fund_credit_status(DEBT, cb.FundCreditFacts("AAA", edge), AS_OF) == ("AAA", False, None)


def test_future_dated_and_short_term_ratings_are_unknown() -> None:
    assert cb.fund_credit_status(DEBT, cb.FundCreditFacts("AAA", AS_OF + timedelta(days=1)), AS_OF)[1] is True
    rating, unknown, why = cb.fund_credit_status(LIQUID, cb.FundCreditFacts("A1+", FRESH), AS_OF)
    assert (rating, unknown) == (None, True) and why is not None and "long-term" in why


def test_credit_risk_fund_without_facts_stays_unrated_and_with_facts_uses_them() -> None:
    cat = "Debt Scheme - Credit Risk Fund"
    assert cb.fund_credit_status(cat, None, AS_OF) == ("UNRATED", False, None)
    assert cb.fund_credit_status(cat, cb.FundCreditFacts("A", FRESH), AS_OF) == ("A", False, None)


# ----------------------------------------------------------------------------------------- ranking rule


def _cand(iid: str, *, rating: str | None = None, unknown: bool = False) -> Candidate:
    return Candidate(
        instrument_id=iid, name=iid, tier=Tier.T4,
        outcome=OutcomeBand(q05=D("101000"), q50=D("106000"), q95=D("110000")), loss_frequency=D("0"),
        days_to_cash=3, exit_cost=D("0"), horizon_fit=True, credit_rating=rating, data_ok=True,
        independent_windows=40, credit_quality_unknown=unknown,
    )  # fmt: skip


def _req(floor: str | None) -> RankingRequest:
    return RankingRequest(objective=Objective.GROWTH, amount=D("100000"), horizon_days=730, credit_floor=floor,
                          loss_budget=D("0.1"))  # fmt: skip


def test_unknown_credit_quality_excluded_only_when_a_floor_is_set() -> None:
    cands = [_cand("debt-no-facts", unknown=True), _cand("equity"), _cand("debt-aaa", rating="AAA"),
             _cand("debt-a", rating="A")]  # fmt: skip
    no_floor = rank(_req(None), cands)
    assert {r.instrument_id for r in no_floor.ranked} == {"debt-no-facts", "equity", "debt-aaa", "debt-a"}
    floor = rank(_req("AA"), cands)
    assert {r.instrument_id for r in floor.ranked} == {"equity", "debt-aaa"}
    excluded = {e.instrument_id: e.reason_codes for e in floor.excluded}
    assert excluded == {"debt-no-facts": ("CREDIT_QUALITY_UNKNOWN",), "debt-a": ("BELOW_CREDIT_FLOOR",)}
    msg = next(e.messages[0] for e in floor.excluded if e.instrument_id == "debt-no-facts")
    assert "not assumed safe" in msg


def test_unknown_is_never_treated_as_a_rating() -> None:
    """Even the lowest floor excludes an unknown-quality fund: unknown is not 'UNRATED or better'."""
    res = rank(_req("UNRATED"), [replace(_cand("x", unknown=True))])
    assert res.ranked == () and res.excluded[0].reason_codes == ("CREDIT_QUALITY_UNKNOWN",)


# ----------------------------------------------------------------------------------------- card-rate buckets


def test_card_rate_bucket_lookup() -> None:
    t = [CardRateBucket(7, 45, D("0.03")), CardRateBucket(46, 179, D("0.045")), CardRateBucket(180, 364, D("0.06"))]
    assert card_rate_for_tenure(t, 7).rate == D("0.03")
    assert card_rate_for_tenure(t, 46).rate == D("0.045")
    assert card_rate_for_tenure(t, 364).rate == D("0.06")
    with pytest.raises(MissingData):
        card_rate_for_tenure(t, 365)  # never borrowed from a neighbouring bucket
    with pytest.raises(MissingData):
        card_rate_for_tenure(t, 6)


@pytest.mark.parametrize(
    "buckets",
    [[], [CardRateBucket(7, 45, D("0.03")), CardRateBucket(45, 90, D("0.04"))],
     [CardRateBucket(10, 5, D("0.03"))], [CardRateBucket(7, 45, D("-0.01"))]],
)  # fmt: skip
def test_malformed_card_rate_tables_are_refused(buckets: list[CardRateBucket]) -> None:
    with pytest.raises(InvalidInput):
        validate_card_rate_table(buckets)
