"""L6 tax actions (PLAN.md A15; design-risk-first.md §5.8 with the design-judgement.md §2.2 item 10 graft;
design-user-first.md §4.3).

All values are SYNTHETIC and hand-computed: fictional scheme ids, fictional NAVs, fictional lots.  Tax rates come from
the shipped ``rules/tax/india.yaml`` through the loader (never literals in the engine); the hand calculations below
restate them only to state the expected value.
"""

from datetime import date
from decimal import Decimal

import pytest

from iip.engine.actions.tax_actions import (
    DEFAULT_WAIT_HORIZON_DAYS,
    HARVEST_FORMULA_ID,
    TAX_LOSS_HARVESTING_ENABLED,
    ActionStatus,
    FolioHolding,
    HarvestWindow,
    TaxContext,
    TaxLot,
    fifo_consume,
    lt_wait_modifier,
    ltcg_harvest,
    pool_left_for,
)
from iip.engine.costs import LoadTier
from iip.engine.errors import InvalidInput
from iip.engine.money import D
from iip.engine.tax import Regime, ResidentialStatus, TaxRuleSet
from iip.rules.loader import load_tax_rules

AS_OF = date(2027, 2, 20)  # inside the default 15-Feb..31-Mar window, FY 2026-27 (ITA 2025 rows)


@pytest.fixture(scope="module")
def rules() -> TaxRuleSet:
    return load_tax_rules()


def ctx(elsewhere: str | None = "0", *, in_app: str = "0", done: str = "0", **kw: object) -> TaxContext:
    base: dict[str, object] = {
        "regime": Regime.NEW,
        "residential_status": ResidentialStatus.RESIDENT,
        "slab_rate": D("0.30"),
        "surcharge_rate": D("0"),
        "realised_ltcg_in_app_fy": D(in_app),
        "realised_ltcg_elsewhere_fy": None if elsewhere is None else D(elsewhere),
        "harvest_already_done_fy": D(done),
    }
    base.update(kw)
    return TaxContext(**base)  # type: ignore[arg-type]


def lot(lot_id: str, acq: date, units: str, cost: str) -> TaxLot:
    return TaxLot(lot_id=lot_id, acquisition_date=acq, units=D(units), cost_inr=D(cost))


def equity_folio(
    folio_id: str = "F-A",
    lots: tuple[TaxLot, ...] | None = None,
    *,
    nav: str = "100",
    elss: bool = False,
    schedule: tuple[LoadTier, ...] | None = (),
) -> FolioHolding:
    if lots is None:
        lots = (
            lot("A1", date(2025, 1, 10), "1000", "50000"),  # LT, gain 50,000
            lot("A2", date(2025, 6, 10), "1000", "80000"),  # LT, gain 20,000
            lot("A3", date(2026, 12, 1), "500", "45000"),  # ST, gain 5,000
        )
    return FolioHolding(
        folio_id=folio_id,
        scheme_id=f"SYN-EQ-{folio_id}",
        nav=D(nav),
        nav_date=AS_OF,
        lots=lots,
        domestic_equity_share=D("0.95"),
        debt_share=D("0.00"),
        is_elss=elss,
        exit_load_schedule=schedule,
    )


# --- pool -----------------------------------------------------------------------------------------


def test_pool_left_subtracts_every_use_and_floors_at_zero() -> None:
    assert pool_left_for(ctx("20000", in_app="5000", done="1000"), D("125000")) == D("99000")
    assert pool_left_for(ctx("200000"), D("125000")) == D("0")
    assert pool_left_for(ctx(None), D("125000")) is None


# --- harvest: happy path --------------------------------------------------------------------------


def test_harvest_stops_at_first_short_term_fifo_lot(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx(), rules, as_of=AS_OF)
    assert r.formula_id == HARVEST_FORMULA_ID
    assert not r.abstentions
    assert len(r.steps) == 1
    step = r.steps[0]
    assert [c.lot_id for c in step.lots_consumed] == ["A1", "A2"]  # A3 is short-term: FIFO blocks it
    assert step.units == D("2000")
    assert r.harvested_gain_inr == D("70000.00")
    assert r.pool_total_inr == D("125000")
    assert r.pool_left_after_inr == D("55000.00")
    # tax deferred = 70,000 × 12.5 % × (1 + 4 % cess), rates from the rule table
    assert r.tax_deferred_inr == D("9100.00")
    assert r.impact_basis == "TAX_DEFERRED"
    assert r.status is ActionStatus.NOT_VERIFIED  # wash-sale treatment NOT VERIFIED → CA review
    assert "WASH_SALE_TREATMENT_NOT_VERIFIED" in r.flags


def test_harvest_costs_stt_on_redemption_and_stamp_on_rebuy(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx(), rules, as_of=AS_OF)
    costs = r.steps[0].costs
    # proceeds 2,000 × 100 = 2,00,000; STT 0.001 % = 2.00; exit load 0;
    # rebuy amount 1,99,998 inclusive of stamp: 199998 × 0.00005 / 1.00005 = 9.9994… → 10.00
    assert r.steps[0].proceeds_inr == D("200000.00")
    assert costs.stt_inr == D("2.00")
    assert costs.exit_load_inr == D("0.00")
    assert costs.stamp_duty_inr == D("10.00")
    assert "STT-MF-01" in r.rule_ids_used and "STAMP-MF-01" in r.rule_ids_used
    assert "ONE_NAV_DAY_OUT_OF_MARKET" in r.flags


def test_harvest_takes_partial_lot_to_fill_exactly_the_pool(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx("95000"), rules, as_of=AS_OF)  # pool left 30,000
    step = r.steps[0]
    assert [c.lot_id for c in step.lots_consumed] == ["A1"]
    assert step.units == D("600")  # gain 50 per unit → 600 units = 30,000
    assert r.harvested_gain_inr == D("30000.00")
    assert r.pool_left_after_inr == D("0.00")


def test_partial_units_are_truncated_so_the_pool_is_never_exceeded(rules: TaxRuleSet) -> None:
    lots = (lot("A1", date(2025, 1, 10), "1000", "70000"),)  # gain 30 per unit at NAV 100
    r = ltcg_harvest((equity_folio(lots=lots),), ctx("115000"), rules, as_of=AS_OF)  # pool 10,000
    step = r.steps[0]
    assert step.units == D("333.333")  # 10,000 / 30 = 333.3333… truncated to 3 dp
    assert r.harvested_gain_inr <= D("10000")


def test_greedy_across_folios_by_gain_per_rupee_then_folio_id(rules: TaxRuleSet) -> None:
    low = equity_folio("F-1", lots=(lot("L1", date(2025, 1, 10), "1000", "90000"),))  # 10 % gain per rupee
    high = equity_folio("F-2", lots=(lot("H1", date(2025, 1, 10), "1000", "40000"),))  # 60 % gain per rupee
    r = ltcg_harvest((low, high), ctx("60000"), rules, as_of=AS_OF)  # pool 65,000
    assert [s.folio_id for s in r.steps] == ["F-2", "F-1"]
    assert r.steps[0].harvested_gain_inr == D("60000.00")
    assert r.steps[1].harvested_gain_inr == D("5000.00")


# --- harvest: exclusions and abstentions ----------------------------------------------------------


def test_elss_is_excluded(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(elss=True),), ctx(), rules, as_of=AS_OF)
    assert not r.steps
    assert [(s.folio_id, s.code) for s in r.skipped] == [("F-A", "ELSS_EXCLUDED")]


def test_unknown_ltcg_elsewhere_abstains_with_upper_bound(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx(None), rules, as_of=AS_OF)
    assert not r.steps
    assert r.status is ActionStatus.REQUIRES_CONFIGURATION
    (a,) = r.abstentions
    assert a.code == "LTCG_ELSEWHERE_UNKNOWN"
    # 1,25,000 × 12.5 % = 15,625 (before cess/surcharge), both from the rule table
    assert a.unlock_upper_bound_inr == D("15625.00")


def test_old_regime_and_non_resident_abstain_blocked(rules: TaxRuleSet) -> None:
    for c in (ctx(regime=Regime.OLD), ctx(residential_status=ResidentialStatus.NON_RESIDENT), ctx(regime=None)):
        r = ltcg_harvest((equity_folio(),), c, rules, as_of=AS_OF)
        assert not r.steps
        assert r.abstentions
    assert ltcg_harvest((equity_folio(),), ctx(regime=Regime.OLD), rules, as_of=AS_OF).status is ActionStatus.BLOCKED


def test_unknown_surcharge_band_abstains(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx(surcharge_rate=None), rules, as_of=AS_OF)
    assert not r.steps
    assert [a.code for a in r.abstentions] == ["SURCHARGE_BAND_UNKNOWN"]


def test_grandfathered_lot_makes_the_folio_abstain(rules: TaxRuleSet) -> None:
    lots = (lot("G1", date(2017, 6, 1), "100", "5000"), lot("G2", date(2025, 1, 10), "100", "5000"))
    r = ltcg_harvest((equity_folio(lots=lots),), ctx(), rules, as_of=AS_OF)
    assert not r.steps
    assert [s.code for s in r.skipped] == ["TAX_RULE_NOT_FOUND"]


def test_lot_inside_a_known_exit_load_window_stops_the_prefix(rules: TaxRuleSet) -> None:
    schedule = (LoadTier(window_days=730, rate=D("0.01")),)  # A1 held 771 days (out), A2 620 days (in)
    r = ltcg_harvest((equity_folio(schedule=schedule),), ctx(), rules, as_of=AS_OF)
    assert [c.lot_id for c in r.steps[0].lots_consumed] == ["A1"]
    assert r.steps[0].costs.exit_load_inr == D("0.00")


def test_unknown_exit_load_on_long_term_lots_is_assumed_zero_and_flagged(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(schedule=None),), ctx(), rules, as_of=AS_OF)
    assert [c.lot_id for c in r.steps[0].lots_consumed] == ["A1", "A2"]
    assert "EXIT_LOAD_ASSUMED_ZERO_AFTER_365_DAYS" in r.flags


def test_non_equity_folio_is_not_harvested(rules: TaxRuleSet) -> None:
    debt = FolioHolding(
        folio_id="F-D",
        scheme_id="SYN-DEBT",
        nav=D("20"),
        nav_date=AS_OF,
        lots=(lot("D1", date(2024, 5, 1), "100", "1500"),),
        domestic_equity_share=D("0"),
        debt_share=D("0.95"),
        exit_load_schedule=(),
    )
    r = ltcg_harvest((debt,), ctx(), rules, as_of=AS_OF)
    assert not r.steps
    assert [s.code for s in r.skipped] == ["NOT_EQUITY_LTCG_POOL"]


def test_tax_loss_harvesting_is_off(rules: TaxRuleSet) -> None:
    assert TAX_LOSS_HARVESTING_ENABLED is False
    loss_only = equity_folio(lots=(lot("X1", date(2025, 1, 10), "1000", "150000"),))  # loss of 50,000
    r = ltcg_harvest((loss_only,), ctx(), rules, as_of=AS_OF)
    assert not r.steps
    assert [s.code for s in r.skipped] == ["NO_POSITIVE_LONG_TERM_GAIN"]


# --- harvest window (a PARAMETER) -----------------------------------------------------------------


def test_window_sets_deadline_inside_and_notice_outside(rules: TaxRuleSet) -> None:
    inside = ltcg_harvest((equity_folio(),), ctx(), rules, as_of=AS_OF)
    assert inside.in_window is True
    assert inside.deadline == date(2027, 3, 31)
    outside_day = date(2027, 1, 20)
    outside = ltcg_harvest((equity_folio(),), ctx(), rules, as_of=outside_day)
    assert outside.in_window is False
    assert outside.deadline is None
    assert "OUTSIDE_HARVEST_WINDOW" in outside.flags
    custom = HarvestWindow(start_month=1, start_day=1, end_month=3, end_day=31)
    assert ltcg_harvest((equity_folio(),), ctx(), rules, as_of=outside_day, window=custom).in_window is True


def test_window_rejects_impossible_dates() -> None:
    with pytest.raises(InvalidInput):
        HarvestWindow(start_month=2, start_day=30, end_month=3, end_day=31)


# --- FIFO -----------------------------------------------------------------------------------------


def test_fifo_consume_is_oldest_first_regardless_of_input_order() -> None:
    f = equity_folio(lots=(lot("N", date(2026, 1, 1), "10", "900"), lot("O", date(2025, 1, 1), "10", "500")))
    consumed = fifo_consume(f, D("15"), AS_OF)
    assert [(c.lot_id, c.units) for c in consumed] == [("O", D("10")), ("N", D("5"))]
    assert consumed[1].cost_inr == D("450")
    assert consumed[1].gain_inr == D("50")
    with pytest.raises(InvalidInput):
        fifo_consume(f, D("21"), AS_OF)


def test_folio_validation() -> None:
    with pytest.raises(InvalidInput):
        equity_folio(lots=(lot("A", date(2025, 1, 1), "1", "1"), lot("A", date(2025, 2, 1), "1", "1")))
    with pytest.raises(InvalidInput):
        equity_folio(nav="0")


# --- "lot turns long-term within 45 days → wait" modifier ------------------------------------------


def _young_folio() -> FolioHolding:
    return FolioHolding(
        folio_id="F-Y",
        scheme_id="SYN-EQ-Y",
        nav=D("100"),
        nav_date=date(2026, 12, 15),
        lots=(lot("Y1", date(2026, 1, 10), "100", "6000"),),  # gain 4,000; LT from 2027-01-11
        domestic_equity_share=D("0.95"),
        debt_share=D("0"),
        exit_load_schedule=(),
    )


def test_wait_modifier_when_gain_fits_the_pool(rules: TaxRuleSet) -> None:
    m = lt_wait_modifier(_young_folio(), D("100"), ctx(), rules, as_of=date(2026, 12, 15), pool_left_inr=D("125000"))
    assert m is not None
    assert DEFAULT_WAIT_HORIZON_DAYS == 45
    assert m.wait_until == date(2027, 1, 11)
    assert m.days_to_wait == 27
    assert m.lots_turning_long_term == ("Y1",)
    # now: 4,000 × 20 % × 1.04 = 832; later: inside the pool → 0
    assert m.tax_now_inr == D("832.00")
    assert m.tax_if_wait_inr == D("0.00")
    assert m.tax_avoided_inr == D("832.00")


def test_wait_modifier_when_pool_is_used(rules: TaxRuleSet) -> None:
    m = lt_wait_modifier(_young_folio(), D("100"), ctx(), rules, as_of=date(2026, 12, 15), pool_left_inr=D("0"))
    assert m is not None
    # 4,000 × (20 % − 12.5 %) × 1.04 = 312
    assert m.tax_avoided_inr == D("312.00")


def test_wait_modifier_absent_beyond_45_days(rules: TaxRuleSet) -> None:
    m = lt_wait_modifier(_young_folio(), D("100"), ctx(), rules, as_of=date(2026, 11, 20), pool_left_inr=D("0"))
    assert m is None  # 52 days to long-term


def test_wait_modifier_absent_for_debt_without_holding_test(rules: TaxRuleSet) -> None:
    debt = FolioHolding(
        folio_id="F-D",
        scheme_id="SYN-DEBT",
        nav=D("20"),
        nav_date=date(2026, 12, 15),
        lots=(lot("D1", date(2026, 1, 10), "100", "1500"),),
        domestic_equity_share=D("0"),
        debt_share=D("0.95"),
        exit_load_schedule=(),
    )
    assert lt_wait_modifier(debt, D("100"), ctx(), rules, as_of=date(2026, 12, 15), pool_left_inr=D("0")) is None


def test_wait_modifier_reports_exit_load_change(rules: TaxRuleSet) -> None:
    f = FolioHolding(
        folio_id="F-Y",
        scheme_id="SYN-EQ-Y",
        nav=D("100"),
        nav_date=date(2026, 12, 15),
        lots=(lot("Y1", date(2026, 1, 10), "100", "6000"),),
        domestic_equity_share=D("0.95"),
        debt_share=D("0"),
        exit_load_schedule=(LoadTier(window_days=365, rate=D("0.01")),),  # 339 days now; 366 at wait date
    )
    m = lt_wait_modifier(f, D("100"), ctx(), rules, as_of=date(2026, 12, 15), pool_left_inr=D("0"))
    assert m is not None
    assert m.exit_load_now_inr == D("100.00")
    assert m.exit_load_if_wait_inr == D("0.00")


def test_engine_result_has_no_expected_return_field(rules: TaxRuleSet) -> None:
    r = ltcg_harvest((equity_folio(),), ctx(), rules, as_of=AS_OF)
    assert not hasattr(r, "expected_return")
    assert isinstance(r.tax_deferred_inr, Decimal)
