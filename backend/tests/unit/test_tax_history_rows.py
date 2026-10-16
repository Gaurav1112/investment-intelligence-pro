"""Historical (pre-FY2024-25) tax rows, package A11 (verify-backtest-method.md BT-3).

The rows are opt-in for backtests, NOT VERIFIED until a CA reviews them, close by 31-Mar-2024, and keep the
31-Jan-2018 grandfathering abstention. Gains below are fictional.
"""

import copy
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine.errors import RuleNotFound
from iip.engine.money import D
from iip.engine.tax import Disposal, TaxRuleSet, Verification, select_rule
from iip.rules.loader import TAX_RULES_PATH, RuleTableError, load_tax_rules, parse_tax_rules

EQ = "LISTED_EQUITY_SHARE"
MF = "MUTUAL_FUND"
HIST_IDS = {"EQ-STCG-HIST", "EQ-LTCG-HIST", "MF-EQ-STCG-HIST", "MF-EQ-LTCG-HIST"}
REPO_ROOT = Path(__file__).resolve().parents[3]


def _raw() -> dict[str, Any]:
    data = yaml.safe_load(TAX_RULES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def hist() -> TaxRuleSet:
    return load_tax_rules(include_historical=True)


def equity(acq: date, sale: date, gain: str = "1000") -> Disposal:
    return Disposal(lot_id="L", instrument_class=EQ, acquisition_date=acq, transfer_date=sale, gain_inr=D(gain))


def eq_mf(acq: date, sale: date, gain: str = "1000") -> Disposal:
    return replace(equity(acq, sale, gain), instrument_class=MF, domestic_equity_share=D("0.95"), debt_share=D("0.05"))


# --- opt-in: the live app's default rule set is unchanged -----------------------------------------------------


def test_default_rule_set_has_no_historical_rows() -> None:
    rs = load_tax_rules()
    assert not HIST_IDS & set(rs.all_rule_ids())
    assert "+" not in rs.table_version
    with pytest.raises(RuleNotFound):
        select_rule(rs, equity(date(2022, 1, 1), date(2023, 1, 2)))


def test_opt_in_merges_rows_and_marks_the_version(hist: TaxRuleSet) -> None:
    assert HIST_IDS <= set(hist.all_rule_ids())
    assert hist.table_version == load_tax_rules().table_version + "+india-tax-hist@2026-10-16.r1"


# --- status and citations ---------------------------------------------------------------------------------------


def test_every_historical_row_is_not_verified_until_ca_review(hist: TaxRuleSet) -> None:
    status = hist.status_by_rule_id()
    assert {status[i] for i in HIST_IDS} == {Verification.NV}


def test_historical_rows_cite_primary_gazette_texts(hist: TaxRuleSet) -> None:
    for r in hist.rules:
        if r.rule_id in HIST_IDS:
            assert r.source_url.startswith("https://egazette.gov.in/"), r.rule_id
            assert "CA" in r.notes, r.rule_id


def test_loader_refuses_a_historical_row_marked_verified() -> None:
    data = _raw()
    data["historical_rules"][0]["verification_status"] = "P"
    with pytest.raises(RuleTableError, match="NV"):
        parse_tax_rules(data, include_historical=True)
    with pytest.raises(RuleTableError, match="NV"):  # validated even when not merged
        parse_tax_rules(data)


@pytest.mark.parametrize("field", ["source_url", "verification_status", "effective_from"])
def test_loader_rejects_historical_rows_missing_provenance(field: str) -> None:
    data = _raw()
    del data["historical_rules"][0][field]
    with pytest.raises(RuleTableError, match=field):
        parse_tax_rules(data, include_historical=True)


@pytest.mark.parametrize("field", ["source_url", "verification_status", "effective_from"])
def test_loader_rejects_main_rows_missing_provenance(field: str) -> None:
    data = _raw()
    del data["rules"][0][field]
    with pytest.raises(RuleTableError, match=field):
        parse_tax_rules(data)


def test_historical_rows_must_close_before_the_main_table() -> None:
    data = _raw()
    data["historical_rules"][0]["effective_to"] = date(2024, 4, 1)
    with pytest.raises(RuleTableError, match="2024-03-31"):
        parse_tax_rules(data, include_historical=True)
    data = _raw()
    data["historical_rules"][0]["effective_to"] = None
    with pytest.raises(RuleTableError, match="effective_to"):
        parse_tax_rules(data, include_historical=True)


def test_historical_ids_may_not_shadow_main_ids() -> None:
    data = _raw()
    data["historical_rules"][0]["rule_id"] = "EQ-STCG-OLD"
    with pytest.raises(RuleTableError, match="duplicate"):
        parse_tax_rules(data)


def test_historical_rows_need_a_version() -> None:
    data = _raw()
    del data["historical_table_version"]
    with pytest.raises(RuleTableError, match="historical_table_version"):
        parse_tax_rules(data)


def test_file_without_historical_section_still_loads() -> None:
    data = copy.deepcopy(_raw())
    del data["historical_rules"], data["historical_table_version"]
    rs = parse_tax_rules(data, include_historical=True)
    assert rs.table_version == load_tax_rules().table_version


# --- the rates -------------------------------------------------------------------------------------------------


def test_fy2018_to_fy2023_equity_ltcg_is_10pc_above_1_lakh(hist: TaxRuleSet) -> None:
    for d in (equity(date(2019, 1, 2), date(2020, 6, 1)), eq_mf(date(2022, 1, 3), date(2024, 3, 31))):
        r = select_rule(hist, d)
        assert r.rule_id in {"EQ-LTCG-HIST", "MF-EQ-LTCG-HIST"}
        assert r.rate == D("0.10") and r.annual_exemption_inr == D("100000")
        assert r.exemption_scope == "EQUITY_LTCG_ANNUAL"


def test_fy2018_to_fy2023_equity_stcg_is_15pc(hist: TaxRuleSet) -> None:
    for d in (equity(date(2019, 1, 2), date(2019, 6, 1)), eq_mf(date(2023, 10, 2), date(2024, 3, 28))):
        r = select_rule(hist, d)
        assert r.rule_id in {"EQ-STCG-HIST", "MF-EQ-STCG-HIST"}
        assert r.rate == D("0.15")


def test_one_lakh_25k_applies_from_1_apr_to_22_jul_2024(hist: TaxRuleSet) -> None:
    for sale in (date(2024, 4, 1), date(2024, 7, 22)):
        r = select_rule(hist, equity(date(2019, 1, 2), sale))
        assert r.rule_id == "EQ-LTCG-OLD"
        assert r.rate == D("0.10") and r.annual_exemption_inr == D("125000")
    assert select_rule(hist, equity(date(2019, 1, 2), date(2024, 3, 31))).annual_exemption_inr == D("100000")
    after = select_rule(hist, equity(date(2019, 1, 2), date(2024, 7, 23)))
    assert after.rate == D("0.125") and after.annual_exemption_inr == D("125000")


@pytest.mark.parametrize("sale", [date(2019, 6, 1), date(2020, 6, 1), date(2024, 3, 31), date(2025, 6, 2)])
def test_lots_bought_on_or_before_31_jan_2018_abstain(hist: TaxRuleSet, sale: date) -> None:
    for d in (equity(date(2018, 1, 31), sale), eq_mf(date(2017, 3, 1), sale)):
        with pytest.raises(RuleNotFound, match="31-Jan-2018"):
            select_rule(hist, d)


def test_lot_bought_1_feb_2018_is_taxed_under_112a(hist: TaxRuleSet) -> None:
    assert select_rule(hist, equity(date(2018, 2, 1), date(2019, 3, 1))).rule_id == "EQ-LTCG-HIST"


def test_transfers_before_1_apr_2018_abstain(hist: TaxRuleSet) -> None:
    # s.10(38) era: no rows (STT-on-acquisition conditions not modelled).
    with pytest.raises(RuleNotFound):
        select_rule(hist, equity(date(2017, 6, 1), date(2018, 3, 30)))


def test_no_overlap_with_the_main_table_at_the_boundary(hist: TaxRuleSet) -> None:
    assert select_rule(hist, equity(date(2023, 10, 2), date(2024, 3, 31))).rule_id == "EQ-STCG-HIST"
    assert select_rule(hist, equity(date(2023, 10, 2), date(2024, 4, 1))).rule_id == "EQ-STCG-OLD"


# --- the research doc (line 485) -------------------------------------------------------------------------------


def test_research_doc_no_longer_shows_one_lakh_for_fy2024_25() -> None:
    lines = (REPO_ROOT / "docs/research/indian-instruments-and-tax.md").read_text(encoding="utf-8").splitlines()
    row = lines[484]
    assert row.startswith("| EQ-LTCG-OLD |")
    cells = [c.strip() for c in row.split("|")]
    assert cells[6].startswith("₹1,25,000/yr")
    assert cells[7] == "2024-04-01" and cells[8] == "2024-07-22"
