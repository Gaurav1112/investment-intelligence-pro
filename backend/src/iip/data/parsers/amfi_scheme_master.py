"""Parser for the AMFI scheme master CSV (source-registry.md §2.3).

Quirks handled:
* the two ISIN columns are glued with no delimiter (``…Growth`` + ``ISIN Div Reinvestment`` share one header cell);
  the value is split on the ISIN pattern and 13/20-character (or otherwise malformed) values are flagged
  ``ISIN_MALFORMED`` while the code → name mapping is kept;
* ``Closure Date`` has a leading space in the header;
* ``Scheme Minimum Amount`` is free text and is kept as text.
Metadata only: no observations are produced.
"""

from __future__ import annotations

import csv
import io
import re

from iip.data.models import (
    IngestionReport,
    ParseResult,
    RawPayload,
    RowRejection,
    SchemaChanged,
    SchemeRecord,
    sha256_hex,
)
from iip.data.parsers._amfi import parse_amfi_date, parse_scheme_code
from iip.data.validators import validate_isin

SCHEME_MASTER_HEADER = (
    "AMC,Code,Scheme Name,Scheme Type,Scheme Category,Scheme NAV Name,Scheme Minimum Amount,Launch Date,"
    " Closure Date,ISIN Div Payout/ ISIN GrowthISIN Div Reinvestment"
)
PARSER_VERSION = "amfi.schememaster/1"
SOURCE_ID = "amfi.schememaster"
_N = 10
_ISIN = r"[A-Z]{2}[A-Z0-9]{9}[0-9]"
_GLUED_RE = re.compile(rf"({_ISIN})({_ISIN})?")


def split_glued_isins(text: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Split the glued ISIN cell into (growth/payout, reinvestment, flags).

    Only exact 12- or 24-character ISIN matches are split. Anything else is ``ISIN_MALFORMED`` with no ISINs
    (never guessed). An ISIN failing its check digit is dropped with ``ISIN_BAD_CHECKSUM``.
    """
    text = text.strip()
    if text == "":
        return None, None, ()
    m = _GLUED_RE.fullmatch(text)
    if not m:
        return None, None, ("ISIN_MALFORMED",)
    flags: list[str] = []
    out: list[str | None] = []
    for part in (m.group(1), m.group(2)):
        if part is None:
            out.append(None)
        elif validate_isin(part) is None:
            out.append(part)
        else:
            out.append(None)
            if "ISIN_BAD_CHECKSUM" not in flags:
                flags.append("ISIN_BAD_CHECKSUM")
    return out[0], out[1], tuple(flags)


def parse_scheme_master(payload: RawPayload) -> ParseResult:
    if payload.source_id != SOURCE_ID:
        raise ValueError(f"payload is for {payload.source_id!r}; this parser handles {SOURCE_ID!r}")
    try:
        text = payload.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SchemaChanged(f"payload is not valid UTF-8 (byte {exc.start})") from None
    if "\x00" in text:
        raise SchemaChanged("NUL byte in CSV payload")
    header, _, body = text.partition("\n")
    if header.rstrip("\r") != SCHEME_MASTER_HEADER:
        raise SchemaChanged("scheme master header does not match the expected layout")

    reader = csv.reader(io.StringIO(body, newline=""), strict=True)
    records: list[SchemeRecord] = []
    rejections: list[RowRejection] = []
    warnings: list[str] = []
    rows_seen = 0
    try:
        for idx, raw in enumerate(reader):
            line_no = reader.line_num + 1
            if not raw or all(c.strip() == "" for c in raw):
                continue
            if len(raw) != _N:
                raise SchemaChanged(f"line {line_no}: expected {_N} columns, found {len(raw)}")
            rows_seen += 1
            f = [c.strip() for c in raw]
            code = parse_scheme_code(f[1])
            if code is None or not f[2]:
                digest = sha256_hex(",".join(raw).encode("utf-8"))
                reason = "BAD_SCHEME_CODE" if code is None else "BAD_NAME"
                rejections.append(RowRejection(line_no, reason, f"row {idx + 1}", digest))
                continue
            isin_g, isin_r, flags = split_glued_isins(f[9])
            flag_list = list(flags)
            if not f[9]:
                flag_list.append("ISIN_MISSING")
            launch = parse_amfi_date(f[7]) if f[7] else None
            if f[7] and launch is None:
                flag_list.append("LAUNCH_DATE_UNPARSED")
            closure = parse_amfi_date(f[8]) if f[8] else None
            if f[8] and closure is None:
                flag_list.append("CLOSURE_DATE_UNPARSED")
            for fl in flags:
                warnings.append(f"line {line_no}: {fl}")
            records.append(
                SchemeRecord(
                    scheme_code=code,
                    scheme_name=f[2],
                    amc=f[0] or None,
                    scheme_type=f[3] or None,
                    category=f[4] or None,
                    nav_name=f[5] or None,
                    min_amount_text=f[6] or None,
                    launch_date=launch,
                    closure_date=closure,
                    isin_growth=isin_g,
                    isin_reinvest=isin_r,
                    flags=tuple(flag_list),
                )
            )
    except csv.Error as exc:
        raise SchemaChanged(f"CSV structure error: {exc}") from None

    report = IngestionReport(
        source_id=SOURCE_ID,
        raw_sha256=payload.sha256,
        rows_seen=rows_seen,
        rows_ok=len(records),
        rows_rejected=len(rejections),
        rejections=tuple(rejections),
        warnings=tuple(warnings),
    )
    return ParseResult(tuple(records), (), report)
