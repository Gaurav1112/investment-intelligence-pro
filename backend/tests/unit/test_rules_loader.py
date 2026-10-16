"""Rule-table loader tests (ADR-0009): strict schema, provenance on every rule, NV never upgraded."""

import copy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine.money import D
from iip.engine.tax import RateKind, Verification
from iip.rules.loader import (
    MF_CATEGORIES_PATH,
    TAX_RULES_PATH,
    RuleTableError,
    load_mf_categories,
    load_tax_rules,
    parse_mf_categories,
    parse_tax_rules,
)

# Rules still NOT VERIFIED after Track 6 (primary-text verification, 2026-10-15). They must stay NV until a CA
# signs off or a primary text is read and cited (see india.yaml header and docs/finance/ca-review-packet.md).
KNOWN_NV = {
    "GSEC-CG-ST/ITA1961",
    "GSEC-CG-ST/ITA2025",
    "GSEC-CG-LT/ITA1961",
    "GSEC-CG-LT/ITA2025",
    "TBILL-01/ITA1961",
    "TBILL-01/ITA2025",
    "SGB-02-ST",
    "SGB-02-LT",
}

# NV rules upgraded to P in Track 6. Each must cite the primary text it was verified against.
UPGRADED_FROM_NV = {
    "MF-DEBT-SMF/ITA2025",
    "MF-OTHER-ST/ITA1961",
    "MF-OTHER-ST/ITA2025",
    "MF-OTHER-LT/ITA1961",
    "MF-OTHER-LT/ITA2025",
    "BOND-L-LT-OLD",
    "BOND-UL/ITA2025",
    "REBATE-01/FY2025-26",
    "REBATE-01/TY2026-27",
    "TDS-SEC-01/ITA2025",
    "TDS-MF-01/ITA2025",
    "DIV-INTEXP-01",
}

PRIMARY_HOSTS = (
    "https://www.incometaxindia.gov.in/",
    "https://egazette.gov.in/",
    "https://thc.nic.in/",
    "https://www.indiacode.nic.in/",
    "https://www.indiabudget.gov.in/",
)


def raw_tax() -> dict[str, Any]:
    data = yaml.safe_load(TAX_RULES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def raw_mf() -> dict[str, Any]:
    data = yaml.safe_load(MF_CATEGORIES_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _all_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("acts", "rules", "slab_tables", "surcharges", "cess", "rebates", "withholding", "deductions", "levies"):
        items.extend(data[key])
    return items


def test_shipped_table_loads() -> None:
    rs = load_tax_rules()
    assert rs.jurisdiction == "IN"
    assert len(rs.rules) >= 40
    assert rs.coverage_to == date(2027, 3, 31)


def test_every_rule_has_source_url_and_status() -> None:
    for item in _all_items(raw_tax()):
        url = str(item["source_url"])
        assert url.startswith(("https://", "doc:docs/")), item["rule_id"]
        assert item["verification_status"] in {"P", "S", "NV"}, item["rule_id"]
    rs = load_tax_rules()
    for rid in rs.all_rule_ids():
        assert rid


def test_rule_ids_are_unique() -> None:
    ids = [item["rule_id"] for item in _all_items(raw_tax())]
    assert len(ids) == len(set(ids))


def test_nv_rules_stay_nv() -> None:
    rs = load_tax_rules()
    status = rs.status_by_rule_id()
    missing = KNOWN_NV - status.keys()
    assert not missing, missing
    upgraded = {rid for rid in KNOWN_NV if status[rid] is not Verification.NV}
    assert not upgraded, f"NV rules upgraded without CA sign-off or a primary citation: {upgraded}"
    unexpected_nv = {rid for rid, st in status.items() if st is Verification.NV} - KNOWN_NV
    assert not unexpected_nv, f"new NV rules must be listed here: {unexpected_nv}"


def test_rules_upgraded_from_nv_cite_a_primary_text() -> None:
    by_id = {item["rule_id"]: item for item in _all_items(raw_tax())}
    for rid in UPGRADED_FROM_NV:
        item = by_id[rid]
        assert item["verification_status"] == "P", rid
        assert str(item["source_url"]).startswith(PRIMARY_HOSTS), rid
        notes = str(item.get("notes", ""))
        assert "PRIMARY [" in notes, f"{rid}: notes must name the primary text read"
        assert '"' in notes, f"{rid}: notes must quote the statute"
        assert " s." in notes, f"{rid}: notes must give the section/clause"


def test_table_version_is_recorded() -> None:
    rs = load_tax_rules()
    assert rs.table_version.startswith("india-tax@")
    data = raw_tax()
    del data["table_version"]
    with pytest.raises(RuleTableError, match="table_version"):
        parse_tax_rules(data)


def test_rebate_exclusions_cover_every_special_rate_section() -> None:
    # Correction r2: s.112A(6) (1961) and s.198(7) (2025) bar the rebate against equity LTCG tax too, and
    # s.87A 2nd proviso / s.156(3) cap it at tax at slab rates — so EVERY special-rate section is excluded.
    rs = load_tax_rules()
    for reb in rs.rebates:
        special = {
            r.section
            for r in rs.rules
            if r.act is reb.act and r.rate_kind is RateKind.SPECIAL and r.section is not None
        }
        assert special <= set(reb.excluded_sections), (reb.rule_id, special - set(reb.excluded_sections))
    by_id = {r.rule_id: r for r in rs.rebates}
    assert by_id["REBATE-01/FY2025-26"].excluded_sections == ("111A", "112", "112A")
    assert by_id["REBATE-01/TY2026-27"].excluded_sections == ("196", "197", "198")


def test_every_research_rule_id_is_present() -> None:
    # Agent B §8 table ids (rows split per Act carry a '/ITA1961' or '/ITA2025' suffix).
    research_ids = {
        "LAW-ITA25", "EQ-STCG-OLD", "EQ-STCG", "EQ-LTCG-OLD", "EQ-LTCG", "MF-DEBT-SMF", "MF-SMF-DEF-OLD",
        "MF-DEBT-PRE2023-ST", "MF-DEBT-PRE2023-LT", "MF-OTHER-ST", "MF-OTHER-LT", "BOND-L-ST", "BOND-L-LT",
        "BOND-L-LT-OLD", "BOND-UL", "GSEC-CG", "TBILL-01", "INT-SLAB-01", "TDS-INT-01", "TDS-INT-OLD",
        "TDS-INT-02", "TDS-SEC-01", "TDS-MF-01", "SGB-01", "SGB-02", "REBATE-01", "SLAB-NEW-01", "SURCH-01",
        "CESS-01", "STT-MF-01", "STAMP-MF-01", "DIV-INTEXP-01", "BUYBACK-01",
    }  # fmt: skip
    present = {rid.split("/")[0] for rid in load_tax_rules().all_rule_ids()}
    prefixes = {p for p in present} | {p.rsplit("-", 1)[0] for p in present}
    assert research_ids <= prefixes, research_ids - prefixes


def test_slab_rule_values() -> None:
    rs = load_tax_rules()
    rule = next(r for r in rs.rules if r.rule_id == "EQ-LTCG/ITA2025")
    assert rule.rate == D("0.125") and rule.rate_kind is RateKind.SPECIAL
    assert rule.annual_exemption_inr == D("125000")
    assert rule.section_1961 == "112A" and rule.section_2025 == "198"


def test_unknown_top_level_field_rejected() -> None:
    data = raw_tax()
    data["surprise"] = 1
    with pytest.raises(RuleTableError, match="surprise"):
        parse_tax_rules(data)


def test_unknown_rule_field_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["discount"] = "0.5"
    with pytest.raises(RuleTableError, match="discount"):
        parse_tax_rules(data)


def test_unknown_condition_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["conditions"]["is_lucky"] = True
    with pytest.raises(RuleTableError, match="is_lucky"):
        parse_tax_rules(data)


@pytest.mark.parametrize("field", ["source_url", "verification_status", "effective_from", "rule_id", "act"])
def test_missing_required_field_rejected(field: str) -> None:
    data = raw_tax()
    del data["rules"][0][field]
    with pytest.raises(RuleTableError):
        parse_tax_rules(data)


def test_bad_status_and_url_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["verification_status"] = "VERIFIED"
    with pytest.raises(RuleTableError):
        parse_tax_rules(data)
    data = raw_tax()
    data["rules"][0]["source_url"] = "memo.pdf"
    with pytest.raises(RuleTableError, match="source_url"):
        parse_tax_rules(data)


def test_float_rates_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["rate"] = 0.15
    with pytest.raises(RuleTableError, match="float"):
        parse_tax_rules(data)


def test_rate_out_of_range_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["rate"] = "1.5"
    with pytest.raises(RuleTableError):
        parse_tax_rules(data)


def test_duplicate_rule_id_rejected() -> None:
    data = raw_tax()
    data["rules"].append(copy.deepcopy(data["rules"][0]))
    with pytest.raises(RuleTableError, match="duplicate"):
        parse_tax_rules(data)


def test_inverted_dates_rejected() -> None:
    data = raw_tax()
    data["rules"][0]["effective_to"] = date(2000, 1, 1)
    with pytest.raises(RuleTableError):
        parse_tax_rules(data)


def test_rule_outside_its_act_period_rejected() -> None:
    data = raw_tax()
    row = next(r for r in data["rules"] if r["rule_id"] == "EQ-STCG/ITA2025")
    row["effective_from"] = date(2026, 3, 1)
    with pytest.raises(RuleTableError, match="act"):
        parse_tax_rules(data)


def test_income_rule_with_holding_threshold_rejected() -> None:
    data = raw_tax()
    row = next(r for r in data["rules"] if r["gain_type"] == "INCOME")
    row["holding_threshold_months"] = 12
    with pytest.raises(RuleTableError):
        parse_tax_rules(data)


def test_exemption_needs_scope() -> None:
    data = raw_tax()
    row = next(r for r in data["rules"] if r.get("annual_exemption_inr") is not None)
    row["exemption_scope"] = None
    with pytest.raises(RuleTableError, match="exemption"):
        parse_tax_rules(data)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuleTableError):
        load_tax_rules(tmp_path / "nope.yaml")


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(RuleTableError):
        load_tax_rules(p)


# --- MF categories and expense regime -----------------------------------------------------------


def test_mf_categories_load_and_map() -> None:
    table = load_mf_categories()
    assert table.rename.effective_from == date(2026, 2, 26)
    assert table.canonical_category("Low Duration Fund") == "Ultra Short to Short Term Fund"
    assert table.canonical_category("Ultra Short Duration Fund") == "Ultra Short Term Fund"
    assert table.canonical_category("Banking and PSU Fund") == "Banking and PSU Debt Fund"  # AMFI probe label
    assert table.canonical_category("  low   duration ") == "Ultra Short to Short Term Fund"
    assert table.canonical_category("Liquid Fund") == "Liquid Fund"  # unchanged names pass through
    assert table.rename.source_url.startswith("https://")


def test_expense_regime_switches_on_1_apr_2026() -> None:
    table = load_mf_categories()
    assert table.expense_ratio_kind(date(2026, 3, 31)) == "TER"
    assert table.expense_ratio_kind(date(2026, 4, 1)) == "BER"


def test_mf_categories_reject_unknown_fields() -> None:
    data = raw_mf()
    data["rename"]["mappings"][0]["colour"] = "blue"
    with pytest.raises(RuleTableError, match="colour"):
        parse_mf_categories(data)


def test_mf_legacy_names_unique() -> None:
    data = raw_mf()
    data["rename"]["mappings"].append(copy.deepcopy(data["rename"]["mappings"][0]))
    with pytest.raises(RuleTableError, match="duplicate"):
        parse_mf_categories(data)


def test_load_action_templates_reads_the_shipped_table_and_rejects_a_bad_file(tmp_path: Path) -> None:
    from iip.engine.errors import InvalidInput
    from iip.rules.loader import ACTION_TEMPLATES_PATH, load_action_templates

    shipped = load_action_templates()
    assert shipped.templates and shipped.version
    assert shipped == load_action_templates(ACTION_TEMPLATES_PATH)
    bad = tmp_path / "action_templates.yaml"
    raw = yaml.safe_load(ACTION_TEMPLATES_PATH.read_text(encoding="utf-8"))
    raw["surprise"] = 1
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(InvalidInput, match="surprise"):
        load_action_templates(bad)
    bad.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(RuleTableError):
        load_action_templates(bad)
