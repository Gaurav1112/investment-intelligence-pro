"""Shared strict state machine for AMFI's `;`-delimited NAV files (NAVAll and NAV history).

Line classes, after the exact header line:
* blank (empty or whitespace only)                → separator, ignored;
* ``(Open Ended|Close Ended|Interval Fund) Schemes(…)`` → category context (resets the AMC);
* contains ``;``                                  → data row; exactly 8 fields or the file fails closed;
* anything else                                   → AMC context line, *unless* it looks like a data row that lost its
  delimiters (ISIN, DD-Mon-YYYY date or leading scheme code), which fails closed. This is the regression for the
  hidden-gems bug where a malformed row silently became the AMC name for every following row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from iip.data.models import (
    IngestionReport,
    Observation,
    ParseResult,
    QualityStatus,
    RawPayload,
    RowRejection,
    SchemaChanged,
    SchemeRecord,
    sha256_hex,
)
from iip.data.validators import validate_isin

N_FIELDS = 8
UNIT = "INR_per_unit"
CURRENCY = "INR"
CONVENTION = "NAV_PER_UNIT_AS_PUBLISHED"

_MONTHS = {
    m: i
    for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)
}
_DATE_RE = re.compile(r"([0-9]{2})-([A-Z][a-z]{2})-([0-9]{4})")
_NAV_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_CODE_RE = re.compile(r"[0-9]{1,9}")
_CATEGORY_RE = re.compile(r"(Open Ended|Close Ended|Interval Fund) Schemes?\s*\(\s*(.*?)\s*\)")
_DATAISH_RE = re.compile(r"\bIN[A-Z0-9]{9}[0-9]\b|\b[0-9]{2}-[A-Za-z]{3}-[0-9]{4}\b|^[0-9]{5,}\b")
_NA_MARKERS = frozenset({"", "-", "n.a.", "n.a", "na", "n/a", "#n/a"})
MAX_CONTEXT_LINE = 300


def decode_lines(content: bytes) -> list[tuple[int, str]]:
    """Strict UTF-8 (optional BOM). Splits on LF only — never on U+2028 etc. — and strips CR/trailing whitespace."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SchemaChanged(f"payload is not valid UTF-8 (byte {exc.start})") from None
    return [(i, line.rstrip(" \t\r")) for i, line in enumerate(text.split("\n"), start=1)]


def parse_amfi_date(text: str) -> date | None:
    """DD-Mon-YYYY with an English month abbreviation (locale independent). ``None`` if invalid."""
    m = _DATE_RE.fullmatch(text)
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def parse_nav(text: str) -> tuple[Decimal | None, str | None]:
    """Parse a published NAV string to Decimal with its original precision. Never via float."""
    if text.lower() in _NA_MARKERS:
        return None, "NAV_NOT_AVAILABLE"
    if not _NAV_RE.fullmatch(text):
        return None, "NAV_NOT_NUMERIC"
    value = Decimal(text)
    if value <= 0:
        return None, "NAV_NON_POSITIVE"
    return value, None


def parse_scheme_code(text: str) -> int | None:
    return int(text) if _CODE_RE.fullmatch(text) else None


def parse_isin_field(text: str) -> tuple[str | None, str | None]:
    """``-`` or empty means absent. Otherwise the ISIN must pass format and check-digit validation."""
    if text in ("", "-"):
        return None, None
    reason = validate_isin(text)
    return (None, reason) if reason else (text, None)


def parse_category(line: str) -> tuple[str, str] | None:
    m = _CATEGORY_RE.fullmatch(line)
    if not m:
        return None
    return f"{m.group(1)} Schemes", m.group(2)


@dataclass(frozen=True, slots=True)
class Layout:
    source_id: str
    header: str
    code: int
    isin_growth: int
    isin_reinvest: int
    name: int
    plan: int
    option: int
    nav: int
    date: int
    name_is_nav_name: bool


def parse_semicolon_file(payload: RawPayload, layout: Layout, quality: QualityStatus) -> ParseResult:
    if payload.source_id != layout.source_id:
        raise ValueError(f"payload is for {payload.source_id!r}; this parser handles {layout.source_id!r}")
    lines = decode_lines(payload.content)
    if not lines or lines[0][1] != layout.header:
        raise SchemaChanged(f"{layout.source_id}: header line does not match the expected layout")

    scheme_type: str | None = None
    category: str | None = None
    amc: str | None = None
    records: list[SchemeRecord] = []
    observations: list[Observation] = []
    rejections: list[RowRejection] = []
    warnings: list[str] = []
    rows_seen = 0

    for line_no, line in lines[1:]:
        if line.strip() == "":
            continue
        if ";" in line:
            fields = [f.strip() for f in line.split(";")]
            if len(fields) != N_FIELDS:
                raise SchemaChanged(f"line {line_no}: expected {N_FIELDS} fields, found {len(fields)}")
            if category is None or amc is None:
                raise SchemaChanged(f"line {line_no}: data row before category/AMC context")
            rows_seen += 1
            parsed = _parse_row(fields, layout, line_no, line, scheme_type=scheme_type, category=category, amc=amc)
            if isinstance(parsed, RowRejection):
                rejections.append(parsed)
                continue
            record, nav_date, value = parsed
            records.append(record)
            observations.append(
                Observation(
                    source_id=layout.source_id,
                    source_url=payload.final_url,
                    retrieved_at=payload.retrieved_at,
                    observation_date=nav_date,
                    publication_time=payload.last_modified,
                    entity_key=str(record.scheme_code),
                    value=value,
                    unit=UNIT,
                    currency=CURRENCY,
                    quality_status=quality,
                    convention=CONVENTION,
                    raw_sha256=payload.sha256,
                )
            )
            continue
        cat = parse_category(line)
        if cat is not None:
            scheme_type, category = cat
            amc = None
            continue
        if _DATAISH_RE.search(line) or len(line) > MAX_CONTEXT_LINE:
            raise SchemaChanged(f"line {line_no}: looks like a malformed data row; refusing to treat it as an AMC")
        if category is None:
            raise SchemaChanged(f"line {line_no}: AMC line before any category line")
        amc = line.strip()
        if not amc.endswith("Mutual Fund"):
            warnings.append(f"line {line_no}: AMC_NAME_UNUSUAL")

    report = IngestionReport(
        source_id=layout.source_id,
        raw_sha256=payload.sha256,
        rows_seen=rows_seen,
        rows_ok=len(observations),
        rows_rejected=len(rejections),
        rejections=tuple(rejections),
        warnings=tuple(warnings),
    )
    return ParseResult(tuple(records), tuple(observations), report)


def _reject(line_no: int, line: str, reason: str, detail: str) -> RowRejection:
    return RowRejection(line_no, reason, detail, sha256_hex(line.encode("utf-8")))


def _parse_row(
    f: list[str], layout: Layout, line_no: int, line: str, *, scheme_type: str | None, category: str, amc: str
) -> RowRejection | tuple[SchemeRecord, date, Decimal]:
    code = parse_scheme_code(f[layout.code])
    if code is None:
        return _reject(line_no, line, "BAD_SCHEME_CODE", "scheme code is not a positive integer")
    isin_g, reason = parse_isin_field(f[layout.isin_growth])
    if reason:
        return _reject(line_no, line, reason, "ISIN Div Payout/Growth column")
    isin_r, reason = parse_isin_field(f[layout.isin_reinvest])
    if reason:
        return _reject(line_no, line, reason, "ISIN Div Reinvestment column")
    value, reason = parse_nav(f[layout.nav])
    if value is None:
        return _reject(line_no, line, reason or "NAV_NOT_NUMERIC", "Net Asset Value column")
    nav_date = parse_amfi_date(f[layout.date])
    if nav_date is None:
        return _reject(line_no, line, "BAD_DATE", "expected DD-Mon-YYYY")
    name = f[layout.name]
    if not name:
        return _reject(line_no, line, "BAD_NAME", "empty scheme name")
    record = SchemeRecord(
        scheme_code=code,
        scheme_name=name,
        amc=amc,
        scheme_type=scheme_type,
        category=category,
        plan=f[layout.plan] or None,
        option=f[layout.option] or None,
        isin_growth=isin_g,
        isin_reinvest=isin_r,
        nav_name=name if layout.name_is_nav_name else None,
    )
    return record, nav_date, value
