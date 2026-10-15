"""Strict parser for the AMFI NAV history report (source-registry.md §2.2).

The column order differs from NAVAll: ``Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;
ISIN Div Reinvestment;Net Asset Value;Date``. Empty ISIN is an empty field; group headers have spaces inside the
brackets. Keyed on its own exact header, so a NAVAll file is refused here and vice versa.
"""

from __future__ import annotations

from iip.data.models import ParseResult, QualityStatus, RawPayload
from iip.data.parsers._amfi import Layout, parse_semicolon_file

NAVHISTORY_HEADER = (
    "Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date"
)
PARSER_VERSION = "amfi.navhistory/1"

_LAYOUT = Layout(
    source_id="amfi.navhistory",
    header=NAVHISTORY_HEADER,
    code=0,
    name=1,
    plan=2,
    option=3,
    isin_growth=4,
    isin_reinvest=5,
    nav=6,
    date=7,
    name_is_nav_name=True,
)


def parse_navhistory(payload: RawPayload, *, quality: QualityStatus = QualityStatus.OK) -> ParseResult:
    """Parse a NAV history payload. One observation per (scheme, date) row, in file order."""
    return parse_semicolon_file(payload, _LAYOUT, quality)
