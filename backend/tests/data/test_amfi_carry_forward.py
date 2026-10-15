"""Regression: real NAVAll (2026-10-15) has category headings followed by rows of the PREVIOUS fund house.

Structure copied from the live file (lines 945–968); names/codes here are synthetic.
"""

from datetime import UTC, datetime

import pytest

from iip.data.models import SchemaChanged
from iip.data.parsers.amfi_navall import parse_navall
from tests.data.conftest import make_payload

HEADER = "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date"
URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def body(second_section_row_name: str) -> bytes:
    lines = [
        HEADER, " ",
        "Open Ended Schemes(Debt Scheme - Low Duration Fund)", " ",
        "Acme Mutual Fund", " ",
        "900101;INF000A01AB9;-;Acme Low Duration Fund;Direct Plan;Growth;12.3456;14-Oct-2026",
        " ",
        "Open Ended Schemes(Debt Scheme - Medium Duration Fund)",
        f"900102;INF000A01AC7;-;{second_section_row_name};Direct Plan;Growth;23.4567;14-Oct-2026",
    ]  # fmt: skip
    return ("\r\n".join(lines) + "\r\n").encode()


def test_rows_continue_previous_fund_house_when_brand_matches() -> None:
    res = parse_navall(make_payload("amfi.navall", body("Acme Medium Duration Fund"), URL, NOW))
    assert res.report.rows_ok == 2
    assert res.records[1].amc == "Acme Mutual Fund"
    assert res.records[1].category is not None and "Medium Duration" in res.records[1].category
    assert any("AMC_CARRIED_FORWARD" in w for w in res.report.warnings)


def test_unrelated_scheme_without_amc_line_still_fails_closed() -> None:
    with pytest.raises(SchemaChanged):
        parse_navall(make_payload("amfi.navall", body("Other House Medium Duration Fund"), URL, NOW))
