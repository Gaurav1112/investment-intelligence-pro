"""Candidate builder tests. All instrument values are FIXTURES (hand-built), not market data."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iip.engine import candidates as cb
from iip.engine.money import D, engine_context
from iip.engine.ranking import Objective, RankingRequest, RankStatus, Tier, rank
from iip.engine.tax import Regime, ResidentialStatus, TaxProfile
from iip.rules.loader import load_tax_rules

RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)
WITHDRAW = date(2027, 4, 15)  # 182 days
AMOUNT = D("100000")
FULL_SPAN = (date(2026, 10, 14) - date(2012, 1, 2)).days  # series ends the day before AS_OF
PROFILE_30 = TaxProfile(
    regime=Regime.NEW, residential_status=ResidentialStatus.RESIDENT, slab_rate=D("0.30"), surcharge_rate=D("0")
)


def _series(
    start: date, days: int, daily_growth: str, shock_every: int | None = None, shock: str = "0"
) -> tuple[list[date], list[Decimal]]:
    ds, ns = [], []
    nav = D("10")
    d = start
    i = 0
    with engine_context():
        while d <= start + timedelta(days=days):
            if d.weekday() < 5:
                ds.append(d)
                ns.append(nav)
                nav = nav * (D("1") + D(daily_growth))
                if shock_every and i % shock_every == shock_every - 1:
                    nav = nav * (D("1") + D(shock))
                i += 1
            d += timedelta(days=1)
    return ds, ns


# ------------------------------------------------------------------ T-bill
def test_tbill_contractual_after_tax() -> None:
    b = cb.tbill_candidate(
        instrument_id="tb",
        name="182-day T-bill (FIXTURE)",
        amount=AMOUNT,
        quoted_yield=D("0.065"),
        settlement=date(2026, 10, 16),
        maturity=date(2027, 4, 15),
        withdrawal=WITHDRAW,
        ruleset=RULES,
        profile=PROFILE_30,
    )
    assert b.evidence is not None and not b.ineligible_reasons
    c = b.candidate
    assert c.tier is Tier.T1 and c.outcome.is_contractual and c.loss_frequency == 0
    # Hand check: days = 181, price = 100/(1+0.065·181/365) = 96.877…; RT-22: whole ₹10,000-face lots only, so
    # 10 lots (face ₹1,00,000) cost ₹96,877.…; the ₹3,122.… remainder is held at 0 %; gain = face − cost.
    days = (date(2027, 4, 15) - date(2026, 10, 16)).days
    assert days == 181
    with engine_context():
        price = D(100) / (D(1) + D("0.065") * D(days) / D(365))
        face = D("100000")
        cost = D(10) * (D(10000) * price / D(100))  # 10 lots × cost of one lot
        gain = face - cost
        assert b.evidence.gross_end_value == face + (AMOUNT - cost)
    assert b.evidence.tax_mid > gain * D("0.30")  # 30 % slab + 4 % cess
    assert b.evidence.tax_mid == pytest.approx(gain * D("0.312"), abs=D("0.01"))
    with engine_context():
        assert c.outcome.q50 == face + (AMOUNT - cost) - b.evidence.tax_mid
    assert b.evidence.tax_unverified  # TBILL-01 head of income is NV → flagged
    # Maturity 15-Apr-2027 is beyond the legislated rule coverage (31-Mar-2027): assumption is explicit, not silent.
    assert "TAX_RULES_ASSUMED_UNCHANGED_AFTER_2027-03-31" in c.flags


def test_tbill_maturing_after_withdrawal_is_horizon_mismatch() -> None:
    b = cb.tbill_candidate(
        instrument_id="tb364",
        name="364-day T-bill",
        amount=AMOUNT,
        quoted_yield=D("0.065"),
        settlement=date(2026, 10, 16),
        maturity=date(2027, 10, 14),
        withdrawal=WITHDRAW,
        ruleset=RULES,
        profile=PROFILE_30,
    )
    assert b.ineligible_reasons and b.ineligible_reasons[0].startswith("HORIZON_MISMATCH")
    assert not b.candidate.data_ok and not b.candidate.horizon_fit


def test_illustrative_tax_basis_when_no_profile() -> None:
    b = cb.tbill_candidate(
        instrument_id="tb",
        name="tb",
        amount=AMOUNT,
        quoted_yield=D("0.065"),
        settlement=date(2026, 10, 16),
        maturity=date(2027, 4, 15),
        withdrawal=WITHDRAW,
        ruleset=RULES,
        profile=None,
    )
    assert b.evidence is not None and b.evidence.tax_basis is cb.TaxBasis.ILLUSTRATIVE


# ------------------------------------------------------------------ FD
def _fd(**kw: object) -> cb.BuiltCandidate:
    args = dict(
        instrument_id="fd",
        name="FD (FIXTURE)",
        amount=AMOUNT,
        rate=D("0.07"),
        start=AS_OF,
        tenure_days=180,
        withdrawal=WITHDRAW,
        dicgc_eligible=True,
        premature_penalty=D("0.01"),
        other_deposits_same_bank=D("0"),
        ruleset=RULES,
        profile=PROFILE_30,
    )
    args.update(kw)
    return cb.fd_candidate(**args)  # type: ignore[arg-type]


def test_fd_insured_is_t2_contractual() -> None:
    b = _fd()
    assert b.candidate.tier is Tier.T2 and b.candidate.loss_frequency == 0
    assert b.candidate.outcome.q50 < b.evidence.gross_end_value  # type: ignore[union-attr]


def test_fd_over_dicgc_limit_drops_to_t3_with_flag() -> None:
    b = _fd(other_deposits_same_bank=D("450000"))
    assert b.candidate.tier is Tier.T3 and "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" in b.candidate.flags
    assert b.candidate.loss_frequency is None


def test_fd_unrecorded_existing_deposits_are_not_assumed_zero() -> None:
    """ECC silent-failure F1: with nothing recorded at this bank, DICGC cover cannot be established, so the deposit
    is never shown as zero-loss insured credit."""
    b = _fd(other_deposits_same_bank=None)
    c = b.candidate
    assert "EXISTING_DEPOSITS_NOT_RECORDED" in c.flags and "EXCEEDS_DICGC_LIMIT_AT_THIS_BANK" not in c.flags
    assert c.tier is Tier.T3 and c.loss_frequency is None and c.credit_rating == "UNRATED"
    assert dict(b.evidence.inputs)["dicgc_existing_deposits"] == "not recorded"  # type: ignore[union-attr]
    assert "dicgc_exposure_at_bank" not in dict(b.evidence.inputs)  # type: ignore[union-attr]


def test_nbfc_deposit_never_insured() -> None:
    b = _fd(dicgc_eligible=False)
    assert b.candidate.tier is Tier.T3 and "NOT_DICGC_INSURED" in b.candidate.flags


def test_fd_unknown_penalty_is_not_assumed_zero() -> None:
    b = _fd(premature_penalty=None)
    assert "PREMATURE_PENALTY_UNKNOWN" in b.candidate.flags
    assert b.candidate.exit_cost == 1 and b.candidate.days_to_cash == 180


# ------------------------------------------------------------------ mutual funds
def test_window_returns_have_no_look_ahead_and_respect_staleness() -> None:
    ds = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 20), date(2026, 1, 21)]
    ns = [D("10"), D("11"), D("12"), D("13")]
    # H = 19 days: from 01-Jan → last NAV on/before 20-Jan = 12; from 02-Jan → 21-Jan = 13; later starts exceed the end.
    r = cb.horizon_window_returns(ds, ns, 19)
    with engine_context():
        assert r == [D("12") / D("10") - 1, D("13") / D("11") - 1]
    # A 10-day gap beyond the 7-day staleness bound is skipped, never forward-filled.
    assert cb.horizon_window_returns([date(2026, 1, 1), date(2026, 1, 15)], [D("1"), D("2")], 5) == []


def _liquid(**kw: object) -> cb.BuiltCandidate:
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.00025")
    args = dict(
        instrument_id="mf:liquid",
        name="Liquid fund (FIXTURE)",
        category="Debt Scheme - Liquid Fund",
        amount=AMOUNT,
        as_of=AS_OF,
        withdrawal=WITHDRAW,
        nav_dates=ds,
        navs=ns,
        exit_load=None,
        ruleset=RULES,
        profile=PROFILE_30,
        settlement_days=1,
    )
    args.update(kw)
    return cb.mf_candidate(**args)  # type: ignore[arg-type]


def test_liquid_fund_band_loss_frequency_and_regulatory_exit_load() -> None:
    b = _liquid()
    assert not b.ineligible_reasons, b.ineligible_reasons
    c = b.candidate
    assert c.tier is Tier.T3 and c.loss_frequency == 0
    assert c.outcome.q05 <= c.outcome.q50 <= c.outcome.q95
    assert b.evidence is not None and b.evidence.n_independent and b.evidence.n_independent >= 20
    assert dict(b.evidence.costs)["exit_load_rate"] == 0  # 182 days > 6-day SEBI window


def test_stale_nav_makes_candidate_ineligible() -> None:
    ds, ns = _series(date(2012, 1, 2), 365 * 14, "0.00025")  # ends ~280 days before as_of
    b = _liquid(nav_dates=ds, navs=ns)
    assert any(r.startswith("STALE_DATA") for r in b.ineligible_reasons)


def test_unknown_exit_load_blocks_non_liquid_funds() -> None:
    b = _liquid(category="Debt Scheme - Short Duration Fund")
    assert any(r.startswith("EXIT_LOAD_UNKNOWN") for r in b.ineligible_reasons)
    ok = _liquid(
        category="Debt Scheme - Short Duration Fund",
        exit_load=cb.ExitLoadSpec(days=30, rate=D("0.0025"), citation="SID FIXTURE"),
    )
    assert not ok.ineligible_reasons and ok.candidate.tier is Tier.T4


def test_elss_lock_in_and_index_fund_tax_class() -> None:
    elss = _liquid(category="Equity Scheme - ELSS", exit_load=cb.ExitLoadSpec(0, D("0"), "SID FIXTURE"))
    assert any(r.startswith("HORIZON_MISMATCH") for r in elss.ineligible_reasons)
    idx = _liquid(category="Other Scheme - Index Funds", exit_load=cb.ExitLoadSpec(0, D("0"), "SID FIXTURE"))
    assert any(r.startswith("TAX_CLASS_UNKNOWN") for r in idx.ineligible_reasons)


def test_amfi_childrens_fund_label_gets_lock_in() -> None:
    # Real NAVAll label (probe 2026-10-15): "Children’s Fund - Childrens' Fund" — no "Solution Oriented" prefix.
    b = _liquid(category="Children’s Fund - Childrens' Fund", exit_load=cb.ExitLoadSpec(0, D("0"), "SID FIXTURE"))
    assert any(r.startswith("HORIZON_MISMATCH") for r in b.ineligible_reasons)


def test_short_history_is_refused_not_extrapolated() -> None:
    ds, ns = _series(date(2024, 1, 1), 1015, "0.00025")
    b = _liquid(nav_dates=ds, navs=ns)
    assert any(r.startswith("INSUFFICIENT_HISTORY") for r in b.ineligible_reasons)


def test_volatile_fund_has_loss_frequency_and_lower_band_below_amount() -> None:
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.0006", shock_every=180, shock="-0.12")
    b = _liquid(
        category="Equity Scheme - Large Cap Fund",
        nav_dates=ds,
        navs=ns,
        exit_load=cb.ExitLoadSpec(365, D("0.01"), "SID FIXTURE"),
    )
    c = b.candidate
    assert not b.ineligible_reasons and c.tier is Tier.T4
    assert c.loss_frequency is not None and c.loss_frequency > D("0.01")
    assert dict(b.evidence.costs)["exit_load_rate"] == D("0.01")  # type: ignore[union-attr]


def test_end_to_end_preservation_ranking_excludes_volatile_fund() -> None:
    tb = cb.tbill_candidate(
        instrument_id="tb",
        name="tb",
        amount=AMOUNT,
        quoted_yield=D("0.065"),
        settlement=date(2026, 10, 16),
        maturity=date(2027, 4, 15),
        withdrawal=WITHDRAW,
        ruleset=RULES,
        profile=PROFILE_30,
    )
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.0006", shock_every=180, shock="-0.12")
    eq = _liquid(
        instrument_id="mf:eq",
        category="Equity Scheme - Large Cap Fund",
        nav_dates=ds,
        navs=ns,
        exit_load=cb.ExitLoadSpec(365, D("0.01"), "SID FIXTURE"),
    )
    result = rank(
        RankingRequest(objective=Objective.CAPITAL_PRESERVATION, amount=AMOUNT, horizon_days=182, max_days_to_cash=7),
        [tb.candidate, eq.candidate, _liquid().candidate],
    )
    assert result.status is RankStatus.RANKED
    assert result.ranked[0].instrument_id == "tb"
    assert "mf:eq" in {e.instrument_id for e in result.excluded}


# Real AMFI category labels observed in the live NAVAll file on 2026-10-15.
@pytest.mark.parametrize(
    ("category", "name", "expect_lock"),
    [
        ("Index Funds - Equity Funds", "360 ONE ELSS Tax Saver Nifty 50 Index Fund", True),
        ("Equity Schemes - ELSS- Tax Saver Fund", "Any Fund", True),
        ("ELSS", "Any Fund", True),
        ("Index Funds - Equity Funds", "Some Nifty 50 Index Fund", False),
        ("Solution Oriented Schemes ** - Retirement Fund", "Any Retirement Fund", True),
    ],
)
def test_live_category_lock_ins(category: str, name: str, expect_lock: bool) -> None:
    assert (cb.mf_lock_in_days(category, name) > 0) is expect_lock


def test_fixed_term_plans_are_never_treated_as_redeemable() -> None:
    b = _liquid(
        category="Income/Debt Oriented Schemes - Fixed Term Plan", exit_load=cb.ExitLoadSpec(0, D("0"), "SID FIXTURE")
    )
    assert any(r.startswith("CLOSE_ENDED_OR_INTERVAL") for r in b.ineligible_reasons)


@pytest.mark.parametrize(
    ("category", "tier"),
    [
        ("Income/Debt Oriented Schemes - Liquid Fund", Tier.T3),
        ("Debt Scheme - Overnight Fund", Tier.T3),
        ("Income/Debt Oriented Schemes - Money Market Fund", Tier.T3),
        ("Income/Debt Oriented Schemes - Ultra Short to Short Term Fund", Tier.T4),
        ("Equity Scheme - Large Cap Fund", Tier.T4),
    ],
)
def test_live_category_tiers(category: str, tier: Tier) -> None:
    assert cb.mf_tier_from_category(category) is tier


@pytest.mark.parametrize(
    "category",
    [
        "Income",
        "Growth",
        "Gilt",
        "Index Funds - Debt Funds",
        "Life Cycle Funds - Life Cycle Fund with Maturity of 5 Years",
        "Exchange Traded Funds (ETFs) - Gold ETF",
        "Hybrid Schemes - Balanced Advantage Fund/ Dynamic Asset Allocation",
    ],
)
def test_ambiguous_live_categories_are_unknown_for_tax(category: str) -> None:
    assert cb.mf_tax_class_from_category(category) is cb.MfTaxClass.UNKNOWN


def test_equity_ltcg_exemption_assumption_is_flagged() -> None:
    """RT-18: when the ₹1.25 lakh exemption reduces tax, the result says it assumed the exemption was unused.

    Uses a table with longer coverage (law in force on the transfer date). Since RT-17 was fixed the shipped table
    triggers the flag too (`test_rt17_equity_mf_candidate_past_coverage_gets_ltcg_and_exemption_flag`).
    """
    import dataclasses

    extended = dataclasses.replace(RULES, coverage_to=date(2028, 12, 31))
    ds, ns = _series(date(2012, 1, 2), FULL_SPAN, "0.0006")
    b = _liquid(category="Equity Scheme - Large Cap Fund", nav_dates=ds, navs=ns, amount=D("2000000"),
                withdrawal=date(2027, 11, 19), exit_load=cb.ExitLoadSpec(365, D("0.01"), "SID FIXTURE"),
                ruleset=extended)  # fmt: skip
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert "LTCG_EXEMPTION_ASSUMED_UNUSED" in b.candidate.flags
