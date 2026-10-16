"""AMFI survivorship probe (PLAN A09): do closed and merged schemes appear in AMFI NAV history, and how far back does
history go for each core-universe role?

PERSONAL, LOCAL USE ONLY (AMFI terms of use: personal, non-commercial; no significant storage). The probe stores
nothing: every response is parsed in memory, then dropped, and only counts are printed. Never paste raw output that
contains scheme codes or NAVs into the repository; ``docs/data/probes/amfi-closed-schemes.md`` takes the answer and
counts only.

Run from backend/ with the worktree's sources on PYTHONPATH:

    .venv/bin/python scripts/probe_amfi_closed.py survivorship --mf 9 --from 2016-01-01 --to 2016-03-31
    .venv/bin/python scripts/probe_amfi_closed.py earliest --roles /path/outside/repo/roles.json --since 2006-04-01

``roles.json`` is user configuration kept OUTSIDE the repository (role bindings name real schemes)::

    {"index_fund.nifty50": {"mf": 9, "tp": 1, "codes": [111111, 222222]}}

where ``codes`` lists the role's Direct-Growth and Regular-Growth scheme codes. The earliest-date report prints to
stdout only, for the user.

How the survivorship answer is decided. The history report never marks a scheme as closed or merged; such a scheme just
stops publishing. So the probe fetches one past window (<= 90 days) for one fund house and every scheme type
(``tp`` 1, 2 and 3), then checks each scheme code found there against today's NAVAll: a code that is absent from NAVAll,
or whose NAVAll date is stale, no longer publishes. If at least one such code appears in the history window, closed or
merged schemes DO appear in AMFI NAV history: VERIFIED. If none does, the answer is NOT VERIFIED (it may be the window).
That one window shows presence, not completeness: whether EVERY closed scheme appears stays NOT VERIFIED.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from iip.data.models import ParseResult, QualityStatus, RawPayload
from iip.data.parsers.amfi_navall import parse_navall
from iip.data.parsers.amfi_navhistory import (
    FLAG_CEASED,
    HistorySpan,
    RoleHistoryStart,
    earliest_nav_date_per_role,
    history_spans,
    parse_navhistory,
    window_flags,
)
from iip.data.parsers.amfi_scheme_master import (
    SchemeStatus,
    classify_scheme_status,
    latest_nav_dates,
    parse_scheme_master,
)
from iip.data.registry import (
    MAX_HISTORY_WINDOW_DAYS,
    SourceRequest,
    navall_request,
    navhistory_request,
    schememaster_request,
)

FetchFn = Callable[[SourceRequest], RawPayload | None]
"""Returns the payload, or ``None`` when the source answered with no data for the query."""

VERIFIED = "VERIFIED"
NOT_VERIFIED = "NOT VERIFIED"
TPS = (1, 2, 3)


# --- pure helpers (tested hermetically) -----------------------------------------------------------------------------


def plan_windows(since: date, until: date, days: int = MAX_HISTORY_WINDOW_DAYS) -> list[tuple[date, date]]:
    """Contiguous, non-overlapping windows covering [since, until], each accepted by ``navhistory_request``."""
    if since > until:
        raise ValueError("since must not be after until")
    if not 0 < days <= MAX_HISTORY_WINDOW_DAYS:
        raise ValueError(f"days must be in 1..{MAX_HISTORY_WINDOW_DAYS}")
    out: list[tuple[date, date]] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=days), until)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def find_first_window(n_windows: int, has_rows: Callable[[int], bool]) -> int | None:
    """Smallest window index with rows, by binary search. Assumes presence is monotone (a live scheme publishes in
    every window after its first). ``None`` if even the last window has no rows."""
    if n_windows <= 0 or not has_rows(n_windows - 1):
        return None
    lo, hi = 0, n_windows - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if has_rows(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


@dataclass(frozen=True)
class SurvivorshipSummary:
    answer: str
    counts: dict[str, int]
    notes: tuple[str, ...] = field(default=())


def survivorship_summary(
    history: Mapping[int, Sequence[ParseResult]],
    navall: ParseResult,
    master: ParseResult | None,
    *,
    window_start: date,
    window_end: date,
) -> SurvivorshipSummary:
    """Counts only. ``history`` maps ``tp`` to the parsed windows fetched for it."""
    navall_dates = latest_nav_dates(navall)
    master_codes = {r.scheme_code for r in master.records} if master is not None else None
    counts: dict[str, int] = {
        "navall_codes": len(navall_dates),
        "history_rows_rejected": sum(r.report.rows_rejected for rs in history.values() for r in rs),
    }
    if master_codes is not None:
        counts["master_codes"] = len(master_codes)
    all_spans: dict[int, HistorySpan] = {}
    by_tp: dict[int, dict[int, HistorySpan]] = {}
    for tp in TPS:
        by_tp[tp] = history_spans(history.get(tp, ()))
        counts[f"history_codes_tp{tp}"] = len(by_tp[tp])
        all_spans.update(by_tp[tp])
    statuses = classify_scheme_status(all_spans, navall_dates)
    for tp in TPS:  # "gone" = no current NAV today; tp 1 separates open-ended closures/mergers from maturities
        counts[f"history_codes_gone_today_tp{tp}"] = sum(statuses[c] is not SchemeStatus.LIVE for c in by_tp[tp])
    counts["history_codes"] = len(all_spans)
    counts["history_codes_live_today"] = sum(s is SchemeStatus.LIVE for s in statuses.values())
    counts["history_codes_dormant_today"] = sum(s is SchemeStatus.DORMANT for s in statuses.values())
    counts["history_codes_absent_from_navall"] = sum(s is SchemeStatus.NOT_PUBLISHED for s in statuses.values())
    if master_codes is not None:
        counts["history_codes_absent_from_master"] = sum(c not in master_codes for c in all_spans)
    counts["history_codes_ceased_in_window"] = sum(
        FLAG_CEASED in window_flags(s, window_start=window_start, window_end=window_end) for s in all_spans.values()
    )
    gone = counts["history_codes_dormant_today"] + counts["history_codes_absent_from_navall"]
    notes: list[str] = []
    if not all_spans:
        notes.append("The history window returned no accepted rows; nothing can be concluded.")
        answer = NOT_VERIFIED
    elif gone > 0:
        answer = VERIFIED
        notes.append(
            "Schemes that no longer publish a current NAV do appear in the history window. "
            "Presence only: whether every closed or merged scheme appears is NOT VERIFIED."
        )
    else:
        answer = NOT_VERIFIED
        notes.append("Every scheme in the window still publishes today; try an older window or another fund house.")
    return SurvivorshipSummary(answer, counts, tuple(notes))


def render_counts(summary: SurvivorshipSummary, *, window_start: date, window_end: date, mf: int) -> str:
    """Markdown with the answer and counts only: no scheme code, name, ISIN or NAV."""
    lines = [
        f"Survivorship answer: **{summary.answer}**",
        "",
        f"Window: {window_start.isoformat()} to {window_end.isoformat()} (fund-house id {mf}, tp 1, 2 and 3)",
        "",
        "| Count | Value |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in summary.counts.items()),
        "",
        *summary.notes,
    ]
    return "\n".join(lines) + "\n"


# --- IO orchestration (fetch is injected so tests stay offline) -------------------------------------------------------


def run_survivorship(fetch: FetchFn, *, mf: int, window_start: date, window_end: date) -> SurvivorshipSummary:
    navall_payload = fetch(navall_request())
    if navall_payload is None:
        raise RuntimeError("NAVAll returned no data; cannot classify schemes")
    navall = parse_navall(navall_payload, quality=QualityStatus.OK)
    master_payload = fetch(schememaster_request())
    master = parse_scheme_master(master_payload) if master_payload is not None else None
    history: dict[int, list[ParseResult]] = {}
    for tp in TPS:
        req = navhistory_request(mf_id=mf, tp=tp, from_date=window_start, to_date=window_end)
        payload = fetch(req)
        history[tp] = [parse_navhistory(payload, quality=QualityStatus.OK)] if payload is not None else []
    return survivorship_summary(history, navall, master, window_start=window_start, window_end=window_end)


@dataclass(frozen=True)
class RoleBinding:
    mf: int
    tp: int
    codes: tuple[int, ...]


def load_roles(path: Path) -> dict[str, RoleBinding]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("roles file must be a non-empty JSON object")
    out: dict[str, RoleBinding] = {}
    for role, spec in raw.items():
        codes = spec.get("codes") if isinstance(spec, dict) else None
        if not isinstance(codes, list) or not codes or not all(isinstance(c, int) and c > 0 for c in codes):
            raise ValueError(f"role {role!r}: 'codes' must be a non-empty list of positive integers")
        mf, tp = spec.get("mf"), spec.get("tp")
        if not isinstance(mf, int) or not isinstance(tp, int):
            raise ValueError(f"role {role!r}: 'mf' and 'tp' must be integers")
        out[str(role)] = RoleBinding(mf, tp, tuple(codes))
    return out


def run_earliest(
    fetch: FetchFn, roles: Mapping[str, RoleBinding], *, since: date, until: date
) -> list[RoleHistoryStart]:
    """Binary-search the first 90-day window with rows for each role, then confirm the window before it is empty."""
    windows = plan_windows(since, until)
    out: list[RoleHistoryStart] = []
    for role in sorted(roles):
        b = roles[role]
        cache: dict[int, ParseResult | None] = {}

        def window(k: int, b: RoleBinding = b, cache: dict[int, ParseResult | None] = cache) -> ParseResult | None:
            if k not in cache:
                start, end = windows[k]
                payload = fetch(navhistory_request(mf_id=b.mf, tp=b.tp, from_date=start, to_date=end))
                cache[k] = parse_navhistory(payload, quality=QualityStatus.OK) if payload is not None else None
            return cache[k]

        def has_rows(k: int, b: RoleBinding = b, window: Callable[[int], ParseResult | None] = window) -> bool:
            res = window(k)
            return res is not None and any(r.scheme_code in b.codes for r in res.records)

        k = find_first_window(len(windows), has_rows)
        if k is None:
            out.extend(earliest_nav_date_per_role({}, {role: b.codes}, searched_from=None).values())
            continue
        found = window(k)
        spans = history_spans([found] if found is not None else [])
        searched_from: date | None = windows[0][0]
        if k > 0:
            searched_from = windows[k - 1][0] if not has_rows(k - 1) else None
        out.extend(earliest_nav_date_per_role(spans, {role: b.codes}, searched_from=searched_from).values())
    return out


def _live_fetch(delay_s: float) -> FetchFn:
    from iip.data.fetch import Fetcher, NoData  # noqa: PLC0415 - only the live path needs the network stack

    fetcher = Fetcher()

    def fetch(req: SourceRequest) -> RawPayload | None:
        time.sleep(delay_s)  # be polite: one request at a time with a pause
        try:
            return fetcher.fetch(req)
        except NoData:
            return None

    return fetch


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survivorship")
    s.add_argument("--mf", type=int, required=True)
    s.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    s.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    e = sub.add_parser("earliest")
    e.add_argument("--roles", type=Path, required=True)
    e.add_argument("--since", type=date.fromisoformat, required=True)
    e.add_argument("--until", type=date.fromisoformat, default=date.today())
    p.add_argument("--delay", type=float, default=2.0)
    args = p.parse_args(argv)
    fetch = _live_fetch(args.delay)
    if args.cmd == "survivorship":
        summary = run_survivorship(fetch, mf=args.mf, window_start=args.start, window_end=args.end)
        sys.stdout.write(render_counts(summary, window_start=args.start, window_end=args.end, mf=args.mf))
        return 0
    for r in run_earliest(fetch, load_roles(args.roles), since=args.since, until=args.until):
        when = r.earliest_date.isoformat() if r.earliest_date else "-"
        sys.stdout.write(f"{r.role}\t{when}\t{r.status.value}\t{','.join(r.labels)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
