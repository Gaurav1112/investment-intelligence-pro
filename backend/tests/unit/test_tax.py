"""Tax engine tests (ADR-0009; calculation-methodology.md §2.12; indian-instruments-and-tax.md §7-§8).

Every expected value is hand-computed from the research rule table. Profiles are fictional
(no real user values). Rule data comes from the shipped ``rules/tax/india.yaml`` through the loader.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from iip.engine.errors import AmbiguousRule, InvalidInput, MissingData, RuleNotFound
from iip.engine.money import D
from iip.engine.tax import (
    ILLUSTRATIVE_PROFILES,
    W_ILLUSTRATIVE,
    W_LOSS_SETOFF,
    W_REBATE_NOT_APPLIED,
    W_SURCHARGE_MARGINAL_RELIEF,
    Act,
    Disposal,
    GainType,
    Regime,
    ResidentialStatus,
    TaxProfile,
    TaxReport,
    TaxRuleSet,
    classify_holding,
    compute_levy,
    compute_tax,
    select_rule,
    slab_tax,
)
from iip.rules.loader import load_tax_rules

EQ = "LISTED_EQUITY_SHARE"
MF = "MUTUAL_FUND"


@pytest.fixture(scope="module")
def rules() -> TaxRuleSet:
    return load_tax_rules()


def profile(slab: str | None = "0.30", surcharge: str | None = "0", income: str | None = None) -> TaxProfile:
    return TaxProfile(
        regime=Regime.NEW,
        residential_status=ResidentialStatus.RESIDENT,
        slab_rate=D(slab) if slab is not None else None,
        taxable_income_inr=D(income) if income is not None else None,
        surcharge_rate=D(surcharge) if surcharge is not None else None,
        label="fictional test profile",
    )


def equity(acq: date, sale: date, gain: str, lot: str = "L1") -> Disposal:
    return Disposal(lot_id=lot, instrument_class=EQ, acquisition_date=acq, transfer_date=sale, gain_inr=D(gain))


def debt_mf(acq: date, sale: date, gain: str, *, listed: bool | None = False) -> Disposal:
    return Disposal(
        lot_id="D1",
        instrument_class=MF,
        acquisition_date=acq,
        transfer_date=sale,
        gain_inr=D(gain),
        listed=listed,
        domestic_equity_share=D("0"),
        debt_share=D("0.90"),
    )


def only_total(report: TaxReport) -> Decimal:
    assert len(report.scenarios) == 1
    return report.scenarios[0].total_tax_inr


# --- holding-period classification -------------------------------------------------------------


def test_exactly_twelve_months_is_short_term() -> None:
    # "held for not more than 12 months" → short-term; long-term only when the threshold is exceeded.
    assert classify_holding(date(2024, 8, 1), date(2025, 8, 1), 12) is GainType.STCG
    assert classify_holding(date(2024, 8, 1), date(2025, 8, 2), 12) is GainType.LTCG


def test_month_end_clamping_on_leap_day() -> None:
    assert classify_holding(date(2024, 2, 29), date(2025, 2, 28), 12) is GainType.STCG
    assert classify_holding(date(2024, 2, 29), date(2025, 3, 1), 12) is GainType.LTCG


def test_twelve_month_boundary_end_to_end(rules: TaxRuleSet) -> None:
    st = compute_tax([equity(date(2024, 8, 1), date(2025, 8, 1), "100000")], rules, profile())
    lt = compute_tax([equity(date(2024, 8, 1), date(2025, 8, 2), "100000")], rules, profile())
    assert st.classifications[0].gain_type is GainType.STCG
    assert st.classifications[0].rule_id == "EQ-STCG/ITA1961"
    assert only_total(st) == D("20800.00")  # 20 % + 4 % cess
    assert lt.classifications[0].gain_type is GainType.LTCG
    assert only_total(lt) == D("0.00")  # whole gain within the ₹1.25 lakh exemption


# --- equity STCG / LTCG ------------------------------------------------------------------------


def test_equity_stcg_15_before_23_jul_2024_and_20_after(rules: TaxRuleSet) -> None:
    before = compute_tax([equity(date(2024, 1, 10), date(2024, 7, 22), "100000")], rules, profile())
    after = compute_tax([equity(date(2024, 1, 10), date(2024, 7, 23), "100000")], rules, profile())
    assert before.classifications[0].rule_id == "EQ-STCG-OLD"
    assert before.classifications[0].base_rate == D("0.15")
    assert only_total(before) == D("15600.00")  # 15,000 + 600 cess
    assert after.classifications[0].rule_id == "EQ-STCG/ITA1961"
    assert only_total(after) == D("20800.00")  # 20,000 + 800 cess


def test_equity_ltcg_12_5_above_1_25_lakh(rules: TaxRuleSet) -> None:
    report = compute_tax([equity(date(2024, 1, 1), date(2025, 6, 2), "200000")], rules, profile())
    c = report.classifications[0]
    assert c.rule_id == "EQ-LTCG/ITA1961"
    assert c.exemption_applied_inr == D("125000")
    assert c.taxable_gain_inr == D("75000")
    lot = report.scenarios[0].lots[0]
    assert lot.base_tax_inr == D("9375.00")
    assert lot.cess_inr == D("375.00")
    assert lot.total_tax_inr == D("9750.00")


def test_ltcg_exemption_is_one_annual_pool(rules: TaxRuleSet) -> None:
    lots = [
        equity(date(2024, 1, 1), date(2025, 6, 2), "100000", "A"),
        equity(date(2024, 1, 1), date(2025, 9, 1), "100000", "B"),
    ]
    report = compute_tax(lots, rules, profile())
    assert [c.exemption_applied_inr for c in report.classifications] == [D("100000"), D("25000")]
    assert only_total(report) == D("9750.00")  # same as a single ₹2 lakh gain


def test_lots_spanning_financial_years_are_rejected(rules: TaxRuleSet) -> None:
    lots = [
        equity(date(2024, 1, 1), date(2025, 3, 31), "1000", "A"),
        equity(date(2024, 1, 1), date(2025, 4, 1), "1000", "B"),
    ]
    with pytest.raises(InvalidInput, match="financial year"):
        compute_tax(lots, rules, profile())


def test_mixed_exemption_limits_in_fy_2024_25_abstain(rules: TaxRuleSet) -> None:
    # FY2024-25 straddles the 23-Jul-2024 change (10 % vs 12.5 %, one ₹1.25 lakh pool); how the pool is split
    # between the two rates is not in the statute text, so the engine abstains.
    lots = [
        equity(date(2023, 1, 2), date(2024, 7, 1), "50000", "A"),
        equity(date(2023, 1, 2), date(2024, 8, 1), "50000", "B"),
    ]
    with pytest.raises(AmbiguousRule):
        compute_tax(lots, rules, profile())


# --- debt mutual funds (specified MF, s.50AA) ---------------------------------------------------


def test_debt_mf_bought_1_apr_2023_is_slab_regardless_of_holding(rules: TaxRuleSet) -> None:
    report = compute_tax([debt_mf(date(2023, 4, 1), date(2025, 6, 30), "50000")], rules, profile())
    c = report.classifications[0]
    assert c.rule_id == "MF-DEBT-SMF/ITA1961"
    assert c.gain_type is GainType.STCG  # deemed short-term after 26+ months
    assert only_total(report) == D("15600.00")  # 30 % slab + cess
    assert report.unverified_assumption is False


def test_debt_mf_bought_31_mar_2023_gets_24_month_ltcg(rules: TaxRuleSet) -> None:
    report = compute_tax([debt_mf(date(2023, 3, 31), date(2025, 6, 30), "50000")], rules, profile())
    c = report.classifications[0]
    assert c.rule_id == "MF-DEBT-PRE2023-LT/ITA1961"
    assert c.gain_type is GainType.LTCG
    assert only_total(report) == D("6500.00")  # 12.5 % = 6,250 + 250 cess


def test_pre_2023_debt_unit_listed_status_decides_the_threshold(rules: TaxRuleSet) -> None:
    # Correction r2 (Finance (No.2) Act 2024 s.3(b); ITA 2025 s.2(101)(b)(i)): a LISTED unit is long-term after
    # 12 months, an unlisted one after 24.  The table only encodes the unlisted case; listed units abstain
    # instead of silently taking the 24-month threshold.
    acq, sale = date(2023, 3, 1), date(2024, 9, 2)  # held 18 months, transfer after 23-Jul-2024
    unlisted = compute_tax([debt_mf(acq, sale, "50000")], rules, profile())
    assert unlisted.classifications[0].rule_id == "MF-DEBT-PRE2023-ST/ITA1961"
    assert unlisted.classifications[0].gain_type is GainType.STCG
    with pytest.raises(RuleNotFound):  # listed (debt ETF): 18 months > 12 → LTCG by statute; not encoded → abstain
        select_rule(rules, debt_mf(acq, sale, "50000", listed=True))
    with pytest.raises(MissingData, match="listed"):
        select_rule(rules, debt_mf(acq, sale, "50000", listed=None))


def test_fy_2024_25_pre_23_jul_equity_ltcg_gets_1_25_lakh_exemption(rules: TaxRuleSet) -> None:
    # Correction r2: Finance (No.2) Act 2024 s.31 — "the limit of one lakh twenty-five thousand rupees shall apply
    # on aggregate of the long-term capital gains under sub-clauses (a) and (b)", (a) being pre-23-Jul-2024 transfers.
    report = compute_tax([equity(date(2023, 1, 2), date(2024, 7, 1), "150000")], rules, profile())
    c = report.classifications[0]
    assert c.rule_id == "EQ-LTCG-OLD"
    assert c.exemption_applied_inr == D("125000")  # was 100000 before r2
    assert c.taxable_gain_inr == D("25000")
    assert only_total(report) == D("2600.00")  # 10 % = 2,500 + 100 cess
    mf = Disposal(
        lot_id="M", instrument_class=MF, acquisition_date=date(2023, 1, 2), transfer_date=date(2024, 7, 1),
        gain_inr=D("150000"), domestic_equity_share=D("0.80"), debt_share=D("0.10"),
    )  # fmt: skip
    assert compute_tax([mf], rules, profile()).classifications[0].exemption_applied_inr == D("125000")


def test_mutual_fund_without_composition_raises_missing_data(rules: TaxRuleSet) -> None:
    d = Disposal(
        lot_id="X",
        instrument_class=MF,
        acquisition_date=date(2024, 1, 1),
        transfer_date=date(2025, 6, 2),
        gain_inr=D("1000"),
    )
    with pytest.raises(MissingData):
        select_rule(rules, d)


# --- bonds -------------------------------------------------------------------------------------


def _bond(listed: bool) -> Disposal:
    return Disposal(
        lot_id="B",
        instrument_class="BOND",
        acquisition_date=date(2024, 8, 1),
        transfer_date=date(2025, 9, 1),
        gain_inr=D("10000"),
        listed=listed,
    )


def test_listed_vs_unlisted_bonds(rules: TaxRuleSet) -> None:
    listed = compute_tax([_bond(True)], rules, profile())
    unlisted = compute_tax([_bond(False)], rules, profile())
    assert listed.classifications[0].rule_id == "BOND-L-LT/ITA1961"
    assert only_total(listed) == D("1300.00")  # 12.5 % + cess
    assert unlisted.classifications[0].rule_id == "BOND-UL/ITA1961"
    assert unlisted.classifications[0].gain_type is GainType.STCG
    assert only_total(unlisted) == D("3120.00")  # deemed STCG at 30 % slab + cess


# --- interest at slab --------------------------------------------------------------------------


def _fd_interest(amount: str = "10000", on: date = date(2025, 12, 31)) -> Disposal:
    return Disposal(lot_id="FD", instrument_class="INTEREST", transfer_date=on, gain_inr=D(amount))


def test_fd_interest_at_slab(rules: TaxRuleSet) -> None:
    report = compute_tax([_fd_interest()], rules, profile())
    assert report.classifications[0].rule_id == "INT-SLAB-01/ITA1961"
    assert report.classifications[0].gain_type is GainType.INCOME
    assert only_total(report) == D("3120.00")
    assert W_REBATE_NOT_APPLIED in report.warnings


def test_slab_income_stacks_on_taxable_income(rules: TaxRuleSet) -> None:
    # Base ₹11,00,000; ₹2,00,000 interest: 1 lakh at 10 % + 1 lakh at 15 % = 25,000; cess 1,000.
    report = compute_tax([_fd_interest("200000")], rules, profile(slab=None, surcharge=None, income="1100000"))
    assert only_total(report) == D("26000.00")
    assert "SLAB-NEW-01/FY2025-26" in report.rule_ids_used
    assert "SURCH-01/FY2025-26" in report.rule_ids_used


def test_slab_table_new_regime() -> None:
    rules = load_tax_rules()
    fy26 = next(t for t in rules.slab_tables if t.rule_id == "SLAB-NEW-01/FY2025-26")
    assert slab_tax(fy26, D("400000")) == D("0")
    assert slab_tax(fy26, D("1200000")) == D("60000")  # 20,000 + 40,000
    assert slab_tax(fy26, D("2500000")) == D("330000")  # 60k + 60k + 80k + 100k + 30k


# --- missing profile ---------------------------------------------------------------------------


def test_missing_profile_gives_labelled_illustrative_scenarios(rules: TaxRuleSet) -> None:
    report = compute_tax([_fd_interest()], rules, None)
    assert len(report.scenarios) == len(ILLUSTRATIVE_PROFILES) >= 2
    assert all(s.illustrative for s in report.scenarios)
    labels = [s.label for s in report.scenarios]
    assert any("30 % slab" in label for label in labels)
    assert any("20 % slab" in label for label in labels)
    assert all(label.startswith("ILLUSTRATIVE") for label in labels)
    totals = {s.label: s.total_tax_inr for s in report.scenarios}
    assert sorted(totals.values()) == [D("2080.00"), D("3120.00")]  # TAX-1 fixture: 20 % × 1.04
    assert W_ILLUSTRATIVE in report.warnings


def test_user_profile_is_not_illustrative(rules: TaxRuleSet) -> None:
    report = compute_tax([_fd_interest()], rules, profile())
    assert report.scenarios[0].illustrative is False
    assert W_ILLUSTRATIVE not in report.warnings


def test_profile_needs_exactly_one_income_basis(rules: TaxRuleSet) -> None:
    with pytest.raises(InvalidInput):
        compute_tax([_fd_interest()], rules, profile(slab="0.30", income="1000000"))
    with pytest.raises(InvalidInput):
        compute_tax([_fd_interest()], rules, profile(slab=None, income=None))
    with pytest.raises(InvalidInput, match="surcharge"):
        compute_tax([_fd_interest()], rules, profile(slab="0.30", surcharge=None))


def test_out_of_scope_profiles_abstain(rules: TaxRuleSet) -> None:
    old = replace(profile(), regime=Regime.OLD)
    nri = replace(profile(), residential_status=ResidentialStatus.NON_RESIDENT)
    for p in (old, nri):
        with pytest.raises(RuleNotFound):
            compute_tax([_fd_interest()], rules, p)


# --- verification status -----------------------------------------------------------------------


def _gsec(sale: date) -> Disposal:
    return Disposal(
        lot_id="G", instrument_class="GSEC", acquisition_date=date(2025, 1, 2), transfer_date=sale, gain_inr=D("50000")
    )


def test_nv_rule_propagates_unverified_flag(rules: TaxRuleSet) -> None:
    # G-sec gains: whether a Retail-Direct G-sec is a "listed" security is NOT VERIFIED (CA question 7).
    report = compute_tax([_gsec(date(2026, 6, 1))], rules, profile())
    assert report.classifications[0].rule_id == "GSEC-CG-LT/ITA2025"
    assert report.unverified_assumption is True
    assert "GSEC-CG-LT/ITA2025" in report.unverified_rule_ids
    assert only_total(report) == D("6500.00")  # 12.5 % = 6,250 + 250 cess


def test_specified_mf_under_2025_act_is_primary_verified(rules: TaxRuleSet) -> None:
    # Track 6: ITA 2025 s.76(2)(a)/(5)(b) read in the primary text → no longer an unverified assumption.
    report = compute_tax([debt_mf(date(2023, 4, 1), date(2026, 6, 1), "50000")], rules, profile())
    assert report.classifications[0].rule_id == "MF-DEBT-SMF/ITA2025"
    assert report.classifications[0].section == "76"
    assert report.unverified_assumption is False
    assert only_total(report) == D("15600.00")


def test_tbill_is_unverified(rules: TaxRuleSet) -> None:
    d = Disposal(lot_id="T", instrument_class="TBILL", transfer_date=date(2025, 11, 5), gain_inr=D("1000"))
    report = compute_tax([d], rules, profile())
    assert report.unverified_assumption is True


# --- abstention --------------------------------------------------------------------------------


def test_no_matching_rule_raises(rules: TaxRuleSet) -> None:
    with pytest.raises(RuleNotFound):
        select_rule(rules, equity(date(2022, 1, 1), date(2023, 1, 2), "1000"))
    with pytest.raises(RuleNotFound):
        select_rule(rules, replace(equity(date(2024, 1, 1), date(2025, 6, 2), "1"), instrument_class="CRYPTO"))


def test_beyond_rule_table_coverage_abstains(rules: TaxRuleSet) -> None:
    with pytest.raises(RuleNotFound, match="coverage"):
        select_rule(rules, equity(date(2026, 4, 1), date(2027, 4, 1), "1000"))


def test_grandfathering_boundary_abstains(rules: TaxRuleSet) -> None:
    # s.112A grandfathering ("on or before 31-Jan-2018", FMV boundary) is not specified → abstain.
    with pytest.raises(RuleNotFound, match="31-Jan-2018"):
        select_rule(rules, equity(date(2018, 1, 31), date(2025, 6, 2), "1000"))
    assert select_rule(rules, equity(date(2018, 2, 1), date(2025, 6, 2), "1000")).rule_id == "EQ-LTCG/ITA1961"


def test_overlapping_rules_raise_ambiguous(rules: TaxRuleSet) -> None:
    rule = select_rule(rules, equity(date(2024, 1, 10), date(2024, 8, 1), "1000"))
    dup = replace(rule, rule_id="EQ-STCG-DUPLICATE")
    overlapping = replace(rules, rules=(*rules.rules, dup))
    with pytest.raises(AmbiguousRule, match="EQ-STCG-DUPLICATE"):
        select_rule(overlapping, equity(date(2024, 1, 10), date(2024, 8, 1), "1000"))


# --- Income-tax Act 2025 transition ------------------------------------------------------------


def test_ita2025_section_mapping_after_1_apr_2026(rules: TaxRuleSet) -> None:
    before = compute_tax([equity(date(2025, 6, 1), date(2026, 3, 31), "1000")], rules, profile())
    after = compute_tax([equity(date(2025, 6, 1), date(2026, 4, 1), "1000")], rules, profile())
    assert (before.act, before.classifications[0].section) == (Act.ITA1961, "111A")
    assert (after.act, after.classifications[0].section) == (Act.ITA2025, "196")
    assert after.classifications[0].rule_id == "EQ-STCG/ITA2025"
    lt = compute_tax([equity(date(2025, 1, 2), date(2026, 4, 1), "200000")], rules, profile())
    assert lt.classifications[0].section == "198"


# --- surcharge and cess ------------------------------------------------------------------------


def test_surcharge_cap_on_special_rate_gains(rules: TaxRuleSet) -> None:
    p = profile(surcharge="0.25")
    eq = compute_tax([equity(date(2025, 1, 2), date(2025, 6, 2), "100000")], rules, p)
    lot = eq.scenarios[0].lots[0]
    assert lot.surcharge_rate == D("0.15")  # capped from 25 %
    assert lot.surcharge_inr == D("3000.00")
    assert lot.cess_inr == D("920.00")
    assert lot.total_tax_inr == D("23920.00")
    fd = compute_tax([_fd_interest("100000")], rules, p)
    fd_lot = fd.scenarios[0].lots[0]
    assert fd_lot.surcharge_rate == D("0.25")  # slab income is not capped
    assert fd_lot.total_tax_inr == D("39000.00")  # 30,000 + 7,500 + 1,500
    assert W_SURCHARGE_MARGINAL_RELIEF in eq.warnings


def test_surcharge_band_derived_from_total_income(rules: TaxRuleSet) -> None:
    p = profile(slab=None, surcharge=None, income="30000000")  # ₹3 crore → 25 % band
    report = compute_tax([equity(date(2025, 1, 2), date(2025, 6, 2), "100000")], rules, p)
    assert report.scenarios[0].surcharge_band_rate == D("0.25")
    assert report.scenarios[0].lots[0].surcharge_rate == D("0.15")


def test_surcharge_band_must_exist_in_table(rules: TaxRuleSet) -> None:
    with pytest.raises(InvalidInput):
        compute_tax([_fd_interest()], rules, profile(surcharge="0.37"))


def test_cess_is_four_percent_of_tax_plus_surcharge(rules: TaxRuleSet) -> None:
    report = compute_tax([equity(date(2025, 1, 2), date(2025, 6, 2), "100000")], rules, profile())
    lot = report.scenarios[0].lots[0]
    assert (lot.base_tax_inr, lot.surcharge_inr, lot.cess_inr) == (D("20000.00"), D("0.00"), D("800.00"))
    assert "CESS-01/ITA1961" in report.rule_ids_used


# --- zero and loss -----------------------------------------------------------------------------


def test_zero_gain(rules: TaxRuleSet) -> None:
    report = compute_tax([equity(date(2025, 1, 2), date(2025, 6, 2), "0")], rules, profile())
    assert only_total(report) == D("0.00")
    assert report.classifications[0].loss is None
    assert report.rule_ids_used == ("EQ-STCG/ITA1961",)


def test_loss_has_no_negative_tax_and_records_carry_forward_info(rules: TaxRuleSet) -> None:
    report = compute_tax([equity(date(2025, 1, 2), date(2025, 6, 2), "-5000")], rules, profile())
    assert only_total(report) == D("0.00")
    lot = report.scenarios[0].lots[0]
    assert lot.base_tax_inr >= 0 and lot.total_tax_inr >= 0
    loss = report.classifications[0].loss
    assert loss is not None
    assert loss.amount_inr == D("5000")
    assert loss.capital_loss_type is GainType.STCG
    assert loss.carry_forward_eligible is True
    assert loss.information_only is True
    assert W_LOSS_SETOFF in report.warnings


def test_loss_does_not_reduce_other_gains(rules: TaxRuleSet) -> None:
    lots = [
        equity(date(2025, 1, 2), date(2025, 6, 2), "-5000", "A"),
        equity(date(2025, 1, 2), date(2025, 6, 3), "10000", "B"),
    ]
    assert only_total(compute_tax(lots, rules, profile())) == D("2080.00")  # set-off not modelled


# --- inputs, levies ----------------------------------------------------------------------------


def test_disposal_validation() -> None:
    with pytest.raises(InvalidInput):
        equity(date(2025, 6, 2), date(2025, 1, 2), "1")
    with pytest.raises(InvalidInput):
        Disposal(lot_id="x", instrument_class=MF, transfer_date=date(2025, 6, 2), gain_inr=D("1"), debt_share=D("1.5"))


def test_empty_input_rejected(rules: TaxRuleSet) -> None:
    with pytest.raises(InvalidInput):
        compute_tax([], rules, profile())


def test_stamp_duty_levy_matches_methodology_sd3(rules: TaxRuleSet) -> None:
    stamp = next(lv for lv in rules.levies if lv.rule_id == "STAMP-MF-01")
    result = compute_levy(stamp, D("100000"), date(2025, 6, 2), inclusive=True)
    assert result.value_inr == D("5.00")  # §2.10 SD-3: 1,00,000 × 0.005/100.005 = 4.99975
    stt = next(lv for lv in rules.levies if lv.rule_id == "STT-MF-01")
    assert compute_levy(stt, D("100000"), date(2025, 6, 2)).value_inr == D("1.00")
    with pytest.raises(RuleNotFound):
        compute_levy(stamp, D("100000"), date(2020, 6, 30))
