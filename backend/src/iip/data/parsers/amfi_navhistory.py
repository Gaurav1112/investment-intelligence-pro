"""Strict parser for the AMFI NAV history report (source-registry.md §2.2).

The column order differs from NAVAll: ``Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;
ISIN Div Reinvestment;Net Asset Value;Date``. Empty ISIN is an empty field; group headers have spaces inside the
brackets. Keyed on its own exact header, so a NAVAll file is refused here and vice versa.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from iip.data.models import ParseResult, QualityStatus, RawPayload, SchemeRecord
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


# --- Survivorship support: per-scheme spans, ceased series, pre-2013 labels and earliest date per role ---------------
#
# Closed and merged schemes are not marked as such anywhere in the NAV history report: a scheme that is wound up,
# matures or is merged into another simply stops publishing rows. What this module can say from the file alone is
# therefore "this series stopped inside the window" (``SERIES_CEASED_IN_WINDOW``), never "this scheme was merged".
# The ``tp`` mapping (1 open-ended, 2 close-ended, 3 interval) is NOT VERIFIED (source-registry.md §2.2).

DIRECT_PLANS_START = date(2013, 1, 1)
"""Direct plans exist from 1-Jan-2013 (research-evidence-mf.md §4.1). Earlier rows are Regular-cost NAVs."""
LABEL_REGULAR_PRE_2013 = "history: regular_plan_pre_2013"
FLAG_CEASED = "SERIES_CEASED_IN_WINDOW"
FLAG_STARTED = "SERIES_STARTED_IN_WINDOW"
CEASED_GRACE_DAYS = 10
"""A series whose last row is more than this many calendar days before the window end is treated as ceased. Ten days
covers the longest run of Indian market holidays plus a weekend; it is a PARAMETER, not a sourced fact."""


class EarliestStatus(StrEnum):
    VERIFIED = "VERIFIED"  # the window before the first row was searched and held no row for this scheme
    NOT_VERIFIED = "NOT VERIFIED"  # rows found, but nothing proves there are no earlier rows
    NO_DATA = "NO DATA"  # no row for any bound scheme


@dataclass(frozen=True, slots=True)
class HistorySpan:
    """What one scheme's rows in one or more parsed history windows show. No NAV values are kept."""

    scheme_code: int
    scheme_type: str | None
    category: str | None
    amc: str | None
    plan: str | None
    first_date: date
    last_date: date
    n_observations: int
    n_pre_direct: int
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoleHistoryStart:
    role: str
    scheme_code: int | None
    earliest_date: date | None
    status: EarliestStatus
    labels: tuple[str, ...] = ()


@dataclass(slots=True)
class _Acc:
    first: date
    last: date
    n: int
    n_pre: int
    latest: SchemeRecord


def history_spans(results: Iterable[ParseResult]) -> dict[int, HistorySpan]:
    """Merge parsed history windows into one span per scheme code (first/last row date, row count).

    Only accepted rows count (rejected rows carry no trustworthy date). Context (type, category, AMC, plan) is taken
    from the row with the latest date, so a later rename wins.
    """
    acc: dict[int, _Acc] = {}
    for result in results:
        if len(result.records) != len(result.observations):
            raise ValueError("ParseResult records and observations are not aligned")
        for rec, obs in zip(result.records, result.observations, strict=True):
            d = obs.observation_date
            cur = acc.get(rec.scheme_code)
            if cur is None:
                cur = acc[rec.scheme_code] = _Acc(d, d, 0, 0, rec)
            cur.first = min(cur.first, d)
            if d >= cur.last:
                cur.last, cur.latest = d, rec
            cur.n += 1
            cur.n_pre += 1 if d < DIRECT_PLANS_START else 0
    spans: dict[int, HistorySpan] = {}
    for code in sorted(acc):
        a = acc[code]
        spans[code] = HistorySpan(
            scheme_code=code,
            scheme_type=a.latest.scheme_type,
            category=a.latest.category,
            amc=a.latest.amc,
            plan=a.latest.plan,
            first_date=a.first,
            last_date=a.last,
            n_observations=a.n,
            n_pre_direct=a.n_pre,
            labels=(LABEL_REGULAR_PRE_2013,) if a.n_pre else (),
        )
    return spans


def window_flags(
    span: HistorySpan, *, window_start: date, window_end: date, grace_days: int = CEASED_GRACE_DAYS
) -> tuple[str, ...]:
    """Flags for a span seen inside one searched window: it started, or ceased, inside the window.

    ``SERIES_CEASED_IN_WINDOW`` means the scheme stopped publishing: closed, matured, merged or suspended. The file does
    not say which, and this function never guesses.
    """
    if window_start > window_end:
        raise ValueError("window_start must not be after window_end")
    if grace_days < 0:
        raise ValueError("grace_days must be >= 0")
    flags: list[str] = []
    if (span.first_date - window_start).days > grace_days:
        flags.append(FLAG_STARTED)
    if (window_end - span.last_date).days > grace_days:
        flags.append(FLAG_CEASED)
    return tuple(flags)


def earliest_nav_date_per_role(
    spans: Mapping[int, HistorySpan],
    bindings: Mapping[str, Sequence[int]],
    *,
    searched_from: date | None,
) -> dict[str, RoleHistoryStart]:
    """Earliest NAV-history date per role, over the role's bound scheme codes (e.g. its Direct and Regular plans).

    ``searched_from`` is the first day covered by the windows that produced ``spans`` (``None`` if unknown). The date is
    VERIFIED only when the search began strictly before it, i.e. an earlier stretch was searched and held no row.
    Rows before 2013-01-01 carry ``history: regular_plan_pre_2013``.
    """
    out: dict[str, RoleHistoryStart] = {}
    for role in sorted(bindings):
        found = [spans[c] for c in bindings[role] if c in spans]
        if not found:
            out[role] = RoleHistoryStart(role, None, None, EarliestStatus.NO_DATA)
            continue
        best = min(found, key=lambda s: (s.first_date, s.scheme_code))
        verified = searched_from is not None and searched_from < best.first_date
        out[role] = RoleHistoryStart(
            role=role,
            scheme_code=best.scheme_code,
            earliest_date=best.first_date,
            status=EarliestStatus.VERIFIED if verified else EarliestStatus.NOT_VERIFIED,
            labels=(LABEL_REGULAR_PRE_2013,) if best.first_date < DIRECT_PLANS_START else (),
        )
    return out
