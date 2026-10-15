"""NAVAll.txt parser tests. Fixture: synthetic file in the NAVAll.txt layout (fictional schemes; see
docs/data/probes/README.md).

Regressions from docs/research/hidden-gems.md §4.4 (ShantanuAnant/mutualfund): NAV parsed as float, a malformed
row becoming the AMC name, `N.A.`/`#N/A` NAVs, no rejection counters. Plus bad ISINs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from iip.data.models import QualityStatus, SchemaChanged
from iip.data.parsers.amfi_navall import NAVALL_HEADER, parse_navall
from tests.data.conftest import (
    NAVALL_LAST_MODIFIED,
    NAVALL_RETRIEVED,
    NAVALL_URL,
    make_payload,
)

AXIS_GROWTH = b"954298;INFZ11K01WO4;-;Asteria Children's Fund;Direct Plan;Growth Option;20.2971;14-Oct-2026"


def _parse(content: bytes, quality: QualityStatus = QualityStatus.FIXTURE):
    payload = make_payload("amfi.navall", content, NAVALL_URL, NAVALL_RETRIEVED, NAVALL_LAST_MODIFIED)
    return parse_navall(payload, quality=quality)


def _mini(*rows: bytes, amc: bytes = b"Asteria Mutual Fund") -> bytes:
    lines = [
        NAVALL_HEADER.encode(),
        b" ",
        "Open Ended Schemes(Children’s Fund - Childrens' Fund)".encode(),
        b" ",
        amc,
        b" ",
        *rows,
    ]
    return b"\r\n".join(lines) + b"\r\n"


# --- happy path on the synthetic NAVAll fixture---------------------------------------------------


def test_fixture_parses_all_rows(navall_bytes: bytes) -> None:
    result = _parse(navall_bytes)
    assert result.report.rows_seen == 40
    assert result.report.rows_ok == 40
    assert result.report.rows_rejected == 0
    assert len(result.observations) == len(result.records) == 40


def test_values_are_decimal_with_original_precision(navall_bytes: bytes) -> None:
    obs = {o.entity_key: o for o in _parse(navall_bytes).observations}
    assert obs["954298"].value == Decimal("20.2971")
    assert isinstance(obs["954298"].value, Decimal)
    # Precision is kept exactly as published: trailing zeros are preserved (3-dp case: test_navhistory fixture).
    assert str(obs["989265"].value) == "15.0950"
    assert str(obs["932567"].value) == "15.5790"


def test_provenance_contract(navall_bytes: bytes) -> None:
    result = _parse(navall_bytes)
    o = next(x for x in result.observations if x.entity_key == "934256")
    assert o.source_id == "amfi.navall"
    assert o.source_url == NAVALL_URL
    assert o.retrieved_at == NAVALL_RETRIEVED
    assert o.publication_time == NAVALL_LAST_MODIFIED
    assert o.observation_date == date(2026, 10, 14)
    assert o.value == Decimal("25.9504")
    assert o.unit == "INR_per_unit"
    assert o.currency == "INR"
    assert o.convention == "NAV_PER_UNIT_AS_PUBLISHED"
    assert o.quality_status is QualityStatus.FIXTURE
    assert o.raw_sha256 == result.report.raw_sha256
    assert len(o.raw_sha256) == 64


def test_context_lines_set_amc_and_category(navall_bytes: bytes) -> None:
    recs = {r.scheme_code: r for r in _parse(navall_bytes).records}
    axis = recs[954298]
    assert axis.amc == "Asteria Mutual Fund"
    assert axis.scheme_type == "Open Ended Schemes"
    assert axis.category == "Children’s Fund - Childrens' Fund"  # U+2019 kept
    assert axis.isin_growth == "INFZ11K01WO4"
    assert axis.isin_reinvest is None  # '-' means empty
    assert axis.plan == "Direct Plan"
    assert axis.option == "Growth Option"
    hdfc = recs[908795]
    assert hdfc.amc == "Halcyon Mutual Fund"
    assert hdfc.category == "Debt Scheme - Banking and PSU Fund"
    assert hdfc.isin_reinvest == "INFZ12KA1JE4"
    icici = recs[950443]
    assert icici.amc == "Ilex Prudent Mutual Fund"
    assert icici.category == "Debt Scheme - Corporate Bond Fund"
    assert icici.plan is None and icici.option is None  # ';;;' rows have empty plan/option


def test_old_nav_dates_are_kept_never_coerced(navall_bytes: bytes) -> None:
    obs = {o.entity_key: o for o in _parse(navall_bytes).observations}
    assert obs["989190"].observation_date == date(2017, 9, 15)
    assert obs["932567"].observation_date == date(2015, 8, 4)


def test_quality_defaults_to_ok_for_live() -> None:
    result = _parse(_mini(AXIS_GROWTH), quality=QualityStatus.OK)
    assert result.observations[0].quality_status is QualityStatus.OK


# --- encoding / line-ending robustness ---------------------------------------------------------


def test_bom_lf_and_trailing_whitespace_tolerated() -> None:
    text = _mini(AXIS_GROWTH + b"   \t").replace(b"\r\n", b"\n")
    result = _parse(b"\xef\xbb\xbf" + text)
    assert result.report.rows_ok == 1
    assert result.observations[0].value == Decimal("20.2971")


def test_non_utf8_is_schema_change() -> None:
    with pytest.raises(SchemaChanged):
        _parse(_mini(AXIS_GROWTH).replace(b"Asteria Mutual Fund", b"Asteria \xff Fund"))


# --- fail-closed schema checks -----------------------------------------------------------------


def test_header_mismatch_fails_closed() -> None:
    old_six_field = b"Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date"
    content = _mini(AXIS_GROWTH).replace(NAVALL_HEADER.encode(), old_six_field)
    with pytest.raises(SchemaChanged):
        _parse(content)


def test_empty_file_fails_closed() -> None:
    with pytest.raises(SchemaChanged):
        _parse(b"")


@pytest.mark.parametrize(
    "bad_row",
    [
        b"954298;INFZ11K01WO4;Asteria Children's Fund;20.2971;14-Oct-2026",  # 5 fields (older layout)
        b"954298;INFZ11K01WO4;-;Asteria Children's Fund;Direct Plan;Growth Option;20.2971;14-Oct-2026;extra",
    ],
)
def test_wrong_field_count_fails_closed(bad_row: bytes) -> None:
    with pytest.raises(SchemaChanged):
        _parse(_mini(AXIS_GROWTH, bad_row))


def test_regression_malformed_row_never_becomes_amc_name() -> None:
    """hidden-gems §4.4 bug 2: a malformed data row (here: delimiter lost) must not become the AMC context."""
    malformed = b"975136 INFZ11K01WP1 - Asteria Children's Fund Direct Plan IDCW Option 21.0043 14-Oct-2026"
    with pytest.raises(SchemaChanged) as exc:
        _parse(_mini(AXIS_GROWTH, malformed))
    assert "line 8" in str(exc.value)


def test_data_row_before_any_amc_fails_closed() -> None:
    content = b"\r\n".join([NAVALL_HEADER.encode(), b" ", AXIS_GROWTH]) + b"\r\n"
    with pytest.raises(SchemaChanged):
        _parse(content)


def test_amc_line_before_category_fails_closed() -> None:
    content = b"\r\n".join([NAVALL_HEADER.encode(), b" ", b"Asteria Mutual Fund", AXIS_GROWTH]) + b"\r\n"
    with pytest.raises(SchemaChanged):
        _parse(content)


# --- row-level rejections with reasons ------------------------------------------------------------


@pytest.mark.parametrize(
    ("nav", "reason"),
    [
        (b"N.A.", "NAV_NOT_AVAILABLE"),
        (b"#N/A", "NAV_NOT_AVAILABLE"),
        (b"", "NAV_NOT_AVAILABLE"),
        (b"NA", "NAV_NOT_AVAILABLE"),
        (b"-", "NAV_NOT_AVAILABLE"),
        (b"0.0000", "NAV_NON_POSITIVE"),
        (b"-20.2971", "NAV_NOT_NUMERIC"),
        (b"1e5", "NAV_NOT_NUMERIC"),
        (b"29,1207", "NAV_NOT_NUMERIC"),
        (b"NaN", "NAV_NOT_NUMERIC"),
        (b"Infinity", "NAV_NOT_NUMERIC"),
    ],
)
def test_bad_nav_rows_are_rejected_with_reason(nav: bytes, reason: str) -> None:
    bad = AXIS_GROWTH.replace(b"20.2971", nav)
    result = _parse(_mini(AXIS_GROWTH, bad))
    assert result.report.rows_seen == 2
    assert result.report.rows_ok == 1
    assert result.report.rows_rejected == 1
    rej = result.report.rejections[0]
    assert rej.reason == reason
    assert rej.line_no == 8
    assert len(rej.line_sha256) == 64
    # The rejected row is never zero-filled into an observation.
    assert len(result.observations) == 1


def test_regression_nav_is_never_float() -> None:
    """hidden-gems §4.4 bug 1. 0.1 + 0.2 style binary error must be impossible: the value equals its source text."""
    row = AXIS_GROWTH.replace(b"20.2971", b"1158.97400001")
    o = _parse(_mini(row)).observations[0]
    assert type(o.value) is Decimal
    assert str(o.value) == "1158.97400001"


@pytest.mark.parametrize(
    ("isin", "reason"),
    [
        (b"INFZ11K01WO5", "ISIN_BAD_CHECKSUM"),  # last digit altered
        (b"INFZ11K01WO", "ISIN_BAD_FORMAT"),  # 11 chars
        (b"infz11k01wo4", "ISIN_BAD_FORMAT"),  # lower case
        (b"US0378331006X", "ISIN_BAD_FORMAT"),
    ],
)
def test_bad_isin_rejects_row(isin: bytes, reason: str) -> None:
    bad = AXIS_GROWTH.replace(b"INFZ11K01WO4", isin)
    result = _parse(_mini(bad))
    assert result.report.rows_rejected == 1
    assert result.report.rejections[0].reason == reason


def test_bad_reinvest_isin_rejects_row() -> None:
    bad = b"916617;INFZ11K01WS5;INFZ11K01WQ0;Asteria Children's Fund;Direct Plan;IDCW Option;18.8401;14-Oct-2026"
    result = _parse(_mini(bad))
    assert result.report.rejections[0].reason == "ISIN_BAD_CHECKSUM"


@pytest.mark.parametrize(
    ("date_text", "reason"),
    [
        (b"14-10-2026", "BAD_DATE"),
        (b"31-Feb-2026", "BAD_DATE"),
        (b"14-oct-2026", "BAD_DATE"),
        (b"", "BAD_DATE"),
    ],
)
def test_bad_dates_rejected(date_text: bytes, reason: str) -> None:
    bad = AXIS_GROWTH.replace(b"14-Oct-2026", date_text)
    result = _parse(_mini(bad))
    assert result.report.rejections[0].reason == reason


@pytest.mark.parametrize("code", [b"", b"ABC", b"12.5", b"-1"])
def test_bad_scheme_code_rejected(code: bytes) -> None:
    bad = AXIS_GROWTH.replace(b"954298", code, 1)
    result = _parse(_mini(bad))
    assert result.report.rejections[0].reason == "BAD_SCHEME_CODE"


def test_wrong_source_id_refused(navall_bytes: bytes) -> None:
    payload = make_payload("amfi.navhistory", navall_bytes, NAVALL_URL, NAVALL_RETRIEVED)
    with pytest.raises(ValueError, match=r"amfi\.navall"):
        parse_navall(payload)
