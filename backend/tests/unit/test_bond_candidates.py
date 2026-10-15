"""Bond candidate builder (G-sec, SDL, corporate). All instrument values are hand-built FIXTURES, not market data.

Hand computations are written out next to each assertion; the cash-flow schedule itself is cross-checked against
QuantLib in tests/oracle/test_bond_candidate_oracle.py.
"""

from datetime import date
from decimal import Decimal

import pytest

from iip.engine import candidates as cb
from iip.engine import fixed_income as fi
from iip.engine.money import ZERO, D, engine_context
from iip.engine.ranking import Objective, RankingRequest, RankStatus, Tier, rank
from iip.engine.tax import Regime, ResidentialStatus, TaxProfile
from iip.rules.loader import load_tax_rules

RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)
SETTLE = date(2026, 10, 16)  # T+1
P30 = TaxProfile(
    regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, slab_rate=D("0.30"), surcharge_rate=D("0")
)
SLAB = D("0.312")  # 30 % slab + 4 % cess
AAA = cb.BondRating("AAA", "CRISIL", date(2026, 6, 1))


def gsec_terms(maturity: date = date(2027, 4, 15), *, kind: fi.BondKind = fi.BondKind.GSEC) -> cb.BondTerms:
    return cb.BondTerms(kind, D("0.071"), 2, date(2022, 4, 15), maturity, D("100"), 1, True)


def corp_terms(
    *,
    maturity: date = date(2029, 10, 15),
    calls: tuple[fi.CallOption, ...] = (),
    listed: bool = True,
    face: str = "10000",
    issue: date = date(2024, 10, 15),
) -> cb.BondTerms:
    return cb.BondTerms(fi.BondKind.CORPORATE, D("0.09"), 1, issue, maturity, D(face), 15, listed, calls, True)


def build(
    terms: cb.BondTerms,
    *,
    withdrawal: date,
    quote: cb.BondQuote | None = None,
    rating: cb.BondRating = cb.NO_RATING,
    amount: str = "100000",
    spread: Decimal | None = ZERO,
    profile: TaxProfile | None = P30,
) -> cb.BuiltCandidate:
    return cb.bond_candidate(
        instrument_id="bond:x", name="FIXTURE bond", amount=D(amount), as_of=AS_OF, withdrawal=withdrawal,
        terms=terms, quote=quote or cb.BondQuote(date(2026, 10, 14), clean_price=D("99.80")), rating=rating,
        transaction_spread=spread, ruleset=RULES, profile=profile,
    )  # fmt: skip


def _inputs(b: cb.BuiltCandidate) -> dict[str, str]:
    assert b.evidence is not None
    return dict(b.evidence.inputs)


# ------------------------------------------------------------------ held to maturity: hand-computed G-sec


def test_gsec_held_to_maturity_hand_computed() -> None:
    """7.10 % G-sec maturing 15-Apr-2027 (coupons 15-Apr / 15-Oct), clean 99.80, settle 16-Oct-2026.

    accrued (30E/360) = 7.10 × 1/360 = 0.0197222…; dirty = 99.8197222…; one bond = ₹100 face.
    units = floor(1,00,000 / 99.8197222…) = 1001; invested = ₹99,919.5419…; idle = ₹80.4580…
    remaining flows: one coupon of 3.55 and redemption 100 on 15-Apr-2027.
    gross = 80.4580… + 1001 × 103.55 = ₹1,03,734.0080…
    tax = interest 1001 × 3.55 × 31.2 % (1,108.7076) + STCG 1001 × 0.20 × 31.2 % (62.4624) = ₹1,171.17
    """
    b = build(gsec_terms(), withdrawal=date(2027, 4, 15))
    assert not b.ineligible_reasons and b.evidence is not None
    c, ev = b.candidate, b.evidence
    with engine_context():
        accrued = D("7.10") * D(1) / D(360)
        dirty = D("99.80") + accrued
        units = int(D("100000") / dirty)
        idle = D("100000") - Decimal(units) * dirty
        gross = idle + Decimal(units) * D("103.55")
        tax = (Decimal(units) * D("3.55") * SLAB).quantize(D("0.0001")) + (Decimal(units) * D("0.20") * SLAB)
    assert units == 1001
    assert Decimal(_inputs(b)["accrued_per_100"]) == accrued
    assert ev.formula_id == "CAND_BOND_HTM@1" and ev.gross_end_value == gross
    assert ev.tax_mid == pytest.approx(tax, abs=D("0.01"))
    assert ev.tax_mid == D("1171.17")
    with engine_context():
        assert c.outcome.q50 == gross - ev.tax_mid
    assert c.outcome.is_contractual and c.tier is Tier.T1 and c.credit_rating == "SOVEREIGN"
    assert c.loss_frequency == 0 and c.days_to_cash == 1 and c.exit_cost == 0
    assert set(ev.tax_rule_ids) >= {"GSEC-CG-ST/ITA2025", "INT-SLAB-01/ITA2025"}
    assert {"COUPONS_HELD_AT_ZERO_PERCENT", "PURCHASED_ACCRUED_INTEREST_NOT_DEDUCTED", "TAX_RULE_UNVERIFIED"} <= set(
        c.flags
    )
    assert c.min_investment == dirty


def test_gsec_multi_coupon_hold_receives_every_coupon_at_zero_percent() -> None:
    """Maturity 15-Apr-2028, withdrawal 1-May-2028: coupons on 15-Apr-27, 15-Oct-27, 15-Apr-28 (3 × 3.55) + 100."""
    b = build(gsec_terms(date(2028, 4, 15)), withdrawal=date(2028, 5, 1))
    assert b.evidence is not None
    units = int(_inputs(b)["units"])
    with engine_context():
        idle = Decimal(_inputs(b)["cash_left_idle"])
        assert b.evidence.gross_end_value == idle + Decimal(units) * (D("3.55") * 3 + D("100"))
    # Held > 12 months. Rates after 31-Mar-2027 are not legislated, so they are taken as of the coverage end and the
    # result is flagged; the holding period uses the ACTUAL dates (RT-17), so the exit is long-term.
    assert "GSEC-CG-LT/ITA2025" in b.evidence.tax_rule_ids
    assert "GSEC-CG-ST/ITA2025" not in b.evidence.tax_rule_ids
    assert "TAX_RULES_ASSUMED_UNCHANGED_AFTER_2027-03-31" in b.candidate.flags


def test_ytm_quote_prices_at_settlement() -> None:
    """A YTM quote of 6.50 % on the Y-2 bond (7.10 % GS 2036) reproduces the spec's clean 104.2024 / AI 0.0197."""
    terms = cb.BondTerms(fi.BondKind.GSEC, D("0.071"), 2, date(2026, 4, 15), date(2036, 4, 15), D("100"), 1, True)
    b = build(terms, withdrawal=date(2036, 5, 1), quote=cb.BondQuote(date(2026, 10, 14), ytm=D("0.065")))
    i = _inputs(b)
    assert Decimal(i["clean_price_per_100"]).quantize(D("0.0001")) == D("104.2024")
    assert Decimal(i["accrued_per_100"]).quantize(D("0.0001")) == D("0.0197")
    assert i["quote"] == "yield to maturity"


# ------------------------------------------------------------------ corporate with a call


def test_callable_corporate_takes_the_worst_path() -> None:
    """9 % annual AAA bond, face ₹10,000, clean 102.50, callable at par on 15-Oct-2027, matures 15-Oct-2029.

    accrued (SEBI ACT/ACT, 365-day period) = 9 × 1/365; units = floor(5,00,000 / 10,252.4657…) = 48; factor = 4,800.
    maturity path: coupons 9 + 9 (366/366 across 29-Feb-2028) + 9; gross = idle + 4,800 × 127; capital loss → tax 0.
    call path: coupon 9 + call 100; gross = idle + 4,800 × 109. Worst (call) net is the contractual outcome.
    """
    terms = corp_terms(calls=(fi.CallOption(date(2027, 10, 15), D("100")),))
    b = build(terms, withdrawal=date(2029, 11, 1), quote=cb.BondQuote(date(2026, 10, 14), clean_price=D("102.50")),
              rating=AAA, amount="500000")  # fmt: skip
    assert not b.ineligible_reasons and b.evidence is not None
    c = b.candidate
    with engine_context():
        dirty = D("102.50") + D(9) / D(365)
        units = int(D("500000") / (D("10000") * dirty / D(100)))
        factor = Decimal(units) * D(100)
        idle = D("500000") - factor * dirty
        call_gross = idle + factor * D(109)
        call_tax = (factor * D(9) * SLAB).quantize(D("0.01"))
        maturity_gross = idle + factor * D(127)
    assert units == 48
    assert b.evidence.gross_end_value == call_gross
    assert b.evidence.tax_mid == call_tax
    with engine_context():
        assert c.outcome.q50 == call_gross - call_tax
    paths = {k: v for k, v in _inputs(b).items() if k.startswith("path_")}
    assert set(paths) == {"path_maturity", "path_call_2027-10-15"}
    assert paths["path_maturity"].startswith(f"gross {maturity_gross};")
    assert c.tier is Tier.T2 and c.credit_rating == "AAA" and c.outcome.is_contractual
    assert c.loss_frequency is None  # corporate default probability is unknown, never assumed 0
    assert {"CALLABLE_WORST_PATH_USED", "CAPITAL_LOSS_SET_OFF_NOT_MODELLED", "CORPORATE_CREDIT_RISK"} <= set(c.flags)
    assert "yield_to_worst" in _inputs(b)


def test_call_date_off_the_coupon_schedule_is_refused() -> None:
    terms = corp_terms(calls=(fi.CallOption(date(2027, 11, 1), D("100")),))
    b = build(terms, withdrawal=date(2029, 11, 1), rating=AAA, amount="500000")
    assert b.evidence is None and b.ineligible_reasons[0].startswith("UNSUPPORTED_SCHEDULE")


def test_corporate_ytm_quote_uses_the_entered_compounding() -> None:
    q_annual = cb.BondQuote(date(2026, 10, 14), ytm=D("0.08"), ytm_compounding=fi.Compounding.ANNUAL)
    q_semi = cb.BondQuote(date(2026, 10, 14), ytm=D("0.08"), ytm_compounding=fi.Compounding.SEMIANNUAL)
    a = build(corp_terms(), withdrawal=date(2029, 11, 1), quote=q_annual, rating=AAA, amount="500000")
    s = build(corp_terms(), withdrawal=date(2029, 11, 1), quote=q_semi, rating=AAA, amount="500000")
    # 8 % semi-annual is a higher effective yield than 8 % annual → a lower price.
    assert Decimal(_inputs(s)["clean_price_per_100"]) < Decimal(_inputs(a)["clean_price_per_100"])
    assert "YIELD_CONVERTED_TO_COUPON_FREQUENCY:semiannual->annual" in s.warnings


# ------------------------------------------------------------------ early exit


def test_early_exit_band_from_stress_scenarios() -> None:
    """7.10 % GS 2036 at YTM 6.50 %, sold on 15-Apr-2027: exit yields 6.50 % + {+100, 0, −100} bp + 25 bp spread."""
    terms = cb.BondTerms(fi.BondKind.GSEC, D("0.071"), 2, date(2026, 4, 15), date(2036, 4, 15), D("100"), 1, True)
    wd = date(2027, 4, 15)
    b = build(terms, withdrawal=wd, quote=cb.BondQuote(date(2026, 10, 14), ytm=D("0.065")), spread=D("0.001"))
    assert not b.ineligible_reasons and b.evidence is not None
    c, ev = b.candidate, b.evidence
    assert not c.outcome.is_contractual and c.tier is Tier.T3 and c.loss_frequency is None
    assert c.outcome.q05 < c.outcome.q50 < c.outcome.q95
    assert ev.formula_id == "CAND_BOND_EARLY_EXIT@1" and ev.band_gross is not None
    assert {"EARLY_EXIT_STRESS_SCENARIOS", "EXIT_PRICE_MARKET_DEPENDENT", "EXIT_SPREAD_ASSUMPTION_NOT_VERIFIED"} <= set(
        c.flags
    )
    # Mid scenario recomputed independently from the engine's price function (exit yield 6.75 %).
    units = int(_inputs(b)["units"])
    bond = fi.gsec(D("0.071"), date(2036, 4, 15), issue_date=date(2026, 4, 15))
    exit_px = fi.price_from_yield(bond, wd, fi.Yield(D("0.0675"), fi.Compounding.SEMIANNUAL))
    with engine_context():
        idle = Decimal(_inputs(b)["cash_left_idle"])
        mid_gross = idle + Decimal(units) * (D("3.55") + exit_px.clean * (1 - D("0.001")) + exit_px.accrued)
    assert ev.band_gross[1] == pytest.approx(mid_gross, abs=D("1e-20"))
    assert ev.costs[0][0] == "transaction_cost_at_purchase" and ev.costs[0][1] > 0
    assert c.exit_cost == D("0.001")


def test_early_exit_is_excluded_for_preservation_but_not_for_growth() -> None:
    terms = cb.BondTerms(fi.BondKind.GSEC, D("0.071"), 2, date(2026, 4, 15), date(2036, 4, 15), D("100"), 1, True)
    b = build(terms, withdrawal=date(2027, 10, 20), quote=cb.BondQuote(date(2026, 10, 14), ytm=D("0.065")))
    pres = rank(RankingRequest(Objective.CAPITAL_PRESERVATION, D("100000"), 370), [b.candidate])
    assert pres.status is RankStatus.NO_SUITABLE_CANDIDATE
    assert "MISSING_LOSS_EVIDENCE" in pres.excluded[0].reason_codes
    growth = rank(RankingRequest(Objective.GROWTH, D("100000"), 370, loss_budget=D("0.2")), [b.candidate])
    assert growth.status is RankStatus.RANKED


def test_unlisted_corporate_cannot_exit_early() -> None:
    b = build(corp_terms(listed=False), withdrawal=date(2027, 10, 20), rating=AAA, amount="500000")
    assert b.evidence is None and any("no exchange exit" in r for r in b.ineligible_reasons)


def test_unlisted_corporate_held_to_maturity_uses_the_unlisted_bond_rule() -> None:
    q = cb.BondQuote(date(2026, 10, 14), clean_price=D("98.00"))
    b = build(corp_terms(listed=False), withdrawal=date(2029, 11, 1), rating=AAA, amount="500000", quote=q)
    assert b.evidence is not None and "BOND-UL/ITA2025" in b.evidence.tax_rule_ids
    assert b.candidate.days_to_cash == (date(2029, 10, 15) - AS_OF).days and b.candidate.exit_cost == 1


# ------------------------------------------------------------------ data gates


@pytest.mark.parametrize(
    ("quote_date", "code"),
    [(date(2026, 10, 7), "STALE_DATA"), (date(2026, 10, 16), "LOOK_AHEAD")],
)
def test_stale_or_future_quote_is_excluded(quote_date: date, code: str) -> None:
    b = build(gsec_terms(), withdrawal=date(2027, 4, 15), quote=cb.BondQuote(quote_date, clean_price=D("99.80")))
    assert b.evidence is None and b.ineligible_reasons[0].startswith(code)
    res = rank(RankingRequest(Objective.CAPITAL_PRESERVATION, D("100000"), 182), [b.candidate])
    assert "INSUFFICIENT_OR_STALE_DATA" in res.excluded[0].reason_codes


def test_quote_exactly_seven_days_old_is_still_usable() -> None:
    b = build(gsec_terms(), withdrawal=date(2027, 4, 15), quote=cb.BondQuote(date(2026, 10, 8), clean_price=D("99.80")))
    assert b.evidence is not None


@pytest.mark.parametrize(
    ("rating", "code"),
    [
        (cb.BondRating("AAA", "CRISIL", date(2025, 10, 14)), "STALE_RATING"),
        (cb.NO_RATING, "MISSING_RATING"),
        (cb.BondRating("AAA", None, date(2026, 6, 1)), "MISSING_RATING"),
        (cb.BondRating("SOVEREIGN", "CRISIL", date(2026, 6, 1)), "INVALID_RATING"),
        (cb.BondRating("AAA", "CRISIL", date(2026, 10, 20)), "LOOK_AHEAD"),
    ],
)
def test_corporate_rating_gates(rating: cb.BondRating, code: str) -> None:
    b = build(corp_terms(), withdrawal=date(2029, 11, 1), rating=rating, amount="500000")
    assert b.evidence is None and b.ineligible_reasons[0].startswith(code)
    assert not b.candidate.data_ok


def test_rating_exactly_twelve_months_old_is_still_usable() -> None:
    b = build(corp_terms(), withdrawal=date(2029, 11, 1), rating=cb.BondRating("AAA", "ICRA", date(2025, 10, 15)),
              amount="500000")  # fmt: skip
    assert b.evidence is not None


def test_below_minimum_ticket() -> None:
    b = build(corp_terms(face="100000"), withdrawal=date(2029, 11, 1), rating=AAA, amount="50000")
    assert b.evidence is None and b.ineligible_reasons[0].startswith("BELOW_MINIMUM_TICKET")


def test_unknown_transaction_spread_is_flagged_not_silently_zero() -> None:
    b = build(gsec_terms(), withdrawal=date(2027, 4, 15), spread=None)
    assert b.evidence is not None
    assert "TRANSACTION_COST_UNKNOWN" in b.candidate.flags and b.evidence.costs == ()
    assert b.candidate.exit_cost == 1  # unknown exit cost fails any maximum the user sets
    known = build(gsec_terms(), withdrawal=date(2027, 4, 15), spread=D("0.0025"))
    assert known.evidence is not None and known.candidate.outcome.q50 < b.candidate.outcome.q50


def test_odd_first_coupon_already_paid_is_priced_without_it() -> None:
    terms = corp_terms(issue=date(2024, 11, 2))  # off the schedule generated back from 15-Oct-2029
    b = build(terms, withdrawal=date(2029, 11, 1), rating=AAA, amount="500000")
    assert b.evidence is not None and "ODD_FIRST_COUPON_ALREADY_PAID" in b.candidate.flags


def test_odd_first_coupon_not_yet_paid_is_refused() -> None:
    terms = corp_terms(issue=date(2026, 9, 1), maturity=date(2029, 12, 15))  # first coupon 15-Dec-2026 still ahead
    b = build(terms, withdrawal=date(2029, 11, 1), rating=AAA, amount="500000")
    assert b.evidence is None and b.ineligible_reasons[0].startswith("UNSUPPORTED_SCHEDULE")


def test_gsec_with_wrong_frequency_is_refused() -> None:
    terms = cb.BondTerms(fi.BondKind.GSEC, D("0.071"), 1, date(2022, 4, 15), date(2027, 4, 15), D("100"), 1, True)
    b = build(terms, withdrawal=date(2027, 4, 15))
    assert b.evidence is None and b.ineligible_reasons[0].startswith("INVALID_INPUT")


def test_quote_needs_exactly_one_of_price_or_yield() -> None:
    with pytest.raises(Exception, match="exactly one"):
        cb.BondQuote(date(2026, 10, 14))
    with pytest.raises(Exception, match="exactly one"):
        cb.BondQuote(date(2026, 10, 14), clean_price=D("99"), ytm=D("0.07"))


# ------------------------------------------------------------------ tiers and the credit floor


@pytest.mark.parametrize(
    ("kind", "rating", "tier", "credit"),
    [
        (fi.BondKind.GSEC, cb.NO_RATING, Tier.T1, "SOVEREIGN"),
        (fi.BondKind.SDL, cb.NO_RATING, Tier.T2, "AAA"),
        (fi.BondKind.CORPORATE, AAA, Tier.T2, "AAA"),
        (fi.BondKind.CORPORATE, cb.BondRating("AA+", "ICRA", date(2026, 6, 1)), Tier.T3, "AA+"),
    ],
)
def test_tier_assignment_held_to_maturity(kind: fi.BondKind, rating: cb.BondRating, tier: Tier, credit: str) -> None:
    if kind is fi.BondKind.CORPORATE:
        b = build(corp_terms(), withdrawal=date(2029, 11, 1), rating=rating, amount="500000")
    else:
        b = build(gsec_terms(kind=kind), withdrawal=date(2027, 4, 15))
    assert b.evidence is not None
    assert b.candidate.tier is tier and b.candidate.credit_rating == credit
    if credit == "AA+":
        assert "BELOW_AAA_CREDIT_RISK" in b.candidate.flags
    if kind is fi.BondKind.SDL:
        assert "SDL_STATE_GOVERNMENT_CREDIT_NOT_SOVEREIGN" in b.candidate.flags


def test_below_aaa_held_to_maturity_fails_preservation_as_uninsured_credit() -> None:
    aa = build(corp_terms(), withdrawal=date(2029, 11, 1), rating=cb.BondRating("AA", "CARE", date(2026, 6, 1)),
               amount="500000")  # fmt: skip
    res = rank(RankingRequest(Objective.CAPITAL_PRESERVATION, D("500000"), 1113), [aa.candidate])
    assert "UNINSURED_CREDIT_EXPOSURE" in res.excluded[0].reason_codes


def test_credit_floor_interaction() -> None:
    wd = date(2029, 11, 1)
    aaa = cb.bond_candidate(
        instrument_id="corp:aaa", name="AAA", amount=D("500000"), as_of=AS_OF, withdrawal=wd, terms=corp_terms(),
        quote=cb.BondQuote(date(2026, 10, 14), clean_price=D("98")), rating=AAA, transaction_spread=D("0"),
        ruleset=RULES, profile=P30,
    )  # fmt: skip
    aa = cb.bond_candidate(
        instrument_id="corp:aa", name="AA", amount=D("500000"), as_of=AS_OF, withdrawal=wd, terms=corp_terms(),
        quote=cb.BondQuote(date(2026, 10, 14), clean_price=D("98")),
        rating=cb.BondRating("AA", "CARE", date(2026, 6, 1)), transaction_spread=D("0"), ruleset=RULES, profile=P30,
    )  # fmt: skip
    sdl = cb.bond_candidate(
        instrument_id="sdl:x", name="SDL", amount=D("500000"), as_of=AS_OF, withdrawal=wd,
        terms=gsec_terms(date(2029, 10, 15), kind=fi.BondKind.SDL), quote=cb.BondQuote(date(2026, 10, 14),
        clean_price=D("100")), rating=cb.NO_RATING, transaction_spread=D("0"), ruleset=RULES, profile=P30,
    )  # fmt: skip
    cands = [aaa.candidate, aa.candidate, sdl.candidate]
    growth = RankingRequest(Objective.GROWTH, D("500000"), (wd - AS_OF).days, loss_budget=D("0.1"), credit_floor="AA+")
    res = rank(growth, cands)
    assert [r.instrument_id for r in res.ranked] == sorted([r.instrument_id for r in res.ranked])  # deterministic
    assert {r.instrument_id for r in res.ranked} == {"corp:aaa", "sdl:x"}
    assert res.excluded[0].instrument_id == "corp:aa" and "BELOW_CREDIT_FLOOR" in res.excluded[0].reason_codes
    sovereign_only = rank(RankingRequest(Objective.INCOME, D("500000"), 1113, credit_floor="SOVEREIGN"), cands)
    assert {e.instrument_id for e in sovereign_only.excluded} == {"corp:aaa", "corp:aa", "sdl:x"}
