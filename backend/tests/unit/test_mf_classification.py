"""MF tax-class classification (PLAN.md row A08). All scheme names are SYNTHETIC fixtures, never real schemes."""

import inspect
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine import candidates as cb
from iip.engine.money import D, engine_context
from iip.rules.loader import load_tax_rules

PATTERNS_PATH = Path(cb.__file__).resolve().parents[1] / "rules" / "index_name_patterns.yaml"
TABLE: dict[str, Any] = yaml.safe_load(PATTERNS_PATH.read_text(encoding="utf-8"))
OTHER_INDEX = "Other Scheme - Index Funds"
EQUITY_INDEX = "Index Funds - Equity Funds"
NAME_FLAG = "TAX_CLASS_INFERRED_FROM_NAME"
CATEGORY_FLAG = "TAX_CLASS_INFERRED_FROM_CATEGORY"

PATTERN_EXAMPLES = [(p["rule_id"], p["tax_class"], ex) for p in TABLE["patterns"] for ex in p["examples"]]
EXCLUSION_EXAMPLES = [(x["rule_id"], ex) for x in TABLE["exclusions"] for ex in x["examples"]]


# ------------------------------------------------------------------ the category false negative
@pytest.mark.parametrize("category", [EQUITY_INDEX, "index funds - equity funds", "Index Funds -  Equity Funds"])
def test_index_funds_equity_funds_label_is_equity(category: str) -> None:
    assert cb.mf_tax_class_from_category(category) is cb.MfTaxClass.EQUITY_ORIENTED
    c = cb.mf_tax_classification(category)
    assert c.tax_class is cb.MfTaxClass.EQUITY_ORIENTED
    assert c.flag == CATEGORY_FLAG and c.rule_id is None


def test_equity_index_category_with_plain_name_stays_category_inferred() -> None:
    c = cb.mf_tax_classification(EQUITY_INDEX, name="Fixture Nifty 50 Index Fund")
    assert c.tax_class is cb.MfTaxClass.EQUITY_ORIENTED and c.flag == CATEGORY_FLAG


def test_equity_index_category_with_overseas_name_is_unknown() -> None:
    """A supplied name can only make the answer more cautious for this label, never change equity into debt."""
    c = cb.mf_tax_classification(EQUITY_INDEX, name="Fixture Nasdaq 100 Index Fund")
    assert c.tax_class is cb.MfTaxClass.UNKNOWN and c.flag is None


def test_category_decision_is_never_overridden_by_name() -> None:
    c = cb.mf_tax_classification("Equity Scheme - Large Cap Fund", name="Fixture Gilt Index Fund")
    assert c.tax_class is cb.MfTaxClass.EQUITY_ORIENTED and c.flag == CATEGORY_FLAG
    d = cb.mf_tax_classification("Debt Scheme - Gilt Fund", name="Fixture Nifty 50 Index Fund")
    assert d.tax_class is cb.MfTaxClass.SPECIFIED_DEBT and d.flag == CATEGORY_FLAG


# ------------------------------------------------------------------ the name-pattern table (table-driven)
@pytest.mark.parametrize(("rule_id", "tax_class", "name"), PATTERN_EXAMPLES)
def test_every_pattern_classifies_its_examples_and_is_flagged(rule_id: str, tax_class: str, name: str) -> None:
    c = cb.mf_tax_classification(OTHER_INDEX, name=name)
    assert c.tax_class is cb.MfTaxClass(tax_class), name
    assert c.flag == NAME_FLAG
    assert c.rule_id is not None and rule_id in c.rule_id.split("+"), (rule_id, c.rule_id)
    assert cb.mf_tax_class_from_category(OTHER_INDEX, name=name) is cb.MfTaxClass(tax_class)


@pytest.mark.parametrize(("rule_id", "name"), EXCLUSION_EXAMPLES)
def test_every_exclusion_forces_unknown(rule_id: str, name: str) -> None:
    c = cb.mf_tax_classification(OTHER_INDEX, name=name)
    assert c.tax_class is cb.MfTaxClass.UNKNOWN and c.flag is None, (rule_id, name)
    assert c.rule_id == rule_id


@pytest.mark.parametrize(
    "name",
    [
        "Fixture Alpha Index Fund",  # names no index at all
        "Fixture Nifty Bank Index Fund",  # an equity index not in the table: not guessed
        "Fixture Nifty 50 and Gilt Index Fund",  # equity AND debt patterns
        "",
    ],
)
def test_unknown_stays_unknown(name: str) -> None:
    c = cb.mf_tax_classification(OTHER_INDEX, name=name)
    assert c.tax_class is cb.MfTaxClass.UNKNOWN and c.flag is None


def test_other_index_without_name_is_unknown_as_before() -> None:
    assert cb.mf_tax_class_from_category(OTHER_INDEX) is cb.MfTaxClass.UNKNOWN
    assert cb.mf_tax_classification(OTHER_INDEX).tax_class is cb.MfTaxClass.UNKNOWN


@pytest.mark.parametrize(
    "category",
    ["Hybrid Schemes - Balanced Advantage Fund/ Dynamic Asset Allocation", "Growth", "Index Funds - Debt Funds"],
)
def test_name_patterns_do_not_apply_outside_listed_categories(category: str) -> None:
    c = cb.mf_tax_classification(category, name="Fixture Nifty 50 Index Fund")
    assert c.tax_class is cb.MfTaxClass.UNKNOWN


def test_name_is_keyword_only_so_existing_callers_are_unchanged() -> None:
    for fn in (cb.mf_tax_class_from_category, cb.mf_tax_classification, cb.fund_has_credit_exposure):
        params = inspect.signature(fn).parameters
        assert params["name"].kind is inspect.Parameter.KEYWORD_ONLY and params["name"].default is None
    with pytest.raises(TypeError):
        cb.mf_tax_class_from_category(OTHER_INDEX, "Fixture Nifty 50 Index Fund")  # type: ignore[misc]


# ------------------------------------------------------------------ the YAML table is cited and matches the engine
def test_yaml_table_is_cited_and_well_formed() -> None:
    assert TABLE["schema_version"] == 1 and TABLE["flag"] == NAME_FLAG
    ids = [r["rule_id"] for r in (*TABLE["basis"], *TABLE["patterns"], *TABLE["exclusions"])]
    assert len(ids) == len(set(ids)), ids
    for r in (*TABLE["basis"], *TABLE["patterns"]):
        assert r["source_url"].startswith(("https://", "doc:docs/")), r["rule_id"]
        assert r["verification_status"] in ("P", "S", "NV"), r["rule_id"]
    for p in TABLE["patterns"]:
        assert p["tax_class"] in ("equity_oriented", "specified_debt")
        assert p["examples"], p["rule_id"]
        re.compile(p["regex"])
    for x in TABLE["exclusions"]:
        assert x["reason"] and x["examples"], x["rule_id"]
        re.compile(x["regex"])


def test_doc_references_exist() -> None:
    repo = PATTERNS_PATH.parents[4]
    for r in (*TABLE["basis"], *TABLE["patterns"]):
        if r["source_url"].startswith("doc:"):
            assert (repo / r["source_url"].removeprefix("doc:")).is_file(), r["source_url"]


def test_engine_table_matches_yaml() -> None:
    t = cb.INDEX_NAME_TABLE
    assert t.flag == TABLE["flag"]
    assert t.applies_to_categories == tuple(TABLE["applies_to_categories"])
    assert t.patterns == tuple((p["rule_id"], cb.MfTaxClass(p["tax_class"]), p["regex"]) for p in TABLE["patterns"])
    assert t.exclusions == tuple((x["rule_id"], x["regex"]) for x in TABLE["exclusions"])


# ------------------------------------------------------------------ credit exposure follows the inferred class
def test_name_inferred_debt_index_fund_has_credit_exposure() -> None:
    assert not cb.fund_has_credit_exposure(OTHER_INDEX)
    assert cb.fund_has_credit_exposure(OTHER_INDEX, name="Fixture Bharat Bond Index Fund April 2033")
    assert not cb.fund_has_credit_exposure(OTHER_INDEX, name="Fixture Nifty 50 Index Fund")
    _, unknown, why = cb.fund_credit_status(OTHER_INDEX, None, date(2026, 10, 15), name="Fixture Gilt Index Fund")
    assert unknown and why


# ------------------------------------------------------------------ the flag reaches the candidate
RULES = load_tax_rules()
AS_OF = date(2026, 10, 15)


def _series() -> tuple[list[date], list[Decimal]]:
    ds: list[date] = []
    ns: list[Decimal] = []
    nav, d, end = D("10"), date(2012, 1, 2), date(2026, 10, 14)
    with engine_context():
        while d <= end:
            if d.weekday() < 5:
                ds.append(d)
                ns.append(nav)
                nav = nav * D("1.00025")
            d += timedelta(days=1)
    return ds, ns


def _mf(name: str, category: str = OTHER_INDEX) -> cb.BuiltCandidate:
    ds, ns = _series()
    return cb.mf_candidate(
        instrument_id="mf:fixture",
        name=name,
        category=category,
        amount=D("100000"),
        as_of=AS_OF,
        withdrawal=date(2027, 4, 15),
        nav_dates=ds,
        navs=ns,
        exit_load=cb.ExitLoadSpec(days=0, rate=D("0"), citation="SID FIXTURE"),
        ruleset=RULES,
        profile=None,
        settlement_days=3,
    )


def test_mf_candidate_carries_name_inference_flag() -> None:
    b = _mf("Fixture Nifty 50 Index Fund")
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert NAME_FLAG in b.candidate.flags and CATEGORY_FLAG not in b.candidate.flags
    assert b.evidence is not None
    assert any("IDX-EQ-NIFTY50" in a for a in b.evidence.assumptions)


def test_mf_candidate_equity_index_category_is_eligible_and_category_flagged() -> None:
    b = _mf("Fixture Index Fund", category=EQUITY_INDEX)
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert CATEGORY_FLAG in b.candidate.flags and NAME_FLAG not in b.candidate.flags


def test_mf_candidate_unmatched_name_stays_tax_class_unknown() -> None:
    b = _mf("Fixture Alpha Index Fund")
    assert any(r.startswith("TAX_CLASS_UNKNOWN") for r in b.ineligible_reasons)


def test_mf_candidate_name_inferred_debt_needs_credit_facts() -> None:
    b = _mf("Fixture Gilt Index Fund")
    assert not b.ineligible_reasons, b.ineligible_reasons
    assert NAME_FLAG in b.candidate.flags
    assert b.candidate.credit_quality_unknown
