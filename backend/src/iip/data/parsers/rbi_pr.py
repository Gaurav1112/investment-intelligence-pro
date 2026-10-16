"""Deterministic parsers for RBI's press-release RSS feed and the T-bill cut-off release (audit-automation.md §3.2).

Pure functions over bytes/text: no clock, no IO, no randomness. Nothing here keeps or returns HTML; only extracted
figures and a plain-text citation leave this module (RBI disclaimer: no caching, no deep links).

* ``parse_feed``: RSS 2.0 via ``defusedxml`` (no DTD, no entities), UTF-8 with or without BOM. ``pubDate`` is IST
  wall time without a zone in the live feed (probe 2026-10-16); an explicit zone is honoured.
* ``select_tbill_cutoffs``: items whose title is exactly ``TBILL_CUTOFF_TITLE`` and whose link is an https
  ``www.rbi.org.in`` press-release page with a numeric ``prid``.
* ``parse_cutoff_text``: exactly three ``price (YTM: y%)`` pairs after the ``T-Bill 91-Day 182-Day 364-Day``
  header, in that order. Each yield is recomputed as ``(100 − P) / P × 365 / days`` (Decimal, 28 digits, rounded
  half-up to the published 4 dp). **Any mismatch abstains**: the source is never silently trusted, and the
  recomputed value is never substituted.

Dates: the release text carries ``Date : Mon DD, YYYY`` (the release date; probe 2026-10-16). No "auction held on"
wording was found in the live release, so ``auction_date`` is ``None`` unless such wording is present; the
observation date is the release date, recorded with ``date_basis``. A release date that disagrees with the feed's
``pubDate`` abstains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from iip.data.models import DataError, SchemaChanged

IST = timezone(timedelta(hours=5, minutes=30), "IST")
TBILL_CUTOFF_TITLE = "91-Day, 182-Day and 364-Day T-Bill Auction Result: Cut-off"
TBILL_TENORS = (91, 182, 364)
RBI_HOST = "www.rbi.org.in"
PRESS_RELEASE_PATH = "/scripts/bs_pressreleasedisplay.aspx"  # compared lower-case
CONVENTION = "RBI_TBILL_IMPLICIT_YIELD_AS_PUBLISHED"
SELF_CHECK_FORMULA = "(100 - P) / P * 365 / tenor_days, rounded half-up to the published 4 dp"
MAX_FEED_ITEMS = 200
MAX_TEXT_CHARS = 2_000_000

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}  # fmt: skip
_PUBDATE_RE = re.compile(
    r"(?:[A-Za-z]{3},\s*)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\s+(GMT|UTC|IST|[+-]\d{4}))?"
)
_HEADER_RE = re.compile(r"T-Bill\s+91-Day\s+182-Day\s+364-Day")
_PAIR_RE = re.compile(r"(?:₹\s*)?(\d{2,3}\.\d{2,4})\s*\(\s*YTM\s*:\s*(\d{1,2}\.\d{4})\s*%\s*\)")
_RELEASE_DATE_RE = re.compile(r"Date\s*:\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})")
_AUCTION_DATE_RE = re.compile(
    r"auction\s+(?:was\s+)?(?:held|conducted)\s+on\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", re.IGNORECASE
)
_PR_REF_RE = re.compile(r"Press Release\s*:\s*(\d{4}-\d{4}/\d{1,6})")
_ACCESS_DENIED_MARKERS = ("Unauthorised Access", "Unauthorized Access")


class TbillAbstain(DataError):
    """The release cannot be used. Nothing from it may be stored. ``code`` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class FeedItem:
    title: str
    link: str
    pub_date: datetime | None  # aware; None when absent or unparseable
    description: str  # HTML fragment as published; parsed in memory, never stored


@dataclass(frozen=True, slots=True)
class TbillYield:
    tenor_days: int
    price: Decimal  # cut-off price per ₹100 face value, as published
    yield_pct: Decimal  # implicit yield at cut-off price, percent, as published (4 dp)
    yield_fraction: Decimal  # yield_pct / 100, exact
    series_id: str


@dataclass(frozen=True, slots=True)
class TbillCutoffRelease:
    prid: int
    release_date: date
    date_basis: Literal["release_text", "feed_pubdate"]
    auction_date: date | None  # only when the text states it; never inferred
    press_release_ref: str | None  # e.g. "2026-2027/1325" when the text carries it
    yields: tuple[TbillYield, ...]
    citation_text: str  # plain text, never a hyperlink (RBI disclaimer)
    convention: str = CONVENTION
    self_check: str = SELF_CHECK_FORMULA


def series_id_for(tenor_days: int) -> str:
    """``riskfree:tbill91`` is the existing risk-free series (services.inputs.RISK_FREE_SERIES); siblings follow it."""
    return f"riskfree:tbill{tenor_days}"


# --- feed --------------------------------------------------------------------------------------------------------


def _child_text(item: Element, tag: str) -> str:
    el = item.find(tag)
    return "" if el is None or el.text is None else el.text.strip()


def parse_pub_date(text: str) -> datetime | None:
    """RFC-822-like ``pubDate``. No zone → IST wall time (how RBI's feed publishes it). ``None`` if unparseable."""
    m = _PUBDATE_RE.fullmatch(text.strip())
    if m is None:
        return None
    day, mon, year, hh, mm, ss, zone = m.groups()
    month = _MONTHS.get(mon.lower())
    if month is None:
        return None
    if zone in (None, "IST"):
        tz: timezone = IST
    elif zone in ("GMT", "UTC"):
        tz = UTC
    else:
        sign = 1 if zone[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5])))
    try:
        return datetime(int(year), month, int(day), int(hh), int(mm), int(ss or 0), tzinfo=tz)
    except ValueError:
        return None


def parse_feed(content: bytes) -> tuple[FeedItem, ...]:
    """Parse the RSS 2.0 feed. Refuses DTDs, entity declarations, external references and non-RSS documents."""
    try:
        root = fromstring(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, DefusedXmlException, ValueError) as exc:
        raise SchemaChanged(f"RBI feed is not acceptable XML: {exc.__class__.__name__}") from None
    if root.tag != "rss":
        raise SchemaChanged(f"RBI feed root is <{root.tag}>, expected <rss>")
    channel = root.find("channel")
    if channel is None:
        raise SchemaChanged("RBI feed has no <channel>")
    raw_items = channel.findall("item")
    if len(raw_items) > MAX_FEED_ITEMS:
        raise SchemaChanged(f"RBI feed has {len(raw_items)} items (> {MAX_FEED_ITEMS})")
    items = []
    for it in raw_items:
        items.append(
            FeedItem(
                title=" ".join(_child_text(it, "title").split()),
                link=_child_text(it, "link"),
                pub_date=parse_pub_date(_child_text(it, "pubDate")),
                description=_child_text(it, "description"),
            )
        )
    return tuple(items)


def press_release_id(link: str) -> int | None:
    """The numeric ``prid`` of an https www.rbi.org.in press-release link, else ``None``."""
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.hostname != RBI_HOST or port not in (None, 443) or parts.username:
        return None
    if parts.path.lower() != PRESS_RELEASE_PATH:
        return None
    values = parse_qs(parts.query).get("prid", [])
    if len(values) != 1 or not re.fullmatch(r"[1-9]\d{0,7}", values[0]):
        return None
    return int(values[0])


def select_tbill_cutoffs(items: tuple[FeedItem, ...]) -> tuple[tuple[FeedItem, int], ...]:
    """Cut-off result items (exact title, RBI host, numeric prid), de-duplicated by prid, in feed order."""
    seen: set[int] = set()
    out = []
    for item in items:
        if item.title != TBILL_CUTOFF_TITLE:
            continue
        prid = press_release_id(item.link)
        if prid is None or prid in seen:
            continue
        seen.add(prid)
        out.append((item, prid))
    return tuple(out)


# --- HTML to text ------------------------------------------------------------------------------------------------


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_text(fragment: str) -> str:
    """Visible text of an HTML fragment, entities decoded, whitespace (incl. NBSP) collapsed to single spaces."""
    if len(fragment) > MAX_TEXT_CHARS:
        raise SchemaChanged("HTML text exceeds the size limit")
    collector = _TextCollector()
    collector.feed(fragment)
    collector.close()
    return " ".join("".join(collector.parts).replace("\xa0", " ").split())


def is_access_denied(text: str) -> bool:
    """RBI's block page ("Unauthorised Access"): stop, never retry with another identity."""
    return any(marker in text for marker in _ACCESS_DENIED_MARKERS)


# --- cut-off release ---------------------------------------------------------------------------------------------


def _date_from(mon: str, day: str, year: str) -> date | None:
    month = _MONTHS.get(mon.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def implied_yield_pct(price: Decimal, tenor_days: int, places: int = 4) -> Decimal:
    """``(100 − P) / P × 365 / tenor_days`` in percent, 28 significant digits, rounded half-up to ``places``."""
    with localcontext() as ctx:
        ctx.prec = 28
        raw = (Decimal(100) - price) / price * Decimal(365) / Decimal(tenor_days) * Decimal(100)
        return raw.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _release_segment(text: str) -> str:
    """Narrow a full page's text to the release body: from the last ``Date :`` before the table header to the end
    of the ``Press Release: …`` reference after it. A feed description is usually already the body."""
    header = _HEADER_RE.search(text)
    if header is None:
        return text
    starts = [m.start() for m in _RELEASE_DATE_RE.finditer(text, 0, header.start())]
    start = starts[-1] if starts else max(0, header.start() - 400)
    ref = _PR_REF_RE.search(text, header.end())
    end = ref.end() if ref is not None else min(len(text), header.end() + 2000)
    return text[start:end]


def parse_cutoff_text(text: str, *, prid: int, pub_date: datetime | None) -> TbillCutoffRelease:
    """Extract and self-check the three cut-off yields from the release text, or raise ``TbillAbstain``."""
    if is_access_denied(text):
        raise TbillAbstain("ACCESS_DENIED", "RBI answered with its access-denied page; stopping")
    body = _release_segment(text)
    header = _HEADER_RE.search(body)
    if header is None:
        raise TbillAbstain("NO_CUTOFF_TABLE", "no 'T-Bill 91-Day 182-Day 364-Day' table header in the release text")
    if len(_HEADER_RE.findall(body)) != 1:
        raise TbillAbstain("SCHEMA_CHANGED", "more than one cut-off table header in the release text")
    pairs = _PAIR_RE.findall(body, header.end())
    if len(pairs) != len(TBILL_TENORS):
        raise TbillAbstain("SCHEMA_CHANGED", f"expected 3 'price (YTM: y%)' pairs, found {len(pairs)}")

    yields = []
    for tenor, (price_text, ytm_text) in zip(TBILL_TENORS, pairs, strict=True):
        price, ytm = Decimal(price_text), Decimal(ytm_text)
        if not Decimal(0) < price < Decimal(100) or not Decimal(0) < ytm < Decimal(50):
            raise TbillAbstain("OUT_OF_RANGE", f"{tenor}-day price {price_text} or yield {ytm_text}% out of range")
        recomputed = implied_yield_pct(price, tenor)
        if recomputed != ytm:
            raise TbillAbstain(
                "SELF_CHECK_MISMATCH",
                f"{tenor}-day: published yield {ytm_text}% but {SELF_CHECK_FORMULA} gives {recomputed}%; "
                "the release is not used",
            )
        yields.append(TbillYield(tenor, price, ytm, ytm / Decimal(100), series_id_for(tenor)))

    release_dates = {d for m in _RELEASE_DATE_RE.finditer(body) if (d := _date_from(*m.groups())) is not None}
    if len(release_dates) > 1:
        raise TbillAbstain("SCHEMA_CHANGED", "more than one release date in the release text")
    feed_day = pub_date.astimezone(IST).date() if pub_date is not None else None
    if release_dates:
        (release_date,) = release_dates
        basis: Literal["release_text", "feed_pubdate"] = "release_text"
        if feed_day is not None and feed_day != release_date:
            raise TbillAbstain(
                "DATE_MISMATCH", f"release text dated {release_date}, feed pubDate {feed_day}; nothing stored"
            )
    elif feed_day is not None:
        release_date, basis = feed_day, "feed_pubdate"
    else:
        raise TbillAbstain("NO_DATE", "neither the release text nor the feed item carries a release date")

    auction_match = _AUCTION_DATE_RE.search(body)
    auction_date = _date_from(*auction_match.groups()) if auction_match else None
    if auction_date is not None and auction_date > release_date:
        raise TbillAbstain("DATE_MISMATCH", "the stated auction date is after the release date")
    ref_match = _PR_REF_RE.search(body)
    ref = ref_match.group(1) if ref_match else None
    label = f"Press Release {ref}" if ref else f"press release id {prid}"
    citation = f'Reserve Bank of India, {label}, "{TBILL_CUTOFF_TITLE}", dated {release_date.isoformat()}'
    return TbillCutoffRelease(
        prid=prid,
        release_date=release_date,
        date_basis=basis,
        auction_date=auction_date,
        press_release_ref=ref,
        yields=tuple(yields),
        citation_text=citation,
    )
