"""Scheme master CSV parser. Fixture: docs/data/probes/amfi_schemedata_mf0_head_20261015T054336Z.csv.

Quirk (source-registry §2.3): the two ISIN columns are glued together with no delimiter.
"""

from __future__ import annotations

from datetime import date

import pytest

from iip.data.models import SchemaChanged
from iip.data.parsers.amfi_scheme_master import SCHEME_MASTER_HEADER, parse_scheme_master, split_glued_isins
from tests.data.conftest import SCHEMEDATA_RETRIEVED, SCHEMEDATA_URL, make_payload


def _parse(content: bytes):
    payload = make_payload("amfi.schememaster", content, SCHEMEDATA_URL, SCHEMEDATA_RETRIEVED, content_type="text/csv")
    return parse_scheme_master(payload)


ROW = (
    b"Aditya Birla Sun Life AMC Limited,100034,Aditya Birla Sun Life Large & Mid Cap Fund,Open Ended,"
    b"Equity Scheme - Large & Mid Cap Fund,Aditya Birla Sun Life Large & Mid Cap Fund -Regular - IDCW,5000,"
    b"24-Feb-1995,24-Feb-1995,INFZ17K01156INFZ17K01CE4"
)


def _mini(*rows: bytes) -> bytes:
    return b"\r\n".join([SCHEME_MASTER_HEADER.encode(), *rows]) + b"\r\n"


def test_fixture_parses(schemedata_bytes: bytes) -> None:
    result = _parse(schemedata_bytes)
    assert result.report.rows_seen == 11
    assert result.report.rows_ok == 11
    assert result.observations == ()


def test_glued_isins_split(schemedata_bytes: bytes) -> None:
    recs = {r.scheme_code: r for r in _parse(schemedata_bytes).records}
    r = recs[100034]
    assert r.isin_growth == "INFZ17K01156"
    assert r.isin_reinvest == "INFZ17K01CE4"
    assert r.amc == "Aditya Birla Sun Life AMC Limited"
    assert r.scheme_type == "Open Ended"
    assert r.category == "Equity Scheme - Large & Mid Cap Fund"
    assert r.nav_name == "Aditya Birla Sun Life Large & Mid Cap Fund -Regular - IDCW"
    assert r.min_amount_text == "5000"
    assert r.launch_date == date(1995, 2, 24)
    assert r.closure_date == date(1995, 2, 24)  # leading-space header column handled
    assert r.flags == ()
    single = recs[100033]
    assert single.isin_growth == "INFZ17K01164" and single.isin_reinvest is None
    empty = recs[100039]
    assert empty.isin_growth is None and empty.isin_reinvest is None
    assert "ISIN_MISSING" in empty.flags


@pytest.mark.parametrize(
    ("glued", "expected"),
    [
        ("", (None, None, ())),
        ("INFZ17K01164", ("INFZ17K01164", None, ())),
        ("INFZ17K01156INFZ17K01CE4", ("INFZ17K01156", "INFZ17K01CE4", ())),
        ("INFZ17K01164X", (None, None, ("ISIN_MALFORMED",))),  # 13 chars
        ("INFZ17K01164INF209K0", (None, None, ("ISIN_MALFORMED",))),  # 20 chars
        ("INF209K01166", (None, None, ("ISIN_BAD_CHECKSUM",))),
        ("INFZ17K01156INF209K01CE6", ("INFZ17K01156", None, ("ISIN_BAD_CHECKSUM",))),
    ],
)
def test_split_glued_isins(glued: str, expected: tuple[str | None, str | None, tuple[str, ...]]) -> None:
    assert split_glued_isins(glued) == expected


def test_malformed_isin_keeps_code_name_mapping() -> None:
    bad = ROW.replace(b"INFZ17K01156INFZ17K01CE4", b"INFZ17K01156INF2")
    result = _parse(_mini(bad))
    assert result.report.rows_ok == 1
    rec = result.records[0]
    assert rec.scheme_code == 100034
    assert rec.scheme_name == "Aditya Birla Sun Life Large & Mid Cap Fund"
    assert rec.isin_growth is None
    assert "ISIN_MALFORMED" in rec.flags
    assert any("ISIN_MALFORMED" in w for w in result.report.warnings)


def test_quoted_comma_in_name() -> None:
    row = ROW.replace(b"Aditya Birla Sun Life Large & Mid Cap Fund -Regular - IDCW", b'"Fund, with comma - IDCW"')
    rec = _parse(_mini(row)).records[0]
    assert rec.nav_name == "Fund, with comma - IDCW"


def test_header_mismatch_fails_closed() -> None:
    content = _mini(ROW).replace(b"GrowthISIN Div", b"Growth,ISIN Div")
    with pytest.raises(SchemaChanged):
        _parse(content)


def test_wrong_column_count_fails_closed() -> None:
    with pytest.raises(SchemaChanged):
        _parse(_mini(ROW + b",extra"))


def test_bad_code_rejected_with_reason() -> None:
    result = _parse(_mini(ROW.replace(b",100034,", b",10OO34,")))
    assert result.report.rows_rejected == 1
    assert result.report.rejections[0].reason == "BAD_SCHEME_CODE"


def test_bad_launch_date_flagged_not_guessed() -> None:
    rec = _parse(_mini(ROW.replace(b"24-Feb-1995,24-Feb-1995", b"1995-02-24,"))).records[0]
    assert rec.launch_date is None and rec.closure_date is None
    assert "LAUNCH_DATE_UNPARSED" in rec.flags
    assert "CLOSURE_DATE_UNPARSED" not in rec.flags  # blank closure date is just absent
