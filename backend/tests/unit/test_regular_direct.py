"""Regular → Direct switch (PLAN.md A15; design-judgement.md §2.1 item 3: NAV-measured gap from
design-user-first.md §4.4, argmin wait date from design-evidence-first.md P2, option (d) first).

Break-even fixtures follow research-evidence-mf.md §4.2 (fictional): holding ₹4,00,000, cost gap 0.80 %/yr → ₹3,200 a
year; ₹50,000 gain.  All NAVs, lots and scheme ids are SYNTHETIC.  The research rounds STT and cess away; this engine
includes both, so the expected values below state them explicitly.
"""

from datetime import date
from decimal import Decimal

import pytest

from iip.engine.actions.regular_direct import (
    REG_TO_DIRECT_FORMULA_ID,
    NavGap,
    NavPoint,
    PlanPair,
    measure_nav_gap,
    regular_to_direct,
)
from iip.engine.actions.tax_actions import Abstention, ActionStatus, FolioHolding, TaxContext, TaxLot
from iip.engine.costs import LoadTier
from iip.engine.dates import BusinessCalendar
from iip.engine.money import D, quantize
from iip.engine.tax import Regime, ResidentialStatus, TaxRuleSet
from iip.rules.loader import load_tax_rules

AS_OF = date(2026, 10, 15)  # Thursday; AS_OF − 365 d = 2025-10-15 (Wednesday)
T0 = date(2025, 10, 15)


@pytest.fixture(scope="module")
def rules() -> TaxRuleSet:
    return load_tax_rules()


def ctx(elsewhere: str | None = "0", **kw: object) -> TaxContext:
    base: dict[str, object] = {
        "regime": Regime.NEW,
        "residential_status": ResidentialStatus.RESIDENT,
        "slab_rate": D("0.30"),
        "surcharge_rate": D("0"),
        "realised_ltcg_elsewhere_fy": None if elsewhere is None else D(elsewhere),
    }
    base.update(kw)
    return TaxContext(**base)  # type: ignore[arg-type]


def pair(
    *,
    reg: tuple[tuple[date, str], ...] = ((T0, "80"), (AS_OF, "100")),
    dirn: tuple[tuple[date, str], ...] = ((T0, "80"), (AS_OF, "100.8")),  # 1.26 / 1.25 = 1.008 → gap 0.80 %
    unique: bool = True,
) -> PlanPair:
    return PlanPair(
        regular_scheme_id="SYN-REG",
        direct_scheme_id="SYN-DIR",
        sibling_match_unique=unique,
        regular_navs=tuple(NavPoint(d, D(v)) for d, v in reg),
        direct_navs=tuple(NavPoint(d, D(v)) for d, v in dirn),
    )


def folio(
    acq: date = date(2025, 1, 10),
    *,
    schedule: tuple[LoadTier, ...] | None = (),
    elss: bool = False,
    lots: tuple[TaxLot, ...] | None = None,
) -> FolioHolding:
    return FolioHolding(
        folio_id="F-R",
        scheme_id="SYN-REG",
        nav=D("100"),
        nav_date=AS_OF,
        lots=lots or (TaxLot("R1", acq, D("4000"), D("350000")),),  # value 4,00,000; gain 50,000
        domestic_equity_share=D("0.95"),
        debt_share=D("0"),
        is_elss=elss,
        exit_load_schedule=schedule,
    )


def option_ids(r: object) -> list[str]:
    return [o.option_id for o in r.options]  # type: ignore[attr-defined]


# --- NAV-measured gap ---------------------------------------------------------------------------------------------


def test_gap_is_measured_from_both_plans_navs() -> None:
    g = measure_nav_gap(pair(), AS_OF)
    assert isinstance(g, NavGap)
    assert (g.t, g.t0) == (AS_OF, T0)
    assert quantize(g.annual_cost_gap, D("0.000001")) == D("0.008000")
    assert g.nav_dir_t == D("100.8") and g.nav_reg_t0 == D("80")


def test_gap_tolerates_a_weekend_within_three_business_days() -> None:
    as_of = date(2026, 10, 19)  # Monday; target t0 = 2025-10-19 (Sunday) → Friday 2025-10-17 is 0 business days away
    p = pair(reg=((date(2025, 10, 17), "80"), (as_of, "100")), dirn=((date(2025, 10, 17), "80"), (as_of, "100.8")))
    g = measure_nav_gap(p, as_of, calendar=BusinessCalendar("weekends", frozenset()))
    assert isinstance(g, NavGap)
    assert g.t0 == date(2025, 10, 17)


def test_gap_abstains_without_a_nav_near_either_date() -> None:
    p = pair(reg=((date(2025, 10, 1), "80"), (AS_OF, "100")), dirn=((date(2025, 10, 1), "80"), (AS_OF, "100.8")))
    a = measure_nav_gap(p, AS_OF)
    assert isinstance(a, Abstention) and a.code == "NAV_MISSING_NEAR_DATE"


def test_gap_abstains_on_short_history() -> None:
    p = pair(reg=((date(2026, 1, 2), "80"), (AS_OF, "100")), dirn=((date(2026, 1, 2), "80"), (AS_OF, "100.8")))
    a = measure_nav_gap(p, AS_OF)
    assert isinstance(a, Abstention) and a.code == "INSUFFICIENT_HISTORY"


def test_gap_needs_the_same_dates_in_both_plans() -> None:
    early = date(2025, 10, 1)  # common to both plans, but 10 business days before t0
    p = pair(
        reg=((early, "79"), (T0, "80"), (AS_OF, "100")),
        dirn=((early, "79"), (date(2025, 10, 16), "80"), (AS_OF, "100.8")),  # direct has no NAV on t0
    )
    a = measure_nav_gap(p, AS_OF)
    assert isinstance(a, Abstention) and a.code == "NAV_MISSING_NEAR_DATE"


# --- abstentions --------------------------------------------------------------------------------------------------


def test_abstains_when_sibling_not_unique(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(unique=False), ctx(), rules, as_of=AS_OF)
    assert [a.code for a in r.abstentions] == ["SIBLING_NOT_UNIQUE"]
    assert r.options == ()
    assert r.status is ActionStatus.REQUIRES_CONFIGURATION


def test_abstains_when_gap_not_positive(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(dirn=((T0, "80"), (AS_OF, "100"))), ctx(), rules, as_of=AS_OF)
    assert [a.code for a in r.abstentions] == ["NO_COST_GAP"]
    assert r.options == ()


def test_unknown_exit_load_abstains_for_lots_under_365_days(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(date(2026, 1, 10), schedule=None), pair(), ctx(), rules, as_of=AS_OF)
    assert [a.code for a in r.abstentions] == ["EXIT_LOAD_UNKNOWN"]
    assert option_ids(r) == ["d"]  # redirecting the SIP needs no exit-load facts and costs nothing
    assert r.status is ActionStatus.REQUIRES_CONFIGURATION


def test_unknown_exit_load_on_old_lots_is_assumed_zero_and_flagged(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(schedule=None), pair(), ctx(), rules, as_of=AS_OF)
    assert not r.abstentions
    assert "EXIT_LOAD_ASSUMED_ZERO_AFTER_365_DAYS" in r.flags


def test_unknown_surcharge_abstains(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(date(2026, 1, 10)), pair(), ctx(surcharge_rate=None), rules, as_of=AS_OF)
    assert [a.code for a in r.abstentions] == ["SURCHARGE_BAND_UNKNOWN"]
    assert option_ids(r) == ["d"]


# --- break-even fixtures (research-evidence-mf.md §4.2) -----------------------------------------------------------


def test_long_term_lots_inside_the_exemption_break_even_within_a_week(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(), ctx(), rules, as_of=AS_OF)
    assert r.formula_id == REG_TO_DIRECT_FORMULA_ID
    assert r.holding_value_inr == D("400000.00")
    assert r.annual_saving_inr == D("3200.00")
    assert option_ids(r) == ["d", "b", "a"]  # nothing turns cheaper within 13 months → no (c)
    a = r.options[-1]
    assert a.tax_inr == D("0.00") and a.exit_load_inr == D("0.00")
    assert a.stt_inr == D("4.00")  # 0.001 % of 4,00,000
    assert a.stamp_duty_inr == D("20.00")  # 3,99,996 × 0.005 % / 1.00005 = 19.998 → 20.00
    assert a.switch_cost_inr == D("24.00")
    assert a.breakeven_months is not None and a.breakeven_months * 30 < 7  # "within about a week"
    assert r.recommended_timing == "a"
    assert "WAIT_NOT_CHEAPER" in r.flags


def test_short_term_gain_waits_for_the_lot_to_turn_long_term(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(date(2026, 1, 10)), pair(), ctx(), rules, as_of=AS_OF)
    assert option_ids(r) == ["d", "c", "a"]  # no long-term lot → no (b)
    d, c, a = r.options
    assert d.verb == "REDIRECT_SIP" and d.switch_cost_inr == D("0.00") and d.tax_inr == D("0.00")
    # (a) now: STCG 50,000 × 20 % = 10,000 + 4 % cess = 10,400; STT 4; stamp 20
    assert a.tax_inr == D("10400.00")
    assert a.switch_cost_inr == D("10424.00")
    assert a.breakeven_months == D("39.09")  # 12 × 10,424 / 3,200 (research: ≈ 3.1 years before cess and STT)
    # (c) wait until 2027-01-11 (88 days): tax 0 inside the exemption; forgone saving 3,200 × 88/365 = 771.51
    assert c.verb == "WAIT_UNTIL" and c.switch_date == date(2027, 1, 11)
    assert c.tax_inr == D("0.00")
    assert c.forgone_saving_inr == D("771.51")
    assert c.total_cost_inr == D("795.51")
    assert r.recommended_timing == "c"


def test_option_b_switches_only_long_term_lots_inside_the_pool(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(), ctx("95000"), rules, as_of=AS_OF)  # pool 30,000; gain 12.5 per unit
    b = next(o for o in r.options if o.option_id == "b")
    assert b.units == D("2400")
    assert b.tax_inr == D("0.00")


def test_unknown_elsewhere_gains_assume_the_exemption_used(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(), ctx(None), rules, as_of=AS_OF)
    assert "EXEMPTION_ASSUMED_USED" in r.flags
    assert "b" not in option_ids(r)
    a = r.options[-1]
    assert a.tax_inr == D("6500.00")  # 50,000 × 12.5 % × 1.04, conservative


def test_wait_candidates_beyond_rule_coverage_are_dropped(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(date(2026, 6, 1)), pair(), ctx(), rules, as_of=AS_OF)  # long-term from 2027-06-02
    assert "c" not in option_ids(r)
    assert "WAIT_CANDIDATE_BEYOND_RULE_COVERAGE" in r.flags


def test_exit_load_window_exit_is_a_wait_candidate(rules: TaxRuleSet) -> None:
    lots = (
        TaxLot("R1", date(2025, 1, 10), D("2000"), D("150000")),
        TaxLot("R2", date(2025, 12, 1), D("2000"), D("190000")),
    )
    schedule = (LoadTier(window_days=365, rate=D("0.01")),)
    r = regular_to_direct(folio(lots=lots, schedule=schedule), pair(), ctx(), rules, as_of=AS_OF)
    a = r.options[-1]
    assert a.exit_load_inr == D("2000.00")  # R2 (318 days) pays 1 % of 2,00,000
    c = next(o for o in r.options if o.option_id == "c")
    assert c.switch_date == date(2026, 12, 2)  # R2 turns long-term and leaves the load window
    assert c.exit_load_inr == D("0.00")


def test_options_always_lead_with_redirect_sip(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(), ctx(), rules, as_of=AS_OF, sip_amount_inr=D("5000"))
    assert r.options[0].option_id == "d"
    assert r.options[0].amount_inr == D("5000")


def test_result_has_no_expected_return_field(rules: TaxRuleSet) -> None:
    r = regular_to_direct(folio(), pair(), ctx(), rules, as_of=AS_OF)
    assert not hasattr(r, "expected_return")
    assert r.impact_basis == "ANNUAL_COST_SAVED"
    assert isinstance(r.annual_saving_inr, Decimal)
