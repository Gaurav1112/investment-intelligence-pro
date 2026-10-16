"""Exit load from a Scheme Information Document's "Load Structure" text, under a STRICT grammar (PLAN.md row B06;
audit-automation.md §3.6; design-evidence-first.md WP14).

Contract:

* The whole text must match the grammar below. Anything unrecognised, and any inconsistent schedule (a gap or overlap
  between tiers, mixed period units, no closing "Nil" clause, a rate outside (0 %, 5 %]), returns
  :class:`ExitLoadAbstain` with a reason code. A partially recognised schedule is never returned, so the scheme stays
  ``EXIT_LOAD_UNKNOWN`` and the engine abstains on lots younger than 365 days (A15).
* Periods keep their own unit. Months and years are never converted to days here: calendar months are not 30 days and
  no cited conversion rule exists in this repo, so :meth:`ExitLoadSchedule.window_days` returns ``None``
  (``PERIOD_NOT_IN_DAYS``) for them. The engine's single-tier and multi-tier models take days only.
* "within N days" is read as "on or before N days" (the engine's ``days_held <= window_days`` convention) and flagged
  ``BOUNDARY_WITHIN_READ_AS_ON_OR_BEFORE``: the boundary day reading is NOT VERIFIED.
* A free-unit allowance ("Nil for up to 10 % of units …; for remaining units: …") parses on its own branch, but the
  engine does not model it, so ``window_days`` abstains (``FREE_UNITS_NOT_MODELLED``).
* Footnote markers (``^ * # †``) are removed and flagged ``FOOTNOTE_MARKER_IGNORED``: the footnote itself is not read.

Accepted clause forms (after case-folding and whitespace/punctuation normalisation; clauses are separated by ";" or
by a full stop followed by a space). ``V`` = "[units are] redeemed | exited | switched out | redeemed or/'/' switched
out", ``P`` = "<n> day(s) | month(s) | year(s)", ``F`` = optional "from the date of allotment":

    nil                                                    (the whole text)
    R% [,] [if|for|in case V] (on or before|within) P F    first tier, or a later tier with a larger bound
    R% [,] [if|for|in case] V after P but|and (on or before|within) P F    a later tier starting at the last bound
    for exit (on or before|within) P F - R%
    [in respect of each purchase[/switch in] of units,] [an] exit load of R% is payable if V (on or before|within) P F
    nil [,] [[if|for|in case] V] after P F | nil thereafter | for exit after P F - nil
    no exit load is payable if V after P F
    nil for [up to] Q% of [the] units|investment [allotted] [[if] V (on or before|within) P F]   (free units, first)
    for [the] remaining units|investment[:] <tier clause>                                    (only after free units)

Pure: no clock, IO or randomness. Rates are ``Decimal`` fractions (1 % -> 0.01), never floats.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

PARSER_VERSION = "sid_exit_load/1"
MAX_RATE = Decimal("0.05")  # services/instruments.ExitLoadIn accepts at most 5 %; SEBI's lower cap is NOT VERIFIED here
MAX_PERIOD = 3650

FLAG_WITHIN = "BOUNDARY_WITHIN_READ_AS_ON_OR_BEFORE"
FLAG_FOOTNOTE = "FOOTNOTE_MARKER_IGNORED"

Unit = Literal["day", "month", "year"]
_UNITS: dict[str, Unit] = {
    "day": "day", "days": "day", "month": "month", "months": "month", "year": "year", "years": "year",
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class LoadPeriod:
    n: int
    unit: str  # 'day' | 'month' | 'year'

    def __post_init__(self) -> None:
        if self.unit not in ("day", "month", "year"):
            raise ValueError(f"unknown period unit {self.unit!r}")
        if not 1 <= self.n <= MAX_PERIOD:
            raise ValueError(f"period {self.n} out of range")


@dataclass(frozen=True, slots=True)
class ParsedTier:
    """``rate`` applies when the holding period is on or before ``upto`` (and after the previous tier's bound)."""

    upto: LoadPeriod
    rate: Decimal


@dataclass(frozen=True, slots=True)
class ExitLoadSchedule:
    tiers: tuple[ParsedTier, ...]
    free_fraction: Decimal | None
    branch: str  # NIL | TIERED | FREE_UNITS
    flags: tuple[str, ...]
    text_sha256: str  # SHA-256 of the normalised text that was parsed
    parser_version: str = PARSER_VERSION
    status: str = "NOT VERIFIED"  # parsed text, not checked against an applied load

    def engine_abstain_reason(self) -> str | None:
        if self.free_fraction is not None:
            return "FREE_UNITS_NOT_MODELLED"
        if any(t.upto.unit != "day" for t in self.tiers):
            return "PERIOD_NOT_IN_DAYS"
        return None

    def window_days(self) -> tuple[tuple[int, Decimal], ...] | None:
        """``((window_days, rate), …)`` for the engine's load tiers, or ``None`` when it must abstain."""
        if self.engine_abstain_reason() is not None:
            return None
        return tuple((t.upto.n, t.rate) for t in self.tiers)


@dataclass(frozen=True, slots=True)
class ExitLoadAbstain:
    reason: str
    detail: str = ""
    parser_version: str = PARSER_VERSION


# ----------------------------------------------------------------------------------------------- grammar

_RATE = r"(?P<rate>\d{1,2}(?:\.\d{1,4})?) ?%"
_VERB = r"(?:(?:the )?units are )?(?:redeemed(?: or switched out|/switched out)?|exited|switched out)"
_COND = r"(?:if|for|in case)"
_BOUND = r"(?P<bound>on or before|within)"
_P = r"(?P<n>\d{1,4}) (?P<u>days?|months?|years?)"
_FROM = r"(?: from the date of allotment)?"

_UPTO = [
    re.compile(rf"^{_RATE},? (?:{_COND} {_VERB} )?{_BOUND} {_P}{_FROM}$"),
    re.compile(rf"^for exit {_BOUND} {_P}{_FROM} ?[-:] ?{_RATE}$"),
    re.compile(
        rf"^(?:in respect of each purchase(?:/switch in)? of units,? )?(?:an )?exit load of {_RATE} is payable"
        rf" if {_VERB} {_BOUND} {_P}{_FROM}$"
    ),
]
_RANGE = re.compile(
    rf"^{_RATE},? (?:{_COND} )?{_VERB} after (?P<a>\d{{1,4}}) (?P<au>days?|months?|years?) (?:but|and) {_BOUND} {_P}"
    rf"{_FROM}$"
)
_NIL_AFTER = [
    re.compile(rf"^nil,? (?:(?:{_COND} )?{_VERB} )?after {_P}{_FROM}$"),
    re.compile(rf"^for exit after {_P}{_FROM} ?[-:] ?nil$"),
    re.compile(rf"^no exit load is payable if {_VERB} after {_P}{_FROM}$"),
]
_NIL_THEREAFTER = re.compile(r"^nil,? thereafter$")
_FREE = re.compile(
    rf"^nil for (?:up to |upto )?(?P<q>\d{{1,3}}(?:\.\d{{1,2}})?) ?% of (?:the )?(?:units|investment)(?: allotted)?"
    rf"(?:,? (?:{_COND} )?{_VERB} {_BOUND} {_P}{_FROM})?$"
)
_REMAINING = re.compile(r"^for (?:the )?remaining (?:units|investment) ?[:,-]? ?")
_LABEL = re.compile(r"^(?:exit load|load structure)\s*[:\-]\s*")
_FOOTNOTES = re.compile(r"[\^*#†]")


def _normalise(text: str) -> tuple[str, bool]:
    t = text.replace("–", "-").replace("—", "-").replace(" ", " ")
    t = " ".join(t.split()).lower()
    footnotes = bool(_FOOTNOTES.search(t))
    t = _FOOTNOTES.sub("", t)
    t = re.sub(r"\s*/\s*", "/", t)
    t = re.sub(r"switch(ed)?-(in|out)", r"switch\1 \2", t)
    t = " ".join(t.split()).strip()
    while (m := _LABEL.match(t)) is not None:
        t = t[m.end() :].strip()
    return t.rstrip(". ").strip(), footnotes


def _period(n: str, u: str) -> LoadPeriod:
    return LoadPeriod(int(n), _UNITS[u])


def _rate(s: str) -> Decimal:
    return Decimal(s).scaleb(-2)


@dataclass(frozen=True, slots=True)
class _Clause:
    kind: str  # upto | range | nil_after | nil_thereafter | free
    rate: Decimal | None = None
    start: LoadPeriod | None = None
    upto: LoadPeriod | None = None
    within: bool = False
    free: Decimal | None = None


class _Abstain(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def _period_or_abstain(n: str, u: str) -> LoadPeriod:
    try:
        return _period(n, u)
    except ValueError as exc:
        raise _Abstain("PERIOD_OUT_OF_RANGE") from exc


def _clause(c: str) -> _Clause:
    for rx in _UPTO:
        if m := rx.match(c):
            return _Clause("upto", rate=_rate(m["rate"]), upto=_period_or_abstain(m["n"], m["u"]),
                           within=m["bound"] == "within")  # fmt: skip
    if m := _RANGE.match(c):
        return _Clause("range", rate=_rate(m["rate"]), start=_period_or_abstain(m["a"], m["au"]),
                       upto=_period_or_abstain(m["n"], m["u"]), within=m["bound"] == "within")  # fmt: skip
    for rx in _NIL_AFTER:
        if m := rx.match(c):
            return _Clause("nil_after", start=_period_or_abstain(m["n"], m["u"]))
    if _NIL_THEREAFTER.match(c):
        return _Clause("nil_thereafter")
    if m := _FREE.match(c):
        upto = _period_or_abstain(m["n"], m["u"]) if m["n"] else None
        return _Clause("free", free=Decimal(m["q"]).scaleb(-2), upto=upto,
                       within=m["bound"] == "within")  # fmt: skip
    raise _Abstain("UNRECOGNISED_PHRASING")


def _clauses(text: str) -> list[_Clause]:
    parts = [p.strip(" ,.") for p in re.split(r";|\.\s", text)]
    parts = [p for p in parts if p]
    out: list[_Clause] = []
    for i, part in enumerate(parts):
        body = part
        if m := _REMAINING.match(part):
            if not out or out[0].kind != "free":
                raise _Abstain("UNRECOGNISED_PHRASING")  # "remaining units" only after a free-unit clause
            body = part[m.end() :].strip()
        c = _clause(body)
        if c.kind == "free" and i != 0:
            raise _Abstain("UNRECOGNISED_PHRASING")
        out.append(c)
    return out


def _check(clauses: list[_Clause]) -> tuple[tuple[ParsedTier, ...], Decimal | None, bool]:
    free = clauses[0].free if clauses and clauses[0].kind == "free" else None
    body = clauses[1:] if free is not None else clauses
    if free is not None and not Decimal("0") < free < Decimal("1"):
        raise _Abstain("FREE_FRACTION_OUT_OF_RANGE")
    nil_at = [i for i, c in enumerate(body) if c.kind in ("nil_after", "nil_thereafter")]
    if not nil_at:
        raise _Abstain("NO_TERMINAL_NIL")
    if nil_at != [len(body) - 1]:
        raise _Abstain("NIL_NOT_LAST")
    loads, last = body[:-1], body[-1]
    if not loads:
        raise _Abstain("UNRECOGNISED_PHRASING")  # "Nil after N days" alone says nothing about the first N days
    periods = [p for c in clauses for p in (c.start, c.upto) if p is not None]
    if len({p.unit for p in periods}) > 1:
        raise _Abstain("MIXED_PERIOD_UNITS")
    tiers: list[ParsedTier] = []
    within = False
    for c in loads:
        assert c.rate is not None and c.upto is not None
        if not Decimal("0") < c.rate <= MAX_RATE:
            raise _Abstain("RATE_OUT_OF_RANGE")
        prev = tiers[-1].upto.n if tiers else 0
        if c.kind == "range":
            assert c.start is not None
            if c.start.n != prev or not tiers:
                raise _Abstain("GAP_OR_OVERLAP_BETWEEN_TIERS")
        if c.upto.n <= prev:
            raise _Abstain("TIERS_NOT_ASCENDING")
        within = within or c.within
        tiers.append(ParsedTier(c.upto, c.rate))
    if last.kind == "nil_after":
        assert last.start is not None
        if last.start.n != tiers[-1].upto.n:
            raise _Abstain("GAP_OR_OVERLAP_BETWEEN_TIERS")
    return tuple(tiers), free, within


def parse_exit_load(text: str) -> ExitLoadSchedule | ExitLoadAbstain:
    """Parse one exit-load text. Returns the schedule, or an abstention with a reason code (never a partial one)."""
    norm, footnotes = _normalise(text or "")
    if not norm:
        return ExitLoadAbstain("EMPTY")
    sha = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    flags = [FLAG_FOOTNOTE] if footnotes else []
    if norm == "nil":
        return ExitLoadSchedule((), None, "NIL", tuple(flags), sha)
    try:
        tiers, free, within = _check(_clauses(norm))
    except _Abstain as a:
        return ExitLoadAbstain(a.reason, a.detail)
    if within:
        flags.append(FLAG_WITHIN)
    return ExitLoadSchedule(tiers, free, "FREE_UNITS" if free is not None else "TIERED", tuple(sorted(flags)), sha)


_BLOCK = re.compile(r"(?im)^[ \t]*exit load[ \t]*[:\-–][ \t]*")


def extract_exit_load_text(document: str) -> str | None:
    """The text after an "Exit Load:" label, up to the next blank line. ``None`` when there is no such block, or when
    two blocks say different things (which one applies is not guessed)."""
    found: list[str] = []
    for m in _BLOCK.finditer(document or ""):
        rest = document[m.end() :]
        end = re.search(r"\n[ \t]*\n", rest)
        block = " ".join((rest[: end.start()] if end else rest).split())
        if block:
            found.append(block)
    if not found:
        return None
    if len({_normalise(b)[0] for b in found}) != 1:
        return None
    return found[0]
