"""CSV export with formula-injection neutralisation (threat-model C-07 export rule, SEC-40).

* Every *text* cell whose first character is ``= + - @``, TAB, CR, or a full-width ``＝ ＋ － ＠`` is prefixed
  with ``'``.
* Numbers are written as canonical plain decimals (``Decimal`` → ``format(d, "f")``) and are never prefixed, so
  ``-1250.50`` stays numeric. Floats are refused.
* Every field is quoted (``csv.QUOTE_ALL``); output is UTF-8 with a BOM so Excel opens it correctly.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

TRIGGERS = frozenset("=+-@\t\r＝＋－＠")
UTF8_BOM = b"\xef\xbb\xbf"

Cell = str | Decimal | int | date | None


def neutralise_cell(text: str) -> str:
    """Prefix ``'`` when a text cell could be interpreted as a formula by a spreadsheet."""
    return "'" + text if text and text[0] in TRIGGERS else text


def format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise TypeError("bool cells are not exported; map them to text explicitly")
    if isinstance(value, str):
        return neutralise_cell(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"non-finite Decimal cannot be exported: {value}")
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not exported")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported export cell type {type(value).__name__}; floats are forbidden")


def export_holdings_csv(rows: Iterable[Mapping[str, object]], columns: Sequence[str]) -> bytes:
    """Serialise rows to escaped CSV bytes (UTF-8 + BOM, all fields quoted, CRLF)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([neutralise_cell(c) for c in columns])
    for row in rows:
        writer.writerow([format_cell(row.get(c)) for c in columns])
    return UTF8_BOM + buf.getvalue().encode("utf-8")
