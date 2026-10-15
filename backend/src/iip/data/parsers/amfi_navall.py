"""Strict parser for AMFI ``NAVAll.txt`` (source-registry.md §2.1).

Layout (8 fields): ``Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;
Net Asset Value;Date``. Empty ISIN is ``-``. NAV dates may be years old (dormant plans) and are never coerced.
A changed header, a row with ≠ 8 fields, or a delimiter-less row that looks like data fails closed (SchemaChanged).
"""

from __future__ import annotations

from iip.data.models import ParseResult, QualityStatus, RawPayload
from iip.data.parsers._amfi import Layout, parse_semicolon_file

NAVALL_HEADER = (
    "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date"
)
PARSER_VERSION = "amfi.navall/1"

_LAYOUT = Layout(
    source_id="amfi.navall",
    header=NAVALL_HEADER,
    code=0,
    isin_growth=1,
    isin_reinvest=2,
    name=3,
    plan=4,
    option=5,
    nav=6,
    date=7,
    name_is_nav_name=False,
)


def parse_navall(payload: RawPayload, *, quality: QualityStatus = QualityStatus.OK) -> ParseResult:
    """Parse a NAVAll payload. ``quality`` is ``OK`` for live data and ``FIXTURE`` for test fixtures."""
    return parse_semicolon_file(payload, _LAYOUT, quality)
