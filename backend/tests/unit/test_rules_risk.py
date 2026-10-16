"""Risk and cost rule tables (package A11): stress drawdowns, allocation policy structure, equity costs.

Every value used here is SYNTHETIC. The real stress constants live only in the user's local config (U-08), never in
the repo or its tests.
"""

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from iip.engine.money import D
from iip.engine.ranking import Objective
from iip.rules.loader import (
    ALLOCATION_POLICY_PATH,
    EQUITY_COSTS_PATH,
    LOCAL_STRESS_ENV,
    STRESS_TABLE_PATH,
    RowStatus,
    RuleTableError,
    ValueSource,
    load_allocation_policy,
    load_equity_costs,
    load_stress_table,
    load_user_stress_table,
    local_stress_values_path,
    parse_allocation_policy,
    parse_equity_costs,
    parse_stress_table,
    parse_user_targets,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_CLASSES = {"EQ_LARGE", "EQ_BROAD", "EQ_MID", "EQ_SMALL", "EQ_FACTOR", "EQ_SECTOR_THEMATIC", "GOLD"}
REQUIRED_ROW_FIELDS = ("source_url", "verification_status", "effective_from")


def _raw(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _synthetic_local(tmp_path: Path, values: list[dict[str, Any]] | None = None) -> Path:
    """Write a synthetic local stress file under a fake data dir and return its path."""
    path = local_stress_values_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "values": values
        if values is not None
        else [
            {"risk_class": "EQ_BROAD", "stress": "0.500", "recovery_years": "4.0"},
            {"risk_class": "EQ_LARGE", "stress": "0.400"},
        ],
    }
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


# --- the generic row contract: source, status and effective_from on every row ------------------------------


ROW_LISTS = [
    (STRESS_TABLE_PATH, "classes", parse_stress_table),
    (ALLOCATION_POLICY_PATH, "horizon_bands", parse_allocation_policy),
    (ALLOCATION_POLICY_PATH, "parameters", parse_allocation_policy),
    (EQUITY_COSTS_PATH, "rows", parse_equity_costs),
    (EQUITY_COSTS_PATH, "parameters", parse_equity_costs),
]


@pytest.mark.parametrize(("path", "section", "parser"), ROW_LISTS)
@pytest.mark.parametrize("field", REQUIRED_ROW_FIELDS)
def test_loader_rejects_rows_without_source_status_or_effective_from(
    path: Path, section: str, parser: Any, field: str
) -> None:
    data = _raw(path)
    for i in range(len(data[section])):
        broken = copy.deepcopy(data)
        del broken[section][i][field]
        with pytest.raises(RuleTableError, match=field):
            parser(broken)


@pytest.mark.parametrize(("path", "section", "parser"), ROW_LISTS)
def test_loader_rejects_blank_or_non_https_source(path: Path, section: str, parser: Any) -> None:
    for bad in ("", "http://example.invalid/x", "see notes"):
        broken = copy.deepcopy(_raw(path))
        broken[section][0]["source_url"] = bad
        with pytest.raises(RuleTableError, match="source_url"):
            parser(broken)


@pytest.mark.parametrize(("path", "section", "parser"), ROW_LISTS)
def test_loader_rejects_unknown_status(path: Path, section: str, parser: Any) -> None:
    broken = copy.deepcopy(_raw(path))
    broken[section][0]["verification_status"] = "VERIFIED-ISH"
    with pytest.raises(RuleTableError, match="verification_status"):
        parser(broken)


@pytest.mark.parametrize("path", [STRESS_TABLE_PATH, ALLOCATION_POLICY_PATH, EQUITY_COSTS_PATH])
def test_doc_citation_pointers_resolve_to_files_in_the_repo(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    pointers = {
        line.split("doc:", 1)[1].split("#", 1)[0].strip() for line in text.splitlines() if "source_url: doc:" in line
    }
    assert pointers
    for rel in pointers:
        assert (REPO_ROOT / rel).is_file(), rel


# --- stress table (U-08: values from local config only) ------------------------------------------------------


def test_shipped_stress_table_holds_no_index_derived_values() -> None:
    table = load_stress_table()
    for cls in LOCAL_CLASSES:
        row = table.row(cls)
        assert row.value_source is ValueSource.LOCAL_CONFIG
        assert row.stress is None and row.recovery_years is None
        assert table.cited_stress(cls) is None
    assert set(table.requires_configuration()) == LOCAL_CLASSES
    assert table.local_values_loaded is False


def test_shipped_yaml_carries_no_number_for_local_classes() -> None:
    for row in _raw(STRESS_TABLE_PATH)["classes"]:
        if row["value_source"] == "LOCAL_CONFIG":
            assert "stress" not in row and "recovery_years" not in row, row["rule_id"]


def test_repo_table_refuses_a_value_on_a_local_config_row() -> None:
    data = _raw(STRESS_TABLE_PATH)
    row = next(r for r in data["classes"] if r["risk_class"] == "EQ_BROAD")
    row["stress"] = "0.500"
    with pytest.raises(RuleTableError, match="local config"):
        parse_stress_table(data)


def test_local_values_merge_into_the_table(tmp_path: Path) -> None:
    table = load_stress_table(local_values_path=_synthetic_local(tmp_path))
    assert table.local_values_loaded is True
    assert table.cited_stress("EQ_BROAD") == D("0.500")
    assert table.row("EQ_BROAD").recovery_years == D("4.0")
    assert table.cited_stress("EQ_LARGE") == D("0.400")
    assert table.row("EQ_LARGE").recovery_years is None
    assert "EQ_BROAD" not in table.requires_configuration()
    assert "EQ_MID" in table.requires_configuration()
    # status and citation stay those of the public row
    assert table.row("EQ_BROAD").verification_status is RowStatus.S
    assert table.row("EQ_BROAD").source_url.startswith("doc:docs/")


def test_missing_local_file_means_requires_configuration_not_an_error(tmp_path: Path) -> None:
    table = load_stress_table(local_values_path=local_stress_values_path(tmp_path))
    assert table.local_values_loaded is False
    assert table.cited_stress("EQ_BROAD") is None


def test_local_stress_path_lives_under_the_data_dir(tmp_path: Path) -> None:
    assert local_stress_values_path(tmp_path) == tmp_path / "config" / "stress_drawdowns.local.yaml"


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ([{"risk_class": "EQ_BROAD", "stress": 0.5}], "float"),
        ([{"risk_class": "EQ_BROAD", "stress": "1.5"}], r"\(0, 1\]"),
        ([{"risk_class": "EQ_BROAD", "stress": "0"}], r"\(0, 1\]"),
        ([{"risk_class": "EQ_BROAD", "stress": "0.5", "recovery_years": "-1"}], "recovery_years"),
        ([{"risk_class": "NOT_A_CLASS", "stress": "0.5"}], "unknown risk class"),
        ([{"risk_class": "CASH_LIKE", "stress": "0.5"}], "not LOCAL_CONFIG"),
        ([{"risk_class": "EQ_BROAD", "stress": "0.5"}, {"risk_class": "EQ_BROAD", "stress": "0.6"}], "duplicate"),
        ([{"risk_class": "EQ_BROAD", "stress": "0.5", "surprise": "x"}], "surprise"),
    ],
)
def test_local_file_is_validated(tmp_path: Path, values: list[dict[str, Any]], match: str) -> None:
    path = _synthetic_local(tmp_path, values)
    with pytest.raises(RuleTableError, match=match):
        load_stress_table(local_values_path=path)


def test_malformed_local_file_is_an_error(tmp_path: Path) -> None:
    path = local_stress_values_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("values: [unclosed", encoding="utf-8")
    with pytest.raises(RuleTableError, match="invalid YAML"):
        load_stress_table(local_values_path=path)


def _local_text(values: list[dict[str, Any]]) -> str:
    return yaml.safe_dump({"schema_version": 1, "values": values})


def test_user_stress_table_reads_the_hosted_env_value(tmp_path: Path) -> None:
    """U-08 on hosted: no local file exists, so the private values come from a secret env var (same schema)."""
    env = {LOCAL_STRESS_ENV: _local_text([{"risk_class": "EQ_BROAD", "stress": "0.500", "recovery_years": "4.0"}])}
    table = load_user_stress_table(tmp_path, env)
    assert table.local_values_loaded is True
    assert table.cited_stress("EQ_BROAD") == D("0.500")
    assert "EQ_MID" in table.requires_configuration()


def test_user_stress_table_env_wins_over_the_local_file(tmp_path: Path) -> None:
    _synthetic_local(tmp_path)  # EQ_BROAD 0.500 in the file
    env = {LOCAL_STRESS_ENV: _local_text([{"risk_class": "EQ_BROAD", "stress": "0.600"}])}
    assert load_user_stress_table(tmp_path, env).cited_stress("EQ_BROAD") == D("0.600")


@pytest.mark.parametrize("blank", ["", "   \n"])
def test_user_stress_table_blank_env_falls_back_to_the_file(tmp_path: Path, blank: str) -> None:
    _synthetic_local(tmp_path)
    assert load_user_stress_table(tmp_path, {LOCAL_STRESS_ENV: blank}).cited_stress("EQ_BROAD") == D("0.500")


def test_user_stress_table_without_env_or_file_requires_configuration(tmp_path: Path) -> None:
    table = load_user_stress_table(tmp_path, {})
    assert table.local_values_loaded is False and table.cited_stress("EQ_BROAD") is None
    assert load_user_stress_table(None, {}).local_values_loaded is False


@pytest.mark.parametrize(
    ("text", "match"),
    [("values: [unclosed", "invalid YAML"), ("- just a list", "mapping"),
     (_local_text([{"risk_class": "EQ_BROAD", "stress": "1.5"}]), r"\(0, 1\]")],
)  # fmt: skip
def test_malformed_env_value_is_an_error_never_ignored(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(RuleTableError, match=match):
        load_user_stress_table(tmp_path, {LOCAL_STRESS_ENV: text})


def test_env_error_never_echoes_the_private_values(tmp_path: Path) -> None:
    with pytest.raises(RuleTableError) as exc:
        load_user_stress_table(tmp_path, {LOCAL_STRESS_ENV: "values: [0.6123, unclosed"})
    assert "0.6123" not in str(exc.value)


def test_hybrid_aliases_broad_equity_and_follows_its_configuration(tmp_path: Path) -> None:
    assert load_stress_table().cited_stress("HYBRID") is None
    table = load_stress_table(local_values_path=_synthetic_local(tmp_path))
    assert table.row("HYBRID").value_source is ValueSource.ALIAS
    assert table.cited_stress("HYBRID") == table.cited_stress("EQ_BROAD") == D("0.500")


def test_parameter_rows_ship_in_the_public_table() -> None:
    table = load_stress_table()
    assert table.cited_stress("CASH_LIKE") == D("0")
    assert table.cited_stress("STOCK") == D("1")
    debt = table.row("DEBT_MTM")
    assert debt.value_source is ValueSource.FORMULA and debt.formula is not None
    assert (debt.formula.dy, debt.formula.ds_aaa, debt.formula.ds_below_aaa) == (D("0.02"), D("0.01"), D("0.03"))
    assert table.cited_stress("DEBT_MTM") is None  # holding-specific: needs the fund's duration


def test_design_fictional_debt_sleeve_reproduces_s_d() -> None:
    # design-risk-first.md §5.3 fictional fund: D_mod = 1.0, AAA → s_d = 1.0 × 0.02 + 1.0 × 0.01 = 0.03.
    f = load_stress_table().row("DEBT_MTM").formula
    assert f is not None
    assert D("1.0") * f.dy + D("1.0") * f.ds_aaa == D("0.03")


def test_GOLD_stays_not_verified() -> None:
    assert load_stress_table().row("GOLD").verification_status is RowStatus.NV


def test_stress_table_structural_checks() -> None:
    data = _raw(STRESS_TABLE_PATH)
    dup = copy.deepcopy(data)
    dup["classes"].append(copy.deepcopy(dup["classes"][0]))
    with pytest.raises(RuleTableError, match="duplicate"):
        parse_stress_table(dup)
    bad_alias = copy.deepcopy(data)
    next(r for r in bad_alias["classes"] if r["value_source"] == "ALIAS")["alias_of"] = "NOPE"
    with pytest.raises(RuleTableError, match="alias"):
        parse_stress_table(bad_alias)
    bad_table = copy.deepcopy(data)
    next(r for r in bad_table["classes"] if r["risk_class"] == "STOCK")["stress"] = "1.2"
    with pytest.raises(RuleTableError, match=r"\[0, 1\]"):
        parse_stress_table(bad_table)
    with pytest.raises(RuleTableError, match="unknown"):
        load_stress_table().row("NOT_A_CLASS")


# --- allocation policy (structure only) ----------------------------------------------------------------------


def test_policy_ships_structure_only() -> None:
    policy = load_allocation_policy()
    assert policy.sleeves == ("EQUITY", "DEBT", "GOLD", "CASH_LIKE")
    assert set(policy.objectives) == {o.value for o in Objective}
    assert _raw(ALLOCATION_POLICY_PATH)["targets"] == []


def test_policy_refuses_any_shipped_target() -> None:
    data = _raw(ALLOCATION_POLICY_PATH)
    data["targets"] = [{"band_id": "H3_5Y_PLUS", "objective": "D_growth", "weights": {"EQUITY": "1"}}]
    with pytest.raises(RuleTableError, match="user decision"):
        parse_allocation_policy(data)


def test_horizon_bands_cover_every_horizon_once() -> None:
    policy = load_allocation_policy()
    assert policy.band_for(D("0")).band_id == "H0_UNDER_1Y"
    assert policy.band_for(D("0.99")).band_id == "H0_UNDER_1Y"
    assert policy.band_for(D("1")).band_id == "H1_1_TO_3Y"
    assert policy.band_for(D("4.5")).band_id == "H2_3_TO_5Y"
    assert policy.band_for(D("40")).band_id == "H3_5Y_PLUS"
    with pytest.raises(RuleTableError):
        policy.band_for(D("-0.1"))


def test_horizon_bands_must_be_contiguous() -> None:
    data = _raw(ALLOCATION_POLICY_PATH)
    data["horizon_bands"][1]["min_years"] = "2"
    with pytest.raises(RuleTableError, match="contiguous"):
        parse_allocation_policy(data)


def test_policy_parameters_are_the_u04_defaults() -> None:
    policy = load_allocation_policy()
    assert policy.parameter("band_abs") == D("0.05")
    assert policy.parameter("review_cadence") == "ANNUAL"
    assert policy.parameter("rebalance_mode") == "CASH_FLOW_ONLY"


def test_policy_rejects_unknown_objective_or_bad_parameter() -> None:
    data = _raw(ALLOCATION_POLICY_PATH)
    data["objectives"] = [*data["objectives"], "F_lottery"]
    with pytest.raises(RuleTableError, match="objective"):
        parse_allocation_policy(data)
    data = _raw(ALLOCATION_POLICY_PATH)
    next(p for p in data["parameters"] if p["parameter"] == "band_abs")["value"] = "1.5"
    with pytest.raises(RuleTableError, match="band_abs"):
        parse_allocation_policy(data)


def _target(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "band_id": "H3_5Y_PLUS",
        "objective": "D_growth",
        "weights": {"EQUITY": "0.40", "DEBT": "0.50", "CASH_LIKE": "0.10"},
        "decided_on": date(2026, 10, 1),
        "set_by": "user",
    }
    return {**base, **over}


def test_user_targets_validate_against_the_structure() -> None:
    policy = load_allocation_policy()
    (t,) = parse_user_targets(policy, [_target()])
    assert t.weight("EQUITY") == D("0.40") and t.weight("GOLD") == Decimal(0)
    assert t.decided_on == date(2026, 10, 1)


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"weights": {"EQUITY": "0.40", "DEBT": "0.50"}}, "sum"),
        ({"weights": {"EQUITY": 0.5, "DEBT": "0.5"}}, "float"),
        ({"weights": {"CRYPTO": "1"}}, "sleeve"),
        ({"band_id": "H9"}, "band"),
        ({"objective": "F_lottery"}, "objective"),
        ({"set_by": "engine"}, "user"),
        ({"decided_on": None}, "decided_on"),
    ],
)
def test_user_targets_reject_bad_rows(over: dict[str, Any], match: str) -> None:
    with pytest.raises(RuleTableError, match=match):
        parse_user_targets(load_allocation_policy(), [_target(**over)])


def test_user_targets_reject_duplicate_cells() -> None:
    with pytest.raises(RuleTableError, match="duplicate"):
        parse_user_targets(load_allocation_policy(), [_target(), _target()])


# --- equity costs --------------------------------------------------------------------------------------------


def test_cost_table_loads_with_statuses() -> None:
    table = load_equity_costs()
    by_id = {r.rule_id: r for r in table.rows}
    assert by_id["COST-EQ-STT"].rate == D("0.001") and by_id["COST-EQ-STT"].side == "BOTH"
    assert by_id["COST-EQ-STAMP"].side == "BUY"
    assert by_id["COST-EQ-BROKERAGE"].verification_status is RowStatus.REQUIRES_CONFIGURATION
    assert by_id["COST-EQ-BROKERAGE"].rate is None
    assert table.parameter("unverified_period_multiplier") == D("1.5")


def test_etf_stt_row_is_not_verified() -> None:
    (etf_stt,) = [r for r in load_equity_costs().rows if r.applies_to == "ETF" and r.component == "STT"]
    assert etf_stt.verification_status is RowStatus.NV
    assert etf_stt.rate is None


def test_cost_rows_before_the_observation_date_are_absent() -> None:
    table = load_equity_costs()
    assert table.rows_on(date(2026, 10, 15), "EQUITY_DELIVERY")
    assert table.rows_on(date(2020, 1, 1), "EQUITY_DELIVERY") == ()


def test_fixture_c1_from_the_table() -> None:
    """Fixture C-1 (research-backtest-method.md §6.1, verify BT-4): ₹1,00,000 bought and sold on NSE with zero
    brokerage costs ₹237.8212 (200 + 6.14 + 0.20 + 15 + 1.1412 + 15.34). Brokerage is supplied, as REQUIRES
    CONFIGURATION demands; every other rate comes from the table."""
    table = load_equity_costs()
    rows = {r.rule_id: r for r in table.rows_on(date(2026, 10, 15), "EQUITY_DELIVERY")}

    def rate(rule_id: str) -> Decimal:
        r = rows[rule_id].rate
        assert r is not None
        return r

    value, brokerage = D("100000"), D("0")
    sides = 2
    stt = value * rate("COST-EQ-STT") * sides
    txn = value * rate("COST-EQ-TXN-NSE") * sides
    sebi = value * rate("COST-EQ-SEBI-FEE") * sides
    stamp = value * rate("COST-EQ-STAMP")  # buy side only
    gst = (brokerage + sebi + txn) * rate("COST-EQ-GST")
    dp = rows["COST-EQ-DP"].amount_inr
    assert dp is not None
    assert (stt, txn, sebi, stamp, gst, dp) == (D("200"), D("6.14"), D("0.2"), D("15"), D("1.1412"), D("15.34"))
    assert stt + txn + sebi + stamp + gst + dp + brokerage == D("237.8212")


@pytest.mark.parametrize(
    ("rule_id", "patch", "match"),
    [
        ("COST-EQ-STT", {"rate": None}, "rate"),
        ("COST-EQ-STT", {"rate": 0.001}, "float"),
        ("COST-EQ-STT", {"rate": "1.2"}, r"\[0, 1\]"),
        ("COST-EQ-DP", {"rate": "0.001"}, "rate or amount_inr"),
        ("COST-EQ-DP", {"amount_inr": "-1"}, "amount_inr"),
        ("COST-EQ-STT", {"effective_to": "2020-01-01"}, "effective_to"),
        ("COST-EQ-STT", {"side": "SOMETIMES"}, "side"),
    ],
)
def test_cost_rows_are_validated(rule_id: str, patch: dict[str, Any], match: str) -> None:
    data = _raw(EQUITY_COSTS_PATH)
    row = next(r for r in data["rows"] if r["rule_id"] == rule_id)
    row.update(patch)
    with pytest.raises(RuleTableError, match=match):
        parse_equity_costs(data)


def test_overlapping_cost_rows_are_rejected() -> None:
    data = _raw(EQUITY_COSTS_PATH)
    clone = copy.deepcopy(next(r for r in data["rows"] if r["rule_id"] == "COST-EQ-STT"))
    clone["rule_id"] = "COST-EQ-STT-2"
    data["rows"].append(clone)
    with pytest.raises(RuleTableError, match="overlap"):
        parse_equity_costs(data)
