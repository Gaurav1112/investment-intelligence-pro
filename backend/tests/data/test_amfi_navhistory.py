"""NAV history parser tests. Fixture: excerpt of
docs/data/probes/amfi_navhistory_mf9_tp1_13to14Oct2026_20261015T053448Z.txt (column order differs from NAVAll)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from iip.data.models import QualityStatus, SchemaChanged
from iip.data.parsers.amfi_navall import NAVALL_HEADER
from iip.data.parsers.amfi_navhistory import NAVHISTORY_HEADER, parse_navhistory
from tests.data.conftest import NAVHISTORY_RETRIEVED, NAVHISTORY_URL, make_payload

ROW = (
    b"119018;HDFC Large Cap Fund - Growth Option - Direct Plan;Direct Plan;Growth Option;"
    b"INFZ12K01YV3;;1385.402;14-Oct-2026"
)


def _parse(content: bytes):
    payload = make_payload("amfi.navhistory", content, NAVHISTORY_URL, NAVHISTORY_RETRIEVED)
    return parse_navhistory(payload, quality=QualityStatus.FIXTURE)


def _mini(*rows: bytes) -> bytes:
    lines = [
        NAVHISTORY_HEADER.encode(),
        b"",
        b"Open Ended Schemes ( Equity Scheme - Large Cap Fund )",
        b"",
        b"",
        b"HDFC Mutual Fund",
        *rows,
    ]
    return b"\r\n".join(lines) + b"\r\n"


def test_fixture_parses(navhistory_bytes: bytes) -> None:
    result = _parse(navhistory_bytes)
    assert result.report.rows_seen == 16
    assert result.report.rows_ok == 16
    assert result.report.rows_rejected == 0


def test_column_order_is_history_layout(navhistory_bytes: bytes) -> None:
    result = _parse(navhistory_bytes)
    pairs = [(o, r) for o, r in zip(result.observations, result.records, strict=True) if r.scheme_code == 119018]
    assert [(o.observation_date, o.value) for o, _ in pairs] == [
        (date(2026, 10, 13), Decimal("1393.087")),
        (date(2026, 10, 14), Decimal("1385.402")),  # matches NAVAll for 119018 on 14-Oct (source-registry §2.2)
    ]
    rec = pairs[0][1]
    assert rec.nav_name == "HDFC Large Cap Fund - Growth Option - Direct Plan"
    assert rec.plan == "Direct Plan"
    assert rec.option == "Growth Option"
    assert rec.isin_growth == "INFZ12K01YV3"
    assert rec.isin_reinvest is None  # empty field, not '-'
    assert str(pairs[1][0].value) == "1385.402"  # 3 dp kept exactly
    assert rec.amc == "HDFC Mutual Fund"
    assert rec.scheme_type == "Open Ended Schemes"
    assert rec.category == "Equity Scheme - Large Cap Fund"  # inner bracket spaces normalised


def test_reinvest_isin_column(navhistory_bytes: bytes) -> None:
    recs = [r for r in _parse(navhistory_bytes).records if r.scheme_code == 149365]
    assert recs[0].isin_growth == "INFZ12KC1BW1"
    assert recs[0].isin_reinvest == "INFZ12KC1BX9"


def test_provenance(navhistory_bytes: bytes) -> None:
    o = _parse(navhistory_bytes).observations[0]
    assert o.source_id == "amfi.navhistory"
    assert o.source_url == NAVHISTORY_URL
    assert o.publication_time is None  # unknown → null, never invented
    assert o.unit == "INR_per_unit" and o.currency == "INR"


def test_navall_header_is_refused_by_history_parser() -> None:
    content = _mini(ROW).replace(NAVHISTORY_HEADER.encode(), NAVALL_HEADER.encode())
    with pytest.raises(SchemaChanged):
        _parse(content)


def test_navall_layout_row_under_history_header_is_rejected_not_misread() -> None:
    """A NAVAll-ordered row (ISIN in column 2) under the history header must not be silently remapped."""
    navall_order = b"119018;INFZ12K01YV3;-;HDFC Large Cap Fund;Direct Plan;Growth Option;1385.402;14-Oct-2026"
    result = _parse(_mini(navall_order))
    assert result.report.rows_rejected == 1
    assert result.report.rejections[0].reason == "ISIN_BAD_FORMAT"  # 'Growth Option' in the ISIN column


def test_na_nav_rejected() -> None:
    result = _parse(_mini(ROW, ROW.replace(b"1385.402", b"N.A.").replace(b"14-Oct", b"13-Oct")))
    assert result.report.rows_ok == 1
    assert result.report.rejections[0].reason == "NAV_NOT_AVAILABLE"


def test_wrong_field_count_fails_closed() -> None:
    with pytest.raises(SchemaChanged):
        _parse(_mini(ROW + b";x"))


def test_malformed_row_never_becomes_amc() -> None:
    with pytest.raises(SchemaChanged):
        _parse(_mini(ROW.replace(b";", b" ")))
